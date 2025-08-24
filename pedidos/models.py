# pedidos/models.py

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from decimal import Decimal

# =========================
# Catálogo online
# =========================

class Categoria(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)
    orden = models.PositiveIntegerField(default=0)
    disponible = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class Sabor(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    disponible = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True, related_name='productos')
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True, help_text="Descripción detallada del producto.")
    precio = models.DecimalField(max_digits=10, decimal_places=2, help_text="Precio base del producto. Las opciones pueden tener precios adicionales.")
    sabores_maximos = models.PositiveIntegerField(default=0, help_text="Número máximo de sabores a elegir para este producto. Cero si no permite elección de sabores (ej. tortas, palitos).")
    disponible = models.BooleanField(default=True)
    imagen = models.CharField(max_length=255, blank=True, null=True, help_text="Ruta a la imagen estática del producto base (ej: 'images/pote_1_5kg.png')")

    def __str__(self):
        if self.categoria:
            return f"{self.nombre} ({self.categoria.nombre})"
        return self.nombre

    class Meta:
        ordering = ['nombre']


class OpcionProducto(models.Model):
    producto_base = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='opciones', help_text="El producto genérico al que pertenece esta opción (ej. 'Torta Helada', 'Palito Bomboneiro').")
    nombre_opcion = models.CharField(max_length=150, help_text="Nombre específico de la opción (ej. 'Sabor Selva Negra', 'Dulce de Leche y Americana').")
    descripcion_opcion = models.TextField(blank=True, null=True, help_text="Descripción detallada de esta opción.")
    precio_adicional = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Precio adicional si esta opción es más cara que el producto base.")
    disponible = models.BooleanField(default=True)
    imagen_opcion = models.CharField(max_length=255, blank=True, null=True, help_text="Ruta a la imagen estática de esta opción (ej: 'images/torta_selva_negra.png')")

    def __str__(self):
        return f"{self.producto_base.nombre} - {self.nombre_opcion}"

    class Meta:
        verbose_name = "Opción de Producto"
        verbose_name_plural = "Opciones de Productos"
        unique_together = ('producto_base', 'nombre_opcion')


class ZonaEnvio(models.Model):
    nombre = models.CharField(max_length=100, unique=True, help_text="Nombre de la zona de envío (ej: Centro, Norte, Sur).")
    costo = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Costo de envío para esta zona.")
    disponible = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Zona de Envío"
        verbose_name_plural = "Zonas de Envío"
        ordering = ['nombre']

    def __str__(self):
        return f"{self.nombre} (${self.costo})"


class CadeteProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='cadeteprofile')
    telefono = models.CharField(max_length=20, unique=True, help_text="Número de teléfono único del cadete.")

    VEHICULO_CHOICES = [
        ('MOTO', 'Motocicleta'),
        ('BICI', 'Bicicleta'),
        ('AUTO', 'Automóvil'),
    ]
    vehiculo = models.CharField(max_length=4, choices=VEHICULO_CHOICES, default='MOTO')

    disponible = models.BooleanField(default=False, help_text="Marcar si el cadete está disponible para recibir pedidos.")

    subscription_info = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Información de Suscripción WebPush",
        help_text="Contiene la información de la suscripción push del navegador del cadete."
    )

    latitud_actual = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud_actual = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        verbose_name = "Perfil de Cadete"
        verbose_name_plural = "Perfiles de Cadetes"

    def __str__(self):
        if self.user.first_name and self.user.last_name:
            return f'Cadete: {self.user.first_name} {self.user.last_name}'
        return f'Cadete: {self.user.username}'


