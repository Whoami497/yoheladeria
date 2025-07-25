# Generated by Django 5.2.4 on 2025-07-03 05:36

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pedidos', '0002_producto'),
    ]

    operations = [
        migrations.CreateModel(
            name='Pedido',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cliente_nombre', models.CharField(max_length=100)),
                ('cliente_direccion', models.CharField(max_length=255)),
                ('cliente_telefono', models.CharField(blank=True, max_length=20)),
                ('fecha_pedido', models.DateTimeField(auto_now_add=True)),
                ('estado', models.CharField(choices=[('RECIBIDO', 'Recibido'), ('EN_PREPARACION', 'En Preparación'), ('EN_CAMINO', 'En Camino'), ('ENTREGADO', 'Entregado'), ('CANCELADO', 'Cancelado')], default='RECIBIDO', max_length=20)),
            ],
        ),
        migrations.CreateModel(
            name='DetallePedido',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('producto', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='pedidos.producto')),
                ('sabores', models.ManyToManyField(to='pedidos.sabor')),
                ('pedido', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='detalles', to='pedidos.pedido')),
            ],
        ),
    ]
