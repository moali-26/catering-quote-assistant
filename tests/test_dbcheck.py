"""Database health check: secret-free URI shape, reason codes, and the /healthz/db endpoint."""
import os
import unittest
from unittest import mock

from app.dbcheck import check_database, classify, describe_dsn

POOLER = 'postgresql://postgres.abcdefghijklmnop:s3cretPass@aws-0-us-west-1.pooler.supabase.com:5432/postgres'


class DescribeDsnTest(unittest.TestCase):
    def test_pooler_uri_shape_without_secrets(self):
        info = describe_dsn(POOLER)
        self.assertEqual(info['host_kind'], 'pooler')
        self.assertTrue(info['user_has_project_ref'])
        self.assertTrue(info['password_present'])
        self.assertEqual(info['port'], 5432)
        text = repr(info)
        for secret in ('s3cretPass', 'abcdefghijklmnop', 'aws-0-us-west-1'):
            self.assertNotIn(secret, text)

    def test_common_mistakes_are_caught_before_connecting(self):
        cases = {
            None: 'not_configured',
            'not a url': 'malformed_url',
            'postgresql://postgres.ref:[YOUR-PASSWORD]@aws-0-us-west-1.pooler.supabase.com:5432/postgres': 'placeholder_left',
            'postgresql://postgres:pw@db.abcdefghijklmnop.supabase.co:5432/postgres': 'direct_host',
        }
        for dsn, reason in cases.items():
            self.assertEqual(check_database(dsn), (False, reason), dsn)

    def test_driver_messages_map_to_reasons(self):
        cases = {
            'FATAL:  password authentication failed for user "postgres"': 'password_failed',
            'FATAL:  Tenant or user not found': 'tenant_not_found',
            'could not translate host name "x" to address': 'host_not_found',
            'relation "catering_private.quotes" does not exist': 'missing_tables',
            'permission denied for schema catering_private': 'permission_denied',
            'connection timeout expired': 'network',
            'something odd': 'other',
        }
        for message, reason in cases.items():
            self.assertEqual(classify(message), reason, message)


try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):
    TestClient = None


@unittest.skipIf(TestClient is None, 'web dependencies not installed')
class HealthEndpointTest(unittest.TestCase):
    def client(self, **env):
        from app.main import create_app
        base = {'APP_ENV': 'production', 'AUTH_BACKEND': '', 'SUPABASE_URL': '', 'SUPABASE_PUBLISHABLE_KEY': ''}
        base.update(env)
        with mock.patch.dict(os.environ, base):
            return TestClient(create_app())

    def test_reports_reason_and_hint_without_secrets(self):
        dsn = 'postgresql://postgres.ref:[YOUR-PASSWORD]@aws-0-us-west-1.pooler.supabase.com:5432/postgres'
        response = self.client(QUOTE_DATABASE_URL=dsn).get('/healthz/db')
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body['reason'], 'placeholder_left')
        self.assertIn('hint', body)
        self.assertNotIn('pooler.supabase.com:5432', response.text)

    def test_ok_when_database_answers(self):
        with mock.patch('app.main.check_database', return_value=(True, 'ok')):
            response = self.client(QUOTE_DATABASE_URL=POOLER).get('/healthz/db')
        self.assertEqual(response.json(), {'database': 'ok'})

    def test_quoted_or_padded_url_is_cleaned(self):
        from app.config import load_settings
        with mock.patch.dict(os.environ, {'QUOTE_DATABASE_URL': f'  "{POOLER}" '}):
            self.assertEqual(load_settings().database_url, POOLER)


if __name__ == '__main__':
    unittest.main()
