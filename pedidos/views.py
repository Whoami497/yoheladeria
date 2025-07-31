# pedidos/views.py

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required # <-- NUEVA IMPORTACIÓN
from django.urls import reverse # <-- NUEVA IMPORTACIÓN

from .forms import ClienteRegisterForm, ClienteProfileForm
from .models import Producto, Sabor, Pedido, DetallePedido, Categoria, OpcionProducto, ClienteProfile, ProductoCanje, CadeteProfile # <-- CadeteProfile añadido
from decimal import Decimal
from django.contrib import messages

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
from webpush import send_notification # <-- NUEVA IMPORTACIÓN


def index(request):
    productos = Producto.objects.filter(disponible=True).order_by('nombre')
    categorias = Categoria.objects.filter(disponible=True).order_by('orden')
    
    contexto = {
        'productos': productos,
        'categorias': categorias,
    }
    return render(request, 'pedidos/index.html', contexto)

# ... (todas las demás vistas como detalle_producto, ver_carrito, etc. se mantienen igual)...
def detalle_producto(request, producto_id):
    producto = get_object_or_404(Producto, id=producto_id)
    sabores_disponibles = Sabor.objects.filter(disponible=True).order_by('nombre')
    
    opciones_disponibles = None
    if producto.opciones.exists():
        opciones_disponibles = OpcionProducto.objects.filter(producto_base=producto, disponible=True)

    if request.method == 'POST':
        sabores_seleccionados_ids_raw = request.POST.getlist('sabores')
        sabores_seleccionados_ids = [s_id for s_id in sabores_seleccionados_ids_raw if s_id]
        
        opcion_id = request.POST.get('opcion_id')
        opcion_seleccionada_obj = None
        if producto.opciones.exists() and opcion_id:
            opcion_seleccionada_obj = get_object_or_404(OpcionProducto, id=opcion_id, producto_base=producto)
            
        if producto.opciones.exists() and not opcion_seleccionada_obj:
            messages.error(request, 'Por favor, selecciona una opción para este producto.')
            contexto = {
                'producto': producto,
                'sabores': sabores_disponibles,
                'opciones': opciones_disponibles,
                'range_sabores': range(1, producto.sabores_maximos + 1) if producto.sabores_maximos > 0 else []
            }
            return render(request, 'pedidos/detalle_producto.html', contexto)

        if producto.sabores_maximos > 0:
            cantidad_sabores_seleccionada_en_form = int(request.POST.get('cantidad_sabores', 0))

            if len(sabores_seleccionados_ids) != cantidad_sabores_seleccionada_en_form:
                messages.error(request, f'Por favor, selecciona {cantidad_sabores_seleccionada_en_form} sabor(es) o ajusta la cantidad de sabores a seleccionar.')
                contexto = {
                    'producto': producto,
                    'sabores': sabores_disponibles,
                    'opciones': opciones_disponibles,
                    'range_sabores': range(1, producto.sabores_maximos + 1) if producto.sabores_maximos > 0 else []
                }
                return render(request, 'pedidos/detalle_producto.html', contexto)
            
            if len(sabores_seleccionados_ids) > producto.sabores_maximos:
                messages.error(request, f'No puedes seleccionar más de {producto.sabores_maximos} sabor(es) para este producto.')
                contexto = {
                    'producto': producto,
                    'sabores': sabores_disponibles,
                    'opciones': opciones_disponibles,
                    'range_sabores': range(1, producto.sabores_maximos + 1) if producto.sabores_maximos > 0 else []
                }
                return render(request, 'pedidos/detalle_producto.html', contexto)
            
        if producto.sabores_maximos == 0 and sabores_seleccionados_ids:
            sabores_seleccionados_ids = []

        if 'carrito' not in request.session:
            request.session['carrito'] = {}

        try:
            cantidad_a_agregar = int(request.POST.get('cantidad_item', 1))
            if cantidad_a_agregar < 1:
                cantidad_a_agregar = 1
        except ValueError:
            cantidad_a_agregar = 1

        sabores_nombres = []
        if sabores_seleccionados_ids:
            sabores_objetos = Sabor.objects.filter(id__in=sabores_seleccionados_ids)
            sabores_nombres = [sabor.nombre for sabor in sabores_objetos]
            sabores_nombres.sort()

        precio_final_item = producto.precio
        nombre_item_carrito = producto.nombre
        opcion_id_para_carrito = None
        opcion_nombre_para_carrito = None
        opcion_imagen_para_carrito = None

        if opcion_seleccionada_obj:
            precio_final_item += opcion_seleccionada_obj.precio_adicional
            nombre_item_carrito = f"{producto.nombre} - {opcion_seleccionada_obj.nombre_opcion}"
            opcion_id_para_carrito = opcion_seleccionada_obj.id
            opcion_nombre_para_carrito = opcion_seleccionada_obj.nombre_opcion
            opcion_imagen_para_carrito = opcion_seleccionada_obj.imagen_opcion if opcion_seleccionada_obj.imagen_opcion else producto.imagen

        item_key = f"{producto.id}_"
        if opcion_id_para_carrito:
            item_key += f"opcion-{opcion_id_para_carrito}_"
        item_key += "_".join(sorted(sabores_seleccionados_ids))

        item = {
            'producto_id': producto.id,
            'producto_nombre': nombre_item_carrito,
            'precio': str(precio_final_item),
            'sabores_ids': sabores_seleccionados_ids,
            'sabores_nombres': sabores_nombres,
            'cantidad': cantidad_a_agregar,
            'sabores_maximos': producto.sabores_maximos,
            'opcion_id': opcion_id_para_carrito,
            'opcion_nombre': opcion_nombre_para_carrito,
            'imagen_mostrada': opcion_imagen_para_carrito if opcion_imagen_para_carrito else producto.imagen,
        }
        
        if item_key in request.session['carrito']:
            request.session['carrito'][item_key]['cantidad'] += cantidad_a_agregar
            messages.info(request, f'Se han añadido {cantidad_a_agregar} unidades más de "{nombre_item_carrito}" al carrito.')
        else:
            request.session['carrito'][item_key] = item
            messages.success(request, f'"{nombre_item_carrito}" ha sido añadido al carrito ({cantidad_a_agregar} unidad{"es" if cantidad_a_agregar > 1 else ""}).')

        request.session.modified = True
        
        return redirect('detalle_producto', producto_id=producto.id)

    range_sabores = []
    if producto.sabores_maximos > 0:
        range_sabores = range(1, producto.sabores_maximos + 1)
        
    contexto = {
        'producto': producto,
        'sabores': sabores_disponibles,
        'opciones': opciones_disponibles,
        'range_sabores': range_sabores,
    }
    return render(request, 'pedidos/detalle_producto.html', contexto)


