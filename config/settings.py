from pathlib import Path
import importlib.util
import os
BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-_rdcpwi^ldwayj1z_&%n$cnm-(n0!hwlgvkfkmn&j=k9*kkgd='

DEBUG = True

ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    'testserver',
    'mah.test',
    '192.168.50.242',
    '192.168.50.219',
]


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
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
        'NAME': 'art_shop',  # نام دیتابیس شما در MySQL
        'USER': 'root',  # نام کاربری MySQL (اگر از لاراگون استفاده می‌کنید، معمولاً 'root' است)
        'PASSWORD': '',  # رمز عبور (اگر رمز عبور ندارید، آن را خالی بگذارید)
        'HOST': '127.0.0.1',  # آدرس میزبان دیتابیس (در لاراگون 'localhost' است)
        'PORT': '3306',  # پورت MySQL (پورت پیش‌فرض 3306 است)
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

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 86400

if importlib.util.find_spec('django_redis') is not None:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/1'),
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

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('BOT_TOKEN')
ADMIN_GROUP_CHAT_ID = (
    os.environ.get('ADMIN_GROUP_CHAT_ID')
    or os.environ.get('TELEGRAM_CHAT_ID')
    or os.environ.get('CHAT_ID')
    or '-1003817296586'
)

TELEGRAM_STORE_MESSAGE_THREAD_ID = 9
TELEGRAM_AUCTION_MESSAGE_THREAD_ID = 11
TELEGRAM_CREDIT_MESSAGE_THREAD_ID = 29
TELEGRAM_MESSAGE_THREAD_ID = TELEGRAM_STORE_MESSAGE_THREAD_ID


# python -m waitress --port=8080 config.wsgi:application
