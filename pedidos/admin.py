from django.contrib import admin
from .models import Sabor, Producto, Pedido, DetallePedido # <-- Importa los nuevos

# Register your models here.
admin.site.register(Sabor)
admin.site.register(Producto)
admin.site.register(Pedido) # <-- Registra Pedido
admin.site.register(DetallePedido) # <-- Registra DetallePedido