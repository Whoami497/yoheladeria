# pedidos/views.py
from django.db.models import Exists, OuterRef, Q
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.views.decorators.http import require_POST, require_GET
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal, ROUND_HALF_UP
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
import mercadopago
import requests
import re
from urllib.parse import quote_plus
from django.template import TemplateDoesNotExist  # <-- NUEVO

from .forms import ClienteRegisterForm, ClienteProfileForm
from .models import (
    Producto, Sabor, Pedido, DetallePedido, Categoria,
    OpcionProducto, ClienteProfile, ProductoCanje, CadeteProfile
)
from django.contrib import messages

# ==> Geocoding util (usa GOOGLE_*_KEY en settings si existe utils/geocoding.py)
try:
    from .utils.geocoding import reverse_geocode as gc_reverse  # lat, lng -> dict
except Exception:
    gc_reverse = None


# =========================
# === util
# =========================
def _abs_https(request, url_or_path: str) -> str:
    """
    Devuelve una URL absoluta y forzada a https (Render puede dar http en request).
    """
    if url_or_path.startswith('http://') or url_or_path.startswith('https://'):
        url = url_or_path
    else:
        url = request.build_absolute_uri(url_or_path)
    if url.startswith('http://'):
        url = 'https://' + url[len('http://'):]
    return url


def cadete_esta_ocupado(cadete_profile) -> bool:
    """True si el cadete tiene un pedido ASIGNADO o EN_CAMINO."""
    if not cadete_profile:
        return False
    return Pedido.objects.filter(
        cadete_asignado=cadete_profile,
        estado__in=['ASIGNADO', 'EN_CAMINO']
    ).exists()


def _compute_total(pedido) -> Decimal:
    """
    Suma segura del total con el envío PERSISTIDO (pedido.costo_envio).
    Evita recalcular envío en propiedades o señales.
    """
    total = Decimal('0.00')
    for d in pedido.detalles.all():
        precio = d.producto.precio
        if d.opcion_seleccionada:
            precio += d.opcion_seleccionada.precio_adicional
        total += (precio * d.cantidad)
    if pedido.costo_envio:
        total += pedido.costo_envio
    return total.quantize(Decimal('0.01'))


def _marcar_estado(pedido, nuevo_estado: str, actor=None, fuente: str = '', meta: dict | None = None):
    """
    Cambia el estado del pedido, intenta completar timestamps de hitos si los campos existen
    (fecha_en_preparacion, fecha_asignado, etc.) y registra un log en PedidoEstadoLog si existe el modelo.
    TODO-SAFE: si los campos/modelo no existen aún, no rompe (está envuelto en try/except).
    """
    anterior = getattr(pedido, 'estado', None)
    pedido.estado = nuevo_estado
    ahora = timezone.now()

    # Intentar setear timestamp del hito si el campo existe
    try:
        mapping = {
            'RECIBIDO': 'fecha_pago_aprobado',
            'EN_PREPARACION': 'fecha_en_preparacion',
            'ASIGNADO': 'fecha_asignado',
            'EN_CAMINO': 'fecha_en_camino',
            'ENTREGADO': 'fecha_entregado',
            'CANCELADO': 'fecha_cancelado',
        }
        campo = mapping.get(nuevo_estado)
        update_fields = ['estado']
        if campo and hasattr(pedido, campo) and not getattr(pedido, campo):
            setattr(pedido, campo, ahora)
            update_fields.append(campo)
        pedido.save(update_fields=update_fields)
    except Exception:
        # Si falla por campos inexistentes, guardamos al menos el estado
        try:
            pedido.save(update_fields=['estado'])
        except Exception:
            pedido.save()

    # Intentar escribir un log si existe el modelo PedidoEstadoLog
    try:
        from .models import PedidoEstadoLog  # puede no existir aún
        actor_tipo = 'sistema'
        if actor is not None and getattr(actor, 'is_authenticated', False):
            if getattr(actor, 'is_staff', False):
                actor_tipo = 'staff'
            elif hasattr(actor, 'cadeteprofile'):
                actor_tipo = 'cadete'
            else:
                actor_tipo = 'cliente'
        PedidoEstadoLog.objects.create(
            pedido=pedido,
            de=anterior,
            a=nuevo_estado,
            actor=actor if getattr(actor, 'is_authenticated', False) else None,
            actor_tipo=actor_tipo,
            fuente=fuente or '',
            meta=meta or {}
        )
    except Exception as e:
        # Modelo no existe o hubo otro error: no rompemos el flujo.
        pass

    return pedido


def _serialize_pedido_for_panel(pedido, include_details=True):
    """
    Serializa un Pedido para mandarlo al panel por WS/JSON.
    Incluye costo_envio como float (para que el front lo formatee).
    """
    data = {
        'id': pedido.id,
        'estado': pedido.estado,
        'cliente_nombre': pedido.cliente_nombre,
        'cliente_direccion': pedido.cliente_direccion,
        'direccion_legible': getattr(pedido, 'direccion_legible', None) or _direccion_legible_from_text(pedido.cliente_direccion),
        'map_url': _map_url_from_text(pedido.cliente_direccion),
        'cliente_telefono': pedido.cliente_telefono,
        'metodo_pago': pedido.metodo_pago,
        # ⚠️ Usamos el total calculado con envío persistido
        'total_pedido': str(_compute_total(pedido)),
        'costo_envio': float(pedido.costo_envio or 0),
        'cadete': (
            pedido.cadete_asignado.user.get_full_name() or pedido.cadete_asignado.user.username
        ) if getattr(pedido, 'cadete_asignado', None) else None,
    }
    if include_details:
        data['detalles'] = [{
            'producto_nombre': d.producto.nombre,
            'opcion_nombre': d.opcion_seleccionada.nombre_opcion if d.opcion_seleccionada else None,
            'cantidad': d.cantidad,
            'sabores_nombres': [s.nombre for s in d.sabores.all()],
        } for d in pedido.detalles.all()]
    # === NUEVO: métricas y logs para panel/cadete/cliente
    data.update({
        'metricas': _serialize_metricas(pedido),
        'logs': _serialize_logs(pedido, limit=8),
    })
    return data


# === NUEVO: serializadores de métricas y logs
def _serialize_logs(pedido, limit=8):
    out = []
    try:
        qs = pedido.logs_estado.select_related('actor').order_by('-created_at')[:limit]
        for l in qs:
            out.append({
                'de': l.de or None,
                'a': l.a,
                'actor': (l.actor.get_full_name() or l.actor.username) if l.actor else None,
                'actor_tipo': l.actor_tipo,
                'fuente': l.fuente or '',
                'created_at': timezone.localtime(l.created_at).strftime('%Y-%m-%d %H:%M'),
            })
    except Exception:
        pass
    return out


def _serialize_metricas(pedido):
    try:
        return pedido.tiempos_en_minutos()
    except Exception:
        return {}


def _notify_panel_update(pedido, message='actualizacion_pedido'):
    try:
        channel_layer = get_channel_layer()
        if message == 'nuevo_pedido':
            order_data = _serialize_pedido_for_panel(pedido, include_details=True)
            order_data['metricas'] = _serialize_metricas(pedido)
            order_data['logs'] = _serialize_logs(pedido)
        else:
            order_data = {
                'estado': pedido.estado,
                'direccion_legible': _direccion_legible_from_text(pedido.cliente_direccion),
                'map_url': _map_url_from_text(pedido.cliente_direccion),
                'total_pedido': str(_compute_total(pedido)),
                'costo_envio': float(pedido.costo_envio or 0),
                'metricas': _serialize_metricas(pedido),
                'logs': _serialize_logs(pedido),
            }

        async_to_sync(channel_layer.group_send)(
            'pedidos_new_orders',
            {
                'type': 'send_order_notification',
                'message': message,
                'order_id': pedido.id,
                'order_data': order_data,
            }
        )
    except Exception as e:
        print(f"WS panel update error: {e}")


