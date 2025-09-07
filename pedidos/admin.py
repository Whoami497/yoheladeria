# pedidos/admin.py

from django.contrib import admin
from django.conf import settings
from django.utils.html import format_html
from django import forms
from django.db import models
from django.urls import reverse

from .models import (
    # Online
    Categoria, Producto, OpcionProducto, Sabor,
    Pedido, DetallePedido, ClienteProfile, ProductoCanje, ZonaEnvio, CadeteProfile,
    PedidoEstadoLog,  # si no existiera en tu models, quitá esta línea y las clases ligadas
)

# =========================
# Catálogo ONLINE
# =========================

@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'orden', 'disponible')
    list_filter = ('disponible',)
    search_fields = ('nombre',)
    ordering = ('orden',)


@admin.register(Sabor)
class SaborAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'disponible')
    list_filter = ('disponible',)
    search_fields = ('nombre',)


class ProductoAdminForm(forms.ModelForm):
    imagen = forms.CharField(
        required=False,
        label="Ruta de Imagen",
        help_text="Ej: images/nombre_producto.png. Debe estar en STATIC/images/"
    )

    class Meta:
        model = Producto
        fields = '__all__'


class OpcionProductoInline(admin.TabularInline):
    model = OpcionProducto
    extra = 1
    fields = ('nombre_opcion', 'precio_adicional', 'disponible', 'imagen_opcion')
    formfield_overrides = {
        models.CharField: {'widget': forms.TextInput(attrs={'size': '50'})},
        models.TextField: {'widget': forms.Textarea(attrs={'rows': 2, 'cols': 50})},
    }


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
            return format_html(
                '<img src="{}" style="width:50px;height:50px;object-fit:contain;" />',
                settings.STATIC_URL + obj.imagen
            )
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
        return ", ".join(s.nombre for s in obj.sabores.all()) if obj.sabores.exists() else "N/A"
    sabores_display_method.short_description = 'Sabores'


