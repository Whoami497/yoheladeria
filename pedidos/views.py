from django.shortcuts import render, redirect, get_object_or_404
from .models import Producto, Sabor, Pedido, DetallePedido
from decimal import Decimal
from django.contrib import messages # Importación necesaria para el sistema de mensajes

def index(request):
    productos = Producto.objects.filter(disponible=True)
    contexto = {'productos': productos}
    return render(request, 'pedidos/index.html', contexto)

def detalle_producto(request, producto_id):
    producto = get_object_or_404(Producto, id=producto_id)
    sabores_disponibles = Sabor.objects.filter(disponible=True).order_by('nombre')

    if request.method == 'POST':
        # Primero, obtenemos todos los IDs de sabores seleccionados, incluyendo los vacíos
        sabores_seleccionados_ids_raw = request.POST.getlist('sabores')

        # Filtramos para quedarnos solo con los IDs que no estén vacíos
        sabores_seleccionados_ids = [s_id for s_id in sabores_seleccionados_ids_raw if s_id]

        # Obtenemos la cantidad de sabores que el usuario seleccionó en el dropdown "Cantidad de Sabores"
        cantidad_sabores_seleccionada_en_form = int(request.POST.get('cantidad_sabores', 0))

        # --- Validaciones de Sabores ---
        if producto.sabores_maximos > 0: # Si el producto permite selección de sabores
            # Validar que el número de sabores seleccionados (limpios) coincida con el número elegido en el dropdown
            if len(sabores_seleccionados_ids) != cantidad_sabores_seleccionada_en_form:
                messages.error(request, f'Por favor, selecciona {cantidad_sabores_seleccionada_en_form} sabor(es) o ajusta la cantidad de sabores a seleccionar.')
                contexto = {
                    'producto': producto,
                    'sabores': sabores_disponibles,
                    'range_sabores': range(1, producto.sabores_maximos + 1)
                }
                return render(request, 'pedidos/detalle_producto.html', contexto)

            # Validar que no exceda el máximo permitido por el producto (aunque el JS debería limitar esto)
            if len(sabores_seleccionados_ids) > producto.sabores_maximos:
                messages.error(request, f'No puedes seleccionar más de {producto.sabores_maximos} sabor(es) para este producto.')
                contexto = {
                    'producto': producto,
                    'sabores': sabores_disponibles,
                    'range_sabores': range(1, producto.sabores_maximos + 1)
                }
                return render(request, 'pedidos/detalle_producto.html', contexto)

        # Si el producto NO permite sabores (sabores_maximos == 0),
        # nos aseguramos de que la lista de IDs de sabores esté vacía, ignorando cualquier envío inesperado.
        if producto.sabores_maximos == 0 and sabores_seleccionados_ids:
            sabores_seleccionados_ids = [] 

        # --- Lógica de Carrito ---
        if 'carrito' not in request.session:
            request.session['carrito'] = {}

        sabores_nombres = []
        if sabores_seleccionados_ids: # Si hay IDs de sabores válidos para procesar
            sabores_objetos = Sabor.objects.filter(id__in=sabores_seleccionados_ids)
            sabores_nombres = [sabor.nombre for sabor in sabores_objetos]
            sabores_nombres.sort() # Para consistencia en la visualización

        # La clave del ítem en el carrito se construye con el ID del producto y los IDs de los sabores (ordenados)
        item_key = f"{producto.id}_" + "_".join(sorted(sabores_seleccionados_ids))

        # Creamos el diccionario que representa el ítem del carrito
        item = {
            'producto_id': producto.id,
            'producto_nombre': producto.nombre,
            'precio': str(producto.precio), # Se guarda como string para evitar problemas de serialización
            'sabores_ids': sabores_seleccionados_ids,
            'sabores_nombres': sabores_nombres,
            'cantidad': 1, # Cantidad inicial del ítem
            'sabores_maximos': producto.sabores_maximos # Para futuras referencias en el carrito
        }

        # Si el ítem ya existe en el carrito (misma clave), incrementamos la cantidad
        if item_key in request.session['carrito']:
            request.session['carrito'][item_key]['cantidad'] += 1
            messages.info(request, f'Se ha añadido otra unidad de "{producto.nombre}" al carrito.') 
        else: # Si es un ítem nuevo, lo añadimos al carrito
            request.session['carrito'][item_key] = item
            messages.success(request, f'"{producto.nombre}" ha sido añadido al carrito.') 

        request.session.modified = True # ¡Fundamental para que Django guarde los cambios en la sesión!

        return redirect('index') # Redirigimos a la página principal después de añadir

    # Para solicitudes GET (cuando la página de detalle se carga por primera vez)
    range_sabores = []
    if producto.sabores_maximos > 0:
        range_sabores = range(1, producto.sabores_maximos + 1) # Genera una lista de números de 1 a 'sabores_maximos'

    contexto = {
        'producto': producto,
        'sabores': sabores_disponibles,
        'range_sabores': range_sabores,
    }
    return render(request, 'pedidos/detalle_producto.html', contexto)

