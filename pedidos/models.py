# pedidos/models.py

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from decimal import Decimal

# =========================
# Estado de la tienda (interruptor maestro)
# =========================
class StoreStatus(models.Model):
    # Fila única (pk=1)
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    is_open = models.BooleanField(default=True, help_text="Si está apagado, no se aceptan nuevos pedidos.")
    message = models.CharField(max_length=200, blank=True, help_text="Mensaje opcional para mostrar en la web.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Estado de la tienda"
        verbose_name_plural = "Estado de la tienda"

    def __str__(self):
        return "Tienda abierta" if self.is_open else "Tienda pausada"

    @classmethod
    def get(cls):
        """Devuelve la única fila de estado (la crea si no existe)."""
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"is_open": True})
        return obj


# =========================
# Configuración global (clave-valor) — usado por las vistas para TIENDA_ABIERTA
# =========================
class GlobalSetting(models.Model):
    """
    Clave-valor simple persistente.
    Las vistas usan GlobalSetting.get_bool('TIENDA_ABIERTA', default=True/False)
    para leer si la tienda está abierta. Esto evita que vuelva al default al recargar.
    """
    key = models.CharField(max_length=64, unique=True)
    value_text = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        verbose_name = "Configuración global"
        verbose_name_plural = "Configuraciones globales"

    def __str__(self):
        return f"{self.key}={self.value_text}"

    # Helpers
    @classmethod
    def get(cls, key: str, default: str = "") -> str:
        try:
            return cls.objects.only("value_text").get(key=key).value_text
        except cls.DoesNotExist:
            return default

    @classmethod
    def set(cls, key: str, value: str) -> None:
        cls.objects.update_or_create(key=key, defaults={"value_text": value})

    @classmethod
    def get_bool(cls, key: str, default: bool = False) -> bool:
        """
        Lee un booleano. Si la clave es 'TIENDA_ABIERTA' y no existe aún en esta tabla,
        intenta caer al valor de StoreStatus (si lo tenés cargado) como compatibilidad.
        """
        raw = cls.get(key, None)
        if raw is None:
            if key == "TIENDA_ABIERTA":
                try:
                    ss = StoreStatus.get()
                    return bool(ss.is_open)
                except Exception:
                    return bool(default)
            return bool(default)
        raw = (raw or "").strip().lower()
        return raw in ("1", "true", "t", "yes", "y", "si", "sí", "on")

    @classmethod
    def set_bool(cls, key: str, value: bool) -> bool:
        cls.set(key, "1" if value else "0")
        return bool(value)


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
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='productos'
    )
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(
        blank=True,
        null=True,
        help_text="Descripción detallada del producto."
    )
    precio = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Precio base del producto. Las opciones pueden tener precios adicionales."
    )
    sabores_maximos = models.PositiveIntegerField(
        default=0,
        help_text="Número máximo de sabores a elegir para este producto. Cero si no permite elección de sabores (ej. tortas, palitos)."
    )
    disponible = models.BooleanField(default=True)
    imagen = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Ruta a la imagen estática del producto base (ej: 'images/pote_1_5kg.png')"
    )

    # NUEVO: controla el orden en la pestaña “Todos”
    orden_todos = models.PositiveIntegerField(
        default=1000,
        db_index=True,
        help_text="Posición en la vista 'Todos'. Menor sale antes."
    )

    def __str__(self):
        if self.categoria:
            return f"{self.nombre} ({self.categoria.nombre})"
        return self.nombre

    class Meta:
        # Hace que por defecto se listen ordenados primero por orden_todos y luego por nombre
        ordering = ("orden_todos", "nombre")

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

    def __str__(self):
        if self.user.first_name and self.user.last_name:
            return f'Cadete: {self.user.first_name} {self.user.last_name}'
        return f'Cadete: {self.user.username}'


