"""FastAPI web app: pages, sign-in, quote screens, health check and error handling.

Run locally:  uvicorn app.main:app --reload   (see docs/app.md for AUTH_BACKEND=memory)
Identity always comes from the auth backend verifying the session cookie; the
owner role comes from OWNER_USER_IDS. Browser forms send only quote IDs, the
displayed revision and the chosen action; QuoteService rechecks every action.
"""
import logging
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote as urlquote, urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from quote_engine.postgres_storage import QuoteStorageUnavailable
from quote_engine.pricing import QuoteError
from quote_engine.storage import QuoteConflict, QuoteNotFound

from . import catalog
from .auth import (ACCESS_COOKIE, REFRESH_COOKIE, AuthError, Authenticator, AuthUnavailable,
                   build_backend)
from .config import load_settings
from .dbcheck import HINTS, check_database, describe_dsn
from .quotes import QuoteApp

HERE = Path(__file__).resolve().parent
STATIC_VERSION = '6'
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
    'approved': ('success', 'Quote approved. The customer can now accept or decline it.'),
    'accepted': ('success', 'You accepted this quote. The owner will see your response.'),
    'declined': ('info', 'You declined this quote. The owner will see your response.'),
    'conflict': ('warning', 'This quote changed while you were viewing it. Review the latest version and try again.'),
    'failed': ('warning', 'That action isn’t available for this quote right now. Review the details below.'),
    'acknowledge': ('warning', 'Tick every review item to confirm you checked it before approving.'),
}

SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'same-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
}
PAGE_METHODS = ['GET', 'HEAD']
SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


def add_security_headers(response):
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    return response


def safe_next(value: Optional[str]) -> Optional[str]:
    """Only allow same-site relative paths after sign-in (no open redirects)."""
    if value and value.startswith('/') and not value.startswith('//') and '\\' not in value:
        return value
    return None


def create_app(*, auth_backend=None, quote_app=None) -> FastAPI:
    settings = load_settings()
    backend = auth_backend if auth_backend is not None else build_backend(settings)
    owner_ids = settings.owner_ids
    if settings.auth_backend == 'memory' and auth_backend is None:
        from . import devseed
        owner_ids = owner_ids or (devseed.DEV_OWNER_ID,)
    business_owner_id = owner_ids[0] if owner_ids else None
    authenticator = Authenticator(backend, owner_ids) if backend else None
    quotes = quote_app or QuoteApp(settings)
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
    app.state.business_owner_id = business_owner_id  # where customer requests are routed (chat PR)
    templates = Jinja2Templates(directory=str(HERE / 'templates'))
    templates.env.globals.update(static_version=STATIC_VERSION, accounts_open=backend is not None,
                                 requests_open=False)  # True once the chat PR lands
    templates.env.globals.update(review_label=quotes.review_label, field_label=quotes.field_label,
                                 event_time=quotes.event_time, tone=quotes.tone, scrub=quotes.scrub)
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
        if request.method not in SAFE_METHODS:
            source = request.headers.get('origin') or request.headers.get('referer')
            expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
            if source:
                parts = urlsplit(source)
                if f'{parts.scheme}://{parts.netloc}' != expected:
                    return error_page(request, 403)
            elif settings.is_production:  # browsers always send one of these on form posts
                return error_page(request, 403)
        # /logout ends the session itself; refreshing it first would re-issue cookies after the clear.
        if authenticator and not path.startswith('/static') and not path.startswith('/healthz') and path != '/logout':
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
        return page(request, 'index.html', menu=catalog.menu_highlights(settings.dataset),
                    example=catalog.example_quote(settings.dataset))

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
                      'conflict' if 'stale' in message or 'revision' in message else 'failed')
            return redirect(f'/quotes/{quote_id}', notice=notice)
        return redirect(f'/quotes/{quote_id}', notice=success)

    def load_list(request: Request, user, workspace: str, template: str):
        try:
            cards = quotes.service.list_quotes(actor_id=user.id, workspace=workspace)
        except QuoteStorageUnavailable:
            return error_page(request, 503)
        return page(request, template, quotes=cards)

    @app.api_route('/quotes', methods=PAGE_METHODS, response_class=HTMLResponse)
    def my_quotes(request: Request):
        user, stop = require(request, 'customer')
        return stop or load_list(request, user, 'customer', 'quotes.html')

    @app.api_route('/owner', methods=PAGE_METHODS, response_class=HTMLResponse)
    def owner_inbox(request: Request):
        user, stop = require(request, 'owner')
        return stop or load_list(request, user, 'owner', 'owner.html')

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
        return page(request, 'quote.html', quote=view)

    @app.post('/quotes/{quote_id}/approve')
    def approve(request: Request, quote_id: str, revision: int = Form(...), ack: List[str] = Form([])):
        quote_id = quote_id.lower()
        user, stop = require(request, 'owner')
        return stop or quote_action(request, user, quote_id, lambda: quotes.service.approve(
            quote_id, actor_id=user.id, expected_revision=revision,
            acknowledged_reviews=[code for code in ack if isinstance(code, str)]), 'approved')

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
