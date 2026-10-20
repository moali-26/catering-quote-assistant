"""Database connectivity check that never reveals secrets.

describe_dsn() reports the *shape* of QUOTE_DATABASE_URL (pooler vs direct host,
whether the user name carries the Supabase project ref, leftover placeholders)
without the password or the full host. check_database() connects the same way
PostgresQuoteStore does and turns a failure into a short reason code.
"""
from typing import Dict, Optional, Tuple
from urllib.parse import unquote, urlsplit

HINTS = {
    'not_configured': 'Set QUOTE_DATABASE_URL in Render to the Supabase Session pooler URI.',
    'malformed_url': 'The connection string is not a valid postgresql:// URI. Copy it again from Supabase > Connect > Session pooler.',
    'placeholder_left': 'The URI still contains [YOUR-PASSWORD] or brackets. Replace it, brackets included, with the database password.',
    'direct_host': 'This is the Direct connection (IPv6 only). Render needs the Session pooler URI (host ends in pooler.supabase.com).',
    'password_failed': 'Supabase rejected the password. Reset the database password and paste the new one into the URI.',
    'tenant_not_found': 'The pooler did not recognise the user. The user name must be postgres.<project-ref> exactly as in the Session pooler URI.',
    'host_not_found': 'The host name could not be resolved. Copy the URI again; check for typos or extra spaces.',
    'network': 'Could not reach the database (timeout or network). Check the host and port (5432 for the session pooler).',
    'missing_tables': 'Connected, but the catering_private tables are missing. Run both SQL migrations in Supabase.',
    'permission_denied': 'Connected, but the user cannot read catering_private. Use the postgres user from the Session pooler URI.',
    'ssl': 'TLS negotiation failed. Use the Supabase URI unchanged (do not add sslmode=disable).',
    'driver_missing': 'psycopg is not installed on the server. Check requirements.txt.',
    'other': 'Unexpected database error. Check the Render logs for the error type.',
}


def describe_dsn(dsn: Optional[str]) -> Dict[str, object]:
    """Secret-free summary of a connection string, safe to log."""
    if not dsn:
        return {'configured': False}
    info: Dict[str, object] = {'configured': True}
    stripped = dsn.strip()
    info['has_surrounding_spaces_or_quotes'] = stripped != dsn or stripped[:1] in '"\''
    info['has_placeholder'] = '[' in dsn or ']' in dsn or 'YOUR-PASSWORD' in dsn.upper()
    try:
        parts = urlsplit(stripped.strip('"\''))
        host = parts.hostname or ''
        user = unquote(parts.username or '')
        info['scheme'] = parts.scheme
        info['host_kind'] = ('pooler' if host.endswith('pooler.supabase.com') else
                             'direct' if host.endswith('.supabase.co') else 'other')
        info['port'] = parts.port
        info['user_has_project_ref'] = user.startswith('postgres.') and len(user) > len('postgres.')
        info['password_present'] = bool(parts.password)
        info['database'] = parts.path.lstrip('/') or None
    except ValueError:
        info['parse_error'] = True
    return info


def _shape_problem(info: Dict[str, object]) -> Optional[str]:
    if not info.get('configured'):
        return 'not_configured'
    if info.get('has_placeholder'):  # checked first: brackets also break URL parsing
        return 'placeholder_left'
    if info.get('parse_error') or info.get('scheme') not in ('postgresql', 'postgres'):
        return 'malformed_url'
    if info.get('host_kind') == 'direct':
        return 'direct_host'
    return None


def classify(message: str) -> str:
    text = (message or '').lower()
    if 'password authentication failed' in text:
        return 'password_failed'
    if 'tenant or user not found' in text or 'tenant/user' in text:
        return 'tenant_not_found'
    if 'could not translate host name' in text or 'name or service not known' in text or 'nodename nor servname' in text:
        return 'host_not_found'
    if 'does not exist' in text and ('relation' in text or 'schema' in text):
        return 'missing_tables'
    if 'permission denied' in text:
        return 'permission_denied'
    if 'ssl' in text or 'tls' in text:
        return 'ssl'
    if 'timeout' in text or 'timed out' in text or 'network is unreachable' in text or 'connection refused' in text:
        return 'network'
    return 'other'


def check_database(dsn: Optional[str]) -> Tuple[bool, str]:
    """Return (ok, reason_code). Connects like PostgresQuoteStore and reads both tables."""
    problem = _shape_problem(describe_dsn(dsn))
    if problem:
        return False, problem
    try:
        import psycopg
    except ImportError:
        return False, 'driver_missing'
    try:
        with psycopg.connect(dsn, sslmode='require', connect_timeout=5,
                             prepare_threshold=None) as db:
            db.execute('SELECT 1 FROM catering_private.quotes LIMIT 1')
            db.execute('SELECT 1 FROM catering_private.conversations LIMIT 1')
    except psycopg.Error as exc:
        return False, classify(str(exc))
    return True, 'ok'
