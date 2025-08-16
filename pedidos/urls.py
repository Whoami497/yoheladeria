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

    # --- URLs para AUTENTICACIÓN Y PERFIL DE CLIENTES ---
    path('register/', views.register_cliente, name='register_cliente'),
    path('perfil/', views.perfil_cliente, name='perfil_cliente'),
    path('logout/', views.logout_cliente, name='logout_cliente'),
    
    # --- URL PARA HISTORIAL DE PEDIDOS DEL CLIENTE ---
    path('historial-pedidos/', views.historial_pedidos_cliente, name='historial_pedidos_cliente'),

    # --- URL PARA CANJEAR PUNTOS DEL CLIENTE ---
    path('canjear/', views.canjear_puntos, name='canjear_puntos'),

    # --- URLs PARA LA TIENDA ---
    path('panel-alertas/', views.panel_alertas, name='panel_alertas'),
    path('confirmar-pedido/<int:pedido_id>/', views.confirmar_pedido, name='confirmar_pedido'),

    # --- URLs PARA PANEL DE CADETES ---
    path('cadete/login/', views.login_cadete, name='login_cadete'),
    path('cadete/panel/', views.panel_cadete, name='panel_cadete'),
    path('cadete/logout/', views.logout_cadete, name='logout_cadete'),
    path('save-subscription/', views.save_subscription, name='save_subscription'),
    
    # URL para que un cadete acepte un pedido.
    path('cadete/aceptar-pedido/<int:pedido_id>/', views.aceptar_pedido, name='aceptar_pedido'),

    # --- URLs de MERCADO PAGO ---
    path('pagos/mp/webhook/', views.mp_webhook_view, name='mp_webhook'),
    path('pagos/mp/success/', views.mp_success, name='mp_success'),
]
