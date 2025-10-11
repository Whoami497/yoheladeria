# pedidos/views.py
from django.db.models import Q, Exists, OuterRef
from django.conf import settings
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal, ROUND_HALF_UP
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.apps import apps
import json
import mercadopago
import requests
import re
import base64
from urllib.parse import quote_plus
from django.template import TemplateDoesNotExist
from django.contrib import messages
import logging
import socket
import textwrap
from django.views.decorators.http import require_GET
from .models import (
    Producto, Sabor, Pedido, DetallePedido, Categoria,
    OpcionProducto, ClienteProfile, ProductoCanje, CadeteProfile
)

# ====== Forms ======
try:
    from .forms import ClienteSignupForm, ClienteProfileForm
except Exception:
    from django import forms
    from django.contrib.auth.models import User
    try:
        from .models import ClienteProfile as _ClienteProfileModel
    except Exception:
        _ClienteProfileModel = None

    class ClienteSignupForm(forms.ModelForm):
        password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
        password2 = forms.CharField(label="Repetir contraseña", widget=forms.PasswordInput)

        class Meta:
            model = User
            fields = ["username", "first_name", "last_name", "email"]

        def clean_username(self):
            u = self.cleaned_data.get("username", "")
            if " " in u:
                raise forms.ValidationError("El usuario no puede contener espacios.")
            return u

        def clean(self):
            data = super().clean()
            if data.get("password1") != data.get("password2"):
                raise forms.ValidationError("Las contraseñas no coinciden.")
            return data

        def save(self, commit=True):
            user = super().save(commit=False)
            user.set_password(self.cleaned_data["password1"])
            if commit:
                user.save()
            try:
                if _ClienteProfileModel:
                    _ClienteProfileModel.objects.get_or_create(user=user)
            except Exception:
                pass
            return user

    if _ClienteProfileModel:
        class ClienteProfileForm(forms.ModelForm):
            first_name = forms.CharField(required=False, label="Nombre")
            last_name = forms.CharField(required=False, label="Apellido")
            email = forms.EmailField(required=False, label="Email")
            class Meta:
                model = _ClienteProfileModel
                fields = ["telefono", "direccion"]
    else:
        class ClienteProfileForm(forms.Form):
            first_name = forms.CharField(required=False, label="Nombre")
            last_name  = forms.CharField(required=False, label="Apellido")
            email      = forms.EmailField(required=False, label="Email")

# ==> Geocoding util
try:
    from .utils.geocoding import reverse_geocode as gc_reverse
except Exception:
    gc_reverse = None


# =========================
# === util
# =========================
def _abs_https(request, url_or_path: str) -> str:
    if url_or_path.startswith('http://') or url_or_path.startswith('https://'):
        url = url_or_path
    else:
        url = request.build_absolute_uri(url_or_path)
    if url.startswith('http://'):
        url = 'https://' + url[len('http://'):]
    return url


def cadete_esta_ocupado(cadete_profile) -> bool:
    if not cadete_profile:
        return False
    return Pedido.objects.filter(
        cadete_asignado=cadete_profile,
        estado__in=['ASIGNADO', 'EN_CAMINO']
    ).exists()


def _compute_total(pedido) -> Decimal:
    total = Decimal('0.00')
    for d in pedido.detalles.all():
        precio = d.producto.precio
        if d.opcion_seleccionada:
            precio += d.opcion_seleccionada.precio_adicional
        total += (precio * d.cantidad)
    if pedido.costo_envio:
        total += pedido.costo_envio
    return total.quantize(Decimal('0.01'))

def _direccion_legible_from_text(text: str) -> str:
    if not text:
        return ""
    parts = text.split(' — GPS:')
    return parts[0].strip()

def _pedido_es_pickup(pedido_or_text) -> bool:
    """
    True si el pedido es 'Retiro en local' (no se debe notificar a cadetes).
    Acepta el modelo Pedido o el string de dirección.
    """
    text = pedido_or_text.cliente_direccion if hasattr(pedido_or_text, 'cliente_direccion') else (pedido_or_text or "")
    dir_legible = (_direccion_legible_from_text(text) or "").strip().lower()
    return dir_legible.startswith("retiro en local")

def _map_url_from_text(text: str) -> str:
    coords = _extract_coords(text)
    if coords:
        lat, lng = coords
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    q = quote_plus(_direccion_legible_from_text(text) or text)
    return f"https://www.google.com/maps/search/?api=1&query={q}"


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


def _serialize_pedido_for_panel(pedido, include_details=True):
    data = {
        'id': pedido.id,
        'estado': pedido.estado,
        'cliente_nombre': pedido.cliente_nombre,
        'cliente_direccion': pedido.cliente_direccion,
        'direccion_legible': getattr(pedido, 'direccion_legible', None) or _direccion_legible_from_text(pedido.cliente_direccion),
        'map_url': _map_url_from_text(pedido.cliente_direccion),
        'cliente_telefono': pedido.cliente_telefono,
        'metodo_pago': pedido.metodo_pago,
        'total_pedido': str(_compute_total(pedido)),
        'costo_envio': float(pedido.costo_envio or 0),
        'cadete': (
            pedido.cadete_asignado.user.get_full_name() or pedido.cadete_asignado.user.username
        ) if getattr(pedido, 'cadete_asignado', None) else None,
    }
    if include_details:
        dets = []
        for d in pedido.detalles.all():
            todos = [s.nombre for s in d.sabores.all()]
            nota = (getattr(d, 'nota', '') or '')
            m = re.search(r'promo\s*1/4\s*:\s*(.+)$', nota, flags=re.IGNORECASE)
            extras = []
            if m:
                extras = [p.strip() for p in m.group(1).split(',') if p.strip()]
            extras_set = {e.lower() for e in extras}
            principales = [n for n in todos if n.lower() not in extras_set]

            dets.append({
                'producto_nombre': d.producto.nombre,
                'opcion_nombre': d.opcion_seleccionada.nombre_opcion if d.opcion_seleccionada else None,
                'cantidad': d.cantidad,
                'sabores_nombres': principales,       # Kg
                'sabores_1_4_nombres': extras,        # 1/4
            })
        data['detalles'] = dets

    data.update({
        'metricas': _serialize_metricas(pedido),
        'logs': _serialize_logs(pedido, limit=8),
    })
    return data



def _notify_panel_update(pedido, message='actualizacion_pedido'):
    """
    Envía por Channels la actualización al panel.
    Incluye siempre el nombre del cadete (o None) para reflejar asignaciones.
    """
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
                'cadete': (
                    pedido.cadete_asignado.user.get_full_name() or pedido.cadete_asignado.user.username
                ) if getattr(pedido, 'cadete_asignado', None) else None,
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


_logger = logging.getLogger(__name__)

def _broadcast_tienda_estado(abierta: bool):
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        async_to_sync(channel_layer.group_send)(
            "pedidos_new_orders",
            {
                "type": "send_order_notification",
                "message": "tienda_estado",
                "order_id": 0,
                "order_data": {"abierta": bool(abierta)},
            },
        )
    except Exception as e:
        _logger.warning("No se pudo broadcastear tienda_estado: %s", e)


def _notify_cadetes_new_order(request, pedido):
    """
    Push a cadetes:
      - Si es 'Retiro en local' => no notifica.
      - Si hay cadete_asignado => notifica SOLO a ese cadete.
      - Si no hay asignado     => broadcast a disponibles sin pedido activo.
    """
    # 1) Filtrar retiros en local
    if _pedido_es_pickup(pedido):
        return

    try:
        from pywebpush import webpush, WebPushException
    except Exception as e:
        print(f"WEBPUSH no disponible: {e}")
        return

    vapid = getattr(settings, 'WEBPUSH_SETTINGS', {}) or {}
    priv = vapid.get('VAPID_PRIVATE_KEY')
    admin = vapid.get('VAPID_ADMIN_EMAIL') or 'admin@example.com'
    if not priv:
        print("WEBPUSH: Falta VAPID_PRIVATE_KEY en settings.")
        return

    dir_legible = _direccion_legible_from_text(pedido.cliente_direccion) or ""

    # 2) Si hay asignado → push dirigido
    if getattr(pedido, 'cadete_asignado_id', None):
        cp = pedido.cadete_asignado
        sub = cp.subscription_info if isinstance(cp.subscription_info, dict) else None
        if not sub:
            print("WEBPUSH: cadete asignado sin subscription_info; no se envía push.")
            return
        payload = {
            "title": "Pedido asignado",
            "body": f"Pedido #{pedido.id} — {dir_legible}",
            "url": _abs_https(request, reverse('panel_cadete')),
        }
        try:
            webpush(
                subscription_info=sub,
                data=json.dumps(payload),
                vapid_private_key=priv,
                vapid_claims={"sub": f"mailto:{admin}"},
            )
        except WebPushException as e:
            print(f"WEBPUSH dirigido error: {e}")
        except Exception as e:
            print(f"WEBPUSH dirigido excepción: {e}")
        return

    # 3) Si no hay asignado → broadcast a disponibles/sin activo
    activos_qs = Pedido.objects.filter(
        cadete_asignado_id=OuterRef('pk'),
        estado__in=['ASIGNADO', 'EN_CAMINO']
    )

    qs = (CadeteProfile.objects
          .exclude(subscription_info__isnull=True)
          .annotate(tiene_activo=Exists(activos_qs))
          .filter(tiene_activo=False))

    try:
        has_disponible = any(f.name == 'disponible' for f in CadeteProfile._meta.get_fields())
    except Exception:
        has_disponible = False

    if has_disponible:
        qs = qs.filter(disponible=True)
    else:
        print("WEBPUSH: CadeteProfile sin campo 'disponible'; no se enviarán push.")
        qs = qs.none()

    targets = list(qs)
    if not targets:
        print("WEBPUSH: no hay cadetes disponibles para notificar.")
        return

    payload = {
        "title": "Nuevo pedido disponible",
        "body": f"Pedido #{pedido.id} — {dir_legible}",
        "url": _abs_https(request, reverse('panel_cadete')),
    }

    for cp in targets:
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
        except WebPushException as e:
            print(f"WEBPUSH cadete {cp.user_id} error: {e}")
        except Exception as e:
            print(f"WEBPUSH cadete {cp.user_id} excepción: {e}")


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


