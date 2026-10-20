"""FastAPI web app: pages, health check and error handling.

Run locally:  uvicorn app.main:app --reload
Auth, quote screens and chat are added in later PRs (see docs/app.md).
"""
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import catalog
from .config import load_settings

HERE = Path(__file__).resolve().parent
STATIC_VERSION = '2'
logger = logging.getLogger('app')

ERROR_COPY = {
    404: ('This page isn’t on the menu', 'The link may be out of date. Head back to the start to request a quote.'),
    405: ('That action isn’t available here', 'Go back and try again from the page you were on.'),
}
CLIENT_ERROR_COPY = ('We couldn’t complete that request', 'Check the link or go back and try again.')
SERVER_ERROR_COPY = ('Something went wrong on our side',
                     'Reload the page in a moment. If it keeps happening, try again in a few minutes.')
FALLBACK_BUSINESS = {'name': 'Catering Quote Assistant', 'place': '', 'captured_at': ''}

SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'same-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
}
PAGE_METHODS = ['GET', 'HEAD']


def add_security_headers(response):
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    return response


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(
        title='Catering Quote Assistant',
        docs_url=None if settings.is_production else '/docs',
        redoc_url=None,
        openapi_url=None if settings.is_production else '/openapi.json',
    )
    templates = Jinja2Templates(directory=str(HERE / 'templates'))
    templates.env.globals.update(static_version=STATIC_VERSION, accounts_open=False)
    app.mount('/static', StaticFiles(directory=str(HERE / 'static')), name='static')

    def page(request: Request, name: str, status_code: int = 200, headers=None, **context):
        if 'business' not in context:
            try:
                context['business'] = catalog.business(settings.dataset)
            except Exception:  # error pages must render even if business data fails to load
                if name != 'error.html':
                    raise
                logger.exception('Business data unavailable while rendering an error page')
                context['business'] = FALLBACK_BUSINESS
        response = templates.TemplateResponse(request, name, context, status_code=status_code, headers=headers)
        return add_security_headers(response)

    @app.middleware('http')
    async def security_headers(request: Request, call_next):
        return add_security_headers(await call_next(request))

    @app.api_route('/', methods=PAGE_METHODS, response_class=HTMLResponse)
    def home(request: Request):
        return page(
            request, 'index.html',
            menu=catalog.menu_highlights(settings.dataset),
            example=catalog.example_quote(settings.dataset),
        )

    @app.api_route('/login', methods=PAGE_METHODS, response_class=HTMLResponse)
    def login(request: Request):
        return page(request, 'login.html')

    @app.api_route('/healthz', methods=PAGE_METHODS)
    def healthz():
        return JSONResponse({'status': 'ok'})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        default = CLIENT_ERROR_COPY if exc.status_code < 500 else SERVER_ERROR_COPY
        title, body = ERROR_COPY.get(exc.status_code, default)
        return page(request, 'error.html', status_code=exc.status_code, headers=exc.headers,
                    code=exc.status_code, title=title, body=body)

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception):
        logger.exception('Unhandled error on %s', request.url.path)
        title, body = SERVER_ERROR_COPY
        return page(request, 'error.html', status_code=500, code=500, title=title, body=body)

    return app


app = create_app()
