# pedidos/routing.py

from django.urls import re_path
from .consumers import notifications

# Este archivo solo debe definir websocket_urlpatterns
# El asgi.py principal es el que usa esto.
websocket_urlpatterns = [
    re_path(r'ws/pedidos/notifications/$', notifications.PedidoNotificationConsumer.as_asgi()),
]