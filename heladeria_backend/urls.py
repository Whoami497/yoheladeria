# heladeria_backend/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from pedidos import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('webpush/', include('webpush.urls')),
    path('', include('pedidos.urls')),
    path("ticket/<int:pedido_id>/", views.ticket_pedido, name="ticket_pedido"),
    # Auth de Django (login/logout/password reset)
    path('accounts/', include('django.contrib.auth.urls')),
]

# Archivos estáticos y media en desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
