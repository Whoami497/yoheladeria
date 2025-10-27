# heladeria_backend/settings.py
from pathlib import Path
import os
import dj_database_url
from decimal import Decimal

BASE_DIR = Path(__file__).resolve().parent.parent

# -------- Helpers
def _split_env_list(name, default=""):
    raw = os.environ.get(name, default)
    return [p.strip() for p in raw.split(",") if p.strip()]

def _env_bool(name, default="False"):
    return str(os.environ.get(name, default)).strip().lower() in ("1", "true", "t", "yes", "y", "si", "sí")

# --- Claves y modo ---
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-tu-clave-secreta-local')
DEBUG = _env_bool('DEBUG', 'True')

# 🔐 HOSTS permitidos
ALLOWED_HOSTS = _split_env_list(
    'ALLOWED_HOSTS',
    '127.0.0.1,localhost,yoheladeria.onrender.com,pedidosyoheladerias.com,www.pedidosyoheladerias.com'
)

# CSRF confiables
CSRF_TRUSTED_ORIGINS = [
    'https://yoheladeria.onrender.com',
    'https://pedidosyoheladerias.com',
    'https://www.pedidosyoheladerias.com',
]
if DEBUG:
    CSRF_TRUSTED_ORIGINS += ['http://127.0.0.1:8000', 'http://localhost:8000']
CSRF_TRUSTED_ORIGINS += _split_env_list('CSRF_TRUSTED_ORIGINS', '')

# Proxy / HTTPS correcto
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Cookies y HTTPS
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_SSL_REDIRECT = not DEBUG

# HSTS en producción
if not DEBUG:
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '3600'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'False')
    SECURE_HSTS_PRELOAD = _env_bool('SECURE_HSTS_PRELOAD', 'False')

SECURE_REFERRER_POLICY = os.environ.get('SECURE_REFERRER_POLICY', 'same-origin')
X_FRAME_OPTIONS = os.environ.get('X_FRAME_OPTIONS', 'SAMEORIGIN')

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

# --- Middleware ---
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

# --- Templates ---
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'pedidos', 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',

                # Contextos del proyecto
                'pedidos.context_processors.store_status',    # estado tienda
                'pedidos.context_processors.transferencia',   # datos transferencia
                'pedidos.context_processors.shop_extras',     # envío gratis / mapa
                'pedidos.context_processors.pwa_flags',       # bandera PWA
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
TIME_ZONE = 'America/Argentina/Catamarca'
USE_I18N = True
USE_TZ = True

# --- Archivos estáticos y media ---
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage" if not DEBUG
                   else "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

# --- Auth redirects ---
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
LOGIN_URL = '/accounts/login/'

# --- Channels ---
ASGI_APPLICATION = 'heladeria_backend.asgi.application'

if os.environ.get('CHANNEL_BACKEND') == 'redis' or os.environ.get('REDIS_URL'):
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [os.environ.get('REDIS_URL', 'redis://localhost:6379/0')]},
        },
    }
else:
    CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}

# --- MERCADO PAGO ---
MERCADO_PAGO_ACCESS_TOKEN = os.environ.get('MERCADO_PAGO_ACCESS_TOKEN', '')
MERCADO_PAGO_PUBLIC_KEY = os.environ.get('MERCADO_PAGO_PUBLIC_KEY', '')

# --- WEBPUSH ---
_VAPID_PUBLIC_ENV = os.environ.get('VAPID_PUBLIC_KEY')
_VAPID_PRIVATE_ENV = os.environ.get('VAPID_PRIVATE_KEY')
_VAPID_ADMIN_ENV = os.environ.get('VAPID_ADMIN_EMAIL')

WEBPUSH_SETTINGS = {
    "VAPID_PUBLIC_KEY": _VAPID_PUBLIC_ENV or "BDp_wB1ExvnVF_GXHbCY_nCuFeixaDcMOW2-x9PrXcA6bKaWku1bjn4QyMZxORPJUpZNYBznZUQ3lSXxKGjLvUc",
    "VAPID_PRIVATE_KEY": _VAPID_PRIVATE_ENV or "rc3tobb6ie6JWXwLf9YUFvkcb2yn1FV0VKxMq38ri5E",
    "VAPID_ADMIN_EMAIL": (_VAPID_ADMIN_ENV or "lucasxlo89@gmail.com"),
}

