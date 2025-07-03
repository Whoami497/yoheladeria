from django.db import migrations

def crear_datos_iniciales(apps, schema_editor):
    # Creamos el Superusuario
    User = apps.get_model('auth', 'User')
    User.objects.create_superuser(
        'whoami497',
        'Lucasxlo89@gmail.com',
        '39014174*'
    )

    # Creamos algunos Sabores de ejemplo
    Sabor = apps.get_model('pedidos', 'Sabor')
    Sabor.objects.create(nombre='Dulce de Leche Granizado')
    Sabor.objects.create(nombre='Chocolate con Almendras')
    Sabor.objects.create(nombre='Frutilla a la Crema')
    Sabor.objects.create(nombre='Limón')

    # Creamos algunos Productos de ejemplo
    Producto = apps.get_model('pedidos', 'Producto')
    Producto.objects.create(nombre='Pote 1 KG', precio=18000.00, sabores_maximos=4)
    Producto.objects.create(nombre='Pote 1/2 KG', precio=10000.00, sabores_maximos=3)
    Producto.objects.create(nombre='Pote 1/4 KG', precio=5500.00, sabores_maximos=2)


class Migration(migrations.Migration):

    dependencies = [
        ('pedidos', '0002_pedido_detallepedido'), # Asegúrate que el número coincida con tu última migración
    ]

    operations = [
        migrations.RunPython(crear_datos_iniciales),
    ]
