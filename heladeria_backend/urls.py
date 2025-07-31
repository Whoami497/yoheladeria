# heladeria_backend/urls.py

from django.contrib import admin
from django.urls import path, include # Asegúrate de que 'include' esté importado
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('webpush/', include('webpush.urls')), # <-- ¡NUEVA LÍNEA IMPORTANTE!
    path('', include('pedidos.urls')),
    
    # --- URLS DE AUTENTICACIÓN DE DJANGO ---
    path('accounts/', include('django.contrib.auth.urls')),
]

# Configuración para servir archivos estáticos y de medios durante el desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)