def _notify_cadetes_new_order(request, pedido):
    """
    Envia WebPush SOLO a cadetes sin pedido activo (ASIGNADO/EN_CAMINO)
    y, si existe el campo, con disponible=True.
    """
    try:
        from pywebpush import webpush
    except Exception as e:
        print(f"WEBPUSH no disponible: {e}")
        return

    vapid = getattr(settings, 'WEBPUSH_SETTINGS', {}) or {}
    priv = vapid.get('VAPID_PRIVATE_KEY')
    admin = vapid.get('VAPID_ADMIN_EMAIL') or 'admin@example.com'
    if not priv:
        print("WEBPUSH: Falta VAPID_PRIVATE_KEY en settings.")
        return

    activos_qs = Pedido.objects.filter(
        cadete_asignado_id=OuterRef('pk'),
        estado__in=['ASIGNADO', 'EN_CAMINO']
    )

    cadetes = (CadeteProfile.objects
            .exclude(subscription_info__isnull=True)
            .annotate(tiene_activo=Exists(activos_qs))
            .filter(tiene_activo=False))

    cadetes = [c for c in cadetes if not hasattr(c, 'disponible') or c.disponible]

    payload = {
        "title": "Nuevo pedido disponible",
        "body": f"Pedido #{pedido.id} — {_direccion_legible_from_text(pedido.cliente_direccion)}",
        "url": _abs_https(request, reverse('panel_cadete')),
    }

    for cp in cadetes:
        sub = cp.subscription_info if isinstance(cp.subscription_info, dict) else None
        if not sub:
            continue
        try:
            webpush(
                subscription_info=sub,
                data=json.dumps(payload),
                vapid_private_key=priv,
                vapid_claims={"sub": f"mailto:{admin}"}
            )
        except Exception as e:
            print(f"WEBPUSH cadete {cp.user_id} error: {e}")


# =========================
# === ENVÍO (Google Maps)
# =========================
def _origin_from_settings() -> str:
    lat = str(getattr(settings, 'ORIGEN_LAT', '')).strip()
    lng = str(getattr(settings, 'ORIGEN_LNG', '')).strip()
    if lat and lng:
        try:
            lat_f = float(lat)
            lng_f = float(lng)
            return f"{lat_f},{lng_f}"
        except Exception:
            pass
    return (getattr(settings, 'SUCURSAL_DIRECCION', '') or '').strip()


def _extract_coords(text: str):
    if not text:
        return None
    m = re.search(r'(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)', text)
    if m:
        return m.group(1), m.group(2)
    return None


def _direccion_legible_from_text(text: str) -> str:
    if not text:
        return ""
    parts = text.split(' — GPS:')
    return parts[0].strip()


def _map_url_from_text(text: str) -> str:
    coords = _extract_coords(text)
    if coords:
        lat, lng = coords
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    q = quote_plus(_direccion_legible_from_text(text) or text)
    return f"https://www.google.com/maps/search/?api=1&query={q}"


# ======= REVERSE GEOCODING (nuevo: fallback local + wrapper) =======
def _reverse_geocode_local(lat: float, lng: float) -> dict:
    """
    Llama directamente a Geocoding API y devuelve:
    {'formatted_address', 'map_url', 'plus_code', 'locality', 'postal_code'}
    """
    api_key = (
        getattr(settings, 'GOOGLE_MAPS_API_KEY', '') or
        getattr(settings, 'GOOGLE_GEOCODING_KEY', '') or
        getattr(settings, 'GOOGLE_API_KEY', '')
    )
    if not api_key:
        if settings.DEBUG:
            print("GEOCODING DEBUG: falta API key (GOOGLE_MAPS_API_KEY/GOOGLE_GEOCODING_KEY/GOOGLE_API_KEY)")
        return {}

    params = {
        'latlng': f'{float(lat):.6f},{float(lng):.6f}',
        'key': api_key,
        'language': getattr(settings, 'MAPS_LANGUAGE', 'es'),
        'region': getattr(settings, 'MAPS_REGION', 'AR'),
    }
    try:
        r = requests.get("https://maps.googleapis.com/maps/api/geocode/json", params=params, timeout=8)
        if settings.DEBUG:
            print(f"GEOCODING DEBUG: HTTP {r.status_code} → {r.url}")
        r.raise_for_status()
        data = r.json()
        status = data.get('status')
        results = data.get('results') or []
        if settings.DEBUG:
            print(f"GEOCODING DEBUG: status={status} results={len(results)}")

        out = {
            'map_url': f"https://www.google.com/maps/search/?api=1&query={float(lat):.6f},{float(lng):.6f}"
        }

        if status == 'OK' and results:
            res0 = results[0]
            out['formatted_address'] = res0.get('formatted_address')
            comps = res0.get('address_components') or []
            for c in comps:
                types = c.get('types') or []
                if 'locality' in types and 'sublocality' not in types:
                    out['locality'] = c.get('long_name')
                if 'postal_code' in types:
                    out['postal_code'] = c.get('long_name')

        pc = data.get('plus_code') or {}
        out['plus_code'] = pc.get('compound_code') or pc.get('global_code')

        return {k: v for k, v in out.items() if v}
    except Exception as e:
        if settings.DEBUG:
            print(f"GEOCODING ERROR: {e}")
        return {}


def _reverse_geocode_any(lat: float, lng: float) -> dict:
    """
    Usa utils.geocoding.reverse_geocode si existe; si no, usa el fallback local.
    """
    if callable(gc_reverse):
        try:
            data = gc_reverse(lat, lng)
            if data:
                return data
        except Exception as e:
            if settings.DEBUG:
                print(f"GEOCODING DEBUG: gc_reverse falló: {e}")
    return _reverse_geocode_local(lat, lng)