def ver_carrito(request):
    carrito = request.session.get('carrito', {})
    
    total = Decimal('0.00')
    items_carrito_procesados = []

    for key, item in carrito.items():
        try:
            item_precio = Decimal(item.get('precio', '0.00'))
            item_cantidad = item.get('cantidad', 1)
            item_subtotal = item_precio * item_cantidad
            total += item_subtotal
            
            items_carrito_procesados.append({
                'key': key,
                'producto_id': item['producto_id'],
                'producto_nombre': item['producto_nombre'],
                'precio_unidad': item_precio,
                'cantidad': item_cantidad,
                'sabores_nombres': item.get('sabores_nombres', []),
                'sabores_maximos': item.get('sabores_maximos', 0),
                'opcion_id': item.get('opcion_id'),
                'opcion_nombre': item.get('opcion_nombre'),
                'imagen_mostrada': item.get('imagen_mostrada'),
                'subtotal': item_subtotal
            })
        except Exception as e:
            print(f"Error procesando ítem en carrito: {e} - Item: {item}")
            messages.warning(request, "Hubo un problema con uno de los ítems en tu carrito y fue omitido.")
            continue

    if request.method == 'POST':
        nombre = request.POST.get('cliente_nombre')
        direccion = request.POST.get('cliente_direccion')
        telefono = request.POST.get('cliente_telefono')
        metodo_pago = request.POST.get('metodo_pago')

        pedido_kwargs = {
            'cliente_nombre': nombre,
            'cliente_direccion': direccion,
            'cliente_telefono': telefono,
            'metodo_pago': metodo_pago
        }
        if request.user.is_authenticated:
            pedido_kwargs['user'] = request.user
            if hasattr(request.user, 'clienteprofile'):
                profile = request.user.clienteprofile
                if not nombre and request.user.first_name and request.user.last_name:
                    pedido_kwargs['cliente_nombre'] = f"{request.user.first_name} {request.user.last_name}"
                if not direccion and profile.direccion:
                    pedido_kwargs['cliente_direccion'] = profile.direccion
                if not telefono and profile.telefono:
                    pedido_kwargs['cliente_telefono'] = profile.telefono

        nuevo_pedido = Pedido.objects.create(**pedido_kwargs)
        
        puntos_ganados = 0
        total_del_pedido_para_puntos = Decimal('0.00')

        detalles_para_notificacion = []

        for key, item_data in carrito.items():
            try:
                producto = Producto.objects.get(id=item_data['producto_id'])
                sabores_seleccionados_ids = item_data.get('sabores_ids', [])
                sabores_seleccionados = Sabor.objects.filter(id__in=sabores_seleccionados_ids)
                
                opcion_obj_pedido = None
                if item_data.get('opcion_id'):
                    opcion_obj_pedido = OpcionProducto.objects.get(id=item_data['opcion_id'])

                detalle = DetallePedido.objects.create(
                    pedido=nuevo_pedido,
                    producto=producto,
                    opcion_seleccionada=opcion_obj_pedido,
                    cantidad=item_data['cantidad'],
                )
                detalle.sabores.set(sabores_seleccionados)

                precio_unitario_item = Decimal(item_data['precio'])
                total_del_pedido_para_puntos += precio_unitario_item * item_data['cantidad']
                
                detalles_para_notificacion.append({
                    'producto_nombre': producto.nombre,
                    'opcion_nombre': opcion_obj_pedido.nombre_opcion if opcion_obj_pedido else None,
                    'cantidad': item_data['cantidad'],
                    'sabores_nombres': [s.nombre for s in sabores_seleccionados],
                })

            except (Producto.DoesNotExist, OpcionProducto.DoesNotExist) as e:
                messages.warning(request, f"Advertencia: Un ítem no pudo ser añadido al pedido final porque ya no existe. Error: {e}")
                continue
            except Exception as e:
                messages.error(request, f"Error al procesar el detalle del pedido para {item_data.get('producto_nombre', 'un producto')}: {e}")
                continue

        if request.user.is_authenticated and hasattr(request.user, 'clienteprofile'):
            puntos_ganados = int(total_del_pedido_para_puntos / Decimal('500')) * 100
            request.user.clienteprofile.puntos_fidelidad += puntos_ganados
            request.user.clienteprofile.save()
            messages.success(request, f"¡Has ganado {puntos_ganados} puntos de fidelidad con este pedido!")

        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'pedidos_new_orders',
                {
                    'type': 'send_order_notification',
                    'message': f'¡Nuevo pedido #{nuevo_pedido.id} recibido!',
                    'order_id': nuevo_pedido.id,
                    'order_data': {
                        'cliente_nombre': nuevo_pedido.cliente_nombre,
                        'cliente_direccion': nuevo_pedido.cliente_direccion,
                        'cliente_telefono': nuevo_pedido.cliente_telefono,
                        'metodo_pago': nuevo_pedido.metodo_pago,
                        'total_pedido': str(nuevo_pedido.total_pedido),
                        'detalles': detalles_para_notificacion,
                    }
                }
            )
            print(f"Notificación de pedido #{nuevo_pedido.id} enviada a Channels.")
        except Exception as e:
            print(f"ERROR al enviar notificación de pedido a Channels: {e}")
            messages.error(request, f"ERROR INTERNO: No se pudo enviar la alerta en tiempo real. Contacta a soporte. Error: {e}")

        del request.session['carrito']
        request.session.modified = True
        
        messages.success(request, f'¡Tu pedido #{nuevo_pedido.id} ha sido realizado con éxito! Pronto nos contactaremos.')

        return redirect('pedido_exitoso')

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

