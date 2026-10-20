"""Regressions for changed inquiries and owner edits during an existing chat."""
import tempfile
import unittest
from pathlib import Path
from ai_service import Conversation, ScriptedLLM, LLMResponse, ToolCall, ServerContext
from ai_service.data_loader import load_context
from menu_admin import MenuService, SQLiteMenuStore
from test_menu_admin import REQUEST, BROWNIE_PRICE, OWNER


def evaluate(args=None):
    return LLMResponse(tool_calls=[ToolCall('q', 'evaluate_catering_quote', REQUEST if args is None else args)])


def say():
    return LLMResponse(content='The owner will review the draft.')


class ChatRefreshTests(unittest.TestCase):
    def setUp(self):
        self.base = load_context('demo', '2026-10-19T12:00:00-07:00')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.menus = MenuService(SQLiteMenuStore(Path(self.tmp.name)/'menus.db'), clock=self.base.now)
        self.menus.seed(OWNER, self.base.menu)

    def fresh(self):
        return ServerContext(menu=self.menus.current_menu(OWNER), rules=self.base.rules,
                             capacity=self.base.capacity, clock=self.base.clock)

    def chat(self, steps):
        return Conversation(ScriptedLLM(steps), self.fresh(), context_loader=self.fresh)

    def test_changed_guest_count_cannot_submit_previous_request(self):
        request = dict(REQUEST, event_at='2026-11-06T12:00:00-08:00')
        chat = self.chat([evaluate(request), say(), say(), evaluate(dict(request, headcount=80)), say()])
        self.assertTrue(chat.send('Quote for 40').ready_to_submit)
        self.assertFalse(chat.send('Actually 80 guests').ready_to_submit)
        self.assertIsNone(chat.submission_request())
        self.assertTrue(chat.send('Please recalculate').ready_to_submit)
        self.assertEqual(chat.submission_request()['headcount'],80)

    def test_owner_price_edit_updates_existing_chat(self):
        chat = self.chat([evaluate(), say(), evaluate(), say()])
        old = chat.send('Quote please').quote['result']['pricing']['total_cents']
        self.menus.update(OWNER,[BROWNIE_PRICE],actor_id=OWNER,expected_revision=1)
        new = chat.send('Check current price').quote['result']['pricing']['total_cents']
        self.assertEqual(new-old,4450)  # $1 x 40 plus 11.25% tax

    def test_unavailable_item_hidden_and_blocks_existing_chat(self):
        chat = self.chat([evaluate(),say(),
            LLMResponse(tool_calls=[ToolCall('s','search_menu',{'item_ids':['pan-tri-tip']})]),evaluate(),say()])
        chat.send('Quote please')
        self.menus.update(OWNER,[{'item_id':'pan-tri-tip','set':{'available':False}}],actor_id=OWNER,expected_revision=1)
        turn=chat.send('Check menu again')
        self.assertEqual(turn.tool_calls[0]['result']['count'],0)
        self.assertFalse(turn.ready_to_submit)
        self.assertEqual(turn.quote['result']['error_code'],'menu_item_unavailable')

    def test_failed_refresh_does_not_use_old_menu_or_quote(self):
        chat=self.chat([evaluate(),say()]);chat.send('Quote please')
        def broken():raise ConnectionError('offline')
        chat.context_loader=broken
        with self.assertLogs('ai_service.conversation',level='ERROR'):
            turn=chat.send('Change guests')
        self.assertFalse(turn.ready_to_submit)
        self.assertIsNone(chat.submission_request())
        self.assertIn('context_refresh_failed',turn.warnings)
        self.assertEqual(turn.tool_calls,[])

    def test_bad_later_evaluation_clears_successful_quote(self):
        chat=self.chat([evaluate(),LLMResponse(tool_calls=[ToolCall('bad','evaluate_catering_quote',[])]),say()])
        self.assertFalse(chat.send('Quote please').ready_to_submit)
        self.assertIsNone(chat.submission_request())