def _calcular_costo_envio(direccion_cliente: str):
    """
    Devuelve (costo_envio_decimal, distancia_km_float) usando Distance Matrix.
    """
    dest = (direccion_cliente or '').strip()
    if not dest:
        return (Decimal('0.00'), 0.0)  # retiro en local

    api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '') or ''
    language = getattr(settings, 'MAPS_LANGUAGE', 'es')
    region   = getattr(settings, 'MAPS_REGION', 'AR')
    origen   = _origin_from_settings()

    base     = Decimal(str(getattr(settings, 'ENVIO_BASE', '300')))
    por_km   = Decimal(str(getattr(settings, 'ENVIO_POR_KM', '50')))
    km_min   = Decimal(str(getattr(settings, 'ENVIO_KM_MIN', '0')))
    km_off   = Decimal(str(getattr(settings, 'ENVIO_KM_OFFSET', '0')))

    _min = str(getattr(settings, 'ENVIO_MIN', '0')).strip()
    _max = str(getattr(settings, 'ENVIO_MAX', '')).strip()
    costo_min = Decimal(_min) if _min and _min != '0' else None
    costo_max = Decimal(_max) if _max else None

    _mul = str(getattr(settings, 'ENVIO_REDONDEO', '0')).strip()
    try:
        multiple = Decimal(_mul)
    except Exception:
        multiple = Decimal('0')

    if not api_key or not origen:
        return (base.quantize(Decimal('0.01')), 0.0)

    destino = dest  # puede ser 'lat,lng' o dirección

    try:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            'origins': origen,
            'destinations': destino,
            'key': api_key,
            'mode': 'driving',
            'units': 'metric',
            'language': language,
            'region': region,
        }
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        el = ((data.get('rows') or [{}])[0].get('elements') or [{}])[0]
        if el.get('status') != 'OK':
            return (base.quantize(Decimal('0.01')), 0.0)

        metros = int(el['distance']['value'])
        km_reales = Decimal(metros) / Decimal('1000')

        km_efectivos = (km_reales if km_reales > km_min else km_min) + km_off

        costo = base + (por_km * km_efectivos)

        if costo_min is not None and costo < costo_min:
            costo = costo_min
        if costo_max is not None and costo > costo_max:
            costo = costo_max

        if multiple > 0:
            costo = (costo / multiple).to_integral_value(rounding=ROUND_HALF_UP) * multiple

        return (costo.quantize(Decimal('0.01')), float(km_reales))
    except Exception as e:
        print(f"MAPS ERROR: {e}")
        return (base.quantize(Decimal('0.01')), 0.0)


@require_GET
def api_costo_envio(request):
    """
    Endpoint para estimar costo/distancia desde el carrito.
    GET ?direccion=...  (dirección o 'lat,lng')
    Ahora también retorna dirección legible/map_url/plus_code si se pasó lat,lng y hay clave de Geocoding.
    """
    direccion = (request.GET.get('direccion') or '').strip()
    if not direccion:
        return JsonResponse({'ok': True, 'costo_envio': 0.0, 'distancia_km': 0.0, 'mode': 'pickup'})

    costo, km = _calcular_costo_envio(direccion)

    # Info de geocoding opcional (no rompe si falla)
    addr = {}
    coords = _extract_coords(direccion)
    if coords:
        try:
            lat, lng = float(coords[0]), float(coords[1])
            addr = _reverse_geocode_any(lat, lng) or {}
        except Exception as e:
            print(f"GEOCODING reverse error: {e}")
            addr = {}

    payload = {
        'ok': True,
        'costo_envio': float(costo),
        'distancia_km': float(km),
        'mode': 'maps',
        'direccion_legible': addr.get('formatted_address') or _direccion_legible_from_text(direccion),
        'map_url': addr.get('map_url') or _map_url_from_text(direccion),
        'plus_code': addr.get('plus_code'),
        'locality': addr.get('locality'),
        'postal_code': addr.get('postal_code'),
    }
    if settings.DEBUG:
        payload['debug'] = {
            'ENVIO_BASE': getattr(settings, 'ENVIO_BASE', '300'),
            'ENVIO_POR_KM': getattr(settings, 'ENVIO_POR_KM', '50'),
            'ENVIO_MIN': getattr(settings, 'ENVIO_MIN', '0'),
            'ENVIO_MAX': getattr(settings, 'ENVIO_MAX', ''),
            'ENVIO_KM_MIN': getattr(settings, 'ENVIO_KM_MIN', '0'),
            'ENVIO_KM_OFFSET': getattr(settings, 'ENVIO_KM_OFFSET', '0'),
            'ENVIO_REDONDEO': getattr(settings, 'ENVIO_REDONDEO', '0'),
            'ORIGEN_LAT': getattr(settings, 'ORIGEN_LAT', ''),
            'ORIGEN_LNG': getattr(settings, 'ORIGEN_LNG', ''),
            'SUCURSAL_DIRECCION': getattr(settings, 'SUCURSAL_DIRECCION', ''),
        }
    return JsonResponse(payload)


# =========================
# === CATÁLOGO / HOME
# =========================
def index(request):
    q = (request.GET.get('q') or '').strip()
    cat = request.GET.get('cat')  # id de categoría
    sort = request.GET.get('sort') or 'recientes'  # precio_asc | precio_desc | recientes | nombre

    productos = Producto.objects.filter(disponible=True)

    if cat:
        productos = productos.filter(categoria_id=cat)
    if q:
        productos = productos.filter(
            Q(nombre__icontains=q) |
            Q(descripcion__icontains=q)
        )

    if sort == 'precio_asc':
        productos = productos.order_by('precio', 'nombre')
    elif sort == 'precio_desc':
        productos = productos.order_by('-precio', 'nombre')
    elif sort == 'nombre':
        productos = productos.order_by('nombre')
    else:  # recientes
        productos = productos.order_by('-id')

    categorias = Categoria.objects.filter(disponible=True).order_by('orden')

    contexto = {
            'productos': productos,
            'categorias': categorias,
            'q': q,
            'cat': int(cat) if cat else None,
            'sort': sort,
        }
    return render(request, 'pedidos/index.html', contexto)


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