class Pedido(models.Model):
    ESTADO_CHOICES = [
        ('RECIBIDO', 'Recibido'),
        ('EN_PREPARACION', 'En Preparación'),
        ('ASIGNADO', 'Asignado a Cadete'),
        ('EN_CAMINO', 'En Camino'),
        ('ENTREGADO', 'Entregado'),
        ('CANCELADO', 'Cancelado'),
    ]

    METODO_PAGO_CHOICES = [
        ('EFECTIVO', 'Efectivo'),
        ('MERCADOPAGO', 'Mercado Pago'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_realizados')
    cliente_nombre = models.CharField(max_length=100)
    cliente_direccion = models.CharField(max_length=255)
    cliente_telefono = models.CharField(max_length=20, blank=True)
    fecha_pedido = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='RECIBIDO')
    metodo_pago = models.CharField(max_length=20, choices=METODO_PAGO_CHOICES, default='EFECTIVO')
    zona_envio = models.ForeignKey(ZonaEnvio, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_en_zona')

    cadete_asignado = models.ForeignKey(
        CadeteProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pedidos_asignados',
        help_text="El cadete que ha aceptado este pedido."
    )

    def __str__(self):
        if self.user:
            return f'Pedido #{self.id} - {self.user.username}'
        return f'Pedido #{self.id} - {self.cliente_nombre}'

    @property
    def total_pedido(self):
        total = Decimal('0.00')
        for detalle in self.detalles.all():
            precio_unitario = detalle.producto.precio
            if detalle.opcion_seleccionada:
                precio_unitario += detalle.opcion_seleccionada.precio_adicional
            total += precio_unitario * detalle.cantidad
        if self.zona_envio and self.zona_envio.costo:
            total += self.zona_envio.costo
        return total


class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, related_name='detalles', on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    opcion_seleccionada = models.ForeignKey(OpcionProducto, on_delete=models.PROTECT, null=True, blank=True)
    sabores = models.ManyToManyField(Sabor)
    cantidad = models.PositiveIntegerField(default=1)

    def __str__(self):
        if self.opcion_seleccionada:
            return f'{self.cantidad}x {self.producto.nombre} - {self.opcion_seleccionada.nombre_opcion} en Pedido #{self.pedido.id}'
        return f'{self.cantidad}x {self.producto.nombre} en Pedido #{self.pedido.id}'


# ---------- Producto de Canje (lo pedía admin.py)
class ProductoCanje(models.Model):
    nombre = models.CharField(max_length=100, unique=True, help_text="Nombre del producto o descuento a canjear.")
    descripcion = models.TextField(blank=True, null=True, help_text="Descripción de la recompensa.")
    puntos_requeridos = models.PositiveIntegerField(default=0, help_text="Puntos necesarios para canjear.")
    disponible = models.BooleanField(default=True)
    imagen = models.CharField(max_length=255, blank=True, null=True, help_text="Ruta a la imagen estática.")

    class Meta:
        verbose_name = "Producto de Canje"
        verbose_name_plural = "Productos de Canje"
        ordering = ['puntos_requeridos', 'nombre']

    def __str__(self):
        return f"{self.nombre} ({self.puntos_requeridos} puntos)"


# ---------- Perfil de cliente + señal
class ClienteProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='clienteprofile')
    direccion = models.CharField(max_length=255, blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    puntos_fidelidad = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self):
        return f'Perfil de {self.user.username}'


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        if not hasattr(instance, 'clienteprofile'):
            ClienteProfile.objects.create(user=instance)
    if hasattr(instance, 'clienteprofile'):
        instance.clienteprofile.save()


# =========================
# POS / CAJA (nuevo)
# =========================

MEDIO_PAGO_POS_CHOICES = [
    ('EFECTIVO', 'Efectivo'),
    ('QR_MP', 'QR / MercadoPago'),
    ('TARJETA', 'Tarjeta (déb./créd.)'),
    ('TRANSFERENCIA', 'Transferencia'),
    ('OTRO', 'Otro'),
]
MEDIO_PAGO_POS_MAXLEN = 30  # margen para futuros valores

class ProductoPOS(models.Model):
    """Catálogo exclusivo para caja (POS), sin sabores ni variantes."""
    nombre = models.CharField(max_length=120)
    precio = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    codigo_sku = models.CharField(max_length=40, blank=True, default='')
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return f"{self.nombre} (${self.precio})"


class Caja(models.Model):
    ESTADO_CAJA = [
        ('ABIERTA', 'ABIERTA'),
        ('CERRADA', 'CERRADA'),
    ]

    fecha_apertura = models.DateTimeField(auto_now_add=True)
    usuario_apertura = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='cajas_abiertas')
    saldo_inicial_efectivo = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    estado = models.CharField(max_length=10, choices=ESTADO_CAJA, default='ABIERTA')
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    usuario_cierre = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='cajas_cerradas')
    saldo_cierre_efectivo = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    observaciones = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"Caja #{self.id} ({self.estado})"

    # ---- Totales & arqueo
    def movimientos_queryset(self):
        return self.movimientos.all()

    def _sum(self, qs):
        agg = qs.aggregate(total=models.Sum('monto'))
        return agg['total'] or Decimal('0')

    def total_ventas_por_medio(self):
        data = {}
        qs = self.movimientos.filter(tipo='VENTA').values('medio_pago').annotate(t=models.Sum('monto'))
        for row in qs:
            data[row['medio_pago']] = row['t'] or Decimal('0')
        return data

    def total_por_tipo_mov(self):
        data = {}
        qs = self.movimientos.values('tipo').annotate(t=models.Sum('monto'))
        for row in qs:
            data[row['tipo']] = row['t'] or Decimal('0')
        return data

    def saldo_efectivo_teorico(self):
        qs = self.movimientos.filter(medio_pago='EFECTIVO')
        ventas = self._sum(qs.filter(tipo='VENTA'))
        ingresos = self._sum(qs.filter(tipo='INGRESO'))
        ajustes = self._sum(qs.filter(tipo='AJUSTE'))
        egresos = self._sum(qs.filter(tipo='EGRESO'))
        retiros = self._sum(qs.filter(tipo='RETIRO'))
        return (self.saldo_inicial_efectivo or Decimal('0')) + ventas + ingresos + ajustes - egresos - retiros

    def diferencia_efectivo(self):
        if self.saldo_cierre_efectivo is None:
            return None
        return (self.saldo_cierre_efectivo or Decimal('0')) - self.saldo_efectivo_teorico()