def _extract_nota_from_direccion(text: str) -> str:
    if not text:
        return ""
    m = re.search(r' — Nota:\s*(.+)$', text)
    return (m.group(1).strip() if m else "")


@require_GET
def api_costo_envio(request):
    direccion = (request.GET.get('direccion') or '').strip()
    if not direccion:
        return JsonResponse({'ok': True, 'costo_envio': 0.0, 'distancia_km': 0.0, 'mode': 'pickup'})

    costo, km = _calcular_costo_envio(direccion)

    addr = {}
    coords = _extract_coords(direccion)
    if coords:
        try:
            lat, lng = float(coords[0]), float(coords[1])
            addr = _reverse_geocode_any(lat, lng) or {}
        except Exception as e:
            print(f"GEOCODING reverse error: {e}")
            addr = {}

    addr_full = addr.get('formatted_address') or _direccion_legible_from_text(direccion)

    payload = {
        'ok': True,
        'costo_envio': float(costo),
        'distancia_km': float(km),
        'mode': 'maps',
        'direccion_legible': addr_full,
        'direccion_corta': _short_address(addr_full),
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


def _short_address(formatted: str, max_len: int = 60) -> str:
    if not formatted:
        return ""
    parts = [p.strip() for p in formatted.split(",") if p.strip()]
    pretty = formatted
    if len(parts) >= 3:
        street = parts[0]
        locality = parts[-3]
        pretty = f"{street} · {locality}"
    if len(pretty) > max_len:
        pretty = pretty[:max_len - 1] + "…"
    return pretty


def _reverse_geocode_local(lat: float, lng: float) -> dict:
    api_key = (
        getattr(settings, 'GOOGLE_MAPS_API_KEY', '') or
        getattr(settings, 'GOOGLE_GEOCODING_KEY', '') or
        getattr(settings, 'GOOGLE_API_KEY', '')
    )
    if not api_key:
        if settings.DEBUG:
            print("GEOCODING DEBUG: falta API key")
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
            comps = res0.get('address_components') or []
            out['formatted_address'] = res0.get('formatted_address')
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
    dest = (direccion_cliente or '').strip()
    if not dest:
        return (Decimal('0.00'), 0.0)

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

    destino = dest

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


# =========================
# === CATÁLOGO / HOME
# =========================
def index(request):
    q = (request.GET.get('q') or '').strip()
    cat = request.GET.get('cat')
    sort = request.GET.get('sort') or 'recientes'

    productos = Producto.objects.filter(disponible=True)

    if cat:
        productos = productos.filter(categoria_id=cat)
    if q:
        productos = productos.filter(Q(nombre__icontains=q) | Q(descripcion__icontains=q))

    # ORDEN
    if sort == 'precio_asc':
        productos = productos.order_by('precio', 'nombre', 'id')
    elif sort == 'precio_desc':
        productos = productos.order_by('-precio', 'nombre', 'id')
    elif sort == 'nombre':
        productos = productos.order_by('nombre', 'id')
    else:
        # orden manual para "Todos" (queda primero), y dentro, recientes
        productos = productos.order_by('orden_todos', '-id')

    categorias = Categoria.objects.filter(disponible=True).order_by('orden')

    try:
        cat_val = int(cat) if cat else None
    except Exception:
        cat_val = None

    contexto = {
        'productos': productos,
        'categorias': categorias,
        'q': q,
        'cat': cat_val,
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
        # --- Sabores del tamaño principal ---
        sabores_seleccionados_ids_raw = request.POST.getlist('sabores')
        sabores_seleccionados_ids = [s_id for s_id in sabores_seleccionados_ids_raw if s_id]

        # --- Opción seleccionada (si corresponde) ---
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

        # Validación sabores principales
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
        else:
            sabores_seleccionados_ids = []

        # --- Sabores extra (PROMO 1/4) ---
        try:
            cant_extra = int(request.POST.get('cantidad_sabores_extra', 0))
        except ValueError:
            cant_extra = 0
        cant_extra = max(0, min(3, cant_extra))  # tope 3

        sabores_extra_ids = [s for s in request.POST.getlist('sabores_extra') if s][:cant_extra]

        # Armar carrito
        if 'carrito' not in request.session:
            request.session['carrito'] = {}

        # cantidad de unidades
        try:
            cantidad_a_agregar = int(request.POST.get('cantidad_item', 1))
            if cantidad_a_agregar < 1:
                cantidad_a_agregar = 1
        except ValueError:
            cantidad_a_agregar = 1

        # nombres sabores principales
        sabores_nombres = []
        if sabores_seleccionados_ids:
            sabores_objetos = Sabor.objects.filter(id__in=sabores_seleccionados_ids)
            sabores_nombres = sorted([s.nombre for s in sabores_objetos])

        # nombres sabores extra
        sabores_extra_nombres = []
        if sabores_extra_ids:
            sabores_extra_obj = Sabor.objects.filter(id__in=sabores_extra_ids)
            sabores_extra_nombres = sorted([s.nombre for s in sabores_extra_obj])

        # precio y metadatos
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
            opcion_imagen_para_carrito = (
                opcion_seleccionada_obj.imagen_opcion
                if (opcion_seleccionada_obj and getattr(opcion_seleccionada_obj, 'imagen_opcion', None))
                else producto.imagen
            )

        # clave del item en carrito (incluye los sabores para “mergear” iguales)
        item_key = f"{producto.id}_"
        if opcion_id_para_carrito:
            item_key += f"opcion-{opcion_id_para_carrito}_"
        item_key += "_".join(sorted(sabores_seleccionados_ids))
        if sabores_extra_ids:
            item_key += "__extra_" + "_".join(sorted(sabores_extra_ids))

        item = {
            'producto_id': producto.id,
            'producto_nombre': nombre_item_carrito,
            'precio': str(precio_final_item),
            'cantidad': cantidad_a_agregar,
            'sabores_ids': sabores_seleccionados_ids,
            'sabores_nombres': sabores_nombres,
            'sabores_maximos': producto.sabores_maximos,
            'opcion_id': opcion_id_para_carrito,
            'opcion_nombre': opcion_nombre_para_carrito,
            'imagen_mostrada': opcion_imagen_para_carrito if opcion_imagen_para_carrito else producto.imagen,
            # --- promo 1/4 extra (opcional) ---
            'sabores_extra_ids': sabores_extra_ids,
            'sabores_extra_nombres': sabores_extra_nombres,
        }

        if item_key in request.session['carrito']:
            request.session['carrito'][item_key]['cantidad'] += cantidad_a_agregar
            messages.info(request, f'Se han añadido {cantidad_a_agregar} unidades más de "{nombre_item_carrito}" al carrito.')
        else:
            request.session['carrito'][item_key] = item
            messages.success(
                request,
                f'"{nombre_item_carrito}" ha sido añadido al carrito '
                f'({cantidad_a_agregar} unidad{"es" if cantidad_a_agregar > 1 else ""}).'
            )

        request.session.modified = True
        return redirect('detalle_producto', producto_id=producto.id)

    # GET
    range_sabores = range(1, producto.sabores_maximos + 1) if producto.sabores_maximos > 0 else []
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

    try:
        if pedido.costo_envio and pedido.costo_envio > 0:
            items.append({
                "title": "Envío",
                "quantity": 1,
                "unit_price": float(pedido.costo_envio),
                "currency_id": "ARS",
            })
    except Exception:
        pass

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

from django.db import transaction

from django.db import transaction

from django.db import transaction

def ver_carrito(request):
    from decimal import Decimal
    carrito = request.session.get('carrito', {})
    total = Decimal('0.00')
    items_carrito_procesados = []

    # ---- Render (GET)
    for key, item in carrito.items():
        try:
            item_precio = Decimal(item.get('precio', '0.00'))
            item_cantidad = int(item.get('cantidad', 1)) or 1
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
                'sabores_extra_nombres': item.get('sabores_extra_nombres', []),
                'nota_extra': item.get('nota_extra') or '',
                'nota': item.get('nota') or '',
                'subtotal': item_subtotal,
            })
        except Exception as e:
            print(f"[CART] GET omitido por error: {e} - Item: {item}")

    if request.method != 'POST':
        return render(request, 'pedidos/carrito.html', {
            'carrito_items': items_carrito_procesados,
            'total': total
        })

    # ---- POST: crear pedido
    resp = _abort_if_store_closed(request)
    if resp:
        return resp

    if not carrito:
        messages.error(request, "Tu carrito está vacío. Agregá productos para continuar.")
        return redirect('ver_carrito')

    items_validos = []
    total_del_pedido_para_puntos = Decimal('0.00')

    for key, raw in carrito.items():
        try:
            prod = Producto.objects.get(id=raw['producto_id'], disponible=True)
        except Producto.DoesNotExist:
            continue
        except Exception as e:
            print(f"[CART] Error cargando producto: {e}")
            continue

        opcion_obj = None
        opt_id = raw.get('opcion_id')
        if opt_id:
            try:
                opcion_obj = OpcionProducto.objects.get(
                    id=opt_id, producto_base=prod, disponible=True
                )
            except OpcionProducto.DoesNotExist:
                continue

        try:
            precio_unit = Decimal(str(raw.get('precio', prod.precio)))
        except Exception:
            precio_unit = Decimal(prod.precio)

        try:
            cantidad = int(raw.get('cantidad', 1))
            if cantidad < 1:
                cantidad = 1
        except Exception:
            cantidad = 1

        # Sabores del kg (M2M)
        sabores_ids = raw.get('sabores_ids', []) or []
        sabores_qs = list(Sabor.objects.filter(id__in=sabores_ids))

        # Sabores del 1/4 (M2M + nota)
        extra_ids = raw.get('sabores_extra_ids', []) or []
        extra_qs = list(Sabor.objects.filter(id__in=extra_ids)) if extra_ids else []
        extra_names = raw.get('sabores_extra_nombres', []) or []

        # Nota legible para ticket
        promo_14_nota = "Promo 1/4: " + ", ".join(extra_names) if extra_names else ""
        nota_manual = (raw.get('nota') or '').strip()
        nota_final_item = ", ".join([t for t in [promo_14_nota, nota_manual] if t])

        items_validos.append({
            'producto': prod,
            'opcion': opcion_obj,
            'cantidad': cantidad,
            'sabores_qs': sabores_qs,
            'sabores_extra_qs': extra_qs,
            'precio_unit': precio_unit,
            'nombre_para_msg': raw.get('producto_nombre') or prod.nombre,
            'nota_final_item': nota_final_item,       # ← se guardará en DetallePedido.nota
            'sabores_extra_nombres': extra_names,
        })
        total_del_pedido_para_puntos += (precio_unit * cantidad)

    if not items_validos:
        messages.error(request, "Ningún ítem de tu carrito es válido.")
        try:
            del request.session['carrito']
            request.session.modified = True
        except Exception:
            pass
        return redirect('index')

    # ---- Dirección / envío
    nombre = request.POST.get('cliente_nombre')
    direccion_input = (request.POST.get('cliente_direccion') or '').strip()
    telefono = request.POST.get('cliente_telefono')
    metodo_pago = (request.POST.get('metodo_pago') or '').strip()
    nota_pedido = (request.POST.get('nota_pedido') or '').strip()

    modo_envio = (request.POST.get('modo_envio') or '').lower()
    geo_latlng = (request.POST.get('geo_latlng') or '').strip()
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

    base_dir = direccion_legible or direccion_input or ("Cerca de " + geo_latlng if geo_latlng else "")
    if not base_dir and es_pickup:
        base_dir = "Retiro en local"

    direccion_a_guardar = base_dir or ""
    if geo_latlng:
        direccion_a_guardar = f"{direccion_a_guardar} — GPS: {geo_latlng}"
    if nota_pedido:
        direccion_a_guardar = f"{direccion_a_guardar} — Nota: {nota_pedido}"

    costo_envio_decimal = Decimal('0.00')
    distancia_km = 0.0
    if not es_pickup and direccion_para_maps:
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

    # ---- Crear pedido + detalles
    with transaction.atomic():
        nuevo_pedido = Pedido.objects.create(**pedido_kwargs)

        detalles_para_notificacion = []
        for it in items_validos:
            det = DetallePedido.objects.create(
                pedido=nuevo_pedido,
                producto=it['producto'],
                opcion_seleccionada=it['opcion'],
                cantidad=it['cantidad'],
            )
            # kg
            if it['sabores_qs']:
                det.sabores.set(it['sabores_qs'])
            # 1/4
            if it['sabores_extra_qs']:
                det.sabores.add(*it['sabores_extra_qs'])

            # ← GUARDA LA MARCA PARA EL TICKET
            if it.get('nota_final_item'):
                det.nota = it['nota_final_item']
                det.save(update_fields=['nota'])

            detalles_para_notificacion.append({
                'producto_nombre': it['producto'].nombre,
                'opcion_nombre': it['opcion'].nombre_opcion if it['opcion'] else None,
                'cantidad': it['cantidad'],
                'sabores_nombres': [s.nombre for s in it['sabores_qs']],
                'sabores_extra_nombres': it.get('sabores_extra_nombres', []),
            })

        if not nuevo_pedido.detalles.exists():
            raise RuntimeError("Pedido sin detalles: abortando creación.")

    # === Pago MP (igual que antes) ===
    if metodo_pago.strip().upper() in ('MP', 'MERCADOPAGO', 'MERCADO_PAGO', 'MERCADO PAGO'):
        try:
            _marcar_estado(nuevo_pedido, 'PENDIENTE_PAGO',
                           actor=request.user if request.user.is_authenticated else None,
                           fuente='checkout_mp')

            nuevo_pedido.metodo_pago = 'MERCADOPAGO'
            nuevo_pedido.save(update_fields=['metodo_pago'])

            request.session['mp_last_order_id'] = nuevo_pedido.id
            request.session.modified = True

            init_point = crear_preferencia_mp(request, nuevo_pedido)

            if 'carrito' in request.session:
                del request.session['carrito']
                request.session.modified = True

            messages.info(request, f"Redirigiendo a Mercado Pago para completar el pago del pedido #{nuevo_pedido.id}.")
            return redirect(init_point)
        except Exception as e:
            messages.error(request, f"No pudimos iniciar el pago con Mercado Pago. Detalle: {e}")
            return redirect('ver_carrito')

    # === SIN MP → directo a cocina
    try:
        _marcar_estado(nuevo_pedido, 'RECIBIDO',
                       actor=request.user if request.user.is_authenticated else None,
                       fuente='checkout_no_mp')
    except Exception:
        pass

    # Puntos
    if request.user.is_authenticated and hasattr(request.user, 'clienteprofile'):
        puntos_ganados = int(total_del_pedido_para_puntos / Decimal('500')) * 100
        request.user.clienteprofile.puntos_fidelidad += puntos_ganados
        request.user.clienteprofile.save()
        if puntos_ganados:
            messages.success(request, f"¡Has ganado {puntos_ganados} puntos de fidelidad con este pedido!")

    # WS panel
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
                    'total_pedido': str(_compute_total(nuevo_pedido)),
                    'costo_envio': float(nuevo_pedido.costo_envio or 0),
                    'distancia_km': float(distancia_km or 0),
                    'nota_pedido': (nota_pedido or None),
                    'detalles': detalles_para_notificacion,
                    'metricas': _serialize_metricas(nuevo_pedido),
                    'logs': _serialize_logs(nuevo_pedido),
                }
            }
        )
    except Exception as e:
        print(f"WS notify error: {e}")

    # Limpiar carrito
    try:
        del request.session['carrito']
        request.session.modified = True
    except Exception:
        pass

    messages.success(request, f'¡Tu pedido #{nuevo_pedido.id} ha sido realizado con éxito! Pronto nos contactaremos.')
    return redirect('pedido_exitoso')





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
    # Respetar el orden manual dentro de la categoría (tu campo existente)
    productos = (Producto.objects
                 .filter(categoria=categoria, disponible=True)
                 .order_by('orden_todos', 'nombre', 'id'))

    contexto = {
        'categoria_seleccionada': categoria,
        'productos': productos,
        'categorias': Categoria.objects.filter(disponible=True).order_by('orden', 'nombre'),
    }
    return render(request, 'pedidos/productos_por_categoria.html', contexto)