def productos_por_categoria(request, categoria_id):
    categoria = get_object_or_404(Categoria, pk=categoria_id)
    productos = Producto.objects.filter(categoria=categoria, disponible=True).order_by('nombre')
    
    contexto = {
        'categoria_seleccionada': categoria,
        'productos': productos,
        'categorias': Categoria.objects.filter(disponible=True).order_by('orden'),
    }
    return render(request, 'pedidos/productos_por_categoria.html', contexto)

def pedido_exitoso(request):
    return render(request, 'pedidos/pedido_exitoso.html')

# --- Vistas para Autenticación y Perfil de Cliente ---

def register_cliente(request):
    if request.user.is_authenticated:
        messages.info(request, "Ya has iniciado sesión.")
        return redirect('index')

    if request.method == 'POST':
        form = ClienteRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"¡Bienvenido, {user.username}! Tu cuenta ha sido creada y has iniciado sesión.")
            return redirect('index')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Error en {field}: {error}")
            for error in form.non_field_errors():
                messages.error(request, error)
    else:
        form = ClienteRegisterForm()

    contexto = {'form': form}
    return render(request, 'pedidos/register.html', contexto)


@login_required
def perfil_cliente(request):
    user = request.user
    cliente_profile, created = ClienteProfile.objects.get_or_create(user=user)

    if request.method == 'POST':
        form = ClienteProfileForm(request.POST, instance=cliente_profile)
        if form.is_valid():
            user.first_name = form.cleaned_data['first_name']
            user.last_name = form.cleaned_data['last_name']
            user.email = form.cleaned_data['email']
            user.save()

            form.save()

            messages.success(request, "¡Tu perfil ha sido actualizado con éxito!")
            return redirect('perfil_cliente')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Error en {field}: {error}")
            for error in form.non_field_errors():
                messages.error(request, error)
    else:
        form = ClienteProfileForm(instance=cliente_profile, initial={
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
        })

    contexto = {'form': form, 'user': user, 'cliente_profile': cliente_profile}
    return render(request, 'pedidos/perfil.html', contexto)


