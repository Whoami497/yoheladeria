# heladeria_backend/asgi.py

import os
import django # Asegúrate de que django esté importado aquí
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator

# Importa el routing de tu aplicación 'pedidos'
# Asegúrate de que esta línea esté correcta
from pedidos import routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'heladeria_backend.settings')

# Configura Django
django.setup()

application = ProtocolTypeRouter({
    "http": get_asgi_application(), # Conexiones HTTP normales (vistas de Django)
    "websocket": AllowedHostsOriginValidator( # Seguridad para WebSockets
        AuthMiddlewareStack( # Para que los WebSockets puedan acceder a request.user
            URLRouter(
                # Las URLs de tus WebSockets de la app 'pedidos'
                # Asegúrate que 'routing' aquí se refiera al módulo 'pedidos/routing.py'
                routing.websocket_urlpatterns
            )
        )
    ),
})