def pedido_exitoso(request):
    return render(request, 'pedidos/pedido_exitoso.html', {})


# =========================
# === AUTENTICACIÓN Y PERFIL
# =========================
def register_cliente(request):
    if request.method == 'POST':
        form = ClienteSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "¡Cuenta creada! Bienvenido/a.")
            return redirect('index')
    else:
        form = ClienteSignupForm()

    return render(request, 'pedidos/register.html', {'form': form})


@login_required
def perfil_cliente(request):
    user = request.user
    cliente_profile, created = ClienteProfile.objects.get_or_create(user=user)

    if request.method == 'POST':
        form = ClienteProfileForm(request.POST, instance=cliente_profile) if hasattr(ClienteProfileForm, '_meta') else ClienteProfileForm(request.POST)
        if form.is_valid():
            for k in ('first_name', 'last_name', 'email'):
                if k in form.cleaned_data:
                    setattr(user, k, form.cleaned_data[k] or getattr(user, k))
            user.save()
            try:
                form.save()
            except Exception:
                pass

            messages.success(request, "¡Tu perfil ha sido actualizado con éxito!")
            return redirect('perfil_cliente')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Error en {field}: {error}")
            for error in form.non_field_errors():
                messages.error(request, error)
    else:
        initial = {'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email}
        form = ClienteProfileForm(instance=cliente_profile, initial=initial) if hasattr(ClienteProfileForm, '_meta') else ClienteProfileForm(initial=initial)

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
    - Cliente: sus pedidos que NO estén ENTREGADO/CANCELADO.
    - Cadete: pedidos ASIGNADO/EN_CAMINO donde él es el cadete.
    """
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

    for p in pedidos:
        setattr(p, 'direccion_legible', _direccion_legible_from_text(p.cliente_direccion))
        setattr(p, 'map_url', _map_url_from_text(p.cliente_direccion))
        setattr(p, 'metricas', _serialize_metricas(p))
        try:
            logs_qs = p.logs_estado.select_related('actor').order_by('-created_at')[:8]
        except Exception:
            logs_qs = []
        setattr(p, 'logs', logs_qs)

    return render(request, 'pedidos/pedido_en_curso.html', {'pedidos': pedidos})


# =========================
# === PANEL DE ALERTAS TIENDA
# =========================
@staff_member_required
def panel_alertas(request):
    hoy = timezone.localdate()
    ayer = hoy - timedelta(days=1)

    pedidos_hoy = (
        Pedido.objects
        .filter(fecha_pedido__date=hoy)
        .exclude(estado__in=['ENTREGADO', 'CANCELADO', 'PENDIENTE_PAGO'])
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
            try:
                logs_qs = p.logs_estado.select_related('actor').order_by('-created_at')[:8]
            except Exception:
                logs_qs = []
            setattr(p, 'logs', logs_qs)
        return qs

    ctx = {
        'pedidos_hoy': enrich(pedidos_hoy),
        'pedidos_ayer': enrich(pedidos_ayer),
        'entregados_hoy': enrich(entregados_hoy),
    }
    return render(request, 'pedidos/panel_alertas.html', ctx)


@staff_member_required
def panel_alertas_data(request):
    scope = request.GET.get('scope', 'hoy')

    if scope == 'cadetes':
        qs = (CadeteProfile.objects
              .select_related('user')
              .annotate(
                  ocupado=Exists(
                      Pedido.objects.filter(
                          cadete_asignado_id=OuterRef('pk'),
                          estado__in=['ASIGNADO', 'EN_CAMINO']
                      )
                  )
              ))

        cadetes = []
        for c in qs:
            pedido_act = None
            if c.ocupado:
                pedido_act = (Pedido.objects
                              .filter(cadete_asignado_id=c.id,
                                      estado__in=['ASIGNADO', 'EN_CAMINO'])
                              .values_list('id', flat=True)
                              .first())
            cadetes.append({
                'id': c.id,
                'nombre': (c.user.get_full_name() or c.user.username),
                'disponible': bool(getattr(c, 'disponible', False)),
                'ocupado': bool(c.ocupado),
                'pedido_id': pedido_act,
                'subscription_ok': bool(c.subscription_info),
            })
        return JsonResponse({'ok': True, 'cadetes': cadetes})

    # default: datos de pedidos de hoy
    hoy = timezone.localdate()
    pedidos = (Pedido.objects
               .filter(fecha_pedido__date=hoy)
               .exclude(estado__in=['ENTREGADO', 'CANCELADO', 'PENDIENTE_PAGO'])
               .order_by('-fecha_pedido'))
    data = [_serialize_pedido_for_panel(p, include_details=True) for p in pedidos]
    return JsonResponse({'ok': True, 'pedidos': data})


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
    html = """
    <div style="padding:20px;font-family:system-ui;-webkit-font-smoothing:antialiased">
    <h3>Pedidos anteriores</h3>
    <p><a href="/panel-alertas/">Volver al panel</a></p>
    <table border="1" cellpadding="6" cellspacing="0">
        <thead><tr><th>ID</th><th>Fecha</th><th>Estado</th><th>Dirección</th><th>Cadete</th><th>Total</th></tr></thead>
        <tbody>{filas}</tbody>
    </table>
    </div>
    """.format(filas=''.join(filas) or '<tr><td colspan="6">Sin datos</td></tr>')
    return HttpResponse(html)


@staff_member_required
@require_POST
def panel_alertas_set_estado(request, pedido_id):
    """
    Cambia el estado del pedido (POST 'estado')
    o asigna/desasigna cadete (POST 'cadete_id').
    'cadete_id' = '0' o vacío -> desasignar (vuelve a A TODOS / EN_PREPARACION)
                 > 0          -> asignar (pone ASIGNADO si corresponde)
    """
    pedido = get_object_or_404(Pedido, pk=pedido_id)

    cadete_id = request.POST.get('cadete_id', None)
    if cadete_id is not None:
        # --- ASIGNACIÓN / DESASIGNACIÓN ---
        if not cadete_id or cadete_id == '0':
            # Desasignar → a todos
            pedido.cadete_asignado = None
            if pedido.estado == 'ASIGNADO':
                pedido.estado = 'EN_PREPARACION'
            if hasattr(pedido, 'fecha_asignado'):
                pedido.fecha_asignado = None
            fields = ['cadete_asignado', 'estado']
            if hasattr(pedido, 'fecha_asignado'):
                fields.append('fecha_asignado')
            pedido.save(update_fields=fields)
            _notify_panel_update(pedido)
            return JsonResponse({'ok': True, 'estado': pedido.estado, 'cadete': '—'})

        # Asignar a un cadete específico
        try:
            cad_id = int(cadete_id)
        except ValueError:
            return JsonResponse({'ok': False, 'error': 'cadete_id inválido'}, status=400)

        cadete = get_object_or_404(CadeteProfile, pk=cad_id)

        ocupado = Pedido.objects.filter(
            cadete_asignado=cadete,
            estado__in=['ASIGNADO', 'EN_CAMINO']
        ).exclude(pk=pedido.pk).exists()
        if ocupado:
            return JsonResponse({'ok': False, 'error': 'Cadete ocupado'}, status=409)

        pedido.cadete_asignado = cadete
        if pedido.estado == 'EN_PREPARACION':
            pedido.estado = 'ASIGNADO'
        if hasattr(pedido, 'fecha_asignado') and not pedido.fecha_asignado:
            pedido.fecha_asignado = timezone.now()
        fields = ['cadete_asignado', 'estado']
        if hasattr(pedido, 'fecha_asignado'):
            fields.append('fecha_asignado')
        pedido.save(update_fields=fields)

        cadete_name = (cadete.user.get_full_name() or cadete.user.username or f'Cadete {cadete.pk}').strip()
        _notify_panel_update(pedido)
        # Push SOLO al asignado (y no si es retiro en local)
        try:
            _notify_cadetes_new_order(request, pedido)
        except Exception as e:
            print(f"WEBPUSH asignar cadete error: {e}")
        return JsonResponse({'ok': True, 'estado': pedido.estado, 'cadete': cadete_name})

    # --- CAMBIO DE ESTADO ---
    estado = (request.POST.get('estado') or '').upper().strip()
    estados_validos = {'EN_PREPARACION', 'EN_CAMINO', 'ENTREGADO', 'CANCELADO', 'RECIBIDO', 'ASIGNADO'}
    if estado not in estados_validos:
        return JsonResponse({'ok': False, 'error': 'estado inválido'}, status=400)

    now = timezone.now()
    try:
        if estado == 'EN_PREPARACION' and getattr(pedido, 'fecha_en_preparacion', None) is None:
            pedido.fecha_en_preparacion = now
        elif estado == 'EN_CAMINO' and getattr(pedido, 'fecha_en_camino', None) is None:
            pedido.fecha_en_camino = now
        elif estado == 'ENTREGADO' and getattr(pedido, 'fecha_entregado', None) is None:
            pedido.fecha_entregado = now
        elif estado == 'CANCELADO' and getattr(pedido, 'fecha_cancelado', None) is None:
            pedido.fecha_cancelado = now
        elif estado == 'ASIGNADO' and getattr(pedido, 'fecha_asignado', None) is None:
            pedido.fecha_asignado = now
    except Exception:
        pass

    pedido.estado = estado
    pedido.save()

    cadete_name = None
    if pedido.cadete_asignado_id:
        u = pedido.cadete_asignado.user
        cadete_name = (u.get_full_name() or u.username).strip()

    _notify_panel_update(pedido)
    return JsonResponse({'ok': True, 'estado': pedido.estado, 'cadete': cadete_name})
# =========================
# === Impresión / Comandera
# =========================
def _format_money(v: Decimal) -> str:
    try:
        return f"${v.quantize(Decimal('0.01'))}"
    except Exception:
        return f"${v}"

def _ticket_width() -> int:
    try:
        return int(getattr(settings, 'COMANDERA_LINE_WIDTH', 32) or 32)
    except Exception:
        return 32

def _wrap_lines(target_list, text, initial_indent="", subsequent_indent=""):
    """Agrega a target_list las líneas envueltas sin partir palabras."""
    width = max(20, _ticket_width())
    if not text:
        target_list.append("")
        return
    wrapped = textwrap.wrap(
        text,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
    )
    target_list.extend(wrapped if wrapped else [""])

def _build_ticket_text(pedido) -> str:
    width = _ticket_width()
    tienda = getattr(settings, 'SITE_NAME', 'YO HELADERÍAS')
    ahora = timezone.localtime(getattr(pedido, 'fecha_pedido', None) or timezone.now())

    def _parse_promo_extras(nota: str):
        if not nota:
            return []
        m = re.search(r'promo\s*1/4\s*:\s*(.+)$', nota.strip(), flags=re.IGNORECASE)
        if not m:
            return []
        raw = m.group(1)
        parts = [p.strip() for p in raw.split(',') if p.strip()]
        seen, out = set(), []
        for p in parts:
            key = p.lower()
            if key not in seen:
                seen.add(key)
                out.append(p)
        return out

    header = [
        "=" * width,
        f"{tienda}".center(width),
        "PEDIDO A COCINA".center(width),
        f"#{pedido.id}  {ahora:%d/%m %H:%M}".center(width),
        "=" * width,
    ]
    cliente = [
        f"Cliente : {pedido.cliente_nombre or '-'}",
        f"Tel     : {pedido.cliente_telefono or '-'}",
    ]
    direccion_legible = _direccion_legible_from_text(pedido.cliente_direccion)
    nota_dir = _extract_nota_from_direccion(pedido.cliente_direccion)
    envio = [f"Entrega : {direccion_legible or 'Retiro en local'}"]
    if nota_dir:
        _wrap_lines(envio, f"Nota    : {nota_dir}", subsequent_indent="          ")
    pago = [f"Pago    : {pedido.metodo_pago or '-'}"]

    detalle = ["", "Items:", "-" * (width - 2)]
    for d in pedido.detalles.all():
        linea_base = f"{d.cantidad} x {d.producto.nombre}"
        if d.opcion_seleccionada:
            linea_base += f" ({d.opcion_seleccionada.nombre_opcion})"
        _wrap_lines(detalle, linea_base)

        todos = [s.nombre for s in d.sabores.all()]
        nota_item = getattr(d, 'nota', '') or ''
        extras = _parse_promo_extras(nota_item)
        extras_set = {e.lower() for e in extras}
        principales = [n for n in todos if n.lower() not in extras_set]

        if principales:
            label = "  Sabores (kg): "
            _wrap_lines(detalle, label + ", ".join(principales),
                        subsequent_indent=" " * len(label))
        if extras:
            label = "  1/4 de regalo: "
            _wrap_lines(detalle, label + ", ".join(extras),
                        subsequent_indent=" " * len(label))
        if not principales and not extras and todos:
            # Fallback
            label = "  Sabores: "
            _wrap_lines(detalle, label + ", ".join(todos),
                        subsequent_indent=" " * len(label))

    totales = ["-" * (width - 2)]
    if (pedido.costo_envio or Decimal('0')) > 0:
        totales.append(f"Envío:      {_format_money(pedido.costo_envio)}")
    totales.append(f"TOTAL:      {_format_money(_compute_total(pedido))}")
    totales.append("-" * (width - 2))
    totales.append("¡Gracias!".center(width))
    totales.append("\n\n")

    return "\n".join(header + [""] + cliente + envio + pago + detalle + totales)





def _send_ticket_webhook(text: str, title: str = "Pedido a cocina", copies: int = 1):
    url = getattr(settings, 'COMANDERA_WEBHOOK_URL', '') or ''
    if not url:
        return False
    headers = {'Content-Type': 'application/json'}
    token = getattr(settings, 'COMANDERA_TOKEN', '') or ''
    if token:
        headers['Authorization'] = f'Bearer {token}'
    payload = {"title": title, "text": text, "copies": int(copies or 1)}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=7)
        if r.status_code // 100 == 2:
            return True
        print(f"COMANDERA webhook status={r.status_code} body={r.text[:180]}")
    except Exception as e:
        print(f"COMANDERA webhook error: {e}")
    return False

def _send_ticket_printnode(text: str, title: str = "Pedido a cocina", copies: int = 1):
    api_key = getattr(settings, 'PRINTNODE_API_KEY', '') or ''
    printer_id = getattr(settings, 'PRINTNODE_PRINTER_ID', None)
    if not api_key or not printer_id:
        return False

    payload = _escpos_wrap_text(text, getattr(settings, 'COMANDERA_ENCODING', 'cp437'))

    body = {
        "printerId": int(printer_id),
        "title": title,
        "contentType": "raw_base64",
        "content": base64.b64encode(payload).decode("ascii"),
        "source": "yo-heladerias-web",
        "options": {"copies": int(copies or 1)},
    }
    try:
        r = requests.post(
            "https://api.printnode.com/printjobs",
            auth=(api_key, ""),
            json=body,
            timeout=10,
        )
        if r.status_code // 100 == 2:
            return True
        print(f"PRINTNODE error status={r.status_code} body={r.text[:180]}")
    except Exception as e:
        print(f"PRINTNODE exception: {e}")
    return False

def _normalize_for_encoding(s: str, encoding: str) -> bytes:
    try:
        return s.encode(encoding, errors='replace')
    except Exception:
        try:
            return s.encode('latin-1', errors='replace')
        except Exception:
            return s.encode('ascii', errors='replace')

def _escpos_wrap_text(text: str, encoding: str) -> bytes:
    """
    Bytes ESC/POS:
      - Init
      - Texto CRLF
      - Feed n líneas
      - 1 solo corte (configurable)
    Ajustes:
      COMANDERA_FEED_LINES (default: 6)
      COMANDERA_CUT_MODE: 'auto' | 'gs_v' | 'esc_i' | 'esc_m'
    """
    ESC = b'\x1b'
    GS  = b'\x1d'

    try:
        feed_lines = int(getattr(settings, 'COMANDERA_FEED_LINES', 6) or 6)
    except Exception:
        feed_lines = 6
    cut_mode = str(getattr(settings, 'COMANDERA_CUT_MODE', 'auto') or 'auto').lower()

    text_crlf = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")

    data = bytearray()
    data += ESC + b'@'  # init
    data += _normalize_for_encoding(text_crlf, encoding)

    # Alimentación: ESC d n
    n = max(0, min(255, feed_lines))
    data += ESC + b'd' + bytes([n])

    # Corte: SOLO UNA VEZ
    if cut_mode in ('auto', 'gs_v'):
        data += GS + b'V' + b'\x00'   # full cut
    elif cut_mode == 'esc_i':
        data += b'\x1b' + b'i'
    elif cut_mode == 'esc_m':
        data += b'\x1b' + b'm'

    return bytes(data)

def _send_ticket_tcp_escpos(text: str, title: str = "Pedido a cocina", copies: int = 1) -> bool:
    host = getattr(settings, 'COMANDERA_PRINTER_HOST', '') or ''
    port = int(getattr(settings, 'COMANDERA_PRINTER_PORT', 9100) or 9100)
    if not host:
        return False

    encoding = getattr(settings, 'COMANDERA_ENCODING', 'cp437')

    try:
        payload = _escpos_wrap_text(text, encoding)
        for _ in range(int(copies or 1)):
            with socket.create_connection((host, port), timeout=6) as s:
                s.sendall(payload)
        return True
    except Exception as e:
        print(f"ESC/POS TCP error ({host}:{port}): {e}")
        return False

def _print_ticket_for_pedido(pedido):
    try:
        copies = int(getattr(settings, 'COMANDERA_COPIES', 1) or 1)
    except Exception:
        copies = 1
    text = _build_ticket_text(pedido)

    if _send_ticket_tcp_escpos(text, title=f"Pedido #{pedido.id}", copies=copies):
        print(f"COMANDERA: ticket #{pedido.id} enviado por TCP/RAW.")
        return
    if _send_ticket_webhook(text, title=f"Pedido #{pedido.id}", copies=copies):
        print(f"COMANDERA: ticket #{pedido.id} enviado por webhook.")
        return
    if _send_ticket_printnode(text, title=f"Pedido #{pedido.id}", copies=copies):
        print(f"COMANDERA: ticket #{pedido.id} enviado por PrintNode.")
        return
    print("COMANDERA: no hay impresora configurada o envío falló.")

# === Ticket HTML 80mm / QZ ===
def _build_ticket_payload(pedido):
    items = []
    for d in pedido.detalles.all():
        precio_unit = d.producto.precio
        if d.opcion_seleccionada:
            precio_unit += d.opcion_seleccionada.precio_adicional
        subtotal = (precio_unit * d.cantidad).quantize(Decimal('0.01'))
        items.append({
            "cantidad": int(d.cantidad),
            "descripcion": f"{d.producto.nombre}" + (f" - {d.opcion_seleccionada.nombre_opcion}" if d.opcion_seleccionada else ""),
            "sabores": [s.nombre for s in d.sabores.all()],
            "subtotal": float(subtotal),
        })

    payload = {
        "site": getattr(settings, "SITE_NAME", "YO HELADERÍAS"),
        "pedido_id": pedido.id,
        "fecha": timezone.localtime(getattr(pedido, 'fecha_pedido', None) or timezone.now()).strftime("%d/%m %H:%M"),
        "cliente": pedido.cliente_nombre or "",
        "direccion": _direccion_legible_from_text(pedido.cliente_direccion) or "",
        "telefono": pedido.cliente_telefono or "",
        "metodo_pago": (pedido.metodo_pago or "").upper(),
        "total": float(_compute_total(pedido)),
        "items": items,
        "copies": int(getattr(settings, "COMANDERA_COPIES", 1)),
    }
    return payload

@staff_member_required
def ticket_pedido(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    payload = _build_ticket_payload(pedido)

    class _L:
        def __init__(self, it):
            self.cantidad = it["cantidad"]
            self.descripcion = it["descripcion"]
            self.sabores = ", ".join(it["sabores"]) if it["sabores"] else ""
            self.subtotal = f"{Decimal(str(it['subtotal'])).quantize(Decimal('0.01'))}"

    lineas = [_L(it) for it in payload["items"]]

    ctx = {
        "site": payload["site"],
        "pedido": pedido,
        "ticket": payload,
        "lineas": lineas,
        "total": f"{Decimal(str(payload['total'])).quantize(Decimal('0.01'))}",
        "auto": (request.GET.get("auto") == "1"),
        "use_qz": (request.GET.get("qz") == "1"),
    }
    return render(request, "pedidos/ticket_pedido.html", ctx)
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect

def _abort_if_store_closed(request):
    """
    Si la tienda está cerrada:
      - En peticiones AJAX devuelve 403 JSON
      - En peticiones normales manda un mensaje y redirige al carrito
    """
    try:
        abierta = _get_tienda_abierta()
    except Exception:
        abierta = True  # si algo falla, no bloqueamos

    if abierta:
        return None

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': False, 'error': 'tienda_cerrada'}, status=403)

    messages.error(
        request,
        "En este momento no estamos tomando pedidos online. Probá dentro del horario de atención."
    )
    return redirect('ver_carrito')

# --- Safe helpers para estado de tienda (por si faltan las funciones originales)
def _safe_get_tienda_abierta():
    default_val = bool(getattr(settings, 'TIENDA_ABIERTA_DEFAULT', True))
    try:
        from .models import GlobalSetting
        try:
            return bool(GlobalSetting.get_bool('TIENDA_ABIERTA', default=default_val))
        except Exception:
            pass
    except Exception:
        pass
    try:
        from .models import StoreStatus
        ss = StoreStatus.get()
        return bool(ss.is_open)
    except Exception:
        pass
    return default_val

def _safe_set_tienda_abierta(value: bool) -> bool:
    val = bool(value)
    try:
        from .models import GlobalSetting
        GlobalSetting.set_bool('TIENDA_ABIERTA', val)
        return val
    except Exception:
        pass
    try:
        from .models import StoreStatus
        ss = StoreStatus.get()
        if ss.is_open != val:
            ss.is_open = val
            ss.save(update_fields=['is_open'])
        return val
    except Exception:
        pass
    return val

# Aliases de compatibilidad: si faltan las originales, usar las "safe"
try:
    _get_tienda_abierta
except NameError:
    _get_tienda_abierta = _safe_get_tienda_abierta
try:
    _set_tienda_abierta
except NameError:
    _set_tienda_abierta = _safe_set_tienda_abierta

# =========================
# === TIENDA (toggle)

# =========================
@require_GET
def tienda_estado_json(request):
    return JsonResponse({'abierta': _get_tienda_abierta()})

@require_GET
def tienda_estado(request):
    return tienda_estado_json(request)

@staff_member_required
@require_POST
def tienda_set_estado(request):
    raw = (request.POST.get('abierta') or '').strip().lower()
    val = True if raw in ('1', 'true', 't', 'yes', 'y', 'si', 'sí') else False
    abierta = _set_tienda_abierta(val)
    _broadcast_tienda_estado(abierta)
    return JsonResponse({'ok': True, 'abierta': abierta})

@staff_member_required
@require_POST
def tienda_toggle(request):
    nueva = not _get_tienda_abierta()
    abierta = _set_tienda_abierta(nueva)
    _broadcast_tienda_estado(abierta)
    return JsonResponse({'ok': True, 'abierta': abierta})

def _marcar_estado(pedido, nuevo_estado: str, actor=None, fuente: str = '', meta: dict | None = None):
    """
    Actualiza el estado del pedido, setea timestamps conocidos y registra un log si existe PedidoEstadoLog.
    """
    anterior = getattr(pedido, 'estado', None)
    pedido.estado = nuevo_estado
    ahora = timezone.now()

    # setear timestamps si existen en el modelo
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
        try:
            pedido.save(update_fields=['estado'])
        except Exception:
            pedido.save()

    # log de estado (si el modelo está)
    try:
        from .models import PedidoEstadoLog
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
    except Exception:
        pass

    return pedido

# =========================
# === TIENDA / CADETES
# =========================
@login_required
@require_http_methods(["POST", "GET"])  # aceptar por POST o por GET (evita "se rompe" si tocan un link)
def aceptar_pedido(request, pedido_id):
    if not hasattr(request.user, 'cadeteprofile'):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': 'no_cadete'}, status=403)
        messages.error(request, "Acción no permitida. No tienes un perfil de cadete.")
        return redirect('index')

    # Si ya tiene otro activo (que NO sea éste) → bloquea
    if Pedido.objects.filter(
        cadete_asignado=request.user.cadeteprofile,
        estado__in=['ASIGNADO', 'EN_CAMINO']
    ).exclude(id=pedido_id).exists():
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': 'ya_tiene_activo'}, status=400)
        messages.warning(request, "Ya tenés un pedido en curso. Entregalo antes de aceptar otro.")
        return redirect('panel_cadete')

    with transaction.atomic():
        try:
            pedido = Pedido.objects.select_for_update().get(id=pedido_id)
        except Pedido.DoesNotExist:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'ok': False, 'error': 'no_disponible'}, status=404)
            messages.warning(request, f"El Pedido #{pedido_id} no existe o ya no está disponible.")
            return redirect('panel_cadete')

        # Releer por si hubo cambios en paralelo
        try:
            pedido.refresh_from_db(fields=['estado', 'cadete_asignado'])
        except Exception:
            pass

        # Finales o en camino → no disponible
        if pedido.estado in ('ENTREGADO', 'CANCELADO', 'EN_CAMINO'):
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'ok': False, 'error': 'no_disponible'}, status=409)
            messages.warning(request, f"El Pedido #{pedido.id} ya no está disponible para ser aceptado.")
            return redirect('panel_cadete')

        # Si está ASIGNADO a otro cadete → bloquear SIEMPRE
        if pedido.cadete_asignado_id and pedido.cadete_asignado_id != request.user.cadeteprofile.id:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'ok': False, 'error': 'asignado_a_otro'}, status=409)
            messages.warning(request, f"El Pedido #{pedido.id} fue asignado a otro cadete.")
            return redirect('panel_cadete')

        # Si está asignado a mí y aún no pasó a ASIGNADO → llevar a ASIGNADO
        if pedido.cadete_asignado_id == request.user.cadeteprofile.id:
            if pedido.estado == 'EN_PREPARACION':
                _marcar_estado(pedido, 'ASIGNADO', actor=request.user, fuente='aceptar_pedido')
        else:
            # No estaba asignado → me asigno y paso a ASIGNADO
            pedido.cadete_asignado = request.user.cadeteprofile
            try:
                pedido.save(update_fields=['cadete_asignado'])
            except Exception:
                pedido.save()
            _marcar_estado(pedido, 'ASIGNADO', actor=request.user, fuente='aceptar_pedido')

    # me pongo NO disponible (igual que antes)
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
        try:
            logs_qs = p.logs_estado.select_related('actor').order_by('-created_at')[:8]
        except Exception:
            logs_qs = []
        setattr(p, 'logs', logs_qs)

    contexto = {'vapid_public_key': vapid_public_key, 'pedidos_en_curso': pedidos_en_curso}
    return render(request, 'pedidos/panel_cadete.html', contexto)

@login_required
def cadete_historial(request):
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
    if not hasattr(request.user, 'cadeteprofile'):
        return JsonResponse({'ok': False, 'error': 'no_cadete'}, status=403)

    raw = (request.POST.get('disponible') or '').strip().lower()
    val = raw in ('1', 'true', 't', 'si', 'sí', 'yes', 'y')

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
    if not hasattr(request.user, 'cadeteprofile'):
        return JsonResponse({'status': 'error', 'message': 'User is not a cadete'}, status=403)

    try:
        data = json.loads(request.body)
        updated_count = CadeteProfile.objects.filter(user=request.user).update(subscription_info=data)
        if updated_count > 0:
            return JsonResponse({'status': 'ok', 'message': 'Subscription saved'})
        else:
            return JsonResponse({'status': 'error', 'message': 'Cadete profile not found for update'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
def cadete_feed(request):
    """
    Feed para la app de cadetes:
      - Si el cadete está ocupado: no listamos nada.
      - Si está disponible: listamos pedidos EN_PREPARACION
        * no asignados (los ven todos)
        * asignados a mí (sólo yo los veo)
      - No listamos pedidos de 'Retiro en local'.
    """
    if not hasattr(request.user, 'cadeteprofile'):
        return JsonResponse({'ok': False, 'error': 'no_cadete'}, status=403)

    cadete = request.user.cadeteprofile

    # Ocupado → no hay feed (ya tiene uno en curso)
    if Pedido.objects.filter(
        cadete_asignado=cadete,
        estado__in=['ASIGNADO', 'EN_CAMINO']
    ).exists():
        return JsonResponse({'ok': True, 'disponible': False, 'pedidos': []})

    # Chequeo de disponible (modelo o sesión)
    disponible = None
    if hasattr(cadete, 'disponible'):
        try:
            disponible = bool(cadete.disponible)
        except Exception:
            disponible = None
    if disponible is None:
        disponible = bool(request.session.get('cadete_disponible', False))

    if not disponible:
        return JsonResponse({'ok': True, 'disponible': False, 'pedidos': []})

    qs = (Pedido.objects
          .filter(estado='EN_PREPARACION')
          .filter(Q(cadete_asignado__isnull=True) | Q(cadete_asignado=cadete))
          .order_by('-fecha_pedido')[:50])

    data = []
    for p in qs:
        if _pedido_es_pickup(p):  # ocultar retiros en local del feed
            continue
        data.append({
            'id': p.id,
            'cliente_nombre': p.cliente_nombre or '',
            'cliente_telefono': p.cliente_telefono or '',
            'direccion_legible': _direccion_legible_from_text(p.cliente_direccion) or '',
            'total': float(_compute_total(p)),
            'map_url': _map_url_from_text(p.cliente_direccion),
            'detalles': [
                {
                    'producto': d.producto.nombre,
                    'opcion': d.opcion_seleccionada.nombre_opcion if d.opcion_seleccionada else '',
                    'cant': d.cantidad,
                    'sabores': [s.nombre for s in d.sabores.all()]
                }
                for d in p.detalles.all()
            ]
        })

    return JsonResponse({'ok': True, 'disponible': True, 'pedidos': data})

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
        'amount': resp.get('amount') or (float(refund_amount) if refund_amount is not None else None),
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
            else:
                _marcar_estado(pedido, 'PENDIENTE_PAGO', actor=None, fuente='webhook_mp', meta={'payment_id': payment_id})
    except Exception as e:
        print(f"WEBHOOK MP: error guardando pedido/estado: {e}")

    try:
        _notify_panel_update(pedido, message='nuevo_pedido' if status == 'approved' else 'actualizacion_pedido')
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
            payment = _mp_find_latest_approved_payment(str(last_id))
            if payment:
                if pedido.estado != 'RECIBIDO':
                    _marcar_estado(pedido, 'RECIBIDO', actor=None, fuente='mp_success_fallback', meta={'payment_id': payment.get('id')})
                _notify_panel_update(pedido, message='nuevo_pedido')
        except Exception as e:
            print(f"MP SUCCESS: error en verificación/WS fallback: {e}")
    messages.info(request, "Gracias. Estamos confirmando tu pago. Si ya fue aprobado, tu pedido entrará a cocina.")
    return redirect('pedido_exitoso')

mp_webhook = mp_webhook_view

# =========================
# === CANJE DE PUNTOS
# =========================
@login_required
def canjear_puntos(request):
    cliente_profile = request.user.clienteprofile
    productos_canje = ProductoCanje.objects.filter(disponible=True).order_by('puntos_requeridos')

    if request.method == 'POST':
        resp = _abort_if_store_closed(request)
        if resp:
            return resp

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
# === Service Worker
# =========================
@require_GET
def service_worker(request):
    resp = render(request, 'pedidos/sw.js', {})
    resp["Content-Type"] = "application/javascript"
    return resp

# === Confirmar pedido (llevar a EN_PREPARACION + notificar/impresión) ===
@staff_member_required
@require_http_methods(["GET", "POST"])
def confirmar_pedido(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    estado_anterior = pedido.estado

    if estado_anterior in ('ENTREGADO', 'CANCELADO'):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': 'estado_final'}, status=400)
        messages.warning(request, f"El pedido #{pedido.id} está '{estado_anterior}' y no puede confirmarse.")
        return redirect('panel_alertas')

    cambiado = False
    if estado_anterior != 'EN_PREPARACION':
        _marcar_estado(pedido, 'EN_PREPARACION', actor=request.user, fuente='confirmar_pedido')
        cambiado = True

        # Releer por seguridad (evita cache de instancia sin la asignación reciente)
        try:
            pedido.refresh_from_db(fields=['cadete_asignado'])
        except Exception:
            pass

        # Notificar: si hay cadete asignado => SOLO a ese, si no => a todos
        try:
            if getattr(pedido, 'cadete_asignado_id', None):
                # notificación dirigida
                _notify_cadetes_new_order(request, pedido)  # ya maneja el "dirigido"
            else:
                _notify_cadetes_new_order(request, pedido)  # broadcast
        except Exception as e:
            print(f"WEBPUSH notify cadetes error: {e}")

    # WS panel + impresión
    try:
        _notify_panel_update(pedido, message='actualizacion_pedido')
    except Exception:
        pass
    try:
        _print_ticket_for_pedido(pedido)
    except Exception:
        pass

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'pedido_id': pedido.id, 'estado': pedido.estado, 'cambiado': cambiado})

    if cambiado:
        messages.success(request, f"Pedido #{pedido.id} confirmado y enviado a cocina.")
    else:
        messages.info(request, f"Pedido #{pedido.id} ya estaba en preparación. Ticket enviado nuevamente.")
    return redirect('panel_alertas')

# =========================
# === Panel: Cadetes (asignar manual - opcional)
# =========================
@staff_member_required
@require_http_methods(["POST"])
def panel_asignar_cadete(request, pedido_id):
    """
    Asigna un cadete o vuelve a 'a todos' (cadete_id=0).
    NO cambia el estado del pedido (se mantiene EN_PREPARACION).
    Además, si asigna, envía push SOLO al asignado.
    """
    CadeteProfileModel = apps.get_model('pedidos', 'CadeteProfile')
    PedidoModel = apps.get_model('pedidos', 'Pedido')

    pedido = get_object_or_404(PedidoModel, id=pedido_id)
    cadete_id = (request.POST.get('cadete_id') or '0').strip()

    # Desasignar → modo a todos
    if cadete_id in ('0', ''):
        pedido.cadete_asignado = None
        if hasattr(pedido, 'fecha_asignado'):
            pedido.fecha_asignado = None
            pedido.save(update_fields=['cadete_asignado', 'fecha_asignado'])
        else:
            pedido.save(update_fields=['cadete_asignado'])
        _notify_panel_update(pedido)
        return JsonResponse({'ok': True, 'estado': pedido.estado, 'cadete': None})

    # Asignar a un cadete específico
    cadete = get_object_or_404(CadeteProfileModel, id=cadete_id)

    # Evitar asignar a un cadete que ya está con un pedido activo
    ocupado = PedidoModel.objects.filter(
        cadete_asignado=cadete,
        estado__in=['ASIGNADO', 'EN_CAMINO']
    ).exclude(pk=pedido.pk).exists()
    if ocupado:
        return JsonResponse({'ok': False, 'error': 'ocupado'}, status=400)

    pedido.cadete_asignado = cadete
    if hasattr(pedido, 'fecha_asignado') and not pedido.fecha_asignado:
        pedido.fecha_asignado = timezone.now()
        pedido.save(update_fields=['cadete_asignado', 'fecha_asignado'])
    else:
        pedido.save(update_fields=['cadete_asignado'])

    cadete_name = cadete.user.get_full_name() or cadete.user.username
    _notify_panel_update(pedido)
    try:
        _notify_cadetes_new_order(request, pedido)
    except Exception as e:
        print(f"WEBPUSH panel_asignar_cadete error: {e}")
    return JsonResponse({'ok': True, 'estado': pedido.estado, 'cadete': cadete_name})
@staff_member_required
@require_GET
def comandera_test(request):
    """
    Diagnóstico de impresión:
      - Manda un ticket de prueba ("TEST COMANDERA") por TCP, Webhook y PrintNode.
      - Si viene ?pedido=<id> intenta imprimir ese pedido real con _print_ticket_for_pedido.
    Devuelve JSON con resultados de cada camino.
    """
    results = {}
    # 1) ticket simple de prueba (texto)
    test_text = "=== TEST COMANDERA ===\n" \
                "Hola! Esto es una prueba.\n" \
                "Fecha: %s\n" \
                "=======================\n" % timezone.localtime().strftime("%d/%m/%Y %H:%M")

    # 1.a) TCP/RAW
    try:
        ok_tcp = _send_ticket_tcp_escpos(test_text, title="TEST", copies=1)
        results['tcp_raw'] = 'ok' if ok_tcp else 'fail'
    except Exception as e:
        results['tcp_raw'] = f'error: {e!s}'

    # 1.b) Webhook
    try:
        ok_wh = _send_ticket_webhook(test_text, title="TEST", copies=1)
        results['webhook'] = 'ok' if ok_wh else 'fail'
    except Exception as e:
        results['webhook'] = f'error: {e!s}'

    # 1.c) PrintNode
    try:
        ok_pn = _send_ticket_printnode(test_text, title="TEST", copies=1)
        results['printnode'] = 'ok' if ok_pn else 'fail'
    except Exception as e:
        results['printnode'] = f'error: {e!s}'

    # 2) Si piden ?pedido=ID, imprimimos el ticket real
    pedido_id = request.GET.get('pedido')
    if pedido_id:
        try:
            pedido = Pedido.objects.get(id=pedido_id)
            _print_ticket_for_pedido(pedido)
            results['pedido'] = f'PRINT pedido #{pedido_id} enviado (ver logs COMANDERA para ruta usada)'
        except Pedido.DoesNotExist:
            results['pedido'] = f'no existe #{pedido_id}'
        except Exception as e:
            results['pedido'] = f'error: {e!s}'

    # Info de settings útil para chequear config actual
    results['config'] = {
        'COMANDERA_PRINTER_HOST': getattr(settings, 'COMANDERA_PRINTER_HOST', ''),
        'COMANDERA_PRINTER_PORT': getattr(settings, 'COMANDERA_PRINTER_PORT', 9100),
        'COMANDERA_WEBHOOK_URL': getattr(settings, 'COMANDERA_WEBHOOK_URL', ''),
        'PRINTNODE_PRINTER_ID': getattr(settings, 'PRINTNODE_PRINTER_ID', None),
        'COMANDERA_CUT_MODE': getattr(settings, 'COMANDERA_CUT_MODE', 'auto'),
        'COMANDERA_ENCODING': getattr(settings, 'COMANDERA_ENCODING', 'cp437'),
        'COMANDERA_COPIES': getattr(settings, 'COMANDERA_COPIES', 1),
    }
    return JsonResponse({'ok': True, 'diagnostico': results})
from django.views.decorators.http import require_POST

@staff_member_required
@require_POST
def reimprimir_ticket(request, pedido_id: int):
    """
    Reimprime el ticket de un pedido específico.
    Intenta TCP → Webhook → PrintNode (mismo orden que _print_ticket_for_pedido).
    Responde JSON.
    """
    pedido = get_object_or_404(Pedido, pk=pedido_id)

    # copias opcionales (si no mandan, cae al valor de settings en cada sender)
    try:
        copies = int(request.POST.get("copies", "").strip() or "0")
    except Exception:
        copies = 0
    if copies < 1:
        try:
            copies = int(getattr(settings, 'COMANDERA_COPIES', 1) or 1)
        except Exception:
            copies = 1

    text = _build_ticket_text(pedido)

    # Enviamos en el mismo orden que usa _print_ticket_for_pedido
    if _send_ticket_tcp_escpos(text, title=f"Reimpresión #{pedido.id}", copies=copies):
        return JsonResponse({"ok": True, "msg": "Enviado por TCP/RAW"})
    if _send_ticket_webhook(text, title=f"Reimpresión #{pedido.id}", copies=copies):
        return JsonResponse({"ok": True, "msg": "Enviado por Webhook"})
    if _send_ticket_printnode(text, title=f"Reimpresión #{pedido.id}", copies=copies):
        return JsonResponse({"ok": True, "msg": "Enviado por PrintNode"})

    return JsonResponse(
        {"ok": False, "error": "No hay ruta de impresión disponible o falló el envío"},
        status=500
    )
@login_required
def transferencia_instrucciones(request):
    last_id = request.session.get('transfer_last_order_id')
    if not last_id:
        return redirect('index')

    try:
        pedido = Pedido.objects.get(id=last_id, user=request.user)
    except Pedido.DoesNotExist:
        return redirect('index')

    ctx = {
        'pedido': pedido,
        'alias': getattr(settings, 'TRANSFERENCIA_ALIAS', ''),
        'titular': getattr(settings, 'TRANSFERENCIA_TITULAR', ''),
        'cuit': getattr(settings, 'TRANSFERENCIA_CUIT', ''),
        'monto': _compute_total(pedido),
    }
    return render(request, 'pedidos/transferencia_instrucciones.html', ctx)

@login_required
@require_POST
def transferencia_avise(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id, user=request.user)

    # (Opcional) marcar que el cliente reportó transferencia
    try:
        if hasattr(pedido, 'cliente_reporto_transferencia'):
            if not pedido.cliente_reporto_transferencia:
                pedido.cliente_reporto_transferencia = True
                pedido.save(update_fields=['cliente_reporto_transferencia'])
    except Exception:
        pass

    try:
        _notify_panel_update(pedido, message='actualizacion_pedido')
    except Exception:
        pass

    messages.info(request, "¡Gracias! Vamos a verificar tu transferencia y confirmar tu pedido.")
    return redirect('pedido_exitoso')

@staff_member_required
@require_POST
def panel_marcar_pago_transferencia(request, pedido_id: int):
    """
    Marca un pedido con método TRANSFERENCIA como 'RECIBIDO'.
    No lo pasa a EN_PREPARACION: eso lo sigue haciendo el botón Confirmar.
    """
    from .models import Pedido  # evita import circular
    try:
        pedido = Pedido.objects.get(id=pedido_id)
    except Pedido.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'no_existe'}, status=404)

    # Solo tiene sentido para transferencia
    metodo = (pedido.metodo_pago or '').upper()
    if metodo != 'TRANSFERENCIA':
        return JsonResponse({'ok': False, 'error': 'no_transferencia'}, status=400)

    # Si ya está recibido o más adelante, no hacemos nada
    if pedido.estado in ('RECIBIDO', 'EN_PREPARACION', 'ASIGNADO', 'EN_CAMINO', 'ENTREGADO'):
        return JsonResponse({'ok': True, 'estado': pedido.estado})

    # Caso típico: estaba 'PENDIENTE_PAGO' -> 'RECIBIDO'
    _marcar_estado(pedido, 'RECIBIDO', actor=request.user, fuente='panel_marcar_pago_transferencia')

    try:
        _notify_panel_update(pedido, message='actualizacion_pedido')
    except Exception:
        pass

    return JsonResponse({'ok': True, 'estado': pedido.estado, 'pedido_id': pedido.id})