@login_required
def historial_pedidos_cliente(request):
    pedidos = Pedido.objects.filter(user=request.user).order_by('-fecha_pedido')
    
    cliente_profile = None
    if hasattr(request.user, 'clienteprofile'):
        cliente_profile = request.user.clienteprofile

    contexto = {
        'pedidos': pedidos,
        'cliente_profile': cliente_profile,
    }
    return render(request, 'pedidos/historial_pedidos.html', contexto)


def logout_cliente(request):
    logout(request)
    messages.info(request, "Has cerrado sesión exitosamente.")
    return redirect('index')

def panel_alertas(request):
    return render(request, 'pedidos/panel_alertas.html')

@login_required
def canjear_puntos(request):
    cliente_profile = request.user.clienteprofile
    productos_canje = ProductoCanje.objects.filter(disponible=True).order_by('puntos_requeridos')

    if request.method == 'POST':
        producto_canje_id = request.POST.get('producto_canje_id')
        try:
            producto_canje = ProductoCanje.objects.get(id=producto_canje_id, disponible=True)
        except ObjectDoesNotExist:
            messages.error(request, "El producto de canje seleccionado no es válido.")
            return redirect('canjear_puntos')

        if cliente_profile.puntos_fidelidad >= producto_canje.puntos_requeridos:
            with transaction.atomic():
                cliente_profile.puntos_fidelidad -= producto_canje.puntos_requeridos
                cliente_profile.save()
                
                messages.success(request, f"¡Has canjeado '{producto_canje.nombre}' por {producto_canje.puntos_requeridos} puntos! Tus puntos actuales son {cliente_profile.puntos_fidelidad}.")
                
                try:
                    producto_ficticio_canje_obj = Producto.objects.get(nombre="Canje de Puntos - No Comprar")
                    
                    nuevo_pedido_canje = Pedido.objects.create(
                        user=request.user,
                        cliente_nombre=request.user.get_full_name() or request.user.username,
                        cliente_direccion=f"Canje de Puntos: {producto_canje.nombre}",
                        cliente_telefono=cliente_profile.telefono or "",
                        estado='RECIBIDO',
                    )

                    DetallePedido.objects.create(
                        pedido=nuevo_pedido_canje,
                        producto=producto_ficticio_canje_obj,
                        opcion_seleccionada=None,
                        cantidad=1,
                    )
                    messages.info(request, f"Se ha generado un pedido de canje (ID #{nuevo_pedido_canje.id}). Puedes consultarlo en tu historial.")

                except Producto.DoesNotExist:
                    messages.error(request, "Error: El producto ficticio 'Canje de Puntos - No Comprar' no se encontró. No se pudo registrar el detalle del canje. Asegúrate de crearlo en el admin como un Producto.")
                except Exception as e:
                    messages.error(request, f"Hubo un problema al registrar el canje como pedido: {e}")

        else:
            messages.error(request, f"No tienes suficientes puntos para canjear '{producto_canje.nombre}'. Necesitas {producto_canje.puntos_requeridos} puntos y solo tienes {cliente_profile.puntos_fidelidad}.")
        
        return redirect('canjear_puntos')

    contexto = {
        'cliente_profile': cliente_profile,
        'productos_canje': productos_canje,
    }
    return render(request, 'pedidos/canjear_puntos.html', contexto)