def ver_carrito(request):
    carrito = request.session.get('carrito', {}) # Obtiene el carrito de la sesión (diccionario vacío si no existe)

    total = Decimal('0.00')
    items_carrito_procesados = []

    # Iteramos sobre los ítems del carrito para calcular totales y prepararlos para el template
    for key, item in carrito.items():
        try:
            item_precio = Decimal(item.get('precio', '0.00')) 
            item_cantidad = item.get('cantidad', 1) 
            item_subtotal = item_precio * item_cantidad
            total += item_subtotal

            items_carrito_procesados.append({
                'key': key, # Clave del ítem en la sesión (útil para eliminar)
                'producto_id': item['producto_id'], 
                'producto_nombre': item['producto_nombre'], 
                'precio_unidad': item_precio, 
                'cantidad': item_cantidad, 
                'sabores_nombres': item.get('sabores_nombres', []), 
                'sabores_maximos': item.get('sabores_maximos', 0), 
                'subtotal': item_subtotal 
            })
        except Exception as e:
            print(f"Error procesando ítem en carrito: {e} - Item: {item}")
            messages.warning(request, "Hubo un problema con uno de los ítems en tu carrito y fue omitido.") 
            continue

    if request.method == 'POST':
        # Obtenemos los datos del formulario de envío
        nombre = request.POST.get('cliente_nombre')
        direccion = request.POST.get('cliente_direccion')
        telefono = request.POST.get('cliente_telefono')

        # Validaciones básicas del formulario
        if not nombre or not direccion: 
            messages.error(request, 'Por favor, completa los campos Nombre y Dirección para finalizar el pedido.') 
            contexto = { # Retornamos el contexto con los ítems del carrito y el total para que el usuario no pierda lo que ya tenía
                'carrito_items': items_carrito_procesados,
                'total': total,
            }
            return render(request, 'pedidos/carrito.html', contexto)

        # Validar que el carrito no esté vacío al intentar finalizar el pedido
        if not items_carrito_procesados: 
            messages.error(request, 'No puedes finalizar un pedido con el carrito vacío.') 
            return redirect('ver_carrito')


        # Creamos el nuevo objeto Pedido en la base de datos
        nuevo_pedido = Pedido.objects.create(
            cliente_nombre=nombre,
            cliente_direccion=direccion,
            cliente_telefono=telefono
        )

        # Iteramos sobre los ítems del carrito para crear los DetallePedido asociados
        for key, item_data in carrito.items(): 
            try:
                producto = Producto.objects.get(id=item_data['producto_id'])
                sabores_seleccionados_ids = item_data.get('sabores_ids', []) 
                sabores_seleccionados = Sabor.objects.filter(id__in=sabores_seleccionados_ids)

                detalle = DetallePedido.objects.create(
                    pedido=nuevo_pedido,
                    producto=producto,
                )
                detalle.sabores.set(sabores_seleccionados) 

            except Producto.DoesNotExist:
                messages.warning(request, f"Advertencia: Un producto con ID {item_data['producto_id']} no pudo ser añadido al pedido porque no existe.") 
                continue
            except Exception as e:
                messages.error(request, f"Error al procesar el detalle del pedido para {item_data.get('producto_nombre', 'un producto')}: {e}") 
                continue

        del request.session['carrito'] # Vaciamos el carrito de la sesión después de crear el pedido
        request.session.modified = True # Fundamental para guardar el cambio de la sesión

        messages.success(request, f'¡Tu pedido #{nuevo_pedido.id} ha sido realizado con éxito! Pronto nos contactaremos.') 

        return redirect('pedido_exitoso')

    # Para solicitudes GET
    contexto = {
        'carrito_items': items_carrito_procesados, 
        'total': total,
    }
    return render(request, 'pedidos/carrito.html', contexto)

def eliminar_del_carrito(request, item_key):
    if 'carrito' in request.session:
        carrito = request.session['carrito']
        if item_key in carrito:
            nombre_producto_eliminado = carrito[item_key]['producto_nombre']
            del carrito[item_key]
            request.session.modified = True
            messages.info(request, f'"{nombre_producto_eliminado}" ha sido eliminado de tu carrito.') 
        else:
            messages.warning(request, 'El producto que intentaste eliminar ya no está en tu carrito.') 
    return redirect('ver_carrito')

def pedido_exitoso(request):
    return render(request, 'pedidos/pedido_exitoso.html')