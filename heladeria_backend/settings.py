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

# 🔐 HOSTS permitidos (incluye Render + tu dominio raíz y www)
ALLOWED_HOSTS = _split_env_list(
    'ALLOWED_HOSTS',
    '127.0.0.1,localhost,yoheladeria.onrender.com,pedidosyoheladerias.com,www.pedidosyoheladerias.com'
)

# CSRF (producción + dev local) — extendible por ENV con CSRF_TRUSTED_ORIGINS
CSRF_TRUSTED_ORIGINS = [
    'https://yoheladeria.onrender.com',
    'https://pedidosyoheladerias.com',
    'https://www.pedidosyoheladerias.com',
]
if DEBUG:
    CSRF_TRUSTED_ORIGINS += ['http://127.0.0.1:8000', 'http://localhost:8000']
CSRF_TRUSTED_ORIGINS += _split_env_list('CSRF_TRUSTED_ORIGINS', '')

# Para proxies (Render) y HTTPS correcto en request.is_secure()
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Cookies/HTTPS en prod
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_SSL_REDIRECT = not DEBUG

# HSTS (solo en prod; valores “suaves” para no romper nada)
if not DEBUG:
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '3600'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'False')
    SECURE_HSTS_PRELOAD = _env_bool('SECURE_HSTS_PRELOAD', 'False')

# Opcional: cabeceras de seguridad suaves
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
                'pedidos.context_processors.store_status',  # banner/estado tienda abierta/cerrada
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
TIME_ZONE = 'America/Argentina/Catamarca'  # ← ajustado a Catamarca
USE_I18N = True
USE_TZ = True

# --- Archivos estáticos y media ---
STATIC_URL = '/static/'
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
        # En prod usa manifest, en dev evita errores de hash
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

# Permite cambiar a Redis con solo setear REDIS_URL o CHANNEL_BACKEND=redis
if os.environ.get('CHANNEL_BACKEND') == 'redis' or os.environ.get('REDIS_URL'):
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [os.environ.get('REDIS_URL', 'redis://localhost:6379/0')],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',  # 1 dyno / MVP
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
# Nota: cuando puedas, pasá estas claves a ENV y evitá los defaults hardcodeados.

# --- GOOGLE MAPS (Distance Matrix / Geocoding) ---
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
GOOGLE_GEOCODING_KEY = os.environ.get("GOOGLE_GEOCODING_KEY", "")
SUCURSAL_DIRECCION = os.environ.get('SUCURSAL_DIRECCION', 'San Martín 123, Catamarca, Argentina')
MAPS_LANGUAGE = os.environ.get('MAPS_LANGUAGE', 'es')
MAPS_REGION   = os.environ.get('MAPS_REGION', 'AR')
MAPS_COMPONENTS = os.environ.get('MAPS_COMPONENTS', 'country:AR|administrative_area:Catamarca')

# --- ENVÍOS (calibrables) ---
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

# --- Sitio / flags varios ---
SITE_NAME = os.environ.get('SITE_NAME', 'YO HELADERÍAS')
TIENDA_ABIERTA_DEFAULT = _env_bool('TIENDA_ABIERTA_DEFAULT', 'True')

# --- COMANDERA / TICKETS ---
# 1) Envío directo TCP/RAW a impresora ESC/POS (lo usa _send_ticket_tcp_escpos)
COMANDERA_PRINTER_HOST = os.environ.get('COMANDERA_PRINTER_HOST', '')      # ej: '192.168.0.50'
COMANDERA_PRINTER_PORT = int(os.environ.get('COMANDERA_PRINTER_PORT', '9100'))

# 2) Webhook HTTP (si tu POS imprime por un endpoint)
COMANDERA_WEBHOOK_URL = os.environ.get('COMANDERA_WEBHOOK_URL', '')  # ej: http://IP_LOCAL:5000/print
COMANDERA_TOKEN = os.environ.get('COMANDERA_TOKEN', '')

# 3) PrintNode (agente instalado en la PC de caja)
PRINTNODE_API_KEY = os.environ.get('PRINTNODE_API_KEY', '')
PRINTNODE_PRINTER_ID = os.environ.get('PRINTNODE_PRINTER_ID', '')

# Comunes
COMANDERA_COPIES = int(os.environ.get('COMANDERA_COPIES', '1'))

# Parámetros de compatibilidad de papel/corte (los consumen _escpos_wrap_text y _send_ticket_tcp_escpos)
COMANDERA_FEED_LINES = int(os.environ.get('COMANDERA_FEED_LINES', '10'))   # 8–12 suele andar bien
COMANDERA_CUT_MODE   = (os.environ.get('COMANDERA_CUT_MODE', 'auto') or 'auto').lower()  # 'auto'|'gs_v'|'esc_i'|'esc_m'
COMANDERA_ENCODING   = os.environ.get('COMANDERA_ENCODING', 'cp437')       # probar 'cp850'/'cp858' si acentos raros

# --- Logging a consola (útil en Render/heroku-like) ---
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO' if not DEBUG else 'DEBUG')
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{levelname}] {name}: {message}", "style": "{"},
        "verbose": {"format": "[{levelname}] {asctime} {name} | {message}", "style": "{"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose" if not DEBUG else "simple",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"level": os.environ.get('DJANGO_LOG_LEVEL', LOG_LEVEL)},
        "pedidos": {"level": LOG_LEVEL},
    },
    
}

# === Transferencia (alias MP) ===
TRANSFERENCIA_ALIAS = os.getenv("TRANSFERENCIA_ALIAS", "ritaregalado.mp")
TRANSFERENCIA_TITULAR = os.getenv("TRANSFERENCIA_TITULAR", "Rita Virginia Regalado")
TRANSFERENCIA_CUIT = os.getenv("TRANSFERENCIA_CUIT", "27-24776697-4")

TEMPLATES[0]['OPTIONS']['context_processors'] += [
    'pedidos.context_processors.transferencia',
 "pedidos.context_processors.shop_extras",
 'pedidos.context_processors.pwa_flags',
]

FREE_SHIPPING_THRESHOLD = Decimal('10000')  # envío gratis desde $10.000

# --- PWA toggle seguro ---
PWA_ENABLE = False  # En producción queda apagado (no afecta nada)

# === Geocerca / cobertura ===
STORE_COORDS = {
    "lat": -28.4705234,   # <--- LATITUD DEL LOCAL (cambiá si hace falta)
    "lng": -65.7937524,   # <--- LONGITUD DEL LOCAL
}
DELIVERY_RADIUS_KM = 5.0  # Radio permitido para operar (delivery y retiro), cambialo si querés.
ALLOW_PICKUP_OUTSIDE_RADIUS = False

# Re-pedir ubicación si cambió > X metros o si pasaron 24h
REASK_THRESHOLD_METERS = 250