# =========================
# === MERCADO PAGO
# =========================
def crear_preferencia_mp(request, pedido):
    """
    Crea la preferencia de Mercado Pago y devuelve el link de checkout.
    Fuerza HTTPS en back_urls/notification_url para evitar el error:
    'auto_return invalid. back_url.success must be defined'
    """
    if not getattr(settings, "MERCADO_PAGO_ACCESS_TOKEN", None):
        raise RuntimeError("MERCADO_PAGO_ACCESS_TOKEN no está configurado en el servidor")

    sdk = mercadopago.SDK(settings.MERCADO_PAGO_ACCESS_TOKEN)

    items = []
    for det in pedido.detalles.all():
        precio_unitario = det.producto.precio
        if det.opcion_seleccionada:
            precio_unitario += det.opcion_seleccionada.precio_adicional
        items.append({
            "title": f"{det.producto.nombre}" + (f" - {det.opcion_seleccionada.nombre_opcion}" if det.opcion_seleccionada else ""),
            "quantity": int(det.cantidad),
            "unit_price": float(precio_unitario),
            "currency_id": "ARS",
        })

    success_url = _abs_https(request, reverse("mp_success"))
    failure_url = _abs_https(request, reverse("index"))
    pending_url = _abs_https(request, reverse("index"))
    notification_url = _abs_https(request, reverse("mp_webhook"))

    payload = {
        "items": items,
        "external_reference": str(pedido.id),
        "back_urls": {
            "success": success_url,
            "failure": failure_url,
            "pending": pending_url,
        },
        "auto_return": "approved",
        "notification_url": notification_url,
    }

    print(f"MP DEBUG URLs -> success={success_url} failure={failure_url} pending={pending_url} notify={notification_url}")

    try:
        pref = sdk.preference().create(payload)
    except Exception as e:
        print(f"MP DEBUG: excepción creando preferencia: {e}")
        raise

    status = pref.get("status")
    resp = pref.get("response", {}) or {}
    print(f"MP DEBUG: create.status={status} resp_keys={list(resp.keys())}")

    if status not in (200, 201):
        msg = resp.get("message") or resp.get("error") or "Error desconocido de MP"
        print(f"MP DEBUG: preferencia fallida -> {msg} resp={resp}")
        raise RuntimeError(f"Mercado Pago rechazó la preferencia: {msg}")

    init_point = resp.get("init_point") or resp.get("sandbox_init_point")
    if not init_point:
        print(f"MP DEBUG: preferencia sin init_point. resp={resp}")
        raise RuntimeError("La preferencia no trajo init_point")

    return init_point


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
                'subtotal': item_subtotal,
            })
        except Exception as e:
            print(f"Error procesando ítem en carrito: {e} - Item: {item}")
            messages.warning(request, "Hubo un problema con uno de los ítems en tu carrito y fue omitido.")
            continue

    if request.method == 'POST':
        nombre = request.POST.get('cliente_nombre')
        direccion_input = (request.POST.get('cliente_direccion') or '').strip()  # puede venir vacío
        telefono = request.POST.get('cliente_telefono')
        metodo_pago = request.POST.get('metodo_pago')
        nota_pedido = (request.POST.get('nota_pedido') or '').strip()

        # Nuevo: modo de envío (opcional). Si no viene, inferimos por datos.
        modo_envio = (request.POST.get('modo_envio') or '').lower()  # 'pickup' | 'delivery' (opcional)
        geo_latlng = (request.POST.get('geo_latlng') or '').strip()

        # "pickup" si lo indica el form o si NO hay ni dirección ni GPS
        es_pickup = (modo_envio == 'pickup') or (not direccion_input and not geo_latlng)

        if es_pickup:
            direccion_para_maps = ''
            direccion_legible = "Retiro en local"
        else:
            direccion_para_maps = geo_latlng if geo_latlng else direccion_input
            direccion_legible = None
            if geo_latlng:
                try:
                    lat_str, lng_str = geo_latlng.split(",", 1)
                    g = _reverse_geocode_any(float(lat_str), float(lng_str)) or {}
                    direccion_legible = g.get("formatted_address")
                except Exception:
                    direccion_legible = None

        base_dir = direccion_legible or direccion_input
        if not base_dir and geo_latlng:
            base_dir = f"Cerca de {geo_latlng}"
        if not base_dir and es_pickup:
            base_dir = "Retiro en local"

        direccion_a_guardar = base_dir or ""  # nunca None
        if geo_latlng:
            direccion_a_guardar = f"{direccion_a_guardar} — GPS: {geo_latlng}"
        if nota_pedido:
            direccion_a_guardar = f"{direccion_a_guardar} — Nota: {nota_pedido}"

        costo_envio_decimal = Decimal('0.00')
        distancia_km = 0.0
        if direccion_para_maps:
            costo_envio_decimal, distancia_km = _calcular_costo_envio(direccion_para_maps)

        pedido_kwargs = {
            'cliente_nombre': nombre,
            'cliente_direccion': direccion_a_guardar,
            'cliente_telefono': telefono,
            'metodo_pago': metodo_pago,
            'costo_envio': costo_envio_decimal,
        }

        if request.user.is_authenticated:
            pedido_kwargs['user'] = request.user
            if hasattr(request.user, 'clienteprofile'):
                profile = request.user.clienteprofile
                if not nombre and request.user.first_name and request.user.last_name:
                    pedido_kwargs['cliente_nombre'] = f"{request.user.first_name} {request.user.last_name}"
                if not telefono and profile.telefono:
                    pedido_kwargs['cliente_telefono'] = profile.telefono

                if (not es_pickup) and (not direccion_para_maps) and profile.direccion:
                    pedido_kwargs['cliente_direccion'] = profile.direccion
                    costo_envio_decimal, distancia_km = _calcular_costo_envio(profile.direccion)
                    pedido_kwargs['costo_envio'] = costo_envio_decimal

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

        if metodo_pago == 'MERCADOPAGO':
            try:
                nuevo_pedido.metodo_pago = 'MERCADOPAGO'
                nuevo_pedido.save()
                request.session['mp_last_order_id'] = nuevo_pedido.id
                request.session.modified = True
                init_point = crear_preferencia_mp(request, nuevo_pedido)
                if 'carrito' in request.session:
                    del request.session['carrito']
                    request.session.modified = True
                messages.info(request, f"Redirigiendo a Mercado Pago para completar el pago del pedido #{nuevo_pedido.id}.")
                return redirect(init_point)
            except Exception as e:
                messages.error(request, f"No pudimos iniciar el pago con Mercado Pago. Probá de nuevo o elegí otro método. Detalle: {e}")
                return redirect('ver_carrito')

        if request.user.is_authenticated and hasattr(request.user, 'clienteprofile'):
            puntos_ganados = int(total_del_pedido_para_puntos / Decimal('500')) * 100
            request.user.clienteprofile.puntos_fidelidad += puntos_ganados
            request.user.clienteprofile.save()
            messages.success(request, f"¡Has ganado {puntos_ganados} puntos de fidelidad con este pedido!")

        # Notificación a panel
        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'pedidos_new_orders',
                {
                    'type': 'send_order_notification',
                    'message': 'nuevo_pedido',
                    'order_id': nuevo_pedido.id,
                    'order_data': {
                        'cliente_nombre': nuevo_pedido.cliente_nombre,
                        'cliente_direccion': nuevo_pedido.cliente_direccion,
                        'direccion_legible': _direccion_legible_from_text(nuevo_pedido.cliente_direccion),
                        'map_url': _map_url_from_text(nuevo_pedido.cliente_direccion),
                        'cliente_telefono': nuevo_pedido.cliente_telefono,
                        'metodo_pago': nuevo_pedido.metodo_pago,
                        'total_pedido': str(nuevo_pedido.total_pedido),
                        'costo_envio': float(nuevo_pedido.costo_envio or 0),
                        'distancia_km': float(distancia_km or 0),
                        'nota_pedido': (nota_pedido or None),
                        'detalles': detalles_para_notificacion,
                        'metricas': _serialize_metricas(nuevo_pedido),
                        'logs': _serialize_logs(nuevo_pedido),
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

    contexto = {'carrito_items': items_carrito_procesados, 'total': total}
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


@require_POST
def carrito_set_nota(request):
    """
    (Aún disponible por compatibilidad, aunque ahora usamos nota general)
    Guarda/borra una 'nota' por ítem del carrito (en sesión).
    Espera: key (clave del item), nota (texto).
    """
    key = request.POST.get('key', '')
    nota = (request.POST.get('nota') or '').strip()
    cart = request.session.get('carrito', {})

    if key not in cart:
        return JsonResponse({'ok': False, 'error': 'item_inexistente'}, status=404)

    if nota:
        cart[key]['nota'] = nota
    else:
        cart[key].pop('nota', None)

    request.session['carrito'] = cart
    request.session.modified = True
    return JsonResponse({'ok': True})


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


# =========================
# === AUTENTICACIÓN Y PERFIL
# =========================
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

    contexto = {'pedidos': pedidos, 'cliente_profile': cliente_profile}
    return render(request, 'pedidos/historial_pedidos.html', contexto)


def logout_cliente(request):
    logout(request)
    messages.info(request, "Has cerrado sesión exitosamente.")
    return redirect('index')


@login_required
def pedido_en_curso(request):
    """
    Muestra el/los pedidos activos del usuario:
    - Cliente: sus pedidos que NO estén ENTREGADO/CANCELADO.
    - Cadete: pedidos ASIGNADO/EN_CAMINO donde él es el cadete.
    """
    pedidos = []
    if hasattr(request.user, 'cadeteprofile'):
        pedidos = (Pedido.objects
                .filter(cadete_asignado=request.user.cadeteprofile,
                        estado__in=['ASIGNADO', 'EN_CAMINO'])
                .order_by('-fecha_pedido'))
    else:
        pedidos = (Pedido.objects
                .filter(user=request.user)
                .exclude(estado__in=['ENTREGADO', 'CANCELADO'])
                .order_by('-fecha_pedido'))

    # NUEVO: enriquecer para template (cliente y cadete)
    for p in pedidos:
        setattr(p, 'direccion_legible', _direccion_legible_from_text(p.cliente_direccion))
        setattr(p, 'map_url', _map_url_from_text(p.cliente_direccion))
        setattr(p, 'metricas', _serialize_metricas(p))
        setattr(p, 'logs', p.logs_estado.select_related('actor').order_by('-created_at')[:8])

    return render(request, 'pedidos/pedido_en_curso.html', {'pedidos': pedidos})


# =========================
# === PANEL DE ALERTAS TIENDA (HOY/AYER/ANTERIORES)
# =========================
@staff_member_required
def panel_alertas(request):
    """
    Muestra HOY (activos), AYER (plegable) y ENTREGADOS de hoy (plegable al final).
    Anotamos cada pedido con direccion_legible y map_url para uso en template.
    """
    hoy = timezone.localdate()
    ayer = hoy - timedelta(days=1)

    pedidos_hoy = (
        Pedido.objects
        .filter(fecha_pedido__date=hoy)
        .exclude(estado__in=['ENTREGADO', 'CANCELADO'])
        .order_by('-fecha_pedido')
    )
    pedidos_ayer = (
        Pedido.objects
        .filter(fecha_pedido__date=ayer)
        .order_by('-fecha_pedido')[:120]
    )
    entregados_hoy = (
        Pedido.objects
        .filter(fecha_pedido__date=hoy, estado='ENTREGADO')
        .order_by('-fecha_pedido')[:200]
    )

    def enrich(qs):
        for p in qs:
            setattr(p, 'direccion_legible', _direccion_legible_from_text(p.cliente_direccion))
            setattr(p, 'map_url', _map_url_from_text(p.cliente_direccion))
            setattr(p, 'metricas', _serialize_metricas(p))
            setattr(p, 'logs', p.logs_estado.select_related('actor').order_by('-created_at')[:8])
        return qs

    ctx = {
        'pedidos_hoy': enrich(pedidos_hoy),
        'pedidos_ayer': enrich(pedidos_ayer),
        'entregados_hoy': enrich(entregados_hoy),
    }
    return render(request, 'pedidos/panel_alertas.html', ctx)


@staff_member_required
def panel_alertas_data(request):
    """
    JSON para rehidratar/pollear el panel.
    Soporta scope=hoy | hoy_finalizados | ayer | YYYY-MM-DD
    Devuelve tambien direccion_legible y map_url.
    """
    scope = (request.GET.get('scope') or 'hoy').lower()
    hoy = timezone.localdate()

    if scope == 'hoy':
        qs = (Pedido.objects
            .filter(fecha_pedido__date=hoy)
            .exclude(estado__in=['ENTREGADO', 'CANCELADO'])
            .order_by('-fecha_pedido'))
    elif scope == 'hoy_finalizados':
        qs = (Pedido.objects
            .filter(fecha_pedido__date=hoy, estado__in=['ENTREGADO', 'CANCELADO'])
            .order_by('-fecha_pedido'))
    elif scope == 'ayer':
        qs = (Pedido.objects
            .filter(fecha_pedido__date=hoy - timedelta(days=1))
            .order_by('-fecha_pedido'))
    else:
        try:
            y, m, d = map(int, scope.split('-'))
            fecha = timezone.datetime(y, m, d).date()
        except Exception:
            fecha = hoy
        qs = Pedido.objects.filter(fecha_pedido__date=fecha).order_by('-fecha_pedido')

    def serialize(p):
        data = {
            'id': p.id,
            'estado': p.estado,
            'cliente_nombre': p.cliente_nombre,
            'cliente_direccion': p.cliente_direccion,
            'direccion_legible': _direccion_legible_from_text(p.cliente_direccion),
            'map_url': _map_url_from_text(p.cliente_direccion),
            'cliente_telefono': p.cliente_telefono,
            'metodo_pago': p.metodo_pago,
            'total_pedido': str(_compute_total(p)),
            'costo_envio': float(p.costo_envio or 0),
            'cadete': (p.cadete_asignado.user.get_full_name() or p.cadete_asignado.user.username)
                    if getattr(p, 'cadete_asignado', None) else None,
            'detalles': [{
                'producto_nombre': d.producto.nombre,
                'opcion_nombre': d.opcion_seleccionada.nombre_opcion if d.opcion_seleccionada else None,
                'cantidad': d.cantidad,
                'sabores_nombres': [s.nombre for s in d.sabores.all()],
            } for d in p.detalles.all()],
            'metricas': _serialize_metricas(p),
            'logs': _serialize_logs(p),
        }
        return data

    return JsonResponse({'pedidos': [serialize(p) for p in qs]})


@staff_member_required
def panel_alertas_anteriores(request):
    hoy = timezone.localdate()
    limite = hoy - timedelta(days=1)
    pedidos = (Pedido.objects
            .filter(fecha_pedido__date__lt=limite)
            .order_by('-fecha_pedido')[:300])

    filas = []
    for p in pedidos:
        cad = '—'
        if getattr(p, 'cadete_asignado', None):
            cad_user = p.cadete_asignado.user
            cad = cad_user.get_full_name() or cad_user.username

        filas.append(
            f"<tr><td>#{p.id}</td><td>{p.fecha_pedido:%Y-%m-%d %H:%M}</td>"
            f"<td>{p.estado}</td><td>{_direccion_legible_from_text(p.cliente_direccion) or 'N/A'}</td>"
            f"<td>{cad}</td><td>${_compute_total(p)}</td></tr>"
        )
    html = f"""
    <div style="padding:20px;font-family:system-ui;-webkit-font-smoothing:antialiased">
    <h3>Pedidos anteriores</h3>
    <p><a href="/panel-alertas/">Volver al panel</a></p>
    <table border="1" cellpadding="6" cellspacing="0">
        <thead><tr><th>ID</th><th>Fecha</th><th>Estado</th><th>Dirección</th><th>Cadete</th><th>Total</th></tr></thead>
        <tbody>{''.join(filas) or '<tr><td colspan="6">Sin datos</td></tr>'}</tbody>
    </table>
    </div>
    """
    return HttpResponse(html)


@require_POST
@login_required
def panel_alertas_set_estado(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    estado = (request.POST.get('estado') or '').upper()
    validos = {'RECIBIDO', 'EN_PREPARACION', 'ASIGNADO', 'EN_CAMINO', 'ENTREGADO', 'CANCELADO'}
    if estado not in validos:
        return JsonResponse({'ok': False, 'error': 'estado_invalido'}, status=400)

    es_staff = bool(request.user.is_staff)
    es_cadete = hasattr(request.user, 'cadeteprofile')

    permitido = False
    if es_staff:
        permitido = True
    elif es_cadete:
        if pedido.cadete_asignado_id == request.user.cadeteprofile.id and estado in {'EN_CAMINO', 'ENTREGADO'}:
            permitido = True

    if not permitido:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': 'no_permiso'}, status=403)
        return redirect('login')

    _marcar_estado(pedido, estado, actor=request.user, fuente='panel_alertas_set_estado')

    _notify_panel_update(pedido)

    cadete_nombre = None
    if getattr(pedido, 'cadete_asignado', None):
        cadete_nombre = pedido.cadete_asignado.user.get_full_name() or pedido.cadete_asignado.user.username

    return JsonResponse({'ok': True, 'pedido_id': pedido.id, 'estado': pedido.estado, 'cadete': cadete_nombre})


# =========================
# === TIENDA / CADETES
# =========================
@staff_member_required
def confirmar_pedido(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)

    if pedido.estado != 'RECIBIDO':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': 'Pedido ya procesado'}, status=400)
        messages.warning(request, f"El Pedido #{pedido.id} ya fue procesado.")
        return redirect('panel_alertas')

    _marcar_estado(pedido, 'EN_PREPARACION', actor=request.user, fuente='confirmar_pedido')

    # WebSocket a tablets/tienda + Push a cadetes
    try:
        channel_layer = get_channel_layer()

        detalles_para_notificacion = []
        for detalle in pedido.detalles.all():
            detalles_para_notificacion.append({
                'producto_nombre': detalle.producto.nombre,
                'opcion_nombre': detalle.opcion_seleccionada.nombre_opcion if detalle.opcion_seleccionada else None,
                'cantidad': detalle.cantidad,
                'sabores_nombres': [s.nombre for s in detalle.sabores.all()],
            })

        order_data = {
            'id': pedido.id,
            'cliente_nombre': pedido.cliente_nombre,
            'cliente_direccion': pedido.cliente_direccion,
            'direccion_legible': _direccion_legible_from_text(pedido.cliente_direccion),
            'map_url': _map_url_from_text(pedido.cliente_direccion),
            'total_pedido': str(_compute_total(pedido)),
            'detalles': detalles_para_notificacion
        }

        async_to_sync(channel_layer.group_send)(
            'cadetes_disponibles',
            {'type': 'send_cadete_notification', 'order_data': order_data}
        )
        print(f"WEBSOCKET: Alerta para Pedido #{pedido.id} enviada al grupo 'cadetes_disponibles'.")
    except Exception as e:
        print(f"ERROR al enviar notificación por WebSocket a cadetes: {e}")

    try:
        _notify_cadetes_new_order(request, pedido)
    except Exception as e:
        print(f"Notify cadetes error: {e}")

    _notify_panel_update(pedido, message='nuevo_pedido')

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'pedido_id': pedido.id, 'estado': 'EN_PREPARACION'})

    messages.success(request, f"Pedido #{pedido.id} confirmado. ¡Alerta enviada a los repartidores conectados!")
    return redirect('panel_alertas')


@login_required
@require_POST
def aceptar_pedido(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)

    if not hasattr(request.user, 'cadeteprofile'):
        messages.error(request, "Acción no permitida. No tienes un perfil de cadete.")
        return redirect('index')

    if Pedido.objects.filter(
        cadete_asignado=request.user.cadeteprofile,
        estado__in=['ASIGNADO', 'EN_CAMINO']
    ).exists():
        messages.warning(request, "Ya tenés un pedido en curso. Entregalo antes de aceptar otro.")
        return redirect('panel_cadete')

    if pedido.estado != 'EN_PREPARACION' or pedido.cadete_asignado_id:
        messages.warning(request, f"El Pedido #{pedido.id} ya no está disponible para ser aceptado.")
        return redirect('panel_cadete')

    pedido.cadete_asignado = request.user.cadeteprofile
    try:
        pedido.save(update_fields=['cadete_asignado'])
    except Exception:
        pedido.save()
    _marcar_estado(pedido, 'ASIGNADO', actor=request.user, fuente='aceptar_pedido')

    cp = request.user.cadeteprofile
    if hasattr(cp, 'disponible'):
        try:
            cp.disponible = False
            cp.save(update_fields=['disponible'])
        except Exception:
            pass
    request.session['cadete_disponible'] = False
    request.session.modified = True

    _notify_panel_update(pedido)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'pedido_id': pedido.id, 'estado': 'ASIGNADO'})

    messages.success(request, f"¡Has aceptado el Pedido #{pedido.id}! Por favor, prepárate para retirarlo.")
    return redirect('panel_cadete')


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
    webpush_settings = getattr(settings, 'WEBPUSH_SETTINGS', {}) or {}
    vapid_public_key = webpush_settings.get('VAPID_PUBLIC_KEY')

    pedidos_en_curso = []
    if hasattr(request.user, 'cadeteprofile'):
        pedidos_en_curso = Pedido.objects.filter(
            cadete_asignado=request.user.cadeteprofile,
            estado__in=['ASIGNADO', 'EN_CAMINO']
        ).order_by('fecha_pedido')

    for p in pedidos_en_curso:
        setattr(p, 'direccion_legible', _direccion_legible_from_text(p.cliente_direccion))
        setattr(p, 'map_url', _map_url_from_text(p.cliente_direccion))
        setattr(p, 'metricas', _serialize_metricas(p))
        setattr(p, 'logs', p.logs_estado.select_related('actor').order_by('-created_at')[:8])

    contexto = {'vapid_public_key': vapid_public_key, 'pedidos_en_curso': pedidos_en_curso}
    return render(request, 'pedidos/panel_cadete.html', contexto)


