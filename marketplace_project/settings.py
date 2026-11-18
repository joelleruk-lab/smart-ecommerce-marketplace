"""
Django settings for Rukomeza Market.

Configuration is environment-driven so the same code runs locally (SQLite) and
in production (PostgreSQL on Neon/Render) without secrets in the repository.
See ``.env.example`` and ``docs/DEPLOYMENT.md``.
"""

from decimal import Decimal
from pathlib import Path
import os
import urllib.parse

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name: str, default: str = '') -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-development-key-change-before-deployment',
)
DEBUG = env_bool('DJANGO_DEBUG', True)
APP_VERSION = os.environ.get('APP_VERSION', '1.0.0')

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver')
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '').strip()
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS')
if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f'https://{RENDER_EXTERNAL_HOSTNAME}')

INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'store.apps.StoreConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'store.middleware.ApiJSONMiddleware',
]

ROOT_URLCONF = 'marketplace_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'store.context_processors.marketplace_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'marketplace_project.wsgi.application'


# ---------------------------------------------------------------------------
# Database: DATABASE_URL (PostgreSQL) in production, SQLite locally.
# ---------------------------------------------------------------------------
def _database_config() -> dict:
    url = os.environ.get('DATABASE_URL', '').strip()
    if not url:
        return {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.environ.get('SQLITE_PATH', str(BASE_DIR / 'db.sqlite3')),
            'OPTIONS': {'timeout': 20},
        }
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme in ('postgres', 'postgresql'):
        config = {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': parsed.path.lstrip('/'),
            'USER': urllib.parse.unquote(parsed.username or ''),
            'PASSWORD': urllib.parse.unquote(parsed.password or ''),
            'HOST': parsed.hostname or '',
            'PORT': str(parsed.port or ''),
            'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '60')),
        }
        query = urllib.parse.parse_qs(parsed.query)
        sslmode = (query.get('sslmode') or [os.environ.get('DB_SSL_MODE', 'require')])[0]
        if sslmode and parsed.hostname not in ('localhost', '127.0.0.1'):
            config['OPTIONS'] = {'sslmode': sslmode}
        return config
    if scheme in ('sqlite', 'sqlite3'):
        return {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': parsed.path or str(BASE_DIR / 'db.sqlite3'),
            'OPTIONS': {'timeout': 20},
        }
    raise ValueError(f'Unsupported DATABASE_URL scheme: {scheme}')


DATABASES = {'default': _database_config()}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Test runs may opt into a fast hasher; production always uses the defaults.
if env_bool('FAST_TESTS', False):
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.environ.get('DJANGO_TIME_ZONE', 'Africa/Kampala')
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'web']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = Path(os.environ.get('DJANGO_MEDIA_ROOT', str(BASE_DIR / 'media')))

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

EMAIL_BACKEND = os.environ.get('DJANGO_EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'Rukomeza Market <no-reply@rukomeza.test>')

AUTH_USER_MODEL = 'store.User'
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'account'
LOGOUT_REDIRECT_URL = 'home'

# ---------------------------------------------------------------------------
# Marketplace / payment settings
# ---------------------------------------------------------------------------
SHIPPING_FEE = Decimal(os.environ.get('SHIPPING_FEE', '0'))
MAX_ORDER_LINE_QUANTITY = int(os.environ.get('MAX_ORDER_LINE_QUANTITY', '99'))
PAYMENT_GATEWAY = os.environ.get('PAYMENT_GATEWAY', 'MOCK')
MOCK_GATEWAY_SECRET = os.environ.get('MOCK_GATEWAY_SECRET', '' if not DEBUG else 'dev-mock-webhook-secret')

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# HTTPS / proxy hardening for Render, Railway, Fly.io, etc.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '2592000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_REFERRER_POLICY = 'same-origin'
    # Render performs health checks over the internal network; do not redirect
    # them to HTTPS or the check can fail.
    SECURE_REDIRECT_EXEMPT = [r'^healthz$']

if env_bool('DJANGO_BEHIND_PROXY', True):
    USE_X_FORWARDED_HOST = True

JAZZMIN_SETTINGS = {
    'site_title': 'Rukomeza Admin',
    'site_header': 'Rukomeza Market',
    'site_brand': 'Rukomeza',
    'welcome_sign': 'Marketplace administration',
    'copyright': 'Rukomeza Market',
    'show_sidebar': True,
    'navigation_expanded': True,
    'icons': {
        'store.Product': 'fas fa-box',
        'store.Order': 'fas fa-receipt',
        'store.SellerProfile': 'fas fa-store',
        'store.User': 'fas fa-users',
        'store.Category': 'fas fa-tags',
        'store.Payment': 'fas fa-credit-card',
        'store.Review': 'fas fa-star',
        'store.Dispute': 'fas fa-scale-balanced',
    },
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'simple': {'format': '[{levelname}] {asctime} {name}: {message}', 'style': '{'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'}},
    'root': {'handlers': ['console'], 'level': os.environ.get('LOG_LEVEL', 'INFO')},
}
