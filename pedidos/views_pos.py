# pedidos/views_pos.py
from decimal import Decimal
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponseForbidden, JsonResponse

from .models import Caja, ProductoPOS, VentaPOS, VentaPOSItem, MovimientoCaja

def es_staff(user):
    return user.is_authenticated and user.is_staff

def _caja_abierta():
    return Caja.objects.filter(estado='ABIERTA').order_by('-id').first()

def _is_ajax(request):
    # Django 5 ya no tiene request.is_ajax()
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'

@user_passes_test(es_staff)
@login_required
def pos_panel(request):
    caja = _caja_abierta()
    productos = ProductoPOS.objects.filter(activo=True).order_by('nombre')
    ventas = VentaPOS.objects.order_by('-id')[:15]

    totales_medio = caja.total_ventas_por_medio() if caja else {}
    totales_tipo = caja.total_por_tipo_mov() if caja else {}
    teorico = caja.saldo_efectivo_teorico() if caja else None

    return render(request, 'pedidos/pos_panel.html', {
        'caja': caja,
        'productos': productos,
        'ventas': ventas,
        'totales_medio': totales_medio,
        'totales_tipo': totales_tipo,
        'saldo_teorico': teorico,
    })

@user_passes_test(es_staff)
@login_required
@transaction.atomic
def pos_abrir_caja(request):
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido')
    if _caja_abierta():
        if _is_ajax(request):
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
    if _is_ajax(request):
        return JsonResponse({'ok': True})
    messages.success(request, 'Caja ABIERTA correctamente.')
    return redirect('pos_panel')

@user_passes_test(es_staff)
@login_required
@transaction.atomic
def pos_vender(request):
    """
    Vende múltiples ítems. Calcula totales explícitamente.
    Devuelve JSON si es AJAX; si no, hace redirect con messages.
    """
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido')
    caja = _caja_abierta()
    if not caja:
        msg = 'Abrí una caja antes de vender.'
        if _is_ajax(request):
            return JsonResponse({'ok': False, 'error': msg}, status=400)
        messages.error(request, msg)
        return redirect('pos_panel')

    medio_pago = request.POST.get('medio_pago') or 'EFECTIVO'
    tipo_comp = request.POST.get('tipo_comprobante') or 'COMANDA'

    ids = request.POST.getlist('item_producto')
    cants = request.POST.getlist('item_cantidad')

    lineas = []
    for pid, cnt in zip(ids, cants):
        pid = (pid or '').strip()
        cnt = (cnt or '').strip()
        if not pid:
            continue
        try:
            q = int(cnt) if cnt else 1
            if q < 1:
                q = 1
        except Exception:
            q = 1
        lineas.append((pid, q))

    if not lineas:
        msg = 'Elegí al menos un producto.'
        if _is_ajax(request):
            return JsonResponse({'ok': False, 'error': msg}, status=400)
        messages.error(request, msg)
        return redirect('pos_panel')

    venta = VentaPOS.objects.create(
        usuario=request.user,
        caja=caja,
        tipo_comprobante=tipo_comp,
        medio_pago=medio_pago,
        total=Decimal('0'),
        estado='COMPLETADA',
    )

    total_venta = Decimal('0')

    for pid, q in lineas:
        prod = get_object_or_404(ProductoPOS, pk=pid)
        precio = prod.precio or Decimal('0')
        desc = prod.nombre

        subtotal = (precio or Decimal('0')) * Decimal(q)
        total_venta += subtotal

        VentaPOSItem.objects.create(
            venta=venta,
            producto=prod,
            descripcion=desc,
            cantidad=q,
            precio_unitario=precio,
            subtotal=subtotal,
        )

    venta.total = total_venta
    venta.save(update_fields=['total'])

    # Movimiento de caja por la venta
    MovimientoCaja.objects.update_or_create(
        caja=caja,
        venta=venta,
        tipo='VENTA',
        defaults={
            'medio_pago': medio_pago,
            'monto': total_venta,
            'usuario': request.user,
            'descripcion': f'VentaPOS #{venta.id}',
        }
    )

    if _is_ajax(request):
        return JsonResponse({'ok': True, 'venta_id': venta.id, 'total': str(total_venta)})
    messages.success(request, f'Venta registrada (${total_venta}).')
    return redirect('pos_panel')

@user_passes_test(es_staff)
@login_required
@transaction.atomic
def pos_movimiento(request):
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido')
    caja = _caja_abierta()
    if not caja:
        msg = 'Abrí una caja antes de registrar movimientos.'
        if _is_ajax(request):
            return JsonResponse({'ok': False, 'error': msg}, status=400)
        messages.error(request, msg)
        return redirect('pos_panel')

    tipo = request.POST.get('tipo')  # INGRESO / EGRESO / AJUSTE / RETIRO
    medio = request.POST.get('medio_pago') or 'EFECTIVO'
    try:
        monto = Decimal(request.POST.get('monto', '0') or '0')
    except Exception:
        monto = Decimal('0')
    desc = (request.POST.get('descripcion') or '').strip()

    if tipo not in ['INGRESO', 'EGRESO', 'AJUSTE', 'RETIRO']:
        msg = 'Tipo de movimiento inválido.'
        if _is_ajax(request):
            return JsonResponse({'ok': False, 'error': msg}, status=400)
        messages.error(request, msg)
        return redirect('pos_panel')
    if monto <= 0:
        msg = 'El monto debe ser mayor a 0.'
        if _is_ajax(request):
            return JsonResponse({'ok': False, 'error': msg}, status=400)
        messages.error(request, msg)
        return redirect('pos_panel')

    MovimientoCaja.objects.create(
        caja=caja,
        tipo=tipo,
        medio_pago=medio,
        monto=monto,
        descripcion=desc,
        usuario=request.user
    )

    if _is_ajax(request):
        return JsonResponse({'ok': True})
    messages.success(request, f'Movimiento {tipo} registrado por ${monto}.')
    return redirect('pos_panel')

@user_passes_test(es_staff)
@login_required
@transaction.atomic
def pos_cerrar_caja(request):
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido')
    caja = _caja_abierta()
    if not caja:
        if _is_ajax(request):
            return JsonResponse({'ok': False, 'error': 'No hay caja ABIERTA.'}, status=400)
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

    if _is_ajax(request):
        return JsonResponse({'ok': True})
    messages.success(request, 'Caja CERRADA. Podés revisar la diferencia de efectivo en el listado.')
    return redirect('pos_panel')