@login_required
def cadete_historial(request):
    """
    Historial del cadete logueado.
    - Intenta renderizar 'pedidos/cadete_historial.html'.
    - Si el template no existe, devuelve una tabla simple (fallback) para no romper.
    """
    if not hasattr(request.user, 'cadeteprofile'):
        messages.error(request, "Acceso denegado: este usuario no es cadete.")
        return redirect('index')

    pedidos = (Pedido.objects
               .filter(cadete_asignado=request.user.cadeteprofile)
               .order_by('-fecha_pedido')[:300])

    ctx = {'pedidos': pedidos}
    try:
        return render(request, 'pedidos/cadete_historial.html', ctx)
    except TemplateDoesNotExist:
        filas = []
        for p in pedidos:
            filas.append(
                f"<tr>"
                f"<td>#{p.id}</td>"
                f"<td>{p.fecha_pedido:%Y-%m-%d %H:%M}</td>"
                f"<td>{p.estado}</td>"
                f"<td>{p.cliente_nombre or ''}</td>"
                f"<td>{_direccion_legible_from_text(p.cliente_direccion) or ''}</td>"
                f"<td>${_compute_total(p)}</td>"
                f"</tr>"
            )
        link = reverse('panel_cadete')
        html = f"""
        <div style="padding:20px;font-family:system-ui;-webkit-font-smoothing:antialiased">
          <h3>Historial de mis pedidos</h3>
          <p><a href="{link}">Volver al panel</a></p>
          <table border="1" cellpadding="6" cellspacing="0">
            <thead><tr><th>ID</th><th>Fecha</th><th>Estado</th><th>Cliente</th><th>Dirección</th><th>Total</th></tr></thead>
            <tbody>{''.join(filas) or '<tr><td colspan="6">Sin datos</td></tr>'}</tbody>
          </table>
        </div>
        """
        return HttpResponse(html)


