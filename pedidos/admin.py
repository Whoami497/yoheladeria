from django.contrib import admin
from django.utils.html import format_html
from .models import Sabor, Producto, Pedido, DetallePedido

# --- Personalización para el modelo Producto ---
@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'precio', 'disponible', 'vista_previa_imagen')
    list_filter = ('disponible',)
    search_fields = ('nombre',)

    # Función para mostrar la miniatura de la imagen en la lista
    def vista_previa_imagen(self, obj):
        if obj.imagen:
            return format_html(f'<img src="{obj.imagen.url}" width="50" height="50" />')
        return "Sin imagen"
    vista_previa_imagen.short_description = 'Imagen'


# --- Personalización para el modelo Pedido ---
class DetallePedidoInline(admin.TabularInline):
    model = DetallePedido
    extra = 0 # No mostrar formularios extra para añadir
    readonly_fields = ('producto', 'sabores_elegidos')
    can_delete = False # Evitar que se borren detalles desde aquí

    # Función para mostrar los sabores de forma legible
    def sabores_elegidos(self, instance):
        return ", ".join([sabor.nombre for sabor in instance.sabores.all()])
    sabores_elegidos.short_description = 'Sabores'

    # Evitar que se pueda añadir un nuevo detalle desde aquí
    def has_add_permission(self, request, obj=None):
        return False

@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'cliente_nombre', 'fecha_pedido', 'estado')
    list_filter = ('estado', 'fecha_pedido')
    search_fields = ('cliente_nombre', 'cliente_direccion')
    readonly_fields = ('fecha_pedido', 'cliente_nombre', 'cliente_direccion', 'cliente_telefono')
    inlines = [DetallePedidoInline] # <-- La magia sucede aquí

    # Evitar que se puedan añadir o borrar pedidos desde el admin
    # para forzar que solo entren desde la web
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# --- Registro simple para Sabor ---
@admin.register(Sabor)
class SaborAdmin(admin.ModelAdmin):
    search_fields = ('nombre',)