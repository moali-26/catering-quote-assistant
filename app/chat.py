"""Customer chat: saved conversations, B's Conversation loop, and submission to C's QuoteService.

Storage is server-only (catering_private.conversations, or SQLite locally). Every
read and write is filtered by the verified customer ID. A conversation belongs to
one customer and the single demo business; once submitted it is linked to the quote
and a new request starts a new conversation.

Concurrency: one customer turn or submit at a time (per-process lock), and every
write is a revision-checked update. The customer's message is saved *before* the
model runs, so a submit from another tab during a reply sees a changed revision.
Submitting uses a quote ID derived from the conversation, so a retry or double
click can never create a second quote.

Cost: each turn may call the model at most MODEL_CALLS_PER_TURN times within
TURN_SECONDS; older tool results are shortened before they are re-sent; customers
have daily turn and conversation caps, and the whole process has a daily turn cap.
"""
import json
import logging
import os
import unicodedata
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_service import Conversation
from quote_engine.ai_tool import TOOL_DEFINITION as EVALUATE_TOOL
from quote_engine.checks import MAX_CUSTOMER_NOTES
from quote_engine.postgres_storage import QuoteStorageUnavailable
from quote_engine.pricing import QuoteError
from quote_engine.service import QuoteService
from quote_engine.storage import QuoteConflict, QuoteNotFound

MAX_MESSAGE_CHARS = 1200
MAX_CUSTOMER_MESSAGES = 15          # per conversation


def _limit(name, default):
    """A positive whole number from the environment, else the default."""
    try:
        value = int(os.environ.get(name, ''))
    except ValueError:
        return default
    return value if value > 0 else default


# Daily limits reset at 00:00 UTC (5 pm Pacific in summer time, 4 pm in winter).
# Messages per customer is what bounds model cost; new requests per day only stops
# runaway "Start a new request" clicks, so it can be generous.
DAILY_TURNS_PER_CUSTOMER = _limit('CHAT_DAILY_MESSAGES_PER_CUSTOMER', 40)
DAILY_CONVERSATIONS_PER_CUSTOMER = _limit('CHAT_DAILY_REQUESTS_PER_CUSTOMER', 20)
DAILY_TURNS_TOTAL = _limit('CHAT_DAILY_MESSAGES_TOTAL', 400)  # whole app, per process; set a hard spend limit at the provider too
logger = logging.getLogger('app.chat')
RATE_WINDOW_SECONDS = 60
RATE_MAX_MESSAGES = 8
MODEL_CALLS_PER_TURN = 5
TURN_SECONDS = 75
QUOTE_NAMESPACE = uuid.UUID('5b3f2a8e-9c1d-4e7a-b0f6-2d8c4a1e7f30')
CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
SERVER_NOTE_PREFIX = re.compile(r'\[\s*automated\s+server\s+check', re.IGNORECASE)
SUBMIT_WAIT_SECONDS = 10
OMITTED_TOOL_RESULT = json.dumps({'note': 'Earlier tool result omitted to save space. Call the tool again if needed.'})


class ChatNotFound(QuoteError):
    """Missing conversation or one that belongs to someone else (same answer)."""


class ChatConflict(QuoteError):
    """The conversation changed in another tab; reload before continuing."""


class ChatLimit(QuoteError):
    """A limit was hit. str() is customer-safe; code names it for no-JavaScript notices."""

    def __init__(self, message, code='chat-limit'):
        super().__init__(message)
        self.code = code


def _uuid(value) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ChatNotFound('conversation not found') from None


def clean_text(text: str) -> str:
    """Drop control characters (Postgres jsonb rejects NUL) and defang fake server notes."""
    text = unicodedata.normalize('NFKC', CONTROL_CHARS.sub('', text or ''))  # full-width ［ → [
    return SERVER_NOTE_PREFIX.sub('[customer wrote: automated server check', text)


def _clean_messages(messages):
    """Control characters can also come back from a model; strip them before saving."""
    return json.loads(CONTROL_CHARS.sub('', json.dumps(messages, ensure_ascii=False)).replace('\\u0000', ''))


def _start_of_day() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------- storage

