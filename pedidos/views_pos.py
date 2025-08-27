# pedidos/views_pos.py
from decimal import Decimal
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponseForbidden, JsonResponse, HttpResponseRedirect
from django.db.models import Sum
from django.urls import reverse
import json
import logging

from .models import Caja, ProductoPOS, VentaPOS, VentaPOSItem, MovimientoCaja

logger = logging.getLogger(__name__)

# ---- Helpers de permisos
def es_staff(user):
    return user.is_authenticated and user.is_staff

def es_manager(user):
    # Superusuarios o quienes estén en el grupo "Gerencia"
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name='Gerencia').exists()

def _caja_abierta():
    # Toma la última caja en estado ABIERTA
    return Caja.objects.filter(estado='ABIERTA').order_by('-id').first()

# =======================
# Panel POS
# =======================
@user_passes_test(es_staff)
@login_required
def pos_panel(request):
    caja = _caja_abierta()
    productos = ProductoPOS.objects.filter(activo=True).order_by('nombre')
    ventas = []
    totales_medio = {}
    totales_tipo = {}
    teorico = None

    if caja:
        # SOLO ventas de la caja abierta
        ventas = VentaPOS.objects.filter(caja=caja).order_by('-id')[:15]
        totales_medio = caja.total_ventas_por_medio() or {}
        totales_tipo = caja.total_por_tipo_mov() or {}
        teorico = caja.saldo_efectivo_teorico()

    return render(request, 'pedidos/pos_panel.html', {
        'caja': caja,
        'productos': productos,
        'ventas': ventas,
        'totales_medio': totales_medio,
        'totales_tipo': totales_tipo,
        'saldo_teorico': teorico,
    })

# =======================
# Abrir caja
# =======================
@user_passes_test(es_staff)
@login_required
@transaction.atomic
def pos_abrir_caja(request):
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido')
    if _caja_abierta():
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': 'Ya hay una caja ABIERTA.'}, status=400)
        messages.warning(request, 'Ya hay una caja ABIERTA.')
        return redirect('pos_panel')

    try:
        inicial = Decimal(request.POST.get('saldo_inicial_efectivo', '0') or '0')
    except Exception:
        inicial = Decimal('0')

    Caja.objects.create(
        usuario_apertura=request.user,
        saldo_inicial_efectivo=inicial,
        estado='ABIERTA',
    )

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True})
    messages.success(request, 'Caja ABIERTA correctamente.')
    return redirect('pos_panel')

# =======================
# Vender (multi items + multi medio)
# =======================
@user_passes_test(es_staff)
@login_required
@transaction.atomic
def pos_vender(request):
    # El front usa fetch + AJAX
    if request.method != 'POST' or request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return JsonResponse({'ok': False, 'error': 'Solicitud inválida'}, status=400)

    caja = _caja_abierta()
    if not caja:
        return JsonResponse({'ok': False, 'error': 'No hay caja abierta.'}, status=400)

    # Ítems enviados como campos repetidos: item_producto / item_cantidad
    prod_ids = request.POST.getlist('item_producto')
    cantidades = request.POST.getlist('item_cantidad')
    if not prod_ids:
        return JsonResponse({'ok': False, 'error': 'Sin ítems.'}, status=400)

    # Armar ítems y calcular total
    items = []
    total = Decimal('0')
    try:
        for pid, cant in zip(prod_ids, cantidades):
            prod = ProductoPOS.objects.get(pk=int(pid))
            q = Decimal(str(cant or '1'))
            precio = prod.precio or Decimal('0')
            subtotal = precio * q
            items.append((prod, q, precio, subtotal))
            total += subtotal
    except ProductoPOS.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Producto inexistente.'}, status=400)
    except Exception:
        logger.exception('Error procesando ítems')
        return JsonResponse({'ok': False, 'error': 'Ítems inválidos.'}, status=400)

    tipo_comp   = request.POST.get('tipo_comprobante', 'COMANDA')
    medio_unico = request.POST.get('medio_pago')  # usado si NO hay pagos_json
    pagos_json  = request.POST.get('pagos_json')  # string JSON opcional

    # Si vienen pagos parciales, validamos su suma
    pagos = None
    if pagos_json:
        try:
            pagos = json.loads(pagos_json) or []
            suma = sum(Decimal(str(p.get('monto', 0) or '0')) for p in pagos)
            if abs(suma - total) > Decimal('0.01'):
                return JsonResponse({'ok': False, 'error': 'La suma de pagos no coincide con el total.'}, status=400)
        except Exception:
            return JsonResponse({'ok': False, 'error': 'Formato de pagos inválido.'}, status=400)

    # Crear Venta + Items + Movimientos
    try:
        venta = VentaPOS.objects.create(
            usuario=request.user,
            caja=caja,
            tipo_comprobante=tipo_comp,
            medio_pago=('MIXTO' if pagos else (medio_unico or 'EFECTIVO')),
            total=total,
            estado='COMPLETADA',
        )

        # Detalles
        for prod, q, precio, subtotal in items:
            VentaPOSItem.objects.create(
                venta=venta,
                producto=prod,
                descripcion=prod.nombre,
                cantidad=q,
                precio_unitario=precio,
                subtotal=subtotal,
            )

        # Movimientos de caja: usamos tipo='VENTA' (KPI "VENTAS (hoy)")
        if pagos:
            for p in pagos:
                monto = Decimal(str(p.get('monto', 0) or '0'))
                medio = p.get('medio') or 'EFECTIVO'
                if monto > 0:
                    MovimientoCaja.objects.create(
                        caja=caja,
                        tipo='VENTA',
                        medio_pago=medio,
                        monto=monto,
                        descripcion=f'VentaPOS #{venta.id}',
                        venta=venta,
                        usuario=request.user
                    )
        else:
            MovimientoCaja.objects.create(
                caja=caja,
                tipo='VENTA',
                medio_pago=medio_unico or 'EFECTIVO',
                monto=total,
                descripcion=f'VentaPOS #{venta.id}',
                venta=venta,
                usuario=request.user
            )

        return JsonResponse({'ok': True, 'venta_id': venta.id})

    except Exception:
        logger.exception('Error en pos_vender')
        return JsonResponse({'ok': False, 'error': 'Error registrando la venta.'}, status=500)

