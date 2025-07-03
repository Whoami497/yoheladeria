from django.contrib import admin
from .models import Sabor, Producto, Pedido, DetallePedido

# Clase para mostrar los detalles del pedido DENTRO del formulario del pedido principal
class DetallePedidoInline(admin.TabularInline):
    model = DetallePedido
    extra = 0 # Para no mostrar formularios extra vacíos
    readonly_fields = ('producto', 'sabores_list') # Hacemos los campos de solo lectura aquí
    can_delete = False

    # Función para mostrar los sabores de forma bonita
    def sabores_list(self, instance):
        return ", ".join([sabor.nombre for sabor in instance.sabores.all()])
    sabores_list.short_description = 'Sabores Elegidos'

@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    # Columnas que se mostrarán en la lista de pedidos
    list_display = ('id', 'cliente_nombre', 'fecha_pedido', 'estado')
    # Filtros que aparecerán en la barra lateral
    list_filter = ('estado', 'fecha_pedido')
    # Campos por los que se podrá buscar
    search_fields = ('cliente_nombre', 'cliente_direccion')
    # Campos que no se pueden editar en el detalle
    readonly_fields = ('fecha_pedido',)
    # Añadimos los detalles del pedido directamente en la vista del pedido
    inlines = [DetallePedidoInline]

# Registramos los otros modelos de forma simple como antes
admin.site.register(Sabor)
admin.site.register(Producto)
# No registramos DetallePedido aquí porque ya está "inline"
# admin.site.register(DetallePedido)