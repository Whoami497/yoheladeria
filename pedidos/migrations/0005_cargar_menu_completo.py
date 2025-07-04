# Generated by Gemini
from django.db import migrations

def cargar_productos_iniciales(apps, schema_editor):
    Producto = apps.get_model('pedidos', 'Producto')

    # Productos extraídos del menú, excluyendo conos y cucuruchones.
    productos_a_cargar = [
        # Página 1
        {'nombre': 'Palito Bombón x 12 u.', 'precio': 14000, 'sabores_maximos': 1},
        {'nombre': 'Doble Yo x 14 u.', 'precio': 15000, 'sabores_maximos': 1},
        {'nombre': 'Palito Fru/Limón x 14 u.', 'precio': 11000, 'sabores_maximos': 1},
        {'nombre': 'Tortas Heladas', 'precio': 17000, 'sabores_maximos': 0},
        {'nombre': 'Escocés x 8 u.', 'precio': 17000, 'sabores_maximos': 0},
        {'nombre': 'Copa Stop', 'precio': 2600, 'sabores_maximos': 0},
        {'nombre': 'Balde Light 500 grs.', 'precio': 10000, 'sabores_maximos': 3},
        {'nombre': 'Balde 500 grs.', 'precio': 8000, 'sabores_maximos': 3},
        {'nombre': 'Balde 1,5 kg.', 'precio': 16000, 'sabores_maximos': 4},
        {'nombre': 'Alfajor Yo', 'precio': 2000, 'sabores_maximos': 0},
        {'nombre': 'Eclipse', 'precio': 1800, 'sabores_maximos': 0},
        {'nombre': 'Bananita', 'precio': 1800, 'sabores_maximos': 0},
        {'nombre': 'Palito XXL', 'precio': 2200, 'sabores_maximos': 0},
        {'nombre': 'Barritas Yo-Bar', 'precio': 1100, 'sabores_maximos': 0},
        {'nombre': 'Cono Magnífico', 'precio': 3000, 'sabores_maximos': 0},
        {'nombre': 'Cool Fruit', 'precio': 800, 'sabores_maximos': 0},
        {'nombre': 'Paleta R & F', 'precio': 1800, 'sabores_maximos': 0},
        {'nombre': 'Circus', 'precio': 1200, 'sabores_maximos': 0},
        {'nombre': 'Palitos ABC', 'precio': 800, 'sabores_maximos': 0},
        {'nombre': 'Yo Crok', 'precio': 1700, 'sabores_maximos': 0},
        {'nombre': 'Cool Cream', 'precio': 1100, 'sabores_maximos': 0},
        {'nombre': 'Inside', 'precio': 1100, 'sabores_maximos': 0},
        {'nombre': 'Cream Granizado', 'precio': 1600, 'sabores_maximos': 0},
        {'nombre': 'Monstruoso', 'precio': 900, 'sabores_maximos': 0},
        # Página 2
        {'nombre': 'Tricolor x 8 u.', 'precio': 11000, 'sabores_maximos': 0},
        {'nombre': 'Almendrado x 8 u.', 'precio': 14000, 'sabores_maximos': 0},
        {'nombre': 'Suizo x 8 u.', 'precio': 16000, 'sabores_maximos': 0},
        {'nombre': 'Barra Capuccino', 'precio': 15000, 'sabores_maximos': 0},
        {'nombre': 'Pinito', 'precio': 5400, 'sabores_maximos': 0},
        {'nombre': 'Lanchita', 'precio': 3500, 'sabores_maximos': 0},
        {'nombre': 'Bombón Andino', 'precio': 4500, 'sabores_maximos': 0},
        {'nombre': 'Capelina Imperial', 'precio': 6400, 'sabores_maximos': 0},
        {'nombre': 'Bandeja Caribean', 'precio': 6500, 'sabores_maximos': 0},
        {'nombre': 'Bandeja Reina', 'precio': 6600, 'sabores_maximos': 0},
        {'nombre': 'Milkshake', 'precio': 5000, 'sabores_maximos': 1},
        {'nombre': 'Tragos Fresh', 'precio': 4300, 'sabores_maximos': 0},
        {'nombre': 'Vaso Yo', 'precio': 4500, 'sabores_maximos': 2},
        {'nombre': 'Vaso 1/8', 'precio': 4500, 'sabores_maximos': 1},
        {'nombre': '1/4 kg.', 'precio': 5000, 'sabores_maximos': 2},
        {'nombre': '1/2 kg.', 'precio': 8400, 'sabores_maximos': 3},
        {'nombre': '1 kg.', 'precio': 16000, 'sabores_maximos': 4},
        {'nombre': 'Ice Tropical', 'precio': 4000, 'sabores_maximos': 0},
        {'nombre': 'Almendrado (Postre)', 'precio': 2000, 'sabores_maximos': 0},
        {'nombre': 'Tricolor (Postre)', 'precio': 1600, 'sabores_maximos': 0},
        {'nombre': 'Bombón Suizo', 'precio': 2200, 'sabores_maximos': 0},
        {'nombre': 'Escoces (Postre)', 'precio': 2300, 'sabores_maximos': 0},
    ]

    for prod in productos_a_cargar:
        Producto.objects.create(
            nombre=prod['nombre'],
            precio=prod['precio'],
            sabores_maximos=prod['sabores_maximos']
        )

class Migration(migrations.Migration):

    dependencies = [
        ('pedidos', '0004_datos_iniciales'), # <-- IMPORTANTE: Asegúrate que este sea el nombre de tu última migración
    ]

    operations = [
        migrations.RunPython(cargar_productos_iniciales),
    ]
