# pedidos/context_processors.py
from django.conf import settings
from decimal import Decimal

def store_status(request):
    """
    Variables globales disponibles en todos los templates.
    Lee TIENDA_ABIERTA desde GlobalSetting si existe; si no, cae a StoreStatus.
    También expone TIENDA_MSG (mensaje opcional), VAPID y Maps.
    """
    abierta_default = bool(getattr(settings, 'TIENDA_ABIERTA_DEFAULT', True))
    abierta = abierta_default
    msg = ""

    # 1) Intentar GlobalSetting (si existe el modelo)
    try:
        from .models import GlobalSetting  # puede no existir si aún no migraste
        try:
            abierta = bool(GlobalSetting.get_bool('TIENDA_ABIERTA', default=abierta_default))
            msg = GlobalSetting.get('TIENDA_MSG', '') or ''
        except Exception:
            pass
    except Exception:
        # 2) Fallback: StoreStatus (fila única)
        try:
            from .models import StoreStatus
            ss = StoreStatus.get()
            abierta = bool(ss.is_open)
            msg = ss.message or ''
        except Exception:
            # último fallback: default de settings
            abierta = abierta_default
            msg = ""

    vapid_pub = (getattr(settings, 'WEBPUSH_SETTINGS', {}) or {}).get('VAPID_PUBLIC_KEY', '')
    maps_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')

    return {
        'TIENDA_ABIERTA': abierta,   # ← única fuente para templates
        'TIENDA_MSG': msg,
        'VAPID_PUBLIC_KEY': vapid_pub,
        'GOOGLE_MAPS_API_KEY': maps_key,
    }

def transferencia(request):
    return {
        'TRANSFERENCIA_ALIAS': getattr(settings, 'TRANSFERENCIA_ALIAS', ''),
        'TRANSFERENCIA_TITULAR': getattr(settings, 'TRANSFERENCIA_TITULAR', ''),
        'TRANSFERENCIA_CUIT': getattr(settings, 'TRANSFERENCIA_CUIT', ''),
    }

def shop_extras(_request):
    # Defaults de settings (fallback)
    threshold_default = Decimal(str(getattr(settings, "FREE_SHIPPING_THRESHOLD", "10000")))
    active_default = bool(getattr(settings, "FREE_SHIPPING_ACTIVE", True))

    # Intentar GlobalSetting
    try:
        from .models import GlobalSetting
        active = GlobalSetting.get_bool("FREE_SHIPPING_ACTIVE", active_default)
        th_raw = GlobalSetting.get("FREE_SHIPPING_THRESHOLD", str(threshold_default))
        try:
            threshold = Decimal(str(th_raw or threshold_default))
        except Exception:
            threshold = threshold_default
    except Exception:
        active = active_default
        threshold = threshold_default

    return {
        "TIENDA_ABIERTA": True,
        "FREE_SHIPPING_THRESHOLD": threshold,            # ← usado por front si querés mostrarlo
        "PROMO_FREE_SHIPPING_ACTIVE": active,            # ← NUEVO: estado visible en templates
        "PROMO_FREE_SHIPPING_THRESHOLD": threshold,      # ← NUEVO: umbral visible en templates

        # ya existentes en tu archivo:
        "STORE_COORDS": getattr(settings, "STORE_COORDS", {}),
        "DELIVERY_RADIUS_KM": getattr(settings, "DELIVERY_RADIUS_KM", None),
        "REASK_THRESHOLD_METERS": getattr(settings, "REASK_THRESHOLD_METERS", 250),
    }