@login_required
def logout_cadete(request):
    logout(request)
    messages.info(request, "Has cerrado sesión como cadete.")
    return redirect('login_cadete')


@login_required
@require_POST
def cadete_toggle_disponible(request):
    """
    Marca disponible/no-disponible al cadete.
    - Si CadeteProfile tiene booleano 'disponible', lo usa.
    - Si no existe, guarda en sesión como fallback.
    """
    if not hasattr(request.user, 'cadeteprofile'):
        return JsonResponse({'ok': False, 'error': 'no_cadete'}, status=403)

    val = (request.POST.get('disponible') == '1')
    if val and cadete_esta_ocupado(request.user.cadeteprofile):
        return JsonResponse({'ok': False, 'error': 'ocupado'}, status=400)

    prof = request.user.cadeteprofile
    used_model_field = False

    if hasattr(prof, 'disponible'):
        try:
            prof.disponible = val
            prof.save(update_fields=['disponible'])
            used_model_field = True
        except Exception:
            used_model_field = False

    if not used_model_field:
        request.session['cadete_disponible'] = val
        request.session.modified = True

    return JsonResponse({'ok': True, 'disponible': val})


@login_required
@require_POST
def cadete_set_estado(request, pedido_id):
    """
    Permite al cadete avanzar estado de su pedido:
    EN_CAMINO -> ENTREGADO.
    Devuelve JSON si es AJAX, o redirige al panel si no lo es.
    """
    if not hasattr(request.user, 'cadeteprofile'):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': 'no_cadete'}, status=403)
        messages.error(request, "Acción no permitida. No tenés perfil de cadete.")
        return redirect('panel_cadete')

    pedido = get_object_or_404(Pedido, id=pedido_id)

    if pedido.cadete_asignado != request.user.cadeteprofile:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': 'no_autorizado'}, status=403)
        messages.error(request, "No estás asignado a este pedido.")
        return redirect('panel_cadete')

    estado = (request.POST.get('estado') or '').upper()
    if estado not in {'EN_CAMINO', 'ENTREGADO'}:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': 'estado_invalido'}, status=400)
        messages.error(request, "Estado inválido.")
        return redirect('panel_cadete')

    _marcar_estado(pedido, estado, actor=request.user, fuente='cadete_set_estado')

    finalizado = False
    if estado == 'ENTREGADO':
        finalizado = True
        cp = request.user.cadeteprofile
        if hasattr(cp, 'disponible'):
            try:
                cp.disponible = False
                cp.save(update_fields=['disponible'])
            except Exception:
                pass
        request.session['cadete_disponible'] = False
        request.session.modified = True

    _notify_panel_update(pedido)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'ok': True,
            'estado': pedido.estado,
            'pedido_id': pedido.id,
            'finalizado': finalizado,
            'disponible': False if finalizado else None
        })
    else:
        if finalizado:
            messages.success(request, f"Pedido #{pedido.id} entregado. Podés volver a ponerte Disponible cuando quieras.")
        else:
            messages.success(request, f"Pedido #{pedido.id} → {pedido.estado}.")
        return redirect('panel_cadete')


