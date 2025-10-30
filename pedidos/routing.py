# pedidos/routing.py
from django.urls import re_path
from .consumers import PedidoNotificationConsumer, CadeteNotificationConsumer  # ← CAMBIA A ESTO

websocket_urlpatterns = [
    re_path(r'ws/pedidos/notifications/$', PedidoNotificationConsumer.as_asgi()),
    re_path(r'ws/cadete/notifications/$', CadeteNotificationConsumer.as_asgi()),
]