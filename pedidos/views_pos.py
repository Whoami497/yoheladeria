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
    Soporta múltiples ítems y múltiples medios de pago.
    - Si vienen arrays pago_medio[] y pago_monto[], crea un MovimientoCaja por cada pago.
    - Si no, usa el campo medio_pago único (compatibilidad).
    - Devuelve JSON si la petición es AJAX (fetch), o redirige con mensajes si es navegación normal.
    """
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido')

    caja = _caja_abierta()
    if not caja:
        msg = 'Abrí una caja antes de vender.'
        if is_ajax:
            return JsonResponse({'ok': False, 'error': msg}, status=400)
        messages.error(request, msg)
        return redirect('pos_panel')

    tipo_comp = (request.POST.get('tipo_comprobante') or 'COMANDA').strip()

    # ---- Ítems (producto + cantidad)
    ids = request.POST.getlist('item_producto')
    cants = request.POST.getlist('item_cantidad')

    lineas = []
    for pid, cnt in zip(ids, cants):
        pid = (pid or '').strip()
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
        if is_ajax:
            return JsonResponse({'ok': False, 'error': msg}, status=400)
        messages.error(request, msg)
        return redirect('pos_panel')

    # Preparamos datos de ítems y calculamos total (aún no grabamos venta)
    items_data = []
    total_venta = Decimal('0')
    for pid, q in lineas:
        prod = get_object_or_404(ProductoPOS, pk=pid)
        precio = prod.precio or Decimal('0')
        subtotal = (precio or Decimal('0')) * Decimal(q)
        items_data.append((prod, q, precio, subtotal))
        total_venta += subtotal

    # ---- Pagos múltiples (opcional)
    pagos_medios = request.POST.getlist('pago_medio')
    pagos_montos = request.POST.getlist('pago_monto')
    pagos = []
    for m, amt in zip(pagos_medios, pagos_montos):
        m = (m or '').strip() or 'EFECTIVO'
        try:
            d = Decimal(str(amt).replace(',', '.'))
        except Exception:
            d = Decimal('0')
        if d > 0:
            pagos.append((m, d))

    # Validamos suma de pagos si se usó modo múltiple
    if pagos:
        suma = sum((d for _, d in pagos), Decimal('0'))
        if (suma - total_venta).copy_abs() > Decimal('0.01'):
            msg = f'La suma de pagos (${suma}) no coincide con el total (${total_venta}).'
            if is_ajax:
                return JsonResponse({'ok': False, 'error': msg}, status=400)
            messages.error(request, msg)
            return redirect('pos_panel')

    # ---- Creamos la venta y sus ítems
    venta = VentaPOS.objects.create(
        usuario=request.user,
        caja=caja,
        tipo_comprobante=tipo_comp,
        medio_pago='PEND',  # lo fijamos más abajo
        total=Decimal('0'),
        estado='COMPLETADA',
    )

    for prod, q, precio, subtotal in items_data:
        VentaPOSItem.objects.create(
            venta=venta,
            producto=prod,
            descripcion=prod.nombre,
            cantidad=q,
            precio_unitario=precio,
            subtotal=subtotal,
        )

    venta.total = total_venta

    # ---- Movimientos de caja según pagos
    if pagos:
        venta.medio_pago = 'MIXTO' if len(pagos) > 1 else pagos[0][0]
        venta.save(update_fields=['total', 'medio_pago'])
        for medio, monto in pagos:
            MovimientoCaja.objects.create(
                caja=caja,
                tipo='VENTA',
                medio_pago=medio,
                monto=monto,
                descripcion=f'VentaPOS #{venta.id} ({len(items_data)} ítem/s)',
                venta=venta,
                usuario=request.user,
            )
    else:
        # Compatibilidad: un solo medio de pago tradicional
        medio_pago = (request.POST.get('medio_pago') or 'EFECTIVO').strip()
        venta.medio_pago = medio_pago
        venta.save(update_fields=['total', 'medio_pago'])
        MovimientoCaja.objects.create(
            caja=caja,
            tipo='VENTA',
            medio_pago=medio_pago,
            monto=total_venta,
            descripcion=f'VentaPOS #{venta.id} ({len(items_data)} ítem/s)',
            venta=venta,
            usuario=request.user,
        )

    if is_ajax:
        return JsonResponse({'ok': True, 'venta_id': venta.id, 'total': str(total_venta)})

    messages.success(request, f'Venta #{venta.id} registrada (${total_venta}).')
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
