from django.shortcuts import render, redirect, get_object_or_404
from .models import Producto, Sabor, Pedido, DetallePedido
from decimal import Decimal

def index(request):
    productos = Producto.objects.filter(disponible=True)
    contexto = {'productos': productos}
    return render(request, 'pedidos/index.html', contexto)

def detalle_producto(request, producto_id):
    producto = get_object_or_404(Producto, id=producto_id)
    sabores = Sabor.objects.filter(disponible=True)

    if request.method == 'POST':
        sabores_seleccionados_ids = request.POST.getlist('sabores')

        if 'carrito' not in request.session:
            request.session['carrito'] = {}

        item_key = f"{producto_id}-{','.join(sabores_seleccionados_ids)}"

        item = {
            'producto_id': producto.id,
            'producto_nombre': producto.nombre,
            'precio': str(producto.precio),
            'sabores_ids': sabores_seleccionados_ids
        }

        request.session['carrito'][item_key] = item
        request.session.modified = True

        return redirect('index')

    contexto = {
        'producto': producto,
        'sabores': sabores
    }
    return render(request, 'pedidos/detalle_producto.html', contexto)

def ver_carrito(request):
    carrito = request.session.get('carrito', {})
    total = sum(Decimal(item['precio']) for item in carrito.values())

    if request.method == 'POST':
        nombre = request.POST.get('cliente_nombre')
        direccion = request.POST.get('cliente_direccion')
        telefono = request.POST.get('cliente_telefono')

        nuevo_pedido = Pedido.objects.create(
            cliente_nombre=nombre,
            cliente_direccion=direccion,
            cliente_telefono=telefono
        )

        for key, item in carrito.items():
            producto = Producto.objects.get(id=item['producto_id'])
            sabores_seleccionados = Sabor.objects.filter(id__in=item['sabores_ids'])

            detalle = DetallePedido.objects.create(
                pedido=nuevo_pedido,
                producto=producto
            )
            detalle.sabores.set(sabores_seleccionados)

        del request.session['carrito']
        request.session.modified = True

        return redirect('pedido_exitoso')

    contexto = {
        'carrito': carrito.values(),
        'total': total,
    }
    return render(request, 'pedidos/carrito.html', contexto)

def pedido_exitoso(request):
    return render(request, 'pedidos/pedido_exitoso.html')