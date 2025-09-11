# pedidos/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # --- Tienda / catálogo ---
    path('', views.index, name='index'),
    path('producto/<int:producto_id>/', views.detalle_producto, name='detalle_producto'),
    path('categoria/<int:categoria_id>/', views.productos_por_categoria, name='productos_por_categoria'),

    # --- Carrito / pedidos del cliente ---
    path('carrito/', views.ver_carrito, name='ver_carrito'),
    path('carrito/eliminar/<str:item_key>/', views.eliminar_del_carrito, name='eliminar_del_carrito'),
    path('carrito/nota/', views.carrito_set_nota, name='carrito_set_nota'),
    # Alias de compatibilidad (algunos templates antiguos usan /carrito/set-nota/)
    path('carrito/set-nota/', views.carrito_set_nota, name='carrito_set_nota_compat'),
    path('pedido_exitoso/', views.pedido_exitoso, name='pedido_exitoso'),

    # === API: costo de envío dinámico (usa Google Distance Matrix) ===
    path('api/costo-envio/', views.api_costo_envio, name='api_costo_envio'),

    # --- Autenticación y perfil de clientes ---
    path('register/', views.register_cliente, name='register_cliente'),
    path('perfil/', views.perfil_cliente, name='perfil_cliente'),
    path('logout/', views.logout_cliente, name='logout_cliente'),

    # --- Historial y canje de puntos ---
    path('historial-pedidos/', views.historial_pedidos_cliente, name='historial_pedidos_cliente'),
    path('canjear/', views.canjear_puntos, name='canjear_puntos'),

    # --- Panel de alertas (tienda) ---
    path('panel-alertas/', views.panel_alertas, name='panel_alertas'),
    path('panel-alertas/data/', views.panel_alertas_data, name='panel_alertas_data'),
    path('panel-alertas/board/', views.panel_alertas, name='panel_alertas_board'),
    path('panel-alertas/anteriores/', views.panel_alertas_anteriores, name='panel_alertas_anteriores'),
    path('panel-alertas/estado/<int:pedido_id>/', views.panel_alertas_set_estado, name='panel_alertas_set_estado'),
    # Confirmación de pedido (tienda)
    path('confirmar-pedido/<int:pedido_id>/', views.confirmar_pedido, name='confirmar_pedido'),
    # Alias opcional por si algún botón viejo apunta a esta ruta
    path('panel-alertas/confirmar/<int:pedido_id>/', views.confirmar_pedido, name='confirmar_pedido_panel'),

    # --- NUEVO: abrir/cerrar tienda ---
    path('tienda/estado/', views.tienda_estado, name='tienda_estado'),  # GET: devuelve flags en JSON
    path('panel-alertas/tienda/toggle/', views.tienda_toggle, name='tienda_toggle'),  # POST staff: abre/cierra

    # --- Panel de cadetes ---
    path('cadete/login/', views.login_cadete, name='login_cadete'),
    path('cadete/panel/', views.panel_cadete, name='panel_cadete'),
    path('cadete/logout/', views.logout_cadete, name='logout_cadete'),
    path('cadete/aceptar-pedido/<int:pedido_id>/', views.aceptar_pedido, name='aceptar_pedido'),
    path('cadete/toggle-disponible/', views.cadete_toggle_disponible, name='cadete_toggle_disponible'),
    path('cadete/estado/<int:pedido_id>/', views.cadete_set_estado, name='cadete_set_estado'),
    path('cadete/feed/', views.cadete_feed, name='cadete_feed'),
    path('cadete/historial/', views.cadete_historial, name='cadete_historial'),
    path('save-subscription/', views.save_subscription, name='save_subscription'),
    # Alias de compatibilidad para scripts que usen esta ruta
    path('cadete/subscription/save/', views.save_subscription, name='save_subscription_compat'),

    # --- Mercado Pago ---
    path('pagos/mp/webhook/', views.mp_webhook_view, name='mp_webhook'),
    path('pagos/mp/success/', views.mp_success, name='mp_success'),
    path('pagos/mp/refund/<int:pedido_id>/', views.mp_refund, name='mp_refund'),

    # --- Otros ---
    path('sw.js', views.service_worker, name='service_worker'),
    path('pedido/en-curso/', views.pedido_en_curso, name='pedido_en_curso'),
]