@login_required
@require_POST
def save_subscription(request):
    print("--- VISTA SAVE_SUBSCRIPTION INICIADA ---")

    if not hasattr(request.user, 'cadeteprofile'):
        print(f"DEBUG: Usuario {request.user.username} intentó suscribirse pero NO es un cadete.")
        return JsonResponse({'status': 'error', 'message': 'User is not a cadete'}, status=403)

    try:
        data = json.loads(request.body)
        print(f"DEBUG: Datos de suscripción recibidos para el cadete {request.user.username}.")
        updated_count = CadeteProfile.objects.filter(user=request.user).update(subscription_info=data)
        print(f"DEBUG: El comando update() afectó a {updated_count} fila(s) para el usuario {request.user.username}.")
        if updated_count > 0:
            print(f"ÉXITO: Suscripción guardada para {request.user.username}.")
            return JsonResponse({'status': 'ok', 'message': 'Subscription saved'})
        else:
            print(f"ERROR: No se encontró el perfil del cadete {request.user.username} para actualizar.")
            return JsonResponse({'status': 'error', 'message': 'Cadete profile not found for update'}, status=404)
    except json.JSONDecodeError:
        print("ERROR: No se pudo decodificar el JSON del request body.")
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        print(f"ERROR: Excepción inesperada en save_subscription: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def cadete_feed(request):
    """
    Si el cadete tiene un pedido activo -> no mostramos ofertas.
    Si el cadete NO está disponible -> no mostramos ofertas.
    Si está disponible y libre -> mostramos pedidos EN_PREPARACION sin cadete.
    """
    if not hasattr(request.user, 'cadeteprofile'):
        return JsonResponse({'ok': False, 'error': 'no_cadete'}, status=403)

    cp = request.user.cadeteprofile

    if Pedido.objects.filter(
        cadete_asignado=cp,
        estado__in=['ASIGNADO', 'EN_CAMINO']
    ).exists():
        return JsonResponse({'ok': True, 'disponible': False, 'pedidos': []})

    disponible = None
    if hasattr(cp, 'disponible'):
        try:
            disponible = bool(cp.disponible)
        except Exception:
            disponible = None
    if disponible is None:
        disponible = bool(request.session.get('cadete_disponible', False))

    if not disponible:
        return JsonResponse({'ok': True, 'disponible': False, 'pedidos': []})

    pedidos = (Pedido.objects
            .filter(estado='EN_PREPARACION', cadete_asignado__isnull=True)
            .order_by('-fecha_pedido')[:50])

    def ser(p):
        return {
            'id': p.id,
            'cliente_nombre': p.cliente_nombre or '',
            'cliente_direccion': p.cliente_direccion or '',
            'direccion_legible': _direccion_legible_from_text(p.cliente_direccion),
            'map_url': _map_url_from_text(p.cliente_direccion),
            'cliente_telefono': p.cliente_telefono or '',
            'total': str(_compute_total(p)),
            'detalles': [{
                'producto': d.producto.nombre,
                'opcion': d.opcion_seleccionada.nombre_opcion if d.opcion_seleccionada else None,
                'cant': d.cantidad,
                'sabores': [s.nombre for s in d.sabores.all()],
            } for d in p.detalles.all()],
        }

    return JsonResponse({'ok': True, 'disponible': True, 'pedidos': [ser(p) for p in pedidos]})


# =========================
# === MERCADO PAGO (Refunds + webhook + success)
# =========================
def _mp_find_latest_approved_payment(external_reference: str):
    if not getattr(settings, "MERCADO_PAGO_ACCESS_TOKEN", None):
        raise RuntimeError("MERCADO_PAGO_ACCESS_TOKEN no está configurado en el servidor")

    sdk = mercadopago.SDK(settings.MERCADO_PAGO_ACCESS_TOKEN)
    try:
        search = sdk.payment().search({
            "external_reference": str(external_reference),
            "sort": "date_created",
            "criteria": "desc",
        })
        results = (search or {}).get("response", {}).get("results") or []
        for it in results:
            p = it.get("payment") if isinstance(it, dict) and "payment" in it else it
            if isinstance(p, dict) and p.get("status") == "approved":
                return p
    except Exception as e:
        print(f"MP SEARCH error: {e}")
    return None


@staff_member_required
@require_POST
def mp_refund(request, pedido_id: int):
    if not getattr(settings, "MERCADO_PAGO_ACCESS_TOKEN", None):
        return JsonResponse({'ok': False, 'error': 'missing_access_token'}, status=500)

    pedido = get_object_or_404(Pedido, id=pedido_id)

    amount_raw = (request.POST.get('monto') or '').strip()
    refund_amount = None
    if amount_raw:
        try:
            refund_amount = Decimal(amount_raw)
            if refund_amount <= 0:
                return JsonResponse({'ok': False, 'error': 'monto_invalido'}, status=400)
        except Exception:
            return JsonResponse({'ok': False, 'error': 'monto_invalido'}, status=400)

    payment = _mp_find_latest_approved_payment(pedido.id)
    if not payment:
        return JsonResponse({'ok': False, 'error': 'payment_no_encontrado'}, status=404)

    payment_id = payment.get("id")
    sdk = mercadopago.SDK(settings.MERCADO_PAGO_ACCESS_TOKEN)

    try:
        if refund_amount is None:
            mp_resp = sdk.refund().create(payment_id)
        else:
            mp_resp = sdk.refund().create(payment_id, {"amount": float(refund_amount)})
    except Exception as e:
        print(f"MP REFUND EXCEPTION: {e}")
        return JsonResponse({'ok': False, 'error': 'mp_exception', 'detail': str(e)}, status=500)

    status = mp_resp.get("status")
    resp = (mp_resp.get("response") or {}) if isinstance(mp_resp, dict) else {}

    if status not in (200, 201):
        return JsonResponse({'ok': False, 'error': 'mp_error', 'detail': resp}, status=400)

    data_out = {
        'ok': True,
        'pedido_id': pedido.id,
        'payment_id': payment_id,
        'refund_id': resp.get('id'),
        'amount': resp.get('amount') or refund_amount and float(refund_amount),
        'status': resp.get('status') or 'created',
    }
    return JsonResponse(data_out, status=200)


@csrf_exempt
def mp_webhook_view(request):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        payload = {}

    payment_id = (
        request.GET.get("id")
        or request.GET.get("data.id")
        or (payload.get("data") or {}).get("id")
    )
    if not payment_id:
        return HttpResponse(status=200)

    try:
        sdk = mercadopago.SDK(settings.MERCADO_PAGO_ACCESS_TOKEN)
        payment = sdk.payment().get(payment_id)["response"]
    except Exception as e:
        print(f"WEBHOOK MP: error consultando pago: {e}")
        return HttpResponse(status=200)

    ref = payment.get("external_reference")
    status = payment.get("status")
    if not ref:
        return HttpResponse(status=200)

    try:
        pedido = Pedido.objects.get(id=ref)
    except Pedido.DoesNotExist:
        print("WEBHOOK MP: Pedido no encontrado por external_reference")
        return HttpResponse(status=200)

    try:
        pedido.metodo_pago = 'MERCADOPAGO'
        try:
            pedido.save(update_fields=['metodo_pago'])
        except Exception:
            pedido.save()

        total_txn = Decimal(str(payment.get("transaction_amount") or "0"))
        refunded_total = Decimal('0')

        try:
            refunded_total = Decimal(str(payment.get("transaction_amount_refunded") or "0"))
        except Exception:
            refunded_total = Decimal('0')

        if refunded_total == 0 and isinstance(payment.get("refunds"), list):
            try:
                refunded_total = sum(Decimal(str(r.get("amount") or "0")) for r in payment.get("refunds"))
            except Exception:
                pass

        if status in ('refunded', 'cancelled', 'charged_back') or (total_txn > 0 and refunded_total >= total_txn):
            _marcar_estado(pedido, 'CANCELADO', actor=None, fuente='webhook_mp', meta={'payment_id': payment_id})
        else:
            if status == 'approved':
                _marcar_estado(pedido, 'RECIBIDO', actor=None, fuente='webhook_mp', meta={'payment_id': payment_id})
            elif status == 'rejected':
                _marcar_estado(pedido, 'CANCELADO', actor=None, fuente='webhook_mp', meta={'payment_id': payment_id})
    except Exception as e:
        print(f"WEBHOOK MP: error guardando pedido/estado: {e}")

    try:
        _notify_panel_update(pedido, message='actualizacion_pedido' if status != 'approved' else 'nuevo_pedido')
    except Exception as e:
        print(f"WEBHOOK MP: error enviando WS: {e}")

    if status == 'approved':
        try:
            if pedido.user and hasattr(pedido.user, 'clienteprofile'):
                total = Decimal(str(_compute_total(pedido)))
                puntos = int(total / Decimal('500')) * 100
                pedido.user.clienteprofile.puntos_fidelidad += puntos
                pedido.user.clienteprofile.save()
        except Exception as e:
            print(f"WEBHOOK MP: error otorgando puntos: {e}")

    return HttpResponse(status=200)


def mp_success(request):
    last_id = request.session.pop('mp_last_order_id', None)
    if last_id:
        try:
            pedido = Pedido.objects.get(id=last_id)
            channel_layer = get_channel_layer()
            detalles_para_notificacion = []
            for d in pedido.detalles.all():
                detalles_para_notificacion.append({
                    'producto_nombre': d.producto.nombre,
                    'opcion_nombre': d.opcion_seleccionada.nombre_opcion if d.opcion_seleccionada else None,
                    'cantidad': d.cantidad,
                    'sabores_nombres': [s.nombre for s in d.sabores.all()],
                })

            async_to_sync(channel_layer.group_send)(
                'pedidos_new_orders',
                {
                    'type': 'send_order_notification',
                    'message': 'nuevo_pedido',
                    'order_id': pedido.id,
                    'order_data': {
                        'cliente_nombre': pedido.cliente_nombre,
                        'cliente_direccion': pedido.cliente_direccion,
                        'direccion_legible': _direccion_legible_from_text(pedido.cliente_direccion),
                        'map_url': _map_url_from_text(pedido.cliente_direccion),
                        'cliente_telefono': pedido.cliente_telefono,
                        'metodo_pago': 'MERCADOPAGO',
                        'total_pedido': str(_compute_total(pedido)),
                        'costo_envio': float(pedido.costo_envio or 0),
                        'detalles': detalles_para_notificacion,
                        'metricas': _serialize_metricas(pedido),
                        'logs': _serialize_logs(pedido),
                    }
                }
            )
            print(f"MP SUCCESS: notificación fallback enviada para pedido #{pedido.id}")
        except Exception as e:
            print(f"MP SUCCESS: error en fallback WS: {e}")
    messages.info(request, "Gracias. Estamos confirmando tu pago. En breve verás tu pedido en cocina.")
    return redirect('pedido_exitoso')


# Alias de compatibilidad
mp_webhook = mp_webhook_view


# =========================
# === CANJE DE PUNTOS
# =========================
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

                messages.success(
                    request,
                    f"¡Has canjeado '{producto_canje.nombre}' por {producto_canje.puntos_requeridos} puntos! "
                    f"Tus puntos actuales son {cliente_profile.puntos_fidelidad}."
                )

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
                    messages.error(request, "Error: No se encontró el producto ficticio 'Canje de Puntos - No Comprar'.")
                except Exception as e:
                    messages.error(request, f"Hubo un problema al registrar el canje como pedido: {e}")

        else:
            messages.error(
                request,
                f"No tienes suficientes puntos para canjear '{producto_canje.nombre}'. "
                f"Necesitas {producto_canje.puntos_requeridos} puntos y solo tienes {cliente_profile.puntos_fidelidad}."
            )

        return redirect('canjear_puntos')

    contexto = {'cliente_profile': cliente_profile, 'productos_canje': productos_canje}
    return render(request, 'pedidos/canjear_puntos.html', contexto)


# =========================
# === Service Worker (scope raíz)
# =========================
@require_GET
def service_worker(request):
    """
    Sirve el service worker con scope raíz (/) para permitir notificaciones
    desde cualquier URL del sitio.
    """
    resp = render(request, 'pedidos/sw.js', {})
    resp["Content-Type"] = "application/javascript"
    return resp
