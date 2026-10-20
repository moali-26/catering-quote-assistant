"""FastAPI web app: pages, sign-in, quote screens, health check and error handling.

Run locally:  uvicorn app.main:app --reload   (see docs/app.md for AUTH_BACKEND=memory)
Identity always comes from the auth backend verifying the session cookie; the
owner role comes from OWNER_USER_IDS. Browser forms send only quote IDs, the
displayed revision and the chosen action; QuoteService rechecks every action.
"""
import logging
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote as urlquote, urlsplit

from fastapi import FastAPI, Form, Request
from markupsafe import Markup, escape
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from quote_engine.postgres_storage import QuoteStorageUnavailable
from quote_engine.pricing import QuoteError
from quote_engine.presentation import money
from quote_engine.storage import QuoteConflict, QuoteNotFound

from . import catalog, menu_editor
from .auth import (ACCESS_COOKIE, REFRESH_COOKIE, AuthError, Authenticator, AuthUnavailable,
                   build_backend)
from .config import load_settings
from .dbcheck import HINTS, check_database, describe_dsn
from .quotes import QuoteApp
from .billing_app import build_billing
from billing import BillingError
from .chat import (ChatConflict, ChatLimit, ChatNotFound, ChatService, PostgresConversationStore,
                   SQLiteConversationStore, visible_messages)

HERE = Path(__file__).resolve().parent
STATIC_VERSION = '31'
NOTICE_COOKIE = 'cqa_notice'
REFRESH_MAX_AGE = 60 * 60 * 24 * 30
logger = logging.getLogger('app')

ERROR_COPY = {
    403: ('That request was blocked', 'For your security, actions must come from this site. Go back and try again.'),
    404: ('This page isn’t on the menu', 'The link may be out of date, or the quote belongs to a different account.'),
    405: ('That action isn’t available here', 'Go back and try again from the page you were on.'),
    503: ('This part of the site is temporarily unavailable', 'Your saved quotes are safe. Try again in a minute.'),
}
CLIENT_ERROR_COPY = ('We couldn’t complete that request', 'Check the link or go back and try again.')
SERVER_ERROR_COPY = ('Something went wrong on our side',
                     'Reload the page in a moment. If it keeps happening, try again in a few minutes.')
FALLBACK_BUSINESS = {'name': 'Catering Quote Assistant', 'place': '', 'captured_at': ''}
NOTICES = {
    'signed-out': ('info', 'You’re signed out.'),
    'menu-saved': ('success', 'Menu saved. New requests and the home page use it right away.'),
    'menu-unchanged': ('info', 'Nothing changed, so there was nothing to save.'),
    'menu-invalid': ('warning', 'Some changes need fixing (marked below). Nothing was saved yet.'),
    'menu-conflict': ('warning', 'The menu was changed in another tab or by someone else. This is the latest version; your edits were not saved.'),
    'menu-changed': ('warning', 'Prices changed since this request was priced (menu, delivery or tax). Reprice it with today’s menu, then approve.'),
    'menu-unavailable': ('warning', 'A dish in this request is off the menu, so it can’t be approved as it is. See the options below.'),
    'repriced': ('success', 'Repriced with today’s menu as a new version. Review it and approve.'),
    'approved': ('success', 'Quote approved. The customer can now accept or decline it.'),
    'accepted': ('success', 'You accepted this quote. The owner will see your response.'),
    'declined': ('info', 'You declined this quote. The owner will see your response.'),
    'conflict': ('warning', 'This quote changed while you were viewing it. Review the latest version and try again.'),
    'failed': ('warning', 'That action isn’t available for this quote right now. Review the details below.'),
    'acknowledge': ('warning', 'Tick every review item to confirm you checked it before approving.'),
    'submitted': ('success', 'Request sent. The owner will review it; check back here for the approved quote.'),
    'chat-conflict': ('warning', 'This conversation changed in another tab. Here is the latest version.'),
    'new-chat': ('info', 'Started a new request.'),
    'not-ready': ('warning', 'That draft can’t be sent yet. Check the draft details, or ask the assistant to recalculate.'),
    'confirm-needed': ('warning', 'Tick the box to confirm the event details, then send it again.'),
    'chat-busy': ('warning', 'Still working on your last message. Wait for the reply, then try again.'),
    'chat-rate': ('warning', 'You’ve sent a lot of messages in the last minute. Try again in about a minute.'),
    'chat-too-long': ('warning', 'That message was too long. Keep messages under 1,200 characters.'),
    'chat-empty': ('warning', 'Type a message first.'),
    'chat-submitted': ('info', 'That request was already sent to the owner. You’re in a new request now.'),
    'chat-long': ('warning', 'This conversation is getting long. Send it for review or start a new request.'),
    'chat-daily': ('warning', 'You’ve reached today’s limit for the assistant. Try again tomorrow.'),
    'chat-off': ('warning', 'The assistant isn’t available right now. Try again later.'),
    'chat-limit': ('warning', 'That message couldn’t be sent. Try again.'),
    'billing-paid': ('success', 'Payment confirmed with Stripe. Your software plan is active.'),
    'billing-pending': ('info', 'Stripe hasn’t confirmed the payment yet. Refresh this page in a moment.'),
    'billing-failed': ('warning', 'We couldn’t start or confirm that checkout. Nothing was charged here; try again.'),
    'billing-off': ('warning', 'Checkout isn’t set up on this server yet.'),
    'billing-canceled': ('info', 'Checkout canceled. Nothing was charged.'),
}

SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'same-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
}
PAGE_METHODS = ['GET', 'HEAD']
SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}
# Stripe calls this server-to-server: no Origin/Referer and no session. Its signature is the check.
STRIPE_WEBHOOK_PATH = '/stripe/webhook'


def add_security_headers(response):
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    return response


def safe_next(value: Optional[str]) -> Optional[str]:
    """Only allow same-site relative paths after sign-in (no open redirects)."""
    if value and value.startswith('/') and not value.startswith('//') and '\\' not in value:
        return value
    return None


def chat_format(text: str) -> Markup:
    """Escape model/customer text, then allow a tiny safe subset: paragraphs, bullets and **bold**."""
    blocks, bullets = [], []

    def inline(line):
        return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', str(escape(line)))

    def flush():
        if bullets:
            blocks.append('<ul>' + ''.join(f'<li>{b}</li>' for b in bullets) + '</ul>')
            bullets.clear()

    for raw in (text or '').splitlines():
        line = raw.strip()
        if re.match(r'^([-*•]|\d+[.)])\s+', line):
            bullets.append(inline(re.sub(r'^([-*•]|\d+[.)])\s+', '', line)))
            continue
        flush()
        if line:
            blocks.append(f'<p>{inline(line)}</p>')
    flush()
    return Markup(''.join(blocks))


def build_llm_factory(settings, clock):
    if settings.llm_provider == 'scripted':
        from .preview_llm import PreviewLLM
        return lambda: PreviewLLM(clock)
    if settings.llm_provider == 'anthropic':
        import anthropic
        from ai_service.providers import make_llm
        # One shared client; short timeout and no retry so a stuck call can't hold a turn for minutes.
        client = anthropic.Anthropic(timeout=30.0, max_retries=0)
        return lambda: make_llm('anthropic', client=client)
    if settings.llm_provider == 'openai':
        import openai
        from ai_service.providers import make_llm
        client = openai.OpenAI(timeout=30.0, max_retries=0)
        return lambda: make_llm('openai', client=client)
    return None


def build_chat_store(settings):
    if settings.database_url:
        return PostgresConversationStore(settings.database_url)
    if settings.is_production:
        return None
    folder = HERE.parent / 'var'
    folder.mkdir(exist_ok=True)
    return SQLiteConversationStore(folder / 'chat.sqlite3')


def build_menu_service(settings, clock):
    """A's MenuService on the same storage as quotes (Postgres in production, SQLite locally)."""
    from menu_admin import MenuService, SQLiteMenuStore
    if settings.database_url:
        from menu_admin.postgres_storage import PostgresMenuStore
        return MenuService(PostgresMenuStore(settings.database_url), clock=clock)
    if settings.is_production:
        return None
    folder = HERE.parent / 'var'
    folder.mkdir(exist_ok=True)
    return MenuService(SQLiteMenuStore(folder / 'menus.sqlite3'), clock=clock)


