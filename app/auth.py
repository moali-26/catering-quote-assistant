"""Sign-in, sign-up and server-side identity checks.

Supabase Auth stores accounts and passwords; this module only talks to its HTTP API.
Every request's identity comes from Supabase verifying the access token
(GET /auth/v1/user), never from a browser-supplied user ID or role.
The owner role comes from server configuration (OWNER_USER_IDS), never from sign-up.
"""
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import httpx

ACCESS_COOKIE = 'cqa_access'
REFRESH_COOKIE = 'cqa_refresh'
VERIFY_CACHE_SECONDS = 60
MIN_PASSWORD_LENGTH = 8
REJECTED = {400, 401, 403}  # token invalid or revoked: treat as signed out
NEGATIVE_CACHE_SECONDS = 30


class AuthError(Exception):
    """A problem the person can fix (wrong password, email taken). Safe to show."""


class AuthUnavailable(Exception):
    """The auth service could not be reached. Show a retry message."""


@dataclass(frozen=True)
class User:
    id: str
    email: str
    role: str  # 'owner' or 'customer'

    @property
    def is_owner(self) -> bool:
        return self.role == 'owner'


@dataclass(frozen=True)
class Session:
    access_token: str
    refresh_token: str
    expires_in: int
    user_id: str
    email: str


def _clean_email(email: str) -> str:
    email = (email or '').strip().lower()
    if '@' not in email or len(email) > 254:
        raise AuthError('Enter a valid email address.')
    return email


def _check_password(password: str) -> str:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f'Use a password with at least {MIN_PASSWORD_LENGTH} characters.')
    return password


