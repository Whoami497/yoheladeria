# pedidos/context_processors.py
from django.conf import settings

# Importamos el helper que ya definimos en views.py para leer el flag
try:
    from .views import _get_tienda_abierta
except Exception:
    _get_tienda_abierta = None

def store_status(request):
    """
    Inyecta en todos los templates si la tienda está abierta o cerrada.
    No toca rutas ni settings. Es liviano y tolerante a errores.
    """
    abierta = True
    try:
        if callable(_get_tienda_abierta):
            abierta = bool(_get_tienda_abierta())
        else:
            abierta = bool(getattr(settings, 'TIENDA_ABIERTA_DEFAULT', True))
    except Exception:
        abierta = bool(getattr(settings, 'TIENDA_ABIERTA_DEFAULT', True))

    return {
        'TIENDA_ABIERTA': abierta
    }