class VentaPOS(models.Model):
    TIPO_COMPROBANTE = [
        ('COMANDA', 'Comanda (sin fiscal)'),
        ('BISTRO', 'Bistró (con factura)'),
    ]
    ESTADO_VENTA = [
        ('COMPLETADA', 'COMPLETADA'),
        ('CANCELADA', 'CANCELADA'),
    ]

    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    caja = models.ForeignKey(Caja, on_delete=models.PROTECT, related_name='ventas')

    tipo_comprobante = models.CharField(max_length=10, choices=TIPO_COMPROBANTE, default='COMANDA')
    medio_pago = models.CharField(max_length=MEDIO_PAGO_POS_MAXLEN, choices=MEDIO_PAGO_POS_CHOICES, default='EFECTIVO')
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estado = models.CharField(max_length=12, choices=ESTADO_VENTA, default='COMPLETADA')

    numero_comprobante = models.CharField(max_length=60, blank=True, default='')
    notas = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"VentaPOS #{self.id} ({self.tipo_comprobante} · {self.medio_pago}) - ${self.total}"

    def recomputar_total(self, save=True):
        t = self.items.aggregate(s=models.Sum('subtotal'))['s'] or Decimal('0')
        self.total = t
        if save:
            self.save(update_fields=['total'])
        return t


class VentaPOSItem(models.Model):
    venta = models.ForeignKey(VentaPOS, on_delete=models.CASCADE, related_name='items')  # <-- ojo: sin espacio en tu editor
    producto = models.ForeignKey(ProductoPOS, on_delete=models.SET_NULL, null=True, blank=True)
    descripcion = models.CharField(max_length=160)
    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.descripcion} x{self.cantidad} = ${self.subtotal}"

    def save(self, *args, **kwargs):
        self.subtotal = (self.precio_unitario or Decimal('0')) * (self.cantidad or 0)
        super().save(*args, **kwargs)


class MovimientoCaja(models.Model):
    TIPO_MOV = [
        ('VENTA', 'VENTA'),
        ('INGRESO', 'INGRESO'),
        ('EGRESO', 'EGRESO'),
        ('AJUSTE', 'AJUSTE'),
        ('RETIRO', 'RETIRO'),
    ]

    caja = models.ForeignKey(Caja, on_delete=models.CASCADE, related_name='movimientos')
    fecha = models.DateTimeField(auto_now_add=True)
    tipo = models.CharField(max_length=10, choices=TIPO_MOV)
    medio_pago = models.CharField(max_length=MEDIO_PAGO_POS_MAXLEN, choices=MEDIO_PAGO_POS_CHOICES, default='EFECTIVO')
    monto = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    descripcion = models.CharField(max_length=240, blank=True, default='')
    venta = models.ForeignKey(VentaPOS, on_delete=models.SET_NULL, null=True, blank=True, related_name='movimiento_caja')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"{self.tipo} {self.medio_pago} ${self.monto} (Caja #{self.caja_id})"
# ===== Señales POS/Caja =====
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

@receiver(post_save, sender=VentaPOSItem)
@receiver(post_delete, sender=VentaPOSItem)
def _recompute_total_on_item_change(sender, instance, **kwargs):
    """Recalcula total de la venta cuando se agregan/editen/borren ítems."""
    if instance.venta_id:
        instance.venta.recomputar_total(save=True)

@receiver(post_save, sender=VentaPOS)
def _sync_movimiento_caja_con_venta(sender, instance: VentaPOS, **kwargs):
    """
    Mantiene el MovimientoCaja sincronizado con la VentaPOS:
    - Si la venta está CANCELADA => elimina movimiento asociado.
    - Si la venta está COMPLETADA => crea/actualiza el movimiento tipo VENTA.
    """
    from .models import MovimientoCaja  # import local para evitar ciclos

    if instance.estado == 'CANCELADA':
        MovimientoCaja.objects.filter(venta=instance).delete()
        return

    mov, created = MovimientoCaja.objects.get_or_create(
        venta=instance,
        defaults={
            'caja': instance.caja,
            'tipo': 'VENTA',
            'medio_pago': instance.medio_pago,
            'monto': instance.total,
            'descripcion': f'VentaPOS #{instance.id}',
            'usuario': instance.usuario,
        }
    )
    if not created:
        # Actualiza por si cambió algo (monto, medio de pago, caja, etc.)
        mov.caja = instance.caja
        mov.medio_pago = instance.medio_pago
        mov.monto = instance.total
        mov.usuario = instance.usuario
        mov.descripcion = f'VentaPOS #{instance.id}'
        mov.save(update_fields=['caja','medio_pago','monto','usuario','descripcion'])