def create_app(*, auth_backend=None, quote_app=None, chat_service=None, menu_service=None,
               billing_app=None) -> FastAPI:
    settings = load_settings()
    backend = auth_backend if auth_backend is not None else build_backend(settings)
    owner_ids = settings.owner_ids
    if settings.auth_backend == 'memory' and auth_backend is None:
        from . import devseed
        owner_ids = owner_ids or (devseed.DEV_OWNER_ID,)
    business_owner_id = owner_ids[0] if owner_ids else None
    authenticator = Authenticator(backend, owner_ids) if backend else None
    quotes = quote_app or QuoteApp(settings)
    if menu_service is not None:
        quotes.attach_menus(menu_service, business_owner_id)
    elif quotes.menus is None and quote_app is None:
        quotes.attach_menus(build_menu_service(settings, quotes.base_context.now), business_owner_id)
    if settings.is_production and not settings.database_url:
        logger.warning('QUOTE_DATABASE_URL is not set: quote pages will show a temporarily unavailable message')
    if settings.database_url:
        logger.warning('QUOTE_DATABASE_URL shape (no secrets): %s', describe_dsn(settings.database_url))
    if backend is None:
        logger.warning('SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY not set: sign-in is disabled')
    if settings.auth_backend == 'memory' and auth_backend is None:
        devseed.seed(backend, quotes)

    app = FastAPI(
        title='Catering Quote Assistant',
        docs_url=None if settings.is_production else '/docs',
        redoc_url=None,
        openapi_url=None if settings.is_production else '/openapi.json',
    )
    app.state.auth_backend = backend
    app.state.quotes = quotes
    app.state.business_owner_id = business_owner_id  # where customer requests are routed
    chat = chat_service
    if chat is None:
        store = build_chat_store(settings)
        factory = build_llm_factory(settings, quotes.context.now)
        chat = ChatService(store, quotes=quotes, llm_factory=factory, owner_id=business_owner_id) if store else None
    app.state.chat = chat
    billing = billing_app if billing_app is not None else build_billing(settings, owner_ids)
    app.state.billing = billing
    if chat is None or not chat.available:
        logger.warning('Customer chat is off (needs LLM_PROVIDER/key, OWNER_USER_IDS and a database)')
    templates = Jinja2Templates(directory=str(HERE / 'templates'))
    templates.env.globals.update(static_version=STATIC_VERSION, accounts_open=backend is not None,
                                 requests_open=bool(backend is not None and chat and chat.available))
    templates.env.globals.update(review_label=quotes.review_label, block_label=quotes.customer_block_label, field_label=quotes.field_label,
                                 event_time=quotes.event_time, tone=quotes.tone, scrub=quotes.scrub)
    templates.env.filters['chat_format'] = chat_format
    templates.env.globals['money'] = money
    app.mount('/static', StaticFiles(directory=str(HERE / 'static')), name='static')
    secure_cookies = settings.is_production

    # ---- helpers ---------------------------------------------------------
    def page(request: Request, name: str, status_code: int = 200, headers=None, **context):
        if 'business' not in context:
            try:
                context['business'] = catalog.business(settings.dataset)
            except Exception:  # error pages must render even if business data fails to load
                if name != 'error.html':
                    raise
                logger.exception('Business data unavailable while rendering an error page')
                context['business'] = FALLBACK_BUSINESS
        context.setdefault('user', getattr(request.state, 'user', None))
        code = request.cookies.get(NOTICE_COOKIE)  # one-shot message set by the previous action
        context.setdefault('notice', NOTICES.get(code or ''))
        response = templates.TemplateResponse(request, name, context, status_code=status_code, headers=headers)
        if code:
            response.delete_cookie(NOTICE_COOKIE, path='/', secure=secure_cookies, httponly=True, samesite='lax')
        return add_security_headers(response)

    def error_page(request: Request, code: int):
        default = CLIENT_ERROR_COPY if code < 500 else SERVER_ERROR_COPY
        title, body = ERROR_COPY.get(code, default)
        return page(request, 'error.html', status_code=code, code=code, title=title, body=body)

    def redirect(url: str, notice: Optional[str] = None):
        response = RedirectResponse(url, status_code=303)
        if notice:
            response.set_cookie(NOTICE_COOKIE, notice, max_age=60, httponly=True, secure=secure_cookies,
                                samesite='lax', path='/')
        return response

    def set_session(response, session):
        response.set_cookie(ACCESS_COOKIE, session.access_token, max_age=session.expires_in, httponly=True,
                            secure=secure_cookies, samesite='lax', path='/')
        response.set_cookie(REFRESH_COOKIE, session.refresh_token, max_age=REFRESH_MAX_AGE, httponly=True,
                            secure=secure_cookies, samesite='lax', path='/')

    def clear_session(response):
        for name in (ACCESS_COOKIE, REFRESH_COOKIE):
            response.delete_cookie(name, path='/', secure=secure_cookies, httponly=True, samesite='lax')

    def home_for(user) -> str:
        return '/owner' if user.is_owner else '/quotes'

    def require(request: Request, role: Optional[str] = None):
        """Return (user, None) or (None, response to send instead)."""
        if authenticator is None or getattr(request.state, 'auth_down', False):
            return None, error_page(request, 503)
        user = request.state.user
        if user is None:
            target = request.url.path
            if request.method not in SAFE_METHODS:  # come back to the page, not to a POST-only URL
                target = target.rsplit('/', 1)[0] if target.startswith('/quotes/') else '/'
            return None, redirect('/login?next=' + urlquote(target))
        if role == 'owner' and not user.is_owner:
            return None, redirect('/quotes')
        if role == 'customer' and user.is_owner:
            return None, redirect('/owner')
        return user, None

    # ---- middleware ------------------------------------------------------
    @app.middleware('http')
    async def session_and_security(request: Request, call_next):
        request.state.user, request.state.auth_down, refreshed = None, False, None
        path = request.url.path
        checked = False
        if request.method not in SAFE_METHODS and path != STRIPE_WEBHOOK_PATH:
            source = request.headers.get('origin') or request.headers.get('referer')
            expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
            if source:
                parts = urlsplit(source)
                if f'{parts.scheme}://{parts.netloc}' != expected:
                    return error_page(request, 403)
            elif settings.is_production:  # browsers always send one of these on form posts
                return error_page(request, 403)
        # /logout ends the session itself; refreshing it first would re-issue cookies after the clear.
        if (authenticator and not path.startswith('/static') and not path.startswith('/healthz')
                and path not in ('/logout', STRIPE_WEBHOOK_PATH)):
            checked = True
            try:
                request.state.user, refreshed = await run_in_threadpool(
                    authenticator.resolve, request.cookies.get(ACCESS_COOKIE), request.cookies.get(REFRESH_COOKIE))
            except AuthUnavailable:
                logger.warning('Auth service unavailable while resolving a session')
                request.state.auth_down = True
        response = await call_next(request)
        if refreshed is not None:
            set_session(response, refreshed)
        elif (checked and request.state.user is None and not request.state.auth_down
              and (ACCESS_COOKIE in request.cookies or REFRESH_COOKIE in request.cookies)
              and not any(c.startswith(ACCESS_COOKIE + '=') for c in response.headers.getlist('set-cookie'))):
            clear_session(response)  # stale cookies
        response.headers.setdefault('Cache-Control', 'no-store' if request.state.user else 'no-cache')
        return add_security_headers(response)

    # ---- public pages ----------------------------------------------------
    @app.api_route('/', methods=PAGE_METHODS, response_class=HTMLResponse)
    def home(request: Request):
        try:
            current = quotes.current_menu()
        except QuoteStorageUnavailable:
            return error_page(request, 503)  # never show prices from a menu that may be out of date
        return page(request, 'index.html', menu=catalog.menu_highlights(settings.dataset, menu=current),
                    example=catalog.example_quote(settings.dataset, current_menu=current))

    @app.api_route('/healthz', methods=PAGE_METHODS)
    def healthz():
        return JSONResponse({'status': 'ok'})

    @app.api_route('/healthz/db', methods=PAGE_METHODS)
    def healthz_db():
        """Database reachability with a reason code; never includes the URI or password."""
        ok, reason = check_database(settings.database_url)
        if ok:
            return JSONResponse({'database': 'ok'})
        logger.warning('Database check failed: %s; URI shape: %s', reason, describe_dsn(settings.database_url))
        return JSONResponse({'database': 'error', 'reason': reason, 'hint': HINTS.get(reason, HINTS['other'])},
                            status_code=503, headers={'Cache-Control': 'no-store'})

    # ---- accounts --------------------------------------------------------
    @app.api_route('/login', methods=PAGE_METHODS, response_class=HTMLResponse)
    def login_page(request: Request, mode: str = 'signin', next: Optional[str] = None):
        if request.state.user:
            return redirect(safe_next(next) or home_for(request.state.user))
        return page(request, 'login.html', mode='signup' if mode == 'signup' else 'signin',
                    next=safe_next(next) or '', email='', error=None)

    def finish_sign_in(request: Request, session, next_url: Optional[str]):
        user = authenticator.user_for(session.user_id, session.email)
        response = redirect(safe_next(next_url) or home_for(user))
        set_session(response, session)
        return response

    def auth_form(request: Request, mode: str, email: str, next_url: str, action):
        if authenticator is None:
            return error_page(request, 503)
        try:
            session = action()
        except AuthError as exc:
            return page(request, 'login.html', status_code=400, mode=mode, next=safe_next(next_url) or '',
                        email=email, error=str(exc))
        except AuthUnavailable:
            return page(request, 'login.html', status_code=503, mode=mode, next=safe_next(next_url) or '',
                        email=email, error='Sign-in is temporarily unavailable. Try again in a minute.')
        return finish_sign_in(request, session, next_url)

    @app.post('/login', response_class=HTMLResponse)
    def login(request: Request, email: str = Form(''), password: str = Form(''), next: str = Form('')):
        return auth_form(request, 'signin', email, next, lambda: backend.sign_in(email, password))

    @app.post('/signup', response_class=HTMLResponse)
    def signup(request: Request, email: str = Form(''), password: str = Form(''), next: str = Form('')):
        return auth_form(request, 'signup', email, next, lambda: backend.sign_up(email, password))

    @app.post('/logout')
    def logout(request: Request):
        if authenticator:
            authenticator.sign_out(request.cookies.get(ACCESS_COOKIE), request.cookies.get(REFRESH_COOKIE))
        response = redirect('/', notice='signed-out')
        clear_session(response)
        return response

    # ---- quotes ----------------------------------------------------------
    def quote_action(request: Request, user, quote_id: str, call, success: str):
        try:
            call()
        except QuoteConflict:
            return redirect(f'/quotes/{quote_id}', notice='conflict')
        except QuoteNotFound:
            return error_page(request, 404)
        except QuoteStorageUnavailable:
            return error_page(request, 503)
        except QuoteError as exc:
            logger.info('Quote action refused for %s: %s', quote_id, exc)
            message = str(exc).lower()
            notice = ('acknowledge' if 'acknowledg' in message else
                      'menu-changed' if 'revise' in message or 'revised draft' in message else
                      'menu-unavailable' if 'unavailable' in message else
                      'conflict' if 'stale' in message or 'revision' in message else 'failed')
            return redirect(f'/quotes/{quote_id}', notice=notice)
        return redirect(f'/quotes/{quote_id}', notice=success)

    def load_list(request: Request, user, workspace: str, template: str, **extra):
        try:
            cards = quotes.service.list_quotes(actor_id=user.id, workspace=workspace)
        except QuoteStorageUnavailable:
            return error_page(request, 503)
        return page(request, template, quotes=cards, **extra)

    @app.api_route('/quotes', methods=PAGE_METHODS, response_class=HTMLResponse)
    def my_quotes(request: Request):
        user, stop = require(request, 'customer')
        return stop or load_list(request, user, 'customer', 'quotes.html')

    @app.api_route('/owner', methods=PAGE_METHODS, response_class=HTMLResponse)
    def owner_inbox(request: Request):
        user, stop = require(request, 'owner')
        if stop:
            return stop
        try:
            plan = billing.status(user.id)
        except QuoteStorageUnavailable:
            plan = None  # the inbox still works if billing storage is down
        return load_list(request, user, 'owner', 'owner.html', plan=plan)

    @app.api_route('/quotes/{quote_id}', methods=PAGE_METHODS, response_class=HTMLResponse)
    def quote_detail(request: Request, quote_id: str):
        quote_id = quote_id.lower()  # UUIDs are case-insensitive; storage backends are not
        user, stop = require(request)
        if stop:
            return stop
        try:
            view = quotes.service.detail(quote_id, actor_id=user.id)
        except QuoteStorageUnavailable:
            return error_page(request, 503)
        except QuoteError:  # not found, not yours, or malformed ID: same answer
            return error_page(request, 404)
        menu_check = {'state': 'ok'}
        if user.is_owner and view['status'] == 'draft':
            try:
                menu_check = quotes.menu_check(quote_id, actor_id=user.id)
            except QuoteError:
                logger.warning('Could not compare quote %s with the current menu', quote_id)
        return page(request, 'quote.html', quote=view, menu_check=menu_check)

    @app.post('/quotes/{quote_id}/approve')
    def approve(request: Request, quote_id: str, revision: int = Form(...), ack: List[str] = Form([])):
        quote_id = quote_id.lower()
        user, stop = require(request, 'owner')
        return stop or quote_action(request, user, quote_id, lambda: quotes.service.approve(
            quote_id, actor_id=user.id, expected_revision=revision,
            acknowledged_reviews=[code for code in ack if isinstance(code, str)]), 'approved')

    @app.post('/quotes/{quote_id}/reprice')
    def reprice(request: Request, quote_id: str, revision: int = Form(...)):
        quote_id = quote_id.lower()
        user, stop = require(request, 'owner')
        return stop or quote_action(request, user, quote_id, lambda: quotes.reprice(
            quote_id, actor_id=user.id, expected_revision=revision), 'repriced')

    # ---- owner menu ------------------------------------------------------
    def render_menu(request: Request, user, *, submitted=None, errors=None, status_code=200, notice_code=None):
        from menu_admin import MenuConflict, MenuNotFound
        from menu_admin.postgres_storage import MenuStorageUnavailable
        ctx = {'menu_groups': None, 'setup': None, 'errors': errors or {}}
        if notice_code:
            ctx['notice'] = NOTICES.get(notice_code)
        menus = quotes.menus
        if menus is None:
            return page(request, 'menu.html', status_code=503, **dict(ctx, setup='off'))
        if user.id != business_owner_id:
            return page(request, 'menu.html', status_code=403, **dict(ctx, setup='not-main-owner'))
        try:
            try:
                view = menus.owner_view(business_owner_id, actor_id=user.id)
            except MenuNotFound:  # first visit: start from the dataset's menu (server-side, trusted file)
                try:
                    menus.seed(business_owner_id, quotes.base_context.menu)
                except MenuConflict:  # another tab seeded it a moment ago; use that one
                    pass
                quotes.forget_menu()
                view = menus.owner_view(business_owner_id, actor_id=user.id)
            log = menus.change_log(business_owner_id, actor_id=user.id)[:40]
            names = dict(quotes.items)
        except (MenuStorageUnavailable, QuoteStorageUnavailable):
            return page(request, 'menu.html', status_code=503, **dict(ctx, setup='storage'))
        groups = menu_editor.editor_view(view, submitted=submitted, errors=errors)
        tz = quotes.base_context.now().tzinfo
        items = [i for g in groups for i in g['items']]
        return page(request, 'menu.html', status_code=status_code, **dict(
            ctx, menu_groups=groups, revision=view['revision'],
            updated=menu_editor.describe_change({'item_id': '', 'field': 'description', 'at': view.get('updated_at')}, {}, tz)['when'],
            stats={'items': len(items), 'off': sum(1 for i in view['items'] if not i['available']),
                   'sizes_off': sum(1 for i in view['items'] for v in i['variants'] if not v['available'])},
            history=[menu_editor.describe_change(e, names, tz) for e in log]))

    @app.api_route('/owner/menu', methods=PAGE_METHODS, response_class=HTMLResponse)
    def owner_menu(request: Request):
        user, stop = require(request, 'owner')
        return stop or render_menu(request, user)

    @app.post('/owner/menu', response_class=HTMLResponse)
    async def owner_menu_save(request: Request):
        user, stop = require(request, 'owner')
        if stop:
            return stop
        form = await request.form()
        fields = {k: v for k, v in form.items() if isinstance(v, str)}
        return await run_in_threadpool(save_menu, request, user, fields)

    def save_menu(request: Request, user, form):
        from menu_admin import MenuConflict, MenuEditError, MenuNotFound
        from menu_admin.postgres_storage import MenuStorageUnavailable
        menus = quotes.menus
        if menus is None or user.id != business_owner_id:
            return render_menu(request, user)
        submitted = None
        try:
            revision = int(form.get('revision', ''))
        except ValueError:
            return error_page(request, 400)
        try:
            view = menus.owner_view(business_owner_id, actor_id=user.id)
            changes, submitted = menu_editor.read_form(view, form)
            if not changes:
                return redirect('/owner/menu', notice='menu-unchanged')
            if revision != view['revision']:
                return render_menu(request, user, status_code=409, notice_code='menu-conflict')
            errors = menu_editor.field_errors(menus.current_menu(business_owner_id), changes)
            if errors:
                return render_menu(request, user, submitted=submitted, errors=errors, status_code=400,
                                   notice_code='menu-invalid')
            menus.update(business_owner_id, changes, actor_id=user.id, expected_revision=revision)
        except MenuConflict:
            return render_menu(request, user, status_code=409, notice_code='menu-conflict')
        except MenuEditError as exc:  # a rule only the whole menu can break
            logger.info('Menu save refused: %s', exc)
            return render_menu(request, user, submitted=submitted, status_code=400, notice_code='menu-invalid')
        except MenuNotFound:
            return render_menu(request, user)
        except (MenuStorageUnavailable, QuoteStorageUnavailable):
            return error_page(request, 503)
        quotes.forget_menu()
        return redirect('/owner/menu', notice='menu-saved')

    @app.post('/quotes/{quote_id}/respond')
    def respond(request: Request, quote_id: str, revision: int = Form(...), decision: str = Form(...)):
        quote_id = quote_id.lower()
        user, stop = require(request, 'customer')
        if stop:
            return stop
        if decision not in ('accept', 'decline'):
            return error_page(request, 400)
        return quote_action(request, user, quote_id, lambda: quotes.service.respond(
            quote_id, actor_id=user.id, expected_revision=revision, decision=decision),
            'accepted' if decision == 'accept' else 'declined')

    # ---- owner software plan (Stripe test mode) ---------------------------
    def base_url(request: Request) -> str:
        # Scheme is https behind Render thanks to --proxy-headers (see render.yaml).
        return f"{request.url.scheme}://{request.headers.get('host', '')}"

    @app.api_route('/owner/billing', methods=PAGE_METHODS, response_class=HTMLResponse)
    def owner_billing(request: Request, canceled: Optional[str] = None):
        user, stop = require(request, 'owner')
        if stop:
            return stop
        try:
            plan = billing.status(user.id)
        except QuoteStorageUnavailable:
            return error_page(request, 503)
        extra = {'notice': NOTICES['billing-canceled']} if canceled else {}
        return page(request, 'owner_billing.html', plan=plan, configured=billing.configured, **extra)

    @app.post('/owner/billing/checkout')
    def owner_billing_checkout(request: Request):
        user, stop = require(request, 'owner')
        if stop:
            return stop
        if not billing.configured:
            return redirect('/owner/billing', notice='billing-off')
        try:
            if (billing.status(user.id) or {}).get('paid'):
                return redirect('/owner/billing')  # already active: never charge twice
            url = billing.start(user.id, base_url(request))
        except BillingError as exc:
            logger.warning('Checkout could not start: %s', exc)
            return redirect('/owner/billing', notice='billing-failed')
        except QuoteStorageUnavailable:
            return error_page(request, 503)
        return RedirectResponse(url, status_code=303)

    @app.api_route('/owner/billing/success', methods=PAGE_METHODS)
    def owner_billing_success(request: Request, session_id: str = ''):
        user, stop = require(request, 'owner')
        if stop:
            return stop
        if not billing.configured:
            return redirect('/owner/billing', notice='billing-off')
        try:
            outcome = billing.confirm(user.id, session_id)  # asks Stripe; the redirect alone proves nothing
        except BillingError as exc:
            logger.warning('Checkout could not be confirmed: %s', exc)
            return redirect('/owner/billing', notice='billing-failed')
        except QuoteStorageUnavailable:
            return error_page(request, 503)
        return redirect('/owner/billing', notice='billing-paid' if outcome == 'paid' else 'billing-pending')

    @app.post(STRIPE_WEBHOOK_PATH)
    async def stripe_webhook(request: Request):
        if not billing.webhook_ready:
            return JSONResponse({'error': 'webhook not configured'}, status_code=503)
        payload = await request.body()  # raw bytes: the signature covers them exactly
        signature = request.headers.get('stripe-signature', '')
        try:
            await run_in_threadpool(billing.webhook, payload, signature)
        except BillingError as exc:
            logger.warning('Stripe webhook rejected: %s', exc)
            return JSONResponse({'error': 'rejected'}, status_code=400)
        except QuoteStorageUnavailable:
            return JSONResponse({'error': 'storage unavailable'}, status_code=503)  # Stripe retries
        return JSONResponse({'received': True})

    # ---- customer chat ---------------------------------------------------
    def chat_fragments(record, *, error=None):
        """Rendered pieces the chat page swaps in after each message (also used for the full page)."""
        context = {'messages': visible_messages(record['messages'], quotes.scrub), 'conversation': record,
                   'error': error, 'business': catalog.business(settings.dataset)}
        try:
            draft = chat.draft(record)
            draft_html = templates.env.get_template('_chat_draft.html').render(dict(context, draft=draft))
        except QuoteStorageUnavailable:
            raise
        except Exception:  # an odd model result must never lock the customer out of the page
            logger.exception('Chat draft could not be shown')
            draft = None
            draft_html = templates.env.get_template('_chat_draft.html').render(dict(context, draft=None))
        return {
            'messages': templates.env.get_template('_chat_messages.html').render(dict(context, draft=draft)),
            'draft': draft_html,
            'revision': record['revision'],
            'ready': bool(draft and draft['ready']),
            'error': error,
        }

    def latest_state(user, conversation_id, *, status, error=None, reload=False):
        """JSON with the conversation as saved now, for the page to resync after a refusal."""
        try:
            record = chat.store.get(conversation_id, customer_id=user.id)
        except ChatNotFound:
            return JSONResponse({'error': 'This conversation isn’t available.'}, status_code=404)
        except QuoteStorageUnavailable:
            return JSONResponse({'error': error or 'We couldn’t load the conversation. Try again in a minute.'},
                                status_code=503)
        payload = chat_fragments(record, error=error)
        if reload:
            payload['reload'] = True
        return JSONResponse(payload, status_code=status)

    def wants_json(request: Request) -> bool:
        return request.headers.get('x-requested-with') == 'fetch'

    @app.api_route('/chat', methods=PAGE_METHODS, response_class=HTMLResponse)
    def chat_page(request: Request):
        user, stop = require(request, 'customer')
        if stop:
            return stop
        if chat is None or not chat.available:
            return page(request, 'chat.html', unavailable=True, conversation=None, fragments=None)
        try:
            record = chat.current(user.id)
            fragments = chat_fragments(record)
        except QuoteStorageUnavailable:
            return error_page(request, 503)
        return page(request, 'chat.html', unavailable=False, conversation=record, fragments=fragments)

    @app.post('/chat/send')
    def chat_send(request: Request, conversation_id: str = Form(...), revision: int = Form(...),
                  message: str = Form('')):
        user, stop = require(request, 'customer')
        if stop:
            return JSONResponse({'error': 'Your session ended. Sign in again.'}, status_code=401) \
                if wants_json(request) and request.state.user is None else stop
        if chat is None or not chat.available:
            return error_page(request, 503)
        try:
            record, _turn = chat.send(user.id, conversation_id, message, expected_revision=revision)
        except ChatLimit as exc:
            if wants_json(request):
                return latest_state(user, conversation_id, error=str(exc),
                                    status=429 if exc.code in ('chat-rate', 'chat-busy') else 400)
            return redirect('/chat', notice=exc.code)
        except ChatConflict:
            if wants_json(request):
                return latest_state(user, conversation_id, status=409, reload=True,
                                    error='This chat changed in another tab. The latest messages are shown; '
                                          'your message is still in the box, so send it again if it’s still needed.')
            return redirect('/chat', notice='chat-conflict')
        except ChatNotFound:
            return error_page(request, 404)
        except QuoteStorageUnavailable:
            if wants_json(request):
                return JSONResponse({'error': 'We couldn’t save that message. Try again in a minute.'}, status_code=503)
            return error_page(request, 503)
        if wants_json(request):
            return JSONResponse(chat_fragments(record))
        return redirect('/chat#latest')  # without JavaScript, land on the newest reply

    @app.post('/chat/submit')
    def chat_submit(request: Request, conversation_id: str = Form(...), revision: int = Form(...),
                    confirm: str = Form('')):
        user, stop = require(request, 'customer')
        if stop:
            return stop
        if chat is None or not chat.available:
            return error_page(request, 503)
        if confirm != 'yes':
            return redirect('/chat', notice='confirm-needed')
        try:
            _record, quote_id = chat.submit(user.id, conversation_id, expected_revision=revision)
        except ChatConflict:
            return redirect('/chat', notice='chat-conflict')
        except ChatNotFound:
            return error_page(request, 404)
        except QuoteStorageUnavailable:
            return error_page(request, 503)
        except ChatLimit as exc:
            return redirect('/chat', notice=exc.code)
        except QuoteError as exc:  # a readiness/business-rule change at submit time
            logger.info('Chat submit refused: %s', exc)
            return redirect('/chat', notice='not-ready')
        return redirect(f'/quotes/{quote_id}', notice='submitted')

    @app.post('/chat/new')
    def chat_new(request: Request):
        user, stop = require(request, 'customer')
        if stop:
            return stop
        if chat is None or not chat.available:
            return error_page(request, 503)
        try:
            chat.start_new(user.id)
        except ChatLimit as exc:
            return redirect('/chat', notice=exc.code)
        except QuoteStorageUnavailable:
            return error_page(request, 503)
        return redirect('/chat', notice='new-chat')

    # ---- errors ----------------------------------------------------------
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        default = CLIENT_ERROR_COPY if exc.status_code < 500 else SERVER_ERROR_COPY
        title, body = ERROR_COPY.get(exc.status_code, default)
        return page(request, 'error.html', status_code=exc.status_code, headers=exc.headers,
                    code=exc.status_code, title=title, body=body)

    @app.exception_handler(RequestValidationError)
    async def bad_form(request: Request, exc: RequestValidationError):
        return error_page(request, 400)

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception):
        logger.exception('Unhandled error on %s', request.url.path)
        title, body = SERVER_ERROR_COPY
        return page(request, 'error.html', status_code=500, code=500, title=title, body=body)

    return app


app = create_app()
