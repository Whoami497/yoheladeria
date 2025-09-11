# heladeria_backend/settings.py

from pathlib import Path
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Claves y modo ---
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-tu-clave-secreta-local')
DEBUG = os.environ.get('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '127.0.0.1,yoheladeria.onrender.com').split(',')

# CSRF (producción + dev local)
CSRF_TRUSTED_ORIGINS = [
    'https://yoheladeria.onrender.com',
]
if DEBUG:
    CSRF_TRUSTED_ORIGINS += ['http://127.0.0.1:8000', 'http://localhost:8000']

# Para proxies (Render) y HTTPS correcto en request.is_secure()
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Cookies seguras en prod
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_SSL_REDIRECT = not DEBUG

# --- Apps ---
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Proyecto
    'pedidos',

    # Realtime / push
    'channels',
    'webpush',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # static en prod
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
                'pedidos.context_processors.store_status',  # ← agregado
            ],
        },
    },
]

WSGI_APPLICATION = 'heladeria_backend.wsgi.application'

# --- Base de datos ---
DATABASES = {
    'default': dj_database_url.config(
        conn_max_age=600,
        default='sqlite:///db.sqlite3'
    )
}

# --- Password validators ---
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --- i18n / zona horaria ---
LANGUAGE_CODE = 'es-ar'
TIME_ZONE = 'America/Argentina/Buenos_Aires'
USE_I18N = True
USE_TZ = True

# --- Archivos estáticos y media ---
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# --- Auth redirects ---
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
LOGIN_URL = '/accounts/login/'

# --- Channels ---
ASGI_APPLICATION = 'heladeria_backend.asgi.application'
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',  # OK para 1 dyno / MVP
    },
}

# --- MERCADO PAGO ---
MERCADO_PAGO_ACCESS_TOKEN = os.environ.get('MERCADO_PAGO_ACCESS_TOKEN', '')
MERCADO_PAGO_PUBLIC_KEY = os.environ.get('MERCADO_PAGO_PUBLIC_KEY', '')

# --- WEBPUSH ---
_VAPID_PUBLIC_ENV = os.environ.get('VAPID_PUBLIC_KEY')
_VAPID_PRIVATE_ENV = os.environ.get('VAPID_PRIVATE_KEY')
_VAPID_ADMIN_ENV = os.environ.get('VAPID_ADMIN_EMAIL')  # sin "mailto:"

WEBPUSH_SETTINGS = {
    "VAPID_PUBLIC_KEY": _VAPID_PUBLIC_ENV or "BDp_wB1ExvnVF_GXHbCY_nCuFeixaDcMOW2-x9PrXcA6bKaWku1bjn4QyMZxORPJUpZNYBznZUQ3lSXxKGjLvUc",
    "VAPID_PRIVATE_KEY": _VAPID_PRIVATE_ENV or "rc3tobb6ie6JWXwLf9YUFvkcb2yn1FV0VKxMq38ri5E",
    "VAPID_ADMIN_EMAIL": (_VAPID_ADMIN_ENV or "lucasxlo89@gmail.com"),
}

# --- GOOGLE MAPS (Distance Matrix / Geocoding) ---
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
GOOGLE_GEOCODING_KEY = os.environ.get("GOOGLE_GEOCODING_KEY", "")
SUCURSAL_DIRECCION = os.environ.get('SUCURSAL_DIRECCION', 'San Martín 123, Catamarca, Argentina')
MAPS_LANGUAGE = os.environ.get('MAPS_LANGUAGE', 'es')
MAPS_REGION   = os.environ.get('MAPS_REGION', 'AR')
# Sesgo opcional para geocoding (no estrictamente usado, pero útil si lo activamos)
MAPS_COMPONENTS = os.environ.get('MAPS_COMPONENTS', 'country:AR|administrative_area:Catamarca')

# --- ENVÍOS (calibrables) ---
# costo = ENVIO_BASE + ENVIO_POR_KM * (km_efectivos)
# km_efectivos = max(km, ENVIO_KM_MIN) + ENVIO_KM_OFFSET
ENVIO_BASE = os.environ.get('ENVIO_BASE', '300')          # ARS
ENVIO_POR_KM = os.environ.get('ENVIO_POR_KM', '50')       # ARS por km
ENVIO_REDONDEO = os.environ.get('ENVIO_REDONDEO', '100')  # múltiplos (0 = sin redondeo)
ENVIO_MIN = os.environ.get('ENVIO_MIN', '0')              # costo mínimo
ENVIO_MAX = os.environ.get('ENVIO_MAX', '')               # '' = sin tope
ENVIO_KM_MIN = os.environ.get('ENVIO_KM_MIN', '0')        # mínimo de km cobrables (ej: 1)
ENVIO_KM_OFFSET = os.environ.get('ENVIO_KM_OFFSET', '0')  # km fantasma

# Origen (recomendado usar coordenadas)
ORIGEN_LAT = os.environ.get('ORIGEN_LAT', '')             # ej: -28.468500
ORIGEN_LNG = os.environ.get('ORIGEN_LNG', '')             # ej: -65.779900
