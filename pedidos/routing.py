# pedidos/routing.py

from django.urls import re_path
from .consumers import notifications

# Este archivo solo debe definir websocket_urlpatterns
# El asgi.py principal es el que usa esto.
websocket_urlpatterns = [
    # Ruta para el panel de alertas de la tienda
    re_path(r'ws/pedidos/notifications/$', notifications.PedidoNotificationConsumer.as_asgi()),
    
    # --- INICIO: NUEVA RUTA PARA EL PANEL DE CADETES ---
    re_path(r'ws/cadete/notifications/$', notifications.CadeteNotificationConsumer.as_asgi()),
    # --- FIN: NUEVA RUTA PARA EL PANEL DE CADETES ---
]