class Pedido(models.Model):
    ESTADO_CHOICES = [
        ('PENDIENTE_PAGO', 'Pendiente de pago'),   # ← NUEVO estado para MP
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
    fecha_pedido = models.DateTimeField(auto_now_add=True, db_index=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='RECIBIDO', db_index=True)
    metodo_pago = models.CharField(max_length=20, choices=METODO_PAGO_CHOICES, default='EFECTIVO')
    zona_envio = models.ForeignKey(ZonaEnvio, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_en_zona')

    # 🆕 Costo real de envío (API o manual)
    costo_envio = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Costo calculado del envío (ej: por Google Maps).")

    cadete_asignado = models.ForeignKey(
        CadeteProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pedidos_asignados',
        help_text="El cadete que ha aceptado este pedido."
    )

    # 🆕 Hitos de tiempo para métricas (opcionales, los setea la vista si existen)
    fecha_pago_aprobado   = models.DateTimeField(null=True, blank=True, help_text="Momento en que el pago fue aprobado (o creación para efectivo).")
    fecha_en_preparacion  = models.DateTimeField(null=True, blank=True, help_text="Cuando la tienda confirma y pasa a preparación.")
    fecha_asignado        = models.DateTimeField(null=True, blank=True, help_text="Cuando un cadete acepta el pedido.")
    fecha_en_camino       = models.DateTimeField(null=True, blank=True, help_text="Cuando el cadete marca 'en camino'.")
    fecha_entregado       = models.DateTimeField(null=True, blank=True, help_text="Cuando el pedido se marca como entregado.")
    fecha_cancelado       = models.DateTimeField(null=True, blank=True, help_text="Cuando el pedido se cancela.")

    class Meta:
        indexes = [
            models.Index(fields=['estado']),
            models.Index(fields=['-fecha_pedido']),
        ]

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
        # Evitar doble cobro: si costo_envio > 0 lo usamos; si no, fallback a zona_envio.costo
        if self.costo_envio:
            total += self.costo_envio
        elif self.zona_envio and self.zona_envio.costo:
            total += self.zona_envio.costo
        return total

    # ---- Helpers de métricas
    def _mins(self, t1, t2):
        if not t1 or not t2:
            return None
        return round((t2 - t1).total_seconds() / 60.0, 2)

    def _secs(self, t1, t2):
        if not t1 or not t2:
            return None
        return int((t2 - t1).total_seconds())

    def tiempos_en_minutos(self):
        """Dict con tiempos clave en minutos (None si falta un hito)."""
        return {
            'm_recibido_a_preparacion': self._mins(self.fecha_pago_aprobado or self.fecha_pedido, self.fecha_en_preparacion),
            'm_preparacion_a_asignado': self._mins(self.fecha_en_preparacion, self.fecha_asignado),
            'm_asignado_a_en_camino':   self._mins(self.fecha_asignado, self.fecha_en_camino),
            'm_en_camino_a_entregado':  self._mins(self.fecha_en_camino, self.fecha_entregado),
            'm_total':                  self._mins(self.fecha_pago_aprobado or self.fecha_pedido, self.fecha_entregado),
        }

    def tiempos_en_segundos(self):
        """Dict con tiempos clave en segundos (None si falta un hito)."""
        return {
            's_recibido_a_preparacion': self._secs(self.fecha_pago_aprobado or self.fecha_pedido, self.fecha_en_preparacion),
            's_preparacion_a_asignado': self._secs(self.fecha_en_preparacion, self.fecha_asignado),
            's_asignado_a_en_camino':   self._secs(self.fecha_asignado, self.fecha_en_camino),
            's_en_camino_a_entregado':  self._secs(self.fecha_en_camino, self.fecha_entregado),
            's_total':                  self._secs(self.fecha_pago_aprobado or self.fecha_pedido, self.fecha_entregado),
        }


class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, related_name='detalles', on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    opcion_seleccionada = models.ForeignKey(OpcionProducto, on_delete=models.PROTECT, null=True, blank=True)
    sabores = models.ManyToManyField(Sabor)
    cantidad = models.PositiveIntegerField(default=1)
    nota = models.CharField(max_length=255, blank=True, default="")  # <— NUEVO
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


# ---------- 🆕 Log de cambios de estado (trazabilidad/metrics)
class PedidoEstadoLog(models.Model):
    ACTOR_CHOICES = [
        ('sistema', 'Sistema'),
        ('staff', 'Staff'),
        ('cadete', 'Cadete'),
        ('cliente', 'Cliente'),
    ]

    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='logs_estado')
    de = models.CharField(max_length=20, blank=True, null=True)
    a = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    actor_tipo = models.CharField(max_length=10, choices=ACTOR_CHOICES, default='sistema')
    fuente = models.CharField(max_length=50, blank=True, help_text="Origen del cambio (panel, cadete, webhook_mp, etc.)")
    meta = models.JSONField(null=True, blank=True, help_text="Datos auxiliares (ej: payment_id, ip, etc.)")

    class Meta:
        verbose_name = "Log de Estado de Pedido"
        verbose_name_plural = "Logs de Estado de Pedido"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['pedido', '-created_at']),
            models.Index(fields=['a']),
        ]

    def __str__(self):
        return f"Pedido #{self.pedido_id}: {self.de or '—'} → {self.a} @ {self.created_at:%Y-%m-%d %H:%M}"


# ---------- 🆕 Señales
@receiver(post_save, sender=Pedido)
def pedido_set_inicio_si_corresponde(sender, instance: Pedido, created, **kwargs):
    """
    Al crear un pedido:
      - Para EFECTIVO: si quedó en RECIBIDO, fijamos fecha_pago_aprobado = fecha_pedido.
      - Para MERCADOPAGO: NO marcamos aprobado acá (queda PENDIENTE_PAGO hasta el webhook).
    """
    if not created:
        return
    try:
        if instance.metodo_pago != 'MERCADOPAGO' and instance.estado == 'RECIBIDO' and not instance.fecha_pago_aprobado:
            instance.fecha_pago_aprobado = instance.fecha_pedido
            instance.save(update_fields=['fecha_pago_aprobado'])
    except Exception:
        pass
