from django.db import models

# Create your models here.

class Sabor(models.Model):
    nombre = models.CharField(max_length=100)
    disponible = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre

class Producto(models.Model):
    nombre = models.CharField(max_length=100)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    sabores_maximos = models.PositiveIntegerField(default=1)
    disponible = models.BooleanField(default=True)
    # --- AÑADE ESTA LÍNEA ---
    imagen = models.ImageField(upload_to='productos/', null=True, blank=True)

    def __str__(self):
        return self.nombre

# --- AGREGA ESTAS DOS NUEVAS CLASES DEBAJO ---

class Pedido(models.Model):
    ESTADO_CHOICES = [
        ('RECIBIDO', 'Recibido'),
        ('EN_PREPARACION', 'En Preparación'),
        ('EN_CAMINO', 'En Camino'),
        ('ENTREGADO', 'Entregado'),
        ('CANCELADO', 'Cancelado'),
    ]
    
    cliente_nombre = models.CharField(max_length=100)
    cliente_direccion = models.CharField(max_length=255)
    cliente_telefono = models.CharField(max_length=20, blank=True)
    fecha_pedido = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='RECIBIDO')
    
    def __str__(self):
        return f'Pedido #{self.id} - {self.cliente_nombre}'

class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, related_name='detalles', on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    sabores = models.ManyToManyField(Sabor)
    
    def __str__(self):
        return f'{self.producto.nombre} en Pedido #{self.pedido.id}'