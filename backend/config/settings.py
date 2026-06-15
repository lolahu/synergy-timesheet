"""
Django settings for config project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

from .env import database_config, env_bool, env_csv, media_root

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


# ── Security ──────────────────────────────────────────────────────────────────

DEFAULT_SECRET_KEY = 'django-insecure-*f8_q$l)7d6azjrxvuv2pguci(2#rvqf@t0&_r3unby0%0k*o7'
SECRET_KEY = os.environ.get('SECRET_KEY', DEFAULT_SECRET_KEY)

DEBUG = env_bool('DEBUG', default=True)

if not DEBUG and SECRET_KEY == DEFAULT_SECRET_KEY:
    raise ImproperlyConfigured('SECRET_KEY must be set when DEBUG=False.')

ALLOWED_HOSTS = env_csv('ALLOWED_HOSTS', default='127.0.0.1,localhost')

CSRF_TRUSTED_ORIGINS = env_csv('CSRF_TRUSTED_ORIGINS')

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', default=not DEBUG)
SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', default=not DEBUG)
CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', default=not DEBUG)
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False)
SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', default=False)


# ── Application ───────────────────────────────────────────────────────────────

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # serves static files in production
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# ── Database ──────────────────────────────────────────────────────────────────
# Uses PostgreSQL in production (when DATABASE_URL or DB_* env vars are set),
# falls back to SQLite for local development.

DATABASES = database_config(BASE_DIR)


# ── Password validation ───────────────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ── Internationalization ──────────────────────────────────────────────────────

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/Toronto'
USE_I18N = True
USE_TZ = True


# ── Static files ──────────────────────────────────────────────────────────────

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# ── Media files (user uploads e.g. parking receipts) ─────────────────────────

MEDIA_URL = '/media/'
MEDIA_ROOT = media_root(BASE_DIR)

# Max upload size: 10MB (phones can produce large photos)
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB


# ── Default primary key ───────────────────────────────────────────────────────

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ── Email (SendGrid) ──────────────────────────────────────────────────────────
# In production set these env vars in Railway:
#   EMAIL_HOST_USER = apikey
#   EMAIL_HOST_PASSWORD = SG.xxxxxxx  (your SendGrid API key)
#   DEFAULT_FROM_EMAIL = noreply@yourdomain.com

EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend'  # prints to terminal in dev
)
EMAIL_HOST = 'smtp.sendgrid.net'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@example.com')

# Redirect to home after login/logout
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# Role group names
FOREMAN_GROUP_NAME = os.environ.get('FOREMAN_GROUP_NAME', 'Foreman')

# Foremen enter last week's timesheet until this weekday, then the current week.
TIMESHEET_ENTRY_DEADLINE_WEEKDAY = os.environ.get('TIMESHEET_ENTRY_DEADLINE_WEEKDAY', 'Tuesday')
