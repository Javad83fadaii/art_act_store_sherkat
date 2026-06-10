from pathlib import Path
import importlib.util
import os

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
LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True
USE_TZ = True
TIME_ZONE = 'Asia/Tehran'

AUTH_USER_MODEL = 'accounts.CustomUser'

# ==========================================
# Security Settings (HTTPS & Cookie Configs)
# ==========================================
# مقدار پیش‌فرض به True تغییر یافت تا تنظیمات امنیتی در سرور اعمال شوند
USE_HTTPS = _as_bool(_get_first_setting("USE_HTTPS", "SECURE_SSL_REDIRECT"), default=True)

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 86400

if USE_HTTPS:
    # این تنظیمات برای استفاده از دامنه و گواهی SSL (HTTPS) فعال خواهند شد
    SECURE_SSL_REDIRECT = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
else:
    SECURE_SSL_REDIRECT = False
    CSRF_COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = _as_bool(_get_first_setting("SESSION_COOKIE_SECURE"), default=False)
    X_FRAME_OPTIONS = 'SAMEORIGIN'


# بررسی خودکار دامنه‌های خوانده شده از .env و اضافه کردن https:// در صورت نیاز
_raw_csrf_origins = _as_csv_list(_get_first_setting("DJANGO_CSRF_TRUSTED_ORIGINS", "CSRF_TRUSTED_ORIGINS"))
_processed_csrf_origins = []
for origin in _raw_csrf_origins:
    if not origin.startswith("http://") and not origin.startswith("https://"):
        _processed_csrf_origins.append(f"https://{origin}")
    else:
        _processed_csrf_origins.append(origin)

# ترکیب مقادیر .env با پیش‌فرض‌ها
CSRF_TRUSTED_ORIGINS = list(set(_processed_csrf_origins + [
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
