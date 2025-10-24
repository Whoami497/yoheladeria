# heladeria_backend/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.template.loader import render_to_string
from pedidos import views  # tus vistas existentes

urlpatterns = [
    path('admin/', admin.site.urls),
    path('webpush/', include('webpush.urls')),
    path('', include('pedidos.urls')),
    path("ticket/<int:pedido_id>/", views.ticket_pedido, name="ticket_pedido"),
    # Auth de Django (login/logout/password reset)
    path('accounts/', include('django.contrib.auth.urls')),
]

# -------------------------------------------------------------------
# Service Workers
# -------------------------------------------------------------------

# SW raíz NO-OP para la PWA (no intercepta nada)
def sw_noop(_req):
    js = "self.addEventListener('install',()=>self.skipWaiting());" \
         "self.addEventListener('activate',()=>self.clients.claim());"
    return HttpResponse(js, content_type='application/javascript')

# SW específico para cadetes: usa tu archivo de templates existente
def sw_cadete_view(_req):
    # Renderiza pedidos/templates/pedidos/sw.js (tu SW de notificaciones)
    js = render_to_string('pedidos/sw.js')
    resp = HttpResponse(js, content_type='application/javascript')
    # Habilita scope en la raíz por si lo necesitás
    resp['Service-Worker-Allowed'] = '/'
    return resp

# Publicar rutas de SW
urlpatterns += [
    path('sw.js', sw_noop, name='sw_root'),                   # PWA (no-op)
    path('sw-cadete.js', sw_cadete_view, name='sw_cadete'),   # Notificaciones cadete
]

# Archivos estáticos y media en desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
