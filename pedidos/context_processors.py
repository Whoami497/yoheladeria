# pedidos/context_processors.py
from django.conf import settings

def store_status(request):
    """
    Variables globales que llegan a todos los templates.
    Sólo lectura, nada raro acá.
    """
    # Flag de tienda: usa DB si existe el modelo, si no usa settings
    abierta = bool(getattr(settings, 'TIENDA_ABIERTA_DEFAULT', True))
    try:
        from .models import GlobalSetting  # opcional
        try:
            abierta = GlobalSetting.get_bool('TIENDA_ABIERTA', default=abierta)
        except Exception:
            pass
    except Exception:
        pass

    vapid_pub = (getattr(settings, 'WEBPUSH_SETTINGS', {}) or {}).get('VAPID_PUBLIC_KEY', '')
    maps_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')

    return {
        'TIENDA_ABIERTA': abierta,
        'VAPID_PUBLIC_KEY': vapid_pub,
        'GOOGLE_MAPS_API_KEY': maps_key,
    }
