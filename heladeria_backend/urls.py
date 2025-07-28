# heladeria_backend/urls.py

from django.contrib import admin
from django.urls import path, include # Asegúrate de que 'include' esté importado
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('pedidos.urls')),
    
    # --- INICIO: NUEVA LÍNEA PARA AUTENTICACIÓN ---
    path('accounts/', include('django.contrib.auth.urls')), # Incluye las URLs de autenticación de Django
    # --- FIN: NUEVA LÍNEA PARA AUTENTICACIÓN ---
]

# Configuración para servir archivos estáticos y de medios durante el desarrollo
# Solo para DEBUG=True
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT) # Usamos STATIC_ROOT para desarrollo
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)