# ---------- Inline solo lectura para ver la trazabilidad de estados
class PedidoEstadoLogInline(admin.TabularInline):
    model = PedidoEstadoLog
    extra = 0
    fields = ('created_at', 'de', 'a', 'actor', 'actor_tipo', 'fuente', 'meta')
    readonly_fields = ('created_at', 'de', 'a', 'actor', 'actor_tipo', 'fuente', 'meta')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'usuario_asociado', 'cliente_nombre', 'cliente_telefono',
        'estado', 'metodo_pago', 'cadete_nombre', 'fecha_pedido',
        'valor_total', 'costo_envio', 'm_total_min',
    )
    list_filter = ('estado', 'metodo_pago', 'zona_envio', 'fecha_pedido', 'cadete_asignado')
    search_fields = (
        'cliente_nombre', 'cliente_telefono', 'cliente_direccion',
        'user__username', 'detalles__producto__nombre'
    )
    date_hierarchy = 'fecha_pedido'
    inlines = [DetallePedidoInline, PedidoEstadoLogInline]

    # ---- campos de solo lectura dinámicos (evita romper si aún no migraste)
    def get_readonly_fields(self, request, obj=None):
        base = ['fecha_pedido', 'valor_total']
        hitos = [
            'fecha_pago_aprobado', 'fecha_en_preparacion', 'fecha_asignado',
            'fecha_en_camino', 'fecha_entregado', 'fecha_cancelado',
        ]
        existentes = [f for f in hitos if self._has_model_field(Pedido, f)]
        return tuple(base + existentes + ['metricas_minutos'])

    # ---- fieldsets dinámicos para no fallar si faltan campos
    def get_fieldsets(self, request, obj=None):
        base = [
            (None, {
                'fields': (('user', 'estado'), ('metodo_pago', 'zona_envio'), ('cadete_asignado', 'costo_envio'))
            }),
            ('Detalles del Cliente', {
                'fields': ('cliente_nombre', 'cliente_direccion', 'cliente_telefono'),
                'classes': ('collapse',)
            }),
            ('Montos y Fechas', {
                'fields': ('valor_total', 'fecha_pedido'),
            }),
        ]
        hitos = [
            'fecha_pago_aprobado', 'fecha_en_preparacion', 'fecha_asignado',
            'fecha_en_camino', 'fecha_entregado', 'fecha_cancelado',
        ]
        existentes = [f for f in hitos if self._has_model_field(Pedido, f)]
        # Siempre incluimos el bloque de métricas; si no hay método/campos, se muestra “—”
        existentes.append('metricas_minutos')
        base.append((
            'Hitos de Tiempo (solo lectura)',
            {'fields': tuple(existentes), 'classes': ('collapse',)}
        ))
        return base

    @staticmethod
    def _has_model_field(model, name: str) -> bool:
        try:
            model._meta.get_field(name)
            return True
        except Exception:
            return False

    # ---- helpers de columnas
    def usuario_asociado(self, obj):
        return obj.user.username if obj.user else 'Invitado'
    usuario_asociado.short_description = 'Usuario'

    def cadete_nombre(self, obj):
        if obj.cadete_asignado and obj.cadete_asignado.user:
            u = obj.cadete_asignado.user
            return u.get_full_name() or u.username
        return '—'
    cadete_nombre.short_description = 'Cadete'

    def valor_total(self, obj):
        return obj.total_pedido
    valor_total.short_description = 'Total'

    # ---- métrica total (min) para lista
    def m_total_min(self, obj):
        try:
            if hasattr(obj, 'tiempos_en_minutos'):
                t = obj.tiempos_en_minutos().get('m_total')
                return t if t is not None else '—'
        except Exception:
            pass
        return '—'
    m_total_min.short_description = 'Total (min)'

    # ---- bloque HTML con métricas en el detalle (a prueba de falta de método/campos)
    def metricas_minutos(self, obj):
        def render_row(lbl, val):
            val = f"{val} min" if val is not None else "—"
            return f"<tr><th style='text-align:left;padding-right:8px'>{lbl}</th><td>{val}</td></tr>"

        m = {}
        try:
            if hasattr(obj, 'tiempos_en_minutos'):
                m = obj.tiempos_en_minutos() or {}
        except Exception:
            m = {}

        html = f"""
        <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu">
          <table>
            {render_row("Recibido → Preparación", m.get("m_recibido_a_preparacion"))}
            {render_row("Preparación → Asignado", m.get("m_preparacion_a_asignado"))}
            {render_row("Asignado → En camino", m.get("m_asignado_a_en_camino"))}
            {render_row("En camino → Entregado", m.get("m_en_camino_a_entregado"))}
            <tr><td colspan="2"><hr/></td></tr>
            {render_row("Total", m.get("m_total"))}
          </table>
        </div>
        """
        return format_html(html)
    metricas_minutos.short_description = "Métricas (min)"


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
        return ", ".join(s.nombre for s in obj.sabores.all()) if obj.sabores.exists() else "N/A"
    sabores_detalle.short_description = 'Sabores'


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


@admin.register(CadeteProfile)
class CadeteProfileAdmin(admin.ModelAdmin):
    list_display = ('user_link', 'telefono', 'vehiculo', 'disponible')
    list_filter = ('disponible', 'vehiculo')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'telefono')
    list_editable = ('disponible', 'vehiculo', 'telefono')

    def user_link(self, obj):
        link = reverse("admin:auth_user_change", args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', link, obj.user.username)
    user_link.short_description = 'Usuario (Cadete)'


@admin.register(ProductoCanje)
class ProductoCanjeAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'puntos_requeridos', 'disponible', 'mostrar_imagen_miniatura')
    list_filter = ('disponible',)
    search_fields = ('nombre', 'descripcion')
    ordering = ('puntos_requeridos',)

    def mostrar_imagen_miniatura(self, obj):
        if obj.imagen:
            return format_html(
                '<img src="{}" style="width:50px;height:50px;object-fit:contain;" />',
                settings.STATIC_URL + obj.imagen
            )
        return "Sin Imagen"
    mostrar_imagen_miniatura.short_description = 'Miniatura'


@admin.register(ZonaEnvio)
class ZonaEnvioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'costo', 'disponible')
    list_filter = ('disponible',)
    search_fields = ('nombre',)
    ordering = ('nombre',)


# ---------- Admin separado para navegar los logs
@admin.register(PedidoEstadoLog)
class PedidoEstadoLogAdmin(admin.ModelAdmin):
    list_display = ('pedido', 'de', 'a', 'created_at', 'actor', 'actor_tipo', 'fuente')
    list_filter = ('a', 'actor_tipo', 'created_at')
    search_fields = ('pedido__id', 'fuente')
    autocomplete_fields = ('pedido', 'actor')
