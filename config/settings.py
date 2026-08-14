from pathlib import Path
import importlib.util
import os
import sys

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file_values(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue

        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value

    return values


ENV_FILE_VALUES = _load_env_file_values(BASE_DIR / '.env')


def _get_setting(name: str, default=None):
    if name in ENV_FILE_VALUES:
        return ENV_FILE_VALUES[name]
    return os.environ.get(name, default)


def _get_first_setting(*names: str, default=None):
    for name in names:
        if name in ENV_FILE_VALUES and ENV_FILE_VALUES[name]:
            return ENV_FILE_VALUES[name]
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _as_bool(value, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _as_csv_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]

SECRET_KEY = _get_first_setting("DJANGO_SECRET_KEY", "SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is not set")

DEBUG = _as_bool(_get_first_setting("DJANGO_DEBUG", "DEBUG"), default=True)

# ترکیب مقادیر .env با مقادیر پیش‌فرض برای اطمینان از کارکرد صحیح
_allowed_hosts_from_env = _as_csv_list(_get_first_setting("DJANGO_ALLOWED_HOSTS", "ALLOWED_HOSTS"))
ALLOWED_HOSTS = list(set(_allowed_hosts_from_env + [
    "localhost",
    "127.0.0.1",
    "testserver",
    "mah.test",
    "192.168.50.242",
    "192.168.50.219",
    "mahauction.com",
    "www.mahauction.com",
    "mahauction.ir",          
    "www.mahauction.ir",      
]))


# Application definition
INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    
    'jalali_date', # پکیج شمسی
    'store.apps.StoreConfig',
    'auction',
    'core',
    'notifications.apps.NotificationsConfig',
    'accounts.apps.AccountsConfig',
    'admin_panel',
]

if importlib.util.find_spec('daphne') is not None:
    INSTALLED_APPS = ['daphne', *INSTALLED_APPS]

if importlib.util.find_spec('channels') is not None:
    INSTALLED_APPS.append('channels')

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'auction.middleware.AuctionEmailDispatchMiddleware',
    'accounts.middleware.EmailVerificationRequiredMiddleware',
    'core.middleware.ErrorLoggingMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    
    'store.middleware.VisitTrackingMiddleware', # آدرس دقیق فایل میدل‌ور شما
]

ROOT_URLCONF = 'config.urls'

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
                'core.context_processors.notification_messages',
            ],
        },
    },
]

ASGI_APPLICATION = 'config.asgi.application'
WSGI_APPLICATION = 'config.wsgi.application'

if importlib.util.find_spec('channels') is not None:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': _get_first_setting('DB_NAME') or 'art_shop',
        'USER': _get_first_setting('DB_USER') or 'root',
        'PASSWORD': _get_setting('DB_PASSWORD', ''),
        'HOST': _get_first_setting('DB_HOST') or '127.0.0.1',
        'PORT': _get_first_setting('DB_PORT') or '3306',
    }
}

if 'test' in sys.argv:
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'test_db.sqlite3',
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]
LANGUAGE_CODE = 'fa'

TIME_ZONE = 'UTC'

USE_I18N = True
USE_TZ = True
TIME_ZONE = 'Asia/Tehran'

AUTH_USER_MODEL = 'accounts.CustomUser'

# ==========================================
# Security Settings (HTTPS & Cookie Configs)
# ==========================================
# مقدار پیش‌فرض به True تغییر یافت تا تنظیمات امنیتی در سرور اعمال شوند
# اگر DEBUG=True باشد (محیط توسعه)، HTTPS غیرفعال می‌شود.
# اگر DEBUG=False باشد (محیط سرور)، مقدار USE_HTTPS از .env خوانده می‌شود.
if DEBUG:
    USE_HTTPS = False
else:
    USE_HTTPS = _as_bool(
        _get_first_setting("USE_HTTPS", "SECURE_SSL_REDIRECT"),
        default=True
    )

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 86400

if USE_HTTPS:
    # تنظیمات محیط Production
    SECURE_SSL_REDIRECT = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True

    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
else:
    # تنظیمات محیط Development
    SECURE_SSL_REDIRECT = False
    CSRF_COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False

    SECURE_BROWSER_XSS_FILTER = False
    SECURE_CONTENT_TYPE_NOSNIFF = False
    X_FRAME_OPTIONS = "SAMEORIGIN"

    SECURE_PROXY_SSL_HEADER = None


# بررسی خودکار دامنه‌های CSRF
_raw_csrf_origins = _as_csv_list(
    _get_first_setting(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "CSRF_TRUSTED_ORIGINS"
    )
)

_processed_csrf_origins = []

for origin in _raw_csrf_origins:
    if origin.startswith(("http://", "https://")):
        _processed_csrf_origins.append(origin)
    else:
        scheme = "https" if USE_HTTPS else "http"
        _processed_csrf_origins.append(f"{scheme}://{origin}")

CSRF_TRUSTED_ORIGINS = _processed_csrf_origins

# ترکیب مقادیر .env با پیش‌فرض‌ها
CSRF_TRUSTED_ORIGINS = list(set(_processed_csrf_origins + [
    "https://mahauction.com",
    "https://www.mahauction.com",
    "https://mahauction.ir",
    "https://www.mahauction.ir",
    "http://127.0.0.1",
    "http://localhost",
]))


if importlib.util.find_spec('django_redis') is not None:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': _get_first_setting('REDIS_URL') or 'redis://127.0.0.1:6379/1',
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            },
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'admin-panel-cache',
        }
    }

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    BASE_DIR / 'static',
]
STATIC_ROOT = BASE_DIR / 'static_collected'


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'home'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