class SQLiteConversationStore:
    """Local development storage with the same contract as the Postgres store."""

    def __init__(self, path):
        self.path = str(Path(path))
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                messages TEXT NOT NULL, quote_id TEXT, revision INTEGER NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _row(row):
        return {'conversation_id': row[0], 'customer_id': row[1], 'owner_id': row[2],
                'messages': json.loads(row[3]), 'quote_id': row[4], 'revision': row[5]}

    COLUMNS = 'conversation_id, customer_id, owner_id, messages, quote_id, revision'

    def create(self, *, customer_id, owner_id):
        now = datetime.now(timezone.utc).isoformat()
        record = {'conversation_id': str(uuid.uuid4()), 'customer_id': customer_id, 'owner_id': owner_id,
                  'messages': [], 'quote_id': None, 'revision': 1}
        with self._db() as db:
            db.execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)',
                       (record['conversation_id'], customer_id, owner_id, '[]', None, 1, now, now))
        return record

    def active(self, *, customer_id):
        with self._db() as db:
            row = db.execute(f'''SELECT {self.COLUMNS} FROM conversations
                WHERE customer_id = ? AND quote_id IS NULL ORDER BY updated_at DESC LIMIT 1''',
                             (customer_id,)).fetchone()
        return self._row(row) if row else None

    def get(self, conversation_id, *, customer_id):
        with self._db() as db:
            row = db.execute(f'SELECT {self.COLUMNS} FROM conversations WHERE conversation_id = ? AND customer_id = ?',
                             (_uuid(conversation_id), customer_id)).fetchone()
        if not row:
            raise ChatNotFound('conversation not found')
        return self._row(row)

    def save(self, record, *, customer_id, expected_revision):
        now = datetime.now(timezone.utc).isoformat()
        messages = _clean_messages(record['messages'])
        with self._db() as db:
            cursor = db.execute('''UPDATE conversations SET messages = ?, quote_id = ?, revision = revision + 1,
                updated_at = ? WHERE conversation_id = ? AND customer_id = ? AND revision = ?''',
                                (json.dumps(messages), record.get('quote_id'), now,
                                 record['conversation_id'], customer_id, expected_revision))
            if cursor.rowcount != 1:
                raise ChatConflict('conversation changed; reload')
        return dict(record, messages=messages, revision=expected_revision + 1)

    def usage_since(self, *, customer_id, since):
        """(conversations created, customer messages sent) since a UTC time."""
        with self._db() as db:
            rows = db.execute('SELECT messages, created_at FROM conversations WHERE customer_id = ? AND updated_at >= ?',
                              (customer_id, since.isoformat())).fetchall()
        created = sum(1 for _, made in rows if made >= since.isoformat())
        return created, sum(customer_message_count(json.loads(m)) for m, _ in rows)


class PostgresConversationStore:
    """catering_private.conversations through the server-only connection (never the browser)."""

    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def _db(self):
        import psycopg
        try:
            with psycopg.connect(self.dsn, sslmode='require', connect_timeout=10, prepare_threshold=None) as db:
                yield db
        except psycopg.Error:
            raise QuoteStorageUnavailable('conversation storage unavailable; please retry') from None

    @staticmethod
    def _row(row):
        return {'conversation_id': str(row[0]), 'customer_id': str(row[1]), 'owner_id': str(row[2]),
                'messages': row[3], 'quote_id': str(row[4]) if row[4] else None, 'revision': row[5]}

    COLUMNS = 'conversation_id, customer_id, owner_id, messages, quote_id, revision'

    def create(self, *, customer_id, owner_id):
        conversation_id = str(uuid.uuid4())
        with self._db() as db:
            db.execute('''INSERT INTO catering_private.conversations (conversation_id, customer_id, owner_id)
                          VALUES (%s, %s, %s)''', (conversation_id, customer_id, owner_id))
        return {'conversation_id': conversation_id, 'customer_id': customer_id, 'owner_id': owner_id,
                'messages': [], 'quote_id': None, 'revision': 1}

    def active(self, *, customer_id):
        with self._db() as db:
            row = db.execute(f'''SELECT {self.COLUMNS} FROM catering_private.conversations
                WHERE customer_id = %s AND quote_id IS NULL ORDER BY updated_at DESC LIMIT 1''',
                             (customer_id,)).fetchone()
        return self._row(row) if row else None

    def get(self, conversation_id, *, customer_id):
        with self._db() as db:
            row = db.execute(f'''SELECT {self.COLUMNS} FROM catering_private.conversations
                WHERE conversation_id = %s AND customer_id = %s''',
                             (_uuid(conversation_id), customer_id)).fetchone()
        if not row:
            raise ChatNotFound('conversation not found')
        return self._row(row)

    def save(self, record, *, customer_id, expected_revision):
        from psycopg.types.json import Jsonb
        messages = _clean_messages(record['messages'])
        with self._db() as db:
            cursor = db.execute('''UPDATE catering_private.conversations
                SET messages = %s, quote_id = %s, revision = revision + 1, updated_at = now()
                WHERE conversation_id = %s AND customer_id = %s AND revision = %s''',
                                (Jsonb(messages), record.get('quote_id'), record['conversation_id'],
                                 customer_id, expected_revision))
            if cursor.rowcount != 1:
                raise ChatConflict('conversation changed; reload')
        return dict(record, messages=messages, revision=expected_revision + 1)

    def usage_since(self, *, customer_id, since):
        with self._db() as db:
            row = db.execute('''SELECT
                    count(*) FILTER (WHERE created_at >= %s),
                    coalesce(sum((SELECT count(*) FROM jsonb_array_elements(messages) m
                                  WHERE m->>'role' = 'user' AND coalesce((m->>'server_note')::boolean, false) = false)), 0)
                FROM catering_private.conversations WHERE customer_id = %s AND updated_at >= %s''',
                             (since, customer_id, since)).fetchone()
        return int(row[0]), int(row[1])


