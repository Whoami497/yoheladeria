# heladeria_backend/settings.py

from pathlib import Path
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-tu-clave-secreta-local')
DEBUG = os.environ.get('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '127.0.0.1,yoheladeria.onrender.com').split(',')

CSRF_TRUSTED_ORIGINS = [
    'https://yoheladeria.onrender.com',
]

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'pedidos',
    'channels',
    'webpush',
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
]

ROOT_URLCONF = 'heladeria_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'pedidos', 'templates'),
        ],
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

WSGI_APPLICATION = 'heladeria_backend.wsgi.application'

# Database
DATABASES = {
    'default': dj_database_url.config(
        conn_max_age=600,
        default='sqlite:///db.sqlite3'
    )
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Auth redirects
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
LOGIN_URL = '/accounts/login/'

# Channels
ASGI_APPLICATION = 'heladeria_backend.asgi.application'
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

# --- MERCADO PAGO ---
MERCADO_PAGO_ACCESS_TOKEN = os.environ.get('MERCADO_PAGO_ACCESS_TOKEN', '')
MERCADO_PAGO_PUBLIC_KEY = os.environ.get('MERCADO_PAGO_PUBLIC_KEY', '')

# --- WEBPUSH ---
# Preferimos variables de entorno; si no están, usamos tus claves actuales.
_VAPID_PUBLIC_ENV = os.environ.get('VAPID_PUBLIC_KEY')
_VAPID_PRIVATE_ENV = os.environ.get('VAPID_PRIVATE_KEY')
_VAPID_ADMIN_ENV = os.environ.get('VAPID_ADMIN_EMAIL')  # sin "mailto:"

WEBPUSH_SETTINGS = {
    "VAPID_PUBLIC_KEY": _VAPID_PUBLIC_ENV or "BDp_wB1ExvnVF_GXHbCY_nCuFeixaDcMOW2-x9PrXcA6bKaWku1bjn4QyMZxORPJUpZNYBznZUQ3lSXxKGjLvUc",
    "VAPID_PRIVATE_KEY": _VAPID_PRIVATE_ENV or "rc3tobb6ie6JWXwLf9YUFvkcb2yn1FV0VKxMq38ri5E",
    # guardar sin 'mailto:' porque en la vista se agrega 'mailto:' automáticamente
    "VAPID_ADMIN_EMAIL": (_VAPID_ADMIN_ENV or "lucasxlo89@gmail.com"),
}

# --- GOOGLE MAPS (Distance Matrix / Geocoding) ---
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
SUCURSAL_DIRECCION = os.environ.get('SUCURSAL_DIRECCION', 'San Martín 123, Catamarca, Argentina')
MAPS_LANGUAGE = os.environ.get('MAPS_LANGUAGE', 'es')
MAPS_REGION   = os.environ.get('MAPS_REGION', 'AR')