ARTWORK_IMAGE_BASE = 'artworks'
ARTWORK_GALLERY_BASE = 'artworks/gallery'

TELEGRAM_BOT_TOKEN = _get_first_setting('TELEGRAM_BOT_TOKEN', 'BOT_TOKEN')
ADMIN_GROUP_CHAT_ID = (
    _get_first_setting('ADMIN_GROUP_CHAT_ID', 'TELEGRAM_CHAT_ID', 'CHAT_ID')
    or '-1003817296586'
)
TELEGRAM_WEBHOOK_SECRET_TOKEN = _get_first_setting('TELEGRAM_WEBHOOK_SECRET_TOKEN')
TELEGRAM_WEBHOOK_BASE_URL = _get_first_setting('TELEGRAM_WEBHOOK_BASE_URL')

TELEGRAM_STORE_MESSAGE_THREAD_ID = 9
TELEGRAM_AUCTION_MESSAGE_THREAD_ID = 11
TELEGRAM_CREDIT_MESSAGE_THREAD_ID = 29
TELEGRAM_MESSAGE_THREAD_ID = TELEGRAM_STORE_MESSAGE_THREAD_ID

# ==========================================
# Celery & Redis Configuration
# ==========================================
CELERY_BROKER_URL = _get_first_setting('CELERY_BROKER_URL') or 'redis://127.0.0.1:6379/0'
CELERY_RESULT_BACKEND = _get_first_setting('CELERY_RESULT_BACKEND') or 'redis://127.0.0.1:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# ==========================================
# Email SMTP Configuration
# ==========================================
EMAIL_BACKEND = _get_first_setting('EMAIL_BACKEND') or 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = _get_first_setting('EMAIL_HOST') or 'smtp.gmail.com'
EMAIL_PORT = int(_get_first_setting('EMAIL_PORT') or 587)
EMAIL_USE_TLS = _as_bool(_get_first_setting('EMAIL_USE_TLS'), default=True)
EMAIL_USE_SSL = _as_bool(_get_first_setting('EMAIL_USE_SSL'), default=False)
EMAIL_HOST_USER = _get_first_setting('EMAIL_HOST_USER') or ''
EMAIL_HOST_PASSWORD = _get_first_setting('EMAIL_HOST_PASSWORD') or ''
DEFAULT_FROM_EMAIL = _get_first_setting('DEFAULT_FROM_EMAIL') or EMAIL_HOST_USER
SERVER_EMAIL = _get_first_setting('SERVER_EMAIL') or DEFAULT_FROM_EMAIL
EMAIL_TIMEOUT = int(_get_first_setting('EMAIL_TIMEOUT') or 30)

if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise RuntimeError("EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be enabled at the same time.")

# ==========================================
# SMS.ir Configuration
# ==========================================
SMS_IR_API_KEY = _get_first_setting('SMS_IR_API_KEY') or ''
SMS_IR_BASE_URL = (_get_first_setting('SMS_IR_BASE_URL') or 'https://api.sms.ir').rstrip('/')
SMS_IR_VERIFY_ENDPOINT = _get_first_setting('SMS_IR_VERIFY_ENDPOINT') or '/v1/send/verify'
SMS_IR_TIMEOUT = int(_get_first_setting('SMS_IR_TIMEOUT') or 30)

SMS_PATTERNS = {
    'verification': {
        'code': _get_first_setting('SMS_PATTERN_VERIFICATION_CODE') or '210072',
        'variables': ('CODE',),
    },
    'signup_welcome': {
        'code': _get_first_setting('SMS_PATTERN_SIGNUP_WELCOME_CODE') or '377204',
        'variables': ('NAME',),
    },
    'auction_started': {
        'code': _get_first_setting('SMS_PATTERN_AUCTION_STARTED_CODE') or '901013',
        'variables': (
            'AUCTIONNAME',
        ),
    },
    'auction_24h': {
        'code': _get_first_setting('SMS_PATTERN_AUCTION_24H_CODE') or '962018',
        'variables': (
            'AUCTIONNAME',
            'AUCTIONSTART_DATE',
        ),
    },
    'auction_end': {
        'code': _get_first_setting('SMS_PATTERN_AUCTION_END_CODE') or '174933',
        'variables': (
            'AUCTIONNAME',
            'NAME',
            'AUCTIONEND_DATE',
        ),
    },
    'auction_Invoice': {
        'code': _get_first_setting('SMS_PATTERN_AUCTION_INVOICE_CODE') or '600256',
        'variables': (
            'AUCTIONNAME',
            'NAME',
            'LINE_ITEMS_TEXT',
            'FORMAT_AMOUNTTOTAL_AMOUNT',
        ),
    },
    'add_bid': {
        'code': _get_first_setting('SMS_PATTERN_ADD_BID_CODE') or '143304',
        'variables': (
            'NAME',
            'PRODUCT_TITLE',
            'FORMAT_AMOUNTBIDBID_AMOUNT',
        ),
    },
    'dell_bid': {
        'code': _get_first_setting('SMS_PATTERN_DELL_BID_CODE') or '456365',
        'variables': (
            'NAME',
            'PRODUCT_TITLE',
            'FORMAT_AMOUNTLATEST_BIDBID_AMOUNT',
        ),
    },
    'auction_starting_soon': {
        'code': _get_first_setting('SMS_PATTERN_AUCTION_STARTING_SOON_CODE') or '962018',
        'variables': (
            'auction_name',
            'auctionstart_date',
        ),
    },
}
