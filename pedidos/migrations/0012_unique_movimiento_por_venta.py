from django.db import migrations, models
from django.db.models import Q

def dedupe_movimientos(apps, schema_editor):
    MovimientoCaja = apps.get_model('pedidos', 'MovimientoCaja')
    # agrupamos por (venta_id, tipo) y si hay más de uno, dejamos el más nuevo
    from collections import defaultdict
    buckets = defaultdict(list)
    for mov in MovimientoCaja.objects.exclude(venta__isnull=True).filter(tipo='VENTA').only('id', 'venta_id', 'tipo'):
        buckets[(mov.venta_id, mov.tipo)].append(mov.id)

    # borrar duplicados dejando el id más alto (último cargado)
    to_delete = []
    for key, ids in buckets.items():
        if len(ids) > 1:
            ids.sort()
            to_delete.extend(ids[:-1])  # todos menos el último

    if to_delete:
        MovimientoCaja.objects.filter(id__in=to_delete).delete()

class Migration(migrations.Migration):

    dependencies = [
        ('pedidos', '0011_productopos_caja_ventapos_movimientocaja_and_more'),
    ]

    operations = [
        migrations.RunPython(dedupe_movimientos, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='movimientocaja',
            constraint=models.UniqueConstraint(
                fields=('venta', 'tipo'),
                condition=Q(venta__isnull=False),
                name='uniq_mov_por_venta_tipo',
            ),
        ),
    ]
