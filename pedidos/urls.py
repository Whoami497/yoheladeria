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
    path('pedido_exitoso/', views.pedido_exitoso, name='pedido_exitoso'),

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

    # --- Confirmación de pedido (tienda) ---
    path('confirmar-pedido/<int:pedido_id>/', views.confirmar_pedido, name='confirmar_pedido'),

    # --- Cadetes ---
    path('cadete/login/', views.login_cadete, name='login_cadete'),
    path('cadete/panel/', views.panel_cadete, name='panel_cadete'),
    path('cadete/logout/', views.logout_cadete, name='logout_cadete'),
    path('save-subscription/', views.save_subscription, name='save_subscription'),
    path('cadete/aceptar-pedido/<int:pedido_id>/', views.aceptar_pedido, name='aceptar_pedido'),

    # NUEVO: Acciones rápidas del cadete
    path('cadete/disponible/', views.cadete_toggle_disponible, name='cadete_toggle_disponible'),
    path('cadete/estado/<int:pedido_id>/', views.cadete_set_estado, name='cadete_set_estado'),
# --- Cadetes extra ---
path('cadete/feed/', views.cadete_feed, name='cadete_feed'),               # JSON: pedidos disponibles
path('cadete/historial/', views.cadete_historial, name='cadete_historial'),# Historial del cadete
path('cadete/estado/<int:pedido_id>/', views.cadete_set_estado, name='cadete_set_estado'),  # ya la tenías, por si faltaba

    # --- Mercado Pago ---
    path('pagos/mp/webhook/', views.mp_webhook_view, name='mp_webhook'),
    path('pagos/mp/success/', views.mp_success, name='mp_success'),
    # pedidos/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # ...tus rutas...
    path('sw.js', views.service_worker, name='service_worker'),  # <-- NUEVO
]

]