# =======================
# Movimiento manual
# =======================
@user_passes_test(es_staff)
@login_required
@transaction.atomic
def pos_movimiento(request):
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido')

    caja = _caja_abierta()
    if not caja:
        return JsonResponse({'ok': False, 'error': 'Abrí una caja antes de registrar movimientos.'}, status=400)

    tipo = request.POST.get('tipo')  # INGRESO / EGRESO / AJUSTE / RETIRO
    medio = request.POST.get('medio_pago') or 'EFECTIVO'
    try:
        monto = Decimal(request.POST.get('monto', '0') or '0')
    except Exception:
        monto = Decimal('0')
    desc = (request.POST.get('descripcion') or '').strip()

    if tipo not in ['INGRESO', 'EGRESO', 'AJUSTE', 'RETIRO']:
        return JsonResponse({'ok': False, 'error': 'Tipo inválido.'}, status=400)
    if monto <= 0:
        return JsonResponse({'ok': False, 'error': 'El monto debe ser mayor a 0.'}, status=400)

    MovimientoCaja.objects.create(
        caja=caja,
        tipo=tipo,
        medio_pago=medio,
        monto=monto,
        descripcion=desc,
        usuario=request.user
    )
    return JsonResponse({'ok': True})

# =======================
# Cerrar caja  ->  Ticket
# =======================
@user_passes_test(es_staff)
@login_required
@transaction.atomic
def pos_cerrar_caja(request):
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido')
    caja = _caja_abierta()
    if not caja:
        messages.warning(request, 'No hay caja ABIERTA.')
        return redirect('pos_panel')

    try:
        contado = Decimal(request.POST.get('saldo_cierre_efectivo', '0') or '0')
    except Exception:
        contado = Decimal('0')

    caja.estado = 'CERRADA'
    caja.usuario_cierre = request.user
    caja.fecha_cierre = timezone.now()
    caja.saldo_cierre_efectivo = contado
    caja.save(update_fields=['estado','usuario_cierre','fecha_cierre','saldo_cierre_efectivo'])

    # Al cerrar, llevamos directo al ticket para imprimir
    return HttpResponseRedirect(reverse('pos_ticket_cierre', args=[caja.id]))

# =======================
# Ticket de cierre (imprimible 80mm)
# =======================
@user_passes_test(es_staff)
@login_required
def pos_ticket_cierre(request, caja_id):
    caja = get_object_or_404(Caja, pk=caja_id)

    totales_medio = caja.total_ventas_por_medio() or {}
    totales_tipo  = caja.total_por_tipo_mov() or {}
    teorico = caja.saldo_efectivo_teorico()
    diff = caja.diferencia_efectivo()

    ventas_qs = VentaPOS.objects.filter(caja=caja, estado='COMPLETADA')
    ventas_count = ventas_qs.count()
    ventas_total = ventas_qs.aggregate(s=Sum('total'))['s'] or Decimal('0')

    return render(request, 'pedidos/pos_ticket_cierre.html', {
        'caja': caja,
        'totales_medio': totales_medio,
        'totales_tipo': totales_tipo,
        'saldo_teorico': teorico,
        'diferencia': diff,
        'ventas_count': ventas_count,
        'ventas_total': ventas_total,
    })

# =======================
# Panel de Cajas (Gerencia)
# =======================
@user_passes_test(es_manager)
@login_required
def pos_cajas(request):
    cajas = Caja.objects.order_by('-id')[:100]
    return render(request, 'pedidos/pos_cajas.html', {'cajas': cajas})

@user_passes_test(es_manager)
@login_required
def pos_caja_detalle(request, caja_id):
    caja = get_object_or_404(Caja, pk=caja_id)
    ventas = VentaPOS.objects.filter(caja=caja).order_by('fecha')
    movs   = MovimientoCaja.objects.filter(caja=caja).order_by('fecha')
    return render(request, 'pedidos/pos_caja_detalle.html', {
        'caja': caja,
        'ventas': ventas,
        'movimientos': movs,
        'totales_medio': caja.total_ventas_por_medio() or {},
        'totales_tipo': caja.total_por_tipo_mov() or {},
        'saldo_teorico': caja.saldo_efectivo_teorico(),
        'diferencia': caja.diferencia_efectivo(),
    })
