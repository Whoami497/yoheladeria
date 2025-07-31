# pedidos/admin.py

from django.contrib import admin
from django.conf import settings
from django.utils.html import format_html
from django import forms
from django.db import models
from django.urls import reverse # Necesario para el enlace al usuario

# Importa todos tus modelos, incluyendo el nuevo CadeteProfile
from .models import (
    Categoria, Producto, OpcionProducto, Sabor, Pedido, DetallePedido, 
    ClienteProfile, ProductoCanje, ZonaEnvio, CadeteProfile
)


# Admin para Categorias
@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'orden', 'disponible')
    list_filter = ('disponible',)
    search_fields = ('nombre',)
    ordering = ('orden',)


# Admin para Sabores
@admin.register(Sabor)
class SaborAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'disponible')
    list_filter = ('disponible',)
    search_fields = ('nombre',)


# Custom Form para seleccionar imagen estática en Producto
class ProductoAdminForm(forms.ModelForm):
    imagen = forms.CharField(
        required=False,
        label="Ruta de Imagen",
        help_text="Ej: images/nombre_producto.png. Debe estar en tu STATICFILES_DIRS/images/"
    )

    class Meta:
        model = Producto
        fields = '__all__'

# Inline para Opciones de Producto
class OpcionProductoInline(admin.TabularInline):
    model = OpcionProducto
    extra = 1
    fields = ('nombre_opcion', 'precio_adicional', 'disponible', 'imagen_opcion')
    formfield_overrides = {
        models.CharField: {'widget': forms.TextInput(attrs={'size': '50'})},
        models.TextField: {'widget': forms.Textarea(attrs={'rows': 2, 'cols': 50})},
    }


# Admin para Productos
@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    form = ProductoAdminForm
    inlines = [OpcionProductoInline]
    list_display = ('nombre', 'categoria', 'precio', 'sabores_maximos', 'disponible', 'mostrar_imagen_miniatura')
    list_filter = ('categoria', 'disponible')
    search_fields = ('nombre', 'descripcion', 'categoria__nombre')
    ordering = ('nombre',)
    
    def mostrar_imagen_miniatura(self, obj):
        if obj.imagen:
            return format_html('<img src="{}" style="width: 50px; height: 50px; object-fit: contain;" />',
                               settings.STATIC_URL + obj.imagen)
        return "Sin Imagen"
    mostrar_imagen_miniatura.short_description = 'Miniatura'


class DetallePedidoInline(admin.TabularInline):
    model = DetallePedido
    extra = 0
    fields = ('producto', 'opcion_seleccionada', 'cantidad', 'sabores_display_method')
    readonly_fields = ('producto', 'opcion_seleccionada', 'cantidad', 'sabores_display_method')
    can_delete = False

    def producto_display_method(self, obj):
        if obj.opcion_seleccionada:
            return f"{obj.producto.nombre} - {obj.opcion_seleccionada.nombre_opcion}"
        return obj.producto.nombre
    producto_display_method.short_description = 'Producto/Opción'

    def sabores_display_method(self, obj):
        return ", ".join([sabor.nombre for sabor in obj.sabores.all()]) if obj.sabores.exists() else "N/A"
    sabores_display_method.short_description = 'Sabores'


# Admin para Pedidos
@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'usuario_asociado', 'cliente_nombre', 'cliente_telefono', 'fecha_pedido', 'estado', 'metodo_pago', 'zona_envio', 'valor_total')
    list_filter = ('estado', 'metodo_pago', 'zona_envio', 'fecha_pedido')
    search_fields = ('cliente_nombre', 'cliente_telefono', 'user__username', 'detalles__producto__nombre')
    date_hierarchy = 'fecha_pedido'
    readonly_fields = ('fecha_pedido', 'valor_total') 
    
    inlines = [DetallePedidoInline] 

    fieldsets = (
        (None, {
            'fields': (('user', 'estado'), ('metodo_pago', 'zona_envio'))
        }),
        ('Detalles del Cliente', {
            'fields': ('cliente_nombre', 'cliente_direccion', 'cliente_telefono'),
            'classes': ('collapse',)
        }),
        ('Información del Pedido', {
            'fields': ('fecha_pedido', 'valor_total'),
        }),
    )

    def usuario_asociado(self, obj):
        return obj.user.username if obj.user else 'Invitado'
    usuario_asociado.short_description = 'Usuario Asociado'

    def valor_total(self, obj):
        return obj.total_pedido
    valor_total.short_description = 'Valor Total'


# Admin para DetallePedido
@admin.register(DetallePedido)
class DetallePedidoAdmin(admin.ModelAdmin):
    list_display = ('pedido', 'producto_detalle', 'cantidad_detalle', 'sabores_detalle')
    search_fields = ('pedido__id', 'producto__nombre', 'sabores__nombre')
    list_filter = ('pedido__estado',)

    def producto_detalle(self, obj):
        if obj.opcion_seleccionada:
            return f"{obj.producto.nombre} - {obj.opcion_seleccionada.nombre_opcion}"
        return obj.producto.nombre
    producto_detalle.short_description = 'Producto'

    def cantidad_detalle(self, obj):
        return f"x{obj.cantidad}"
    cantidad_detalle.short_description = 'Cantidad'

    def sabores_detalle(self, obj):
        return ", ".join([sabor.nombre for sabor in obj.sabores.all()]) if obj.sabores.exists() else "N/A"
    sabores_detalle.short_description = 'Sabores'


# Admin para ClienteProfile
@admin.register(ClienteProfile)
class ClienteProfileAdmin(admin.ModelAdmin):
    list_display = ('user_username', 'user_email', 'direccion', 'telefono', 'puntos_fidelidad')
    search_fields = ('user__username', 'user__email', 'telefono')
    readonly_fields = ('puntos_fidelidad',)

    def user_username(self, obj):
        return obj.user.username
    user_username.short_description = 'Usuario'

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'

# --- INICIO: NUEVO ADMIN PARA CadeteProfile ---
@admin.register(CadeteProfile)
class CadeteProfileAdmin(admin.ModelAdmin):
    list_display = ('user_link', 'telefono', 'vehiculo', 'disponible')
    list_filter = ('disponible', 'vehiculo')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'telefono')
    list_editable = ('disponible', 'vehiculo', 'telefono') # Permite editar estos campos directamente en la lista

    def user_link(self, obj):
        # Crea un enlace clickeable al perfil del usuario en el admin
        link = reverse("admin:auth_user_change", args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', link, obj.user.username)
    user_link.short_description = 'Usuario (Cadete)'
# --- FIN: NUEVO ADMIN PARA CadeteProfile ---


# Admin para ProductoCanje
@admin.register(ProductoCanje)
class ProductoCanjeAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'puntos_requeridos', 'disponible', 'mostrar_imagen_miniatura')
    list_filter = ('disponible',)
    search_fields = ('nombre', 'descripcion')
    ordering = ('puntos_requeridos',)
    
    def mostrar_imagen_miniatura(self, obj):
        if obj.imagen:
            return format_html('<img src="{}" style="width: 50px; height: 50px; object-fit: contain;" />',
                               settings.STATIC_URL + obj.imagen)
        return "Sin Imagen"
    mostrar_imagen_miniatura.short_description = 'Miniatura'


# Admin para ZonaEnvio
@admin.register(ZonaEnvio)
class ZonaEnvioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'costo', 'disponible')
    list_filter = ('disponible',)
    search_fields = ('nombre',)
    ordering = ('nombre',)