# heladeria_backend/asgi.py
import os
import django
from django.core.asgi import get_asgi_application

# 1. CONFIGURAR DJANGO ANTES DE CARGAR NADA
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'heladeria_backend.settings')
django.setup()

# 2. AHORA SÍ IMPORTAR RUTAS
from pedidos import routing

# 3. CREAR LA APP ASGI
application = get_asgi_application()

# 4. PROTOCOL TYPE ROUTER (para WebSocket + HTTP)
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(routing.websocket_urlpatterns)
    ),
})