# --- Vistas para Tienda y Cadetes ---

@staff_member_required
def confirmar_pedido(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    
    # Prevenir que se confirme un pedido que no está en estado 'RECIBIDO'
    if pedido.estado != 'RECIBIDO':
        messages.warning(request, f"El Pedido #{pedido.id} ya fue procesado o cancelado.")
        return redirect('panel_alertas')

    # 1. Cambiar el estado del pedido
    pedido.estado = 'EN_PREPARACION'
    pedido.save()

    # 2. Preparar el contenido (payload) de la notificación
    payload = {
        "head": "¡Nuevo Pedido Disponible!",
        "body": f"Pedido #{pedido.id} para entregar en: {pedido.cliente_direccion}",
        "icon": request.build_absolute_uri(settings.STATIC_URL + 'images/logo_yo_heladeria_blanco.png'),
        "url": request.build_absolute_uri(reverse('panel_cadete'))
    }

    # 3. Buscar a todos los cadetes disponibles y suscritos
    cadetes_suscritos = CadeteProfile.objects.filter(disponible=True).exclude(subscription_info__isnull=True)
    
    # 4. Enviar la notificación a cada uno
    for perfil in cadetes_suscritos:
        try:
            send_notification(perfil.subscription_info, json.dumps(payload), ttl=1000)
            print(f"Notificación enviada a {perfil.user.username}")
        except Exception as e:
            # Es importante registrar errores pero no detener el proceso por un cadete que falle
            print(f"ERROR enviando notificación a {perfil.user.username}: {e}")

    # 5. Redirigir de vuelta al panel con un mensaje de éxito
    messages.success(request, f"Pedido #{pedido.id} confirmado. Notificando a {cadetes_suscritos.count()} cadete(s) disponible(s).")
    return redirect('panel_alertas')


def login_cadete(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'cadeteprofile'):
            return redirect('panel_cadete')
        else:
            return redirect('index')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                if hasattr(user, 'cadeteprofile'):
                    login(request, user)
                    messages.success(request, f'¡Bienvenido de vuelta, {user.first_name or user.username}!')
                    return redirect('panel_cadete')
                else:
                    messages.error(request, 'Acceso denegado. Este usuario no es un cadete.')
            else:
                messages.error(request, 'Usuario o contraseña incorrectos.')
        else:
            messages.error(request, 'Usuario o contraseña incorrectos.')
    else:
        form = AuthenticationForm()
    
    return render(request, 'pedidos/login_cadete.html', {'form': form})

@login_required
def panel_cadete(request):
    vapid_public_key = settings.WEBPUSH_SETTINGS.get('VAPID_PUBLIC_KEY')
    contexto = {
        'vapid_public_key': vapid_public_key
    }
    return render(request, 'pedidos/panel_cadete.html', contexto)


@login_required
def logout_cadete(request):
    logout(request)
    messages.info(request, "Has cerrado sesión como cadete.")
    return redirect('login_cadete')

@login_required
@require_POST
def save_subscription(request):
    if not hasattr(request.user, 'cadeteprofile'):
        return JsonResponse({'status': 'error', 'message': 'User is not a cadete'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    try:
        profile = request.user.cadeteprofile
        profile.subscription_info = data
        profile.save()
        return JsonResponse({'status': 'ok', 'message': 'Subscription saved'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)