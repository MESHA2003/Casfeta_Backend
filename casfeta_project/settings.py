"""
Django settings for the CASFETA Zanzibar Digital Management & Ministry Platform (CZDMP).

Short name : CZDMP
Owner      : CASFETA Jimbo la Zanzibar
Scope      : Zanzibar only (Jimbo level down to branches and members)

Configuration is environment driven so that the same code base can run with
SQLite (local development / test), MySQL (recommended production database)
or PostgreSQL.
"""

from datetime import timedelta
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def env_bool(name, default=False):
    """Read a boolean value from the environment."""
    return str(os.environ.get(name, str(default))).strip().lower() in {'1', 'true', 'yes', 'on'}


def env_list(name, default=''):
    """Read a comma separated list from the environment."""
    return [item.strip() for item in str(os.environ.get(name, default)).split(',') if item.strip()]


def env_int(name, default=0):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Core security settings
# ---------------------------------------------------------------------------

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'unsafe-development-key')
DEBUG = env_bool('DJANGO_DEBUG', True)

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,your-domain.com,192.168.0.115')

CSRF_TRUSTED_ORIGINS = env_list(
    'DJANGO_CSRF_TRUSTED_ORIGINS',
    'http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080,http://192.168.0.115:8080',
)


# ---------------------------------------------------------------------------
# Applications  (SRS section 56 - modular Django apps)
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',

    # CZDMP modules
    'core',
    'accounts',
    'audit',
    'branches',
    'members',
    'leadership',
    'ministries',
    'events',
    'attendance',
    'finance',
    'reports',
    'notifications',
    'resources',
    'prayer',
    'testimonies',
    'certificates',

    # Legacy CASFETA modules (kept for backwards compatibility)
    'myapp1',
    'api',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # Must be first
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'casfeta_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'casfeta_project.wsgi.application'
ASGI_APPLICATION = 'casfeta_project.asgi.application'

# ---------------------------------------------------------------------------
# Database  (SRS section 52 / 82 - MySQL recommended, configurable)
# ---------------------------------------------------------------------------

DB_ENGINE = os.environ.get('DB_ENGINE', 'sqlite').strip().lower()

if DB_ENGINE in {'mysql', 'mariadb'}:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('DB_NAME', 'casfeta_czdmp'),
            'USER': os.environ.get('DB_USER', 'root'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '3306'),
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
elif DB_ENGINE in {'postgres', 'postgresql'}:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'webapp'),
            'USER': os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.environ.get('DB_NAME', str(BASE_DIR / 'db.sqlite3')),
        }
    }


# ---------------------------------------------------------------------------
# Django REST Framework  (SRS section 45 - JWT authentication, RBAC)
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'core.pagination.StandardResultsSetPagination',
    'PAGE_SIZE': 25,
    'EXCEPTION_HANDLER': 'core.exceptions.czdmp_exception_handler',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'login': '20/min',
        'public_join': '10/hour',
        'prayer_request': '30/hour',
        'qr_scan': '240/min',
    },
    'TEST_REQUEST_DEFAULT_FORMAT': 'json',
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=env_int('JWT_ACCESS_MINUTES', 60)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=env_int('JWT_REFRESH_DAYS', 7)),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': os.environ.get('JWT_SIGNING_KEY', SECRET_KEY),
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'TOKEN_OBTAIN_SERIALIZER': 'accounts.serializers.CZDMPTokenObtainPairSerializer',
}


# ---------------------------------------------------------------------------
# CORS  (SRS section 45)
# ---------------------------------------------------------------------------

CORS_ALLOW_CREDENTIALS = True
# Chrome sends a private-network preflight when the UI is opened through the
# machine's LAN address (e.g. http://192.168.0.115:8080) while the API lives on
# 127.0.0.1; that preflight only succeeds with this response header.
CORS_ALLOW_PRIVATE_NETWORK = True
CORS_ALLOWED_ORIGINS = env_list(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080,http://192.168.0.115:8080,http://192.168.0.115:3000,http://192.168.0.115:5173',
)
# While developing, allow every origin so the UI keeps working when it is
# opened via localhost, 127.0.0.1 or a LAN address whose IP may change (the API
# itself only listens on 127.0.0.1). With DEBUG off only the list above is used.
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
APPEND_SLASH = True

X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_REFERRER_POLICY = 'same-origin'

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env_int('SECURE_HSTS_SECONDS', 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# ---------------------------------------------------------------------------
# Static and media files  (SRS section 62 - evidence uploads)
# ---------------------------------------------------------------------------

STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'staticfiles')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles_collected')

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Upload validation limits (SRS section 45 - file validation)
MAX_UPLOAD_SIZE_MB = env_int('MAX_UPLOAD_SIZE_MB', 20)
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = env_list(
    'ALLOWED_UPLOAD_EXTENSIONS',
    'pdf,doc,docx,ppt,pptx,xls,xlsx,csv,txt,png,jpg,jpeg,gif,webp,mp3,mp4,webm,m4a,zip',
)

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# Internationalisation  (SRS section 51 - Kiswahili primary, English secondary)
# ---------------------------------------------------------------------------

LANGUAGE_CODE = os.environ.get('DJANGO_LANGUAGE_CODE', 'sw')
LANGUAGES = [
    ('sw', 'Kiswahili'),
    ('en', 'English'),
]
LOCALE_PATHS = [os.path.join(BASE_DIR, 'locale')]
TIME_ZONE = os.environ.get('DJANGO_TIME_ZONE', 'Africa/Dar_es_Salaam')
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Authentication / password policy  (SRS section 45)
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': env_int('MIN_PASSWORD_LENGTH', 8)}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ---------------------------------------------------------------------------
# CZDMP platform configuration  (SRS sections 8, 9, 85, 86, 87)
# ---------------------------------------------------------------------------

CZDMP = {
    # Fallback percentage only. The authoritative value is stored in the
    # FinancialPolicy table so that administrators can change it without code
    # changes. Only Jimbo administrators may edit financial policies.
    'DEFAULT_JIMBO_CONTRIBUTION_PERCENTAGE': os.environ.get('JIMBO_CONTRIBUTION_PERCENTAGE', '10.00'),
    'DEFAULT_CURRENCY': os.environ.get('DEFAULT_CURRENCY', 'TZS'),
    'DEFAULT_LANGUAGE': 'sw',
    'REPORT_DEADLINE_DAY': env_int('REPORT_DEADLINE_DAY', 5),
    'CONTRIBUTION_DUE_DAYS': env_int('CONTRIBUTION_DUE_DAYS', 7),
    'ORG_TIME_ZONE': os.environ.get('DJANGO_TIME_ZONE', 'Africa/Dar_es_Salaam'),
}

# Notification channels (SRS sections 11, 44). Only 'console' is active in
# development; email/SMS/WhatsApp require credentials and are optional.
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = env_int('EMAIL_PORT', 587)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@casfeta-zanzibar.or.tz')

SMS_GATEWAY_URL = os.environ.get('SMS_GATEWAY_URL', '')
SMS_GATEWAY_API_KEY = os.environ.get('SMS_GATEWAY_API_KEY', '')
WHATSAPP_GATEWAY_URL = os.environ.get('WHATSAPP_GATEWAY_URL', '')

# Backup directory (SRS section 47)
BACKUP_DIR = os.environ.get('BACKUP_DIR', str(BASE_DIR / 'backups'))


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'czdmp.finance': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
