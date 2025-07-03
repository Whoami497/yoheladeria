from django.db import migrations

def restaurar_superusuario(apps, schema_editor):
    User = apps.get_model('auth', 'User')

    # Define los datos de tu admin
    username = 'lucasxlo89'
    email = 'lucasxlo89@gmail.com'
    password = '39014174*'

    # Borra el usuario si existe, para empezar de limpio
    if User.objects.filter(username=username).exists():
        User.objects.get(username=username).delete()

    # Crea el superusuario de nuevo
    User.objects.create_superuser(username, email, password)
    print(f"\nSuperusuario '{username}' restaurado correctamente.")


class Migration(migrations.Migration):

    dependencies = [
        # Asegúrate que apunte a tu última migración (la de limpiar datos)
        ('pedidos', '0007_limpiar_datos_viejos'),
    ]

    operations = [
        migrations.RunPython(restaurar_superusuario),
    ]
