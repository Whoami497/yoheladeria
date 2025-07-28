# pedidos/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('producto/<int:producto_id>/', views.detalle_producto, name='detalle_producto'),
    path('carrito/', views.ver_carrito, name='ver_carrito'),
    path('carrito/eliminar/<str:item_key>/', views.eliminar_del_carrito, name='eliminar_del_carrito'),
    path('pedido_exitoso/', views.pedido_exitoso, name='pedido_exitoso'),
    path('categoria/<int:categoria_id>/', views.productos_por_categoria, name='productos_por_categoria'),

    # --- INICIO: NUEVAS URLS PARA AUTENTICACIÓN Y PERFIL ---
    path('register/', views.register_cliente, name='register_cliente'),
    path('perfil/', views.perfil_cliente, name='perfil_cliente'),
    path('logout/', views.logout_cliente, name='logout_cliente'),
    # --- FIN: NUEVAS URLS PARA AUTENTICACIÓN Y PERFIL ---

    # --- INICIO: NUEVA URL PARA HISTORIAL DE PEDIDOS ---
    path('historial-pedidos/', views.historial_pedidos_cliente, name='historial_pedidos_cliente'),
    # --- FIN: NUEVA URL PARA HISTORIAL DE PEDIDOS ---

    # --- INICIO: NUEVA URL PARA CANJEAR PUNTOS ---
    path('canjear/', views.canjear_puntos, name='canjear_puntos'),
    # --- FIN: NUEVA URL PARA CANJEAR PUNTOS ---

    # --- INICIO: NUEVA URL PARA PANEL DE ALERTAS ---
    path('panel-alertas/', views.panel_alertas, name='panel_alertas'), # <-- NUEVA LÍNEA
    # --- FIN: NUEVA URL PARA PANEL DE ALERTAS ---
]