# ---------------------------------------------------------------- model guard

class TurnBudgetExceeded(RuntimeError):
    """Raised inside a turn when it used its model calls or time; Conversation shows a safe reply."""


class GuardedLLM:
    """Wraps the provider for one customer turn: caps calls and time, shortens old tool results."""

    def __init__(self, inner, *, max_calls=MODEL_CALLS_PER_TURN, seconds=TURN_SECONDS, clock=time.monotonic):
        self.inner, self.max_calls, self.seconds, self.clock = inner, max_calls, seconds, clock
        self.calls, self.started = 0, clock()

    @staticmethod
    def compact(messages):
        """Keep tool results from the current turn; replace older ones with a short note.

        Only what is sent to the model changes; the saved history (and the price guard,
        which reads it) keeps the full results.
        """
        last_customer = max((i for i, m in enumerate(messages)
                             if m.get('role') == 'user' and not m.get('server_note')), default=-1)
        return [dict(m, content=OMITTED_TOOL_RESULT) if m.get('role') == 'tool' and i < last_customer else m
                for i, m in enumerate(messages)]

    def generate(self, system, messages, tools):
        if self.calls >= self.max_calls:
            raise TurnBudgetExceeded('model call limit for this turn')
        if self.clock() - self.started > self.seconds:
            raise TurnBudgetExceeded('time limit for this turn')
        self.calls += 1
        return self.inner.generate(system, self.compact(messages), tools)


class _FixedIdStore:
    """Gives a new quote a deterministic ID so a retried submit can't create a duplicate."""

    def __init__(self, inner, quote_id):
        self.inner, self.quote_id = inner, quote_id

    def insert(self, record, *, actor_id):
        record['quote_id'] = self.quote_id
        return self.inner.insert(record, actor_id=actor_id)

    def __getattr__(self, name):
        return getattr(self.inner, name)


# ---------------------------------------------------------------- service

def visible_messages(messages: List[Dict[str, Any]], scrub=None) -> List[Dict[str, str]]:
    """What the customer sees: their own words and the assistant's text replies."""
    scrub = scrub or (lambda text: text)
    shown = []
    for message in messages:
        if message.get('role') == 'user' and not message.get('server_note'):
            shown.append({'role': 'customer', 'text': message.get('content', '')})
        elif message.get('role') == 'assistant' and (message.get('content') or '').strip():
            shown.append({'role': 'assistant', 'text': scrub(message['content'].strip())})
    return shown


def safe_arguments(arguments) -> Dict[str, Any]:
    """Model tool arguments, coerced to the shapes the draft panel shows (a model can send anything)."""
    args = arguments if isinstance(arguments, dict) else {}
    text = lambda v: v.strip()[:300] if isinstance(v, str) and v.strip() else None
    headcount = args.get('headcount')
    allergens = args.get('allergens')
    notes = args.get('customer_notes', '')
    return {
        'customer_notes': notes if isinstance(notes, str) and len(notes) <= MAX_CUSTOMER_NOTES else '',
        'event_at': text(args.get('event_at')),
        'headcount': headcount if isinstance(headcount, int) and not isinstance(headcount, bool) and headcount > 0 else None,
        'service_mode': args.get('service_mode') if args.get('service_mode') in ('pickup', 'delivery') else None,
        'address': text(args.get('address')),
        # None = not confirmed; [] = confirmed none
        'allergens': [a[:60] for a in allergens if isinstance(a, str)] if isinstance(allergens, list) else None,
    }