# --- GOOGLE MAPS ---
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
GOOGLE_GEOCODING_KEY = os.environ.get("GOOGLE_GEOCODING_KEY", "")
SUCURSAL_DIRECCION = os.environ.get('SUCURSAL_DIRECCION', 'San Martín 123, Catamarca, Argentina')
MAPS_LANGUAGE = os.environ.get('MAPS_LANGUAGE', 'es')
MAPS_REGION = os.environ.get('MAPS_REGION', 'AR')
MAPS_COMPONENTS = os.environ.get('MAPS_COMPONENTS', 'country:AR|administrative_area:Catamarca')

# --- ENVÍOS ---
ENVIO_BASE = os.environ.get('ENVIO_BASE', '300')
ENVIO_POR_KM = os.environ.get('ENVIO_POR_KM', '50')
ENVIO_REDONDEO = os.environ.get('ENVIO_REDONDEO', '100')
ENVIO_MIN = os.environ.get('ENVIO_MIN', '0')
ENVIO_MAX = os.environ.get('ENVIO_MAX', '')
ENVIO_KM_MIN = os.environ.get('ENVIO_KM_MIN', '0')
ENVIO_KM_OFFSET = os.environ.get('ENVIO_KM_OFFSET', '0')

ORIGEN_LAT = os.environ.get('ORIGEN_LAT', '')
ORIGEN_LNG = os.environ.get('ORIGEN_LNG', '')

# --- Sitio / flags ---
SITE_NAME = os.environ.get('SITE_NAME', 'YO HELADERÍAS')
TIENDA_ABIERTA_DEFAULT = _env_bool('TIENDA_ABIERTA_DEFAULT', 'True')

# --- COMANDERA / TICKETS ---
COMANDERA_PRINTER_HOST = os.environ.get('COMANDERA_PRINTER_HOST', '')
COMANDERA_PRINTER_PORT = int(os.environ.get('COMANDERA_PRINTER_PORT', '9100'))
COMANDERA_WEBHOOK_URL = os.environ.get('COMANDERA_WEBHOOK_URL', '')
COMANDERA_TOKEN = os.environ.get('COMANDERA_TOKEN', '')
PRINTNODE_API_KEY = os.environ.get('PRINTNODE_API_KEY', '')
PRINTNODE_PRINTER_ID = os.environ.get('PRINTNODE_PRINTER_ID', '')
COMANDERA_COPIES = int(os.environ.get('COMANDERA_COPIES', '1'))
COMANDERA_FEED_LINES = int(os.environ.get('COMANDERA_FEED_LINES', '10'))
COMANDERA_CUT_MODE = (os.environ.get('COMANDERA_CUT_MODE', 'auto') or 'auto').lower()
COMANDERA_ENCODING = os.environ.get('COMANDERA_ENCODING', 'cp437')

# --- Logging ---
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO' if not DEBUG else 'DEBUG')
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{levelname}] {name}: {message}", "style": "{"},
        "verbose": {"format": "[{levelname}] {asctime} {name} | {message}", "style": "{"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {"django": {"level": LOG_LEVEL}, "pedidos": {"level": LOG_LEVEL}},
}

# --- Transferencia ---
TRANSFERENCIA_ALIAS = os.getenv("TRANSFERENCIA_ALIAS", "ritaregalado.mp")
TRANSFERENCIA_TITULAR = os.getenv("TRANSFERENCIA_TITULAR", "Rita Virginia Regalado")
TRANSFERENCIA_CUIT = os.getenv("TRANSFERENCIA_CUIT", "27-24776697-4")

# --- PWA toggle / envío gratis ---
FREE_SHIPPING_THRESHOLD = Decimal("10000")
FREE_SHIPPING_DEFAULT_ACTIVE = False
PWA_ENABLE = False  # PWA apagada por defecto

# --- Geocerca ---
STORE_COORDS = {"lat": -28.4705234, "lng": -65.7937524}
DELIVERY_RADIUS_KM = 5.0
ALLOW_PICKUP_OUTSIDE_RADIUS = False
REASK_THRESHOLD_METERS = 250
