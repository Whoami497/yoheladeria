# pedidos/context_processors.py
from django.conf import settings

def store_status(request):
    """
    Variables globales disponibles en todos los templates.
    Lee TIENDA_ABIERTA desde GlobalSetting si existe; si no, cae a StoreStatus.
    También expone TIENDA_MSG (mensaje opcional).
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
        'TIENDA_ABIERTA': abierta,
        'TIENDA_MSG': msg,
        'VAPID_PUBLIC_KEY': vapid_pub,
        'GOOGLE_MAPS_API_KEY': maps_key,
    }