def customer_message_count(messages) -> int:
    return sum(1 for m in messages if m.get('role') == 'user' and not m.get('server_note'))


class ChatService:
    def __init__(self, store, *, quotes, llm_factory, owner_id, daily_turns_total=DAILY_TURNS_TOTAL):
        self.store = store
        self.quotes = quotes              # app.quotes.QuoteApp
        self.llm_factory = llm_factory    # () -> LLM client, or None when chat is not configured
        self.owner_id = owner_id          # trusted business routing, never from the browser
        self.daily_turns_total = daily_turns_total
        self._locks: Dict[str, threading.Lock] = {}
        self._recent: Dict[str, List[float]] = {}
        self._day, self._turns_today = None, 0
        self._guard = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self.llm_factory and self.owner_id)

    # ---- conversation lifecycle
    def current(self, customer_id):
        return self.store.active(customer_id=customer_id) or self.store.create(
            customer_id=customer_id, owner_id=self.owner_id)

    def start_new(self, customer_id):
        created, _ = self.store.usage_since(customer_id=customer_id, since=_start_of_day())
        if created >= DAILY_CONVERSATIONS_PER_CUSTOMER:
            logger.warning('Chat limit: %s new requests today for one customer', created)
            raise ChatLimit('You’ve started the most new requests allowed today. Continue your current one, '
                            'or try again tomorrow.', 'chat-new-limit')
        return self.store.create(customer_id=customer_id, owner_id=self.owner_id)

    def _conversation(self, record, llm=None):
        def fresh_context():  # trusted callback bound to this business, re-read every turn
            return self.quotes.context
        convo = Conversation(llm, fresh_context(), messages=record['messages'], context_loader=fresh_context)
        self._restore_latest_quote(convo)
        return convo

    @staticmethod
    def _restore_latest_quote(convo):
        """latest_quote is not part of the saved history: rebuild it by re-running the last
        evaluate call made since the customer's latest message (current data, current time)."""
        last_args = None
        for message in convo.messages:
            if message.get('role') == 'user' and not message.get('server_note'):
                last_args = None
            for call in message.get('tool_calls') or []:
                if call.get('name') == EVALUATE_TOOL['name']:
                    last_args = call.get('arguments')
        if isinstance(last_args, dict):
            try:
                convo._evaluate(last_args)
            except Exception:
                convo.latest_quote = None

    def draft(self, record) -> Optional[Dict[str, Any]]:
        """The latest priced draft for the side panel (code-computed amounts only)."""
        convo = self._conversation(record)
        quote = convo.latest_quote
        if not quote:
            return None
        result = quote['result']
        return {'status': result.get('status'), 'pricing': result.get('pricing'),
                'missing_fields': result.get('missing_fields', []),
                'blocking_reasons': result.get('blocking_reasons', []),
                'review_reasons': result.get('review_reasons', []),
                'budget': result.get('budget'), 'arguments': safe_arguments(quote['arguments']),
                'ready': convo.submission_request() is not None}

    # ---- limits
    def _lock_for(self, customer_id) -> threading.Lock:
        with self._guard:
            if len(self._locks) > 5000:  # keep memory bounded; drop locks nobody holds
                self._locks = {k: v for k, v in self._locks.items() if v.locked()}
            return self._locks.setdefault(customer_id, threading.Lock())

    def _check_rate(self, customer_id):
        now = time.monotonic()
        with self._guard:
            if len(self._recent) > 5000:
                self._recent = {k: v for k, v in self._recent.items() if v and now - v[-1] < RATE_WINDOW_SECONDS}
            recent = [t for t in self._recent.get(customer_id, []) if now - t < RATE_WINDOW_SECONDS]
            if len(recent) >= RATE_MAX_MESSAGES:
                raise ChatLimit('You’ve sent a lot of messages in the last minute. Try again in about a minute.', 'chat-rate')
            today = datetime.now(timezone.utc).date()
            if self._day != today:
                self._day, self._turns_today = today, 0
            if self._turns_today >= self.daily_turns_total:
                logger.warning('Chat limit: app-wide daily messages reached (%s)', self._turns_today)
                raise ChatLimit('The assistant has reached today’s limit. Try again tomorrow.', 'chat-daily-total')
            recent.append(now)
            self._recent[customer_id] = recent
            self._turns_today += 1

    # ---- sending
    def send(self, customer_id, conversation_id, text, *, expected_revision):
        text = clean_text(text).strip()
        if not text:
            raise ChatLimit('Type a message first.', 'chat-empty')
        if len(text) > MAX_MESSAGE_CHARS:
            raise ChatLimit(f'Keep messages under {MAX_MESSAGE_CHARS} characters.', 'chat-too-long')
        if not self.available:
            raise ChatLimit('The assistant isn’t available right now. Try again later.', 'chat-off')
        lock = self._lock_for(customer_id)
        if not lock.acquire(blocking=False):
            raise ChatLimit('Still working on your last message. One moment.', 'chat-busy')
        try:
            record = self.store.get(conversation_id, customer_id=customer_id)
            if record['quote_id']:
                raise ChatLimit('This request was already sent to the owner. Start a new request to ask for '
                                'another quote.', 'chat-submitted')
            if record['revision'] != expected_revision:
                raise ChatConflict('conversation changed; reload')
            if customer_message_count(record['messages']) >= MAX_CUSTOMER_MESSAGES:
                raise ChatLimit('This conversation is getting long. Send it for review or start a new request.',
                                'chat-long')
            _, turns_today = self.store.usage_since(customer_id=customer_id, since=_start_of_day())
            if turns_today >= DAILY_TURNS_PER_CUSTOMER:
                logger.warning('Chat limit: %s messages today for one customer', turns_today)
                raise ChatLimit('You’ve reached today’s message limit. Try again tomorrow.', 'chat-daily')
            if self._link_existing_quote(record, customer_id):
                raise ChatLimit('This request was already sent to the owner. Start a new request to ask for '
                                'changes.', 'chat-submitted')
            self._check_rate(customer_id)
            # Save the customer's message first: a submit from another tab now sees a new revision.
            before = record['messages']
            record = self.store.save(dict(record, messages=before + [{'role': 'user', 'content': text}]),
                                     customer_id=customer_id, expected_revision=expected_revision)
            convo = self._conversation(dict(record, messages=before),
                                       llm=GuardedLLM(self.llm_factory()))
            turn = convo.send(text)
            record = self.store.save(dict(record, messages=convo.messages), customer_id=customer_id,
                                     expected_revision=record['revision'])
            return record, turn
        finally:
            lock.release()

    # ---- submitting
    def _quote_id(self, record) -> str:
        return str(uuid.uuid5(QUOTE_NAMESPACE, record['conversation_id']))

    def _link_existing_quote(self, record, customer_id) -> bool:
        """A submit that stored the quote but failed to link it (e.g. a database blip) is finished here,
        so the conversation can't drift away from what the owner received."""
        if record.get('quote_id') or not customer_message_count(record['messages']):
            return False
        quote_id = self._quote_id(record)
        try:
            self.quotes.service.detail(quote_id, actor_id=customer_id)
        except QuoteNotFound:  # nothing was submitted (the usual case)
            return False
        self.store.save(dict(record, quote_id=quote_id), customer_id=customer_id, expected_revision=record['revision'])
        return True

    def submit(self, customer_id, conversation_id, *, expected_revision):
        lock = self._lock_for(customer_id)
        # Wait briefly: a double click should land on the first click's result, not a "busy" page.
        if not lock.acquire(timeout=SUBMIT_WAIT_SECONDS):
            raise ChatLimit('Still working on your last message. Wait for the reply, then send it.', 'chat-busy')
        try:
            record = self.store.get(conversation_id, customer_id=customer_id)
            if record['quote_id']:
                return record, record['quote_id']  # idempotent: already submitted
            if record['revision'] != expected_revision:
                raise ChatConflict('conversation changed; reload')
            request = self._conversation(record).submission_request()
            if request is None:
                raise ChatLimit('This draft isn’t ready yet. Answer the assistant’s questions first.', 'not-ready')
            quote_id = self._quote_id(record)
            base = self.quotes.service
            service = QuoteService(_FixedIdStore(base.store, quote_id), context_for=base.context_for, clock=base.clock)
            try:
                service.submit(request, actor_id=customer_id, owner_id=self.owner_id)
            except QuoteConflict:
                base.detail(quote_id, actor_id=customer_id)  # saved by an earlier attempt; must be ours
            record = self.store.save(dict(record, quote_id=quote_id), customer_id=customer_id,
                                     expected_revision=expected_revision)
            return record, quote_id
        finally:
            lock.release()