class SupabaseAuth:
    """Minimal client for the Supabase Auth (GoTrue) REST API."""

    def __init__(self, url: str, publishable_key: str, *, client: Optional[httpx.Client] = None):
        self.base = url.rstrip('/') + '/auth/v1'
        self.key = publishable_key
        self.client = client or httpx.Client(timeout=5)

    def _post(self, path: str, payload: dict, token: Optional[str] = None) -> httpx.Response:
        headers = {'apikey': self.key, 'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        try:
            return self.client.post(self.base + path, json=payload, headers=headers)
        except httpx.HTTPError:
            raise AuthUnavailable('auth service unreachable') from None

    @staticmethod
    def _error_code(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return ''
        return str(body.get('error_code') or body.get('error') or '')

    @staticmethod
    def _session(body: dict) -> Session:
        user = body.get('user') or {}
        if not body.get('access_token') or not user.get('id'):
            raise AuthUnavailable('unexpected auth response')
        return Session(access_token=body['access_token'], refresh_token=body.get('refresh_token', ''),
                       expires_in=int(body.get('expires_in') or 3600),
                       user_id=user['id'], email=user.get('email', ''))

    def sign_up(self, email: str, password: str) -> Session:
        email, password = _clean_email(email), _check_password(password)
        response = self._post('/signup', {'email': email, 'password': password})
        code = self._error_code(response)
        if response.status_code == 429:
            raise AuthError('Too many attempts. Wait a minute and try again.')
        if code in ('user_already_exists', 'email_exists') or response.status_code == 422 and 'exist' in code:
            raise AuthError('An account with this email already exists. Sign in instead.')
        if code == 'weak_password':
            raise AuthError(f'Choose a stronger password (at least {MIN_PASSWORD_LENGTH} characters, not a common one).')
        if response.status_code >= 500:
            raise AuthUnavailable('auth service error')
        if response.status_code >= 400:
            raise AuthError('We couldn’t create that account. Check the email and password.')
        body = response.json()
        if not body.get('access_token'):
            # Email confirmation is switched on in Supabase; the demo expects it off.
            raise AuthError('Check your inbox to confirm your email, then sign in.')
        return self._session(body)

    def sign_in(self, email: str, password: str) -> Session:
        email = _clean_email(email)
        if not password:
            raise AuthError('Enter your password.')
        response = self._post('/token?grant_type=password', {'email': email, 'password': password})
        if response.status_code == 429:
            raise AuthError('Too many attempts. Wait a minute and try again.')
        if response.status_code >= 500:
            raise AuthUnavailable('auth service error')
        if response.status_code >= 400:
            if self._error_code(response) == 'email_not_confirmed':
                raise AuthError('Confirm your email first, then sign in.')
            raise AuthError('Email or password is incorrect.')
        return self._session(response.json())

    def refresh(self, refresh_token: str) -> Optional[Session]:
        if not refresh_token:
            return None
        response = self._post('/token?grant_type=refresh_token', {'refresh_token': refresh_token})
        if response.status_code in REJECTED:
            return None
        if response.status_code != 200:  # 429 rate limit, 5xx: keep the session, show a retry page
            raise AuthUnavailable('auth service error')
        return self._session(response.json())

    def verify(self, access_token: str) -> Optional[Tuple[str, str]]:
        """Return (user_id, email) if Supabase accepts the token, else None."""
        try:
            response = self.client.get(self.base + '/user', headers={
                'apikey': self.key, 'Authorization': f'Bearer {access_token}'})
        except httpx.HTTPError:
            raise AuthUnavailable('auth service unreachable') from None
        if response.status_code in REJECTED:
            return None
        if response.status_code != 200:
            raise AuthUnavailable('auth service error')
        body = response.json()
        return (body['id'], body.get('email', '')) if body.get('id') else None

    def sign_out(self, access_token: str) -> None:
        try:
            self._post('/logout', {}, token=access_token)
        except AuthUnavailable:
            pass  # cookies are cleared regardless


class MemoryAuth:
    """In-process accounts for local development and tests only (never production)."""

    def __init__(self):
        self._users: Dict[str, Tuple[str, str]] = {}   # email -> (user_id, password hash)
        self._tokens: Dict[str, Tuple[str, str]] = {}  # access token -> (user_id, email)
        self._refresh: Dict[str, Tuple[str, str]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _hash(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    def _issue(self, user_id: str, email: str) -> Session:
        access, refresh = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        self._tokens[access] = (user_id, email)
        self._refresh[refresh] = (user_id, email)
        return Session(access, refresh, 3600, user_id, email)

    def sign_up(self, email: str, password: str, *, user_id: Optional[str] = None) -> Session:
        email, password = _clean_email(email), _check_password(password)
        with self._lock:
            if email in self._users:
                raise AuthError('An account with this email already exists. Sign in instead.')
            import uuid
            uid = user_id or str(uuid.uuid4())
            self._users[email] = (uid, self._hash(password))
            return self._issue(uid, email)

    def sign_in(self, email: str, password: str) -> Session:
        email = _clean_email(email)
        with self._lock:
            found = self._users.get(email)
            if not found or not secrets.compare_digest(found[1], self._hash(password or '')):
                raise AuthError('Email or password is incorrect.')
            return self._issue(found[0], email)

    def refresh(self, refresh_token: str) -> Optional[Session]:
        with self._lock:
            found = self._refresh.pop(refresh_token, None)
            return self._issue(*found) if found else None

    def verify(self, access_token: str) -> Optional[Tuple[str, str]]:
        return self._tokens.get(access_token)

    def sign_out(self, access_token: str) -> None:
        with self._lock:
            found = self._tokens.pop(access_token, None)
            if found:  # like Supabase's global sign-out: end every session of this user
                for store in (self._tokens, self._refresh):
                    for token in [t for t, owner in store.items() if owner[0] == found[0]]:
                        store.pop(token, None)

    def expire(self, access_token: str) -> None:
        """Test helper: simulate an expired access token."""
        self._tokens.pop(access_token, None)


class Authenticator:
    """Turns cookies into a verified User, with a short in-memory verification cache."""

    def __init__(self, backend, owner_ids):
        self.backend = backend
        self.owner_ids = frozenset(owner_ids)
        self._cache: Dict[str, Tuple[float, str, str]] = {}
        self._lock = threading.Lock()

    def user_for(self, user_id: str, email: str) -> User:
        return User(id=user_id, email=email, role='owner' if user_id.lower() in self.owner_ids else 'customer')

    def _cached(self, token: str) -> Optional[Tuple[str, str]]:
        key = hashlib.sha256(token.encode()).hexdigest()
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > now:
                return (hit[1], hit[2]) if hit[1] else None
        found = self.backend.verify(token)
        with self._lock:
            if len(self._cache) > 2000:
                self._cache.clear()
            if found:
                self._cache[key] = (now + VERIFY_CACHE_SECONDS, found[0], found[1])
            else:  # remember rejected tokens briefly so a bad cookie can't hammer Supabase
                self._cache[key] = (now + NEGATIVE_CACHE_SECONDS, '', '')
        return found

    def sign_out(self, access_token: Optional[str], refresh_token: Optional[str]) -> None:
        """End the session server-side, even when only the refresh cookie is left."""
        if not access_token and refresh_token:
            try:
                session = self.backend.refresh(refresh_token)
            except AuthUnavailable:
                session = None
            access_token = session.access_token if session else None
        if access_token:
            try:
                self.backend.sign_out(access_token)
            except AuthUnavailable:
                pass
            self.forget(access_token)

    def forget(self, token: Optional[str]) -> None:
        if token:
            with self._lock:
                self._cache.pop(hashlib.sha256(token.encode()).hexdigest(), None)

    def resolve(self, access_token: Optional[str], refresh_token: Optional[str]):
        """Return (User or None, new Session or None if tokens were refreshed)."""
        if access_token:
            found = self._cached(access_token)
            if found:
                return self.user_for(*found), None
        if refresh_token:
            session = self.backend.refresh(refresh_token)
            if session:
                return self.user_for(session.user_id, session.email), session
        return None, None


def build_backend(settings):
    if settings.auth_backend == 'supabase':
        return SupabaseAuth(settings.supabase_url, settings.supabase_key)
    if settings.auth_backend == 'memory':
        return MemoryAuth()
    return None
