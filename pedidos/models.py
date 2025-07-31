# pedidos/models.py

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from decimal import Decimal

# Modelo para las Categorías de Productos (ej. Potes, Tortas, Palitos)
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

# Los "Sabores" que se eligen para productos que permiten multiples sabores (ej. potes)
class Sabor(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    disponible = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre

# Modelo Producto ahora representa el "tipo" de producto (ej. "Pote 1.5Kg", "Palito Bomboneiro", "Torta Helada")
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


# Modelo para Opciones Específicas o Variaciones de un Producto Base
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


# Modelo ZonaEnvio
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


class Pedido(models.Model):
    ESTADO_CHOICES = [
        ('RECIBIDO', 'Recibido'),
        ('EN_PREPARACION', 'En Preparación'),
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


# Modelo ProductoCanje
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


# Modelo CadeteProfile
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
    
    # --- INICIO: NUEVO CAMPO PARA SUSCRIPCIÓN WEBPUSH ---
    subscription_info = models.JSONField(
        null=True, 
        blank=True, 
        verbose_name="Información de Suscripción WebPush",
        help_text="Contiene la información de la suscripción push del navegador del cadete."
    )
    # --- FIN: NUEVO CAMPO PARA SUSCRIPCIÓN WEBPUSH ---

    latitud_actual = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud_actual = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        verbose_name = "Perfil de Cadete"
        verbose_name_plural = "Perfiles de Cadetes"

    def __str__(self):
        if self.user.first_name and self.user.last_name:
            return f'Cadete: {self.user.first_name} {self.user.last_name}'
        return f'Cadete: {self.user.username}'


# Modelo ClienteProfile y Señales
class ClienteProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='clienteprofile') # related_name añadido
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
    # Asegurarse de que el perfil se guarde en cada actualización del usuario también
    if hasattr(instance, 'clienteprofile'):
        instance.clienteprofile.save()