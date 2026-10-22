"""Owner archive: hides quotes from the owner's inbox without touching quote records."""
import os
import unittest
from pathlib import Path
from unittest import mock

import test_app_accounts as accounts
from test_app_accounts import OWNER_ID, PASSWORD
from app.archive import Archive, ArchiveUnavailable, SQLiteArchiveStore
from app.main import create_app, note_lines


@unittest.skipIf(accounts.TestClient is None, 'web dependencies not installed')
class OwnerArchiveTest(unittest.TestCase):
    client = accounts.AccountsAndQuotesTest.client
    signed_in = accounts.AccountsAndQuotesTest.signed_in
    customer = accounts.AccountsAndQuotesTest.customer
    submit_for = accounts.AccountsAndQuotesTest.submit_for

    def setUp(self):
        accounts.AccountsAndQuotesTest.setUp(self)
        self.addCleanup(self.tmp.cleanup)
        self.archive = Archive(SQLiteArchiveStore(Path(self.tmp.name) / 'archive.sqlite3'))
        self.make_app(self.archive)
        self.owner = self.signed_in('owner@example.com')
        self.ana, self.ana_id = self.customer()

    def make_app(self, archive):
        with mock.patch.dict(os.environ, {'APP_ENV': 'development', 'APP_DATASET': 'sample', 'OWNER_USER_IDS': OWNER_ID,
                                          'AUTH_BACKEND': '', 'QUOTE_DATABASE_URL': ''}):
            self.app = create_app(auth_backend=self.auth, quote_app=self.quotes, archive_app=archive)

    def answered(self):
        """A quote the owner approved and the customer accepted."""
        quote_id = self.submit_for(self.ana_id)
        view = self.quotes.service.detail(quote_id, actor_id=OWNER_ID)
        self.quotes.service.approve(quote_id, actor_id=OWNER_ID, expected_revision=view['revision'],
                                    acknowledged_reviews=view['approval_requires_acknowledgment'])
        view = self.quotes.service.detail(quote_id, actor_id=self.ana_id)
        self.quotes.service.respond(quote_id, actor_id=self.ana_id, expected_revision=view['revision'], decision='accept')
        return quote_id

    def test_archive_hides_from_inbox_only_and_restore_brings_it_back(self):
        quote_id = self.answered()
        record_before = self.quotes.service.store.get(quote_id, actor_id=OWNER_ID)
        self.assertIn(f'/quotes/{quote_id}', self.owner.get('/owner').text)
        self.assertIn('>Archive<', self.owner.get(f'/quotes/{quote_id}').text.replace('</svg>', '>'))

        response = self.owner.post(f'/quotes/{quote_id}/archive')
        self.assertEqual((response.status_code, response.headers['location']), (303, '/owner'))
        inbox = self.owner.get('/owner').text
        self.assertNotIn(f'/quotes/{quote_id}', inbox)
        self.assertIn('href="/owner/archived"', inbox)
        self.assertIn(f'/quotes/{quote_id}', self.owner.get('/owner/archived').text)
        # the quote itself, its history and the customer's view are untouched
        self.assertEqual(self.quotes.service.store.get(quote_id, actor_id=OWNER_ID), record_before)
        self.assertIn(f'/quotes/{quote_id}', self.ana.get('/quotes').text)
        page = self.owner.get(f'/quotes/{quote_id}').text
        self.assertEqual(self.owner.get(f'/quotes/{quote_id}').status_code, 200)
        self.assertIn('Restore to inbox', page)

        response = self.owner.post(f'/quotes/{quote_id}/restore')
        self.assertEqual(response.status_code, 303)
        self.assertIn(f'/quotes/{quote_id}', self.owner.get('/owner').text)
        self.assertNotIn('href="/owner/archived"', self.owner.get('/owner').text)  # nothing archived any more

    def test_archive_all_keeps_quotes_waiting_for_review(self):
        done = [self.answered(), self.answered()]
        waiting = self.submit_for(self.ana_id)
        response = self.owner.post('/owner/archive-answered')
        self.assertEqual(response.status_code, 303)
        inbox = self.owner.get('/owner').text
        self.assertIn(f'/quotes/{waiting}', inbox)
        for quote_id in done:
            self.assertNotIn(f'/quotes/{quote_id}', inbox)
        self.assertEqual(self.archive.archived_ids(OWNER_ID), set(done))
        archived = self.owner.get('/owner/archived').text
        self.assertEqual(archived.count('>Restore</button>'), 2)

    def test_only_the_quotes_owner_can_archive(self):
        quote_id = self.answered()
        self.assertEqual(self.ana.post(f'/quotes/{quote_id}/archive').status_code, 303)  # customer: sent to sign-in/home
        self.assertEqual(self.archive.archived_ids(OWNER_ID), set())
        self.assertNotIn('/archive"', self.ana.get(f'/quotes/{quote_id}').text)
        self.assertEqual(self.owner.post('/quotes/00000000-0000-4000-8000-000000000000/archive').status_code, 404)
        cross = self.owner.post(f'/quotes/{quote_id}/archive', headers={'Origin': 'https://evil.example'})
        self.assertEqual(cross.status_code, 403)
        self.assertEqual(self.archive.archived_ids(OWNER_ID), set())

    def test_inbox_works_as_before_when_the_archive_is_unavailable(self):
        quote_id = self.answered()
        broken = mock.Mock()
        broken.archived_ids.side_effect = ArchiveUnavailable('no table')
        broken.archive.side_effect = ArchiveUnavailable('no table')
        self.make_app(Archive(broken))
        owner = self.signed_in('owner@example.com')
        inbox = owner.get('/owner')
        self.assertEqual(inbox.status_code, 200)
        self.assertIn(f'/quotes/{quote_id}', inbox.text)
        self.assertNotIn('Archive all', inbox.text)
        page = owner.get(f'/quotes/{quote_id}').text
        self.assertNotIn(f'/quotes/{quote_id}/archive', page)
        response = owner.post(f'/quotes/{quote_id}/archive')
        self.assertEqual((response.status_code, response.headers['location']), (303, f'/quotes/{quote_id}'))

    def test_inbox_pages_past_the_storage_page_size(self):
        ids = [self.submit_for(self.ana_id) for _ in range(3)]
        with mock.patch('app.main.OWNER_LIST_MAX', 300), \
             mock.patch.object(self.quotes.service, 'list_quotes', wraps=self.quotes.service.list_quotes) as listing:
            self.owner.get('/owner')
        self.assertTrue(all(call.kwargs['limit'] <= 100 for call in listing.call_args_list))
        inbox = self.owner.get('/owner').text
        self.assertTrue(all(f'/quotes/{q}' in inbox for q in ids))


class NoteLinesTest(unittest.TestCase):
    def test_splits_on_semicolons_and_lines_without_changing_words(self):
        self.assertEqual(note_lines('Pasta Duo: marinara and macaroni & cheese; garden salad.'),
                         ['Pasta Duo: marinara and macaroni & cheese', 'Garden salad.'])
        self.assertEqual(note_lines('one\n\n two ;; three'), ['One', 'Two', 'Three'])
        self.assertEqual(note_lines(''), [])
        self.assertEqual(note_lines(None), [])


if __name__ == '__main__':
    unittest.main()
