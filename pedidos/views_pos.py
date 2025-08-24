# pedidos/views_pos.py
from decimal import Decimal
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponseForbidden

from .models import Caja, ProductoPOS, VentaPOS, VentaPOSItem, MovimientoCaja

def es_staff(user):
    return user.is_authenticated and user.is_staff

def _caja_abierta():
    return Caja.objects.filter(estado='ABIERTA').order_by('-id').first()

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
        messages.warning(request, 'Ya hay una caja ABIERTA.')
        return redirect('pos_panel')

    try:
        inicial = Decimal(request.POST.get('saldo_inicial_efectivo', '0') or '0')
    except:
        inicial = Decimal('0')

    Caja.objects.create(
        usuario_apertura=request.user,
        saldo_inicial_efectivo=inicial,
        estado='ABIERTA',
    )
    messages.success(request, 'Caja ABIERTA correctamente.')
    return redirect('pos_panel')

@user_passes_test(es_staff)
@login_required
@transaction.atomic
def pos_vender(request):
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido')
    caja = _caja_abierta()
    if not caja:
        messages.error(request, 'Abrí una caja antes de vender.')
        return redirect('pos_panel')

    producto_id = request.POST.get('producto_id')
    cantidad = int(request.POST.get('cantidad', '1') or 1)
    medio_pago = request.POST.get('medio_pago') or 'EFECTIVO'
    tipo_comp = request.POST.get('tipo_comprobante') or 'COMANDA'

    prod = get_object_or_404(ProductoPOS, pk=producto_id)
    precio = prod.precio or Decimal('0')
    desc = prod.nombre

    venta = VentaPOS.objects.create(
        usuario=request.user,
        caja=caja,
        tipo_comprobante=tipo_comp,
        medio_pago=medio_pago,
        total=Decimal('0'),
        estado='COMPLETADA',
    )
    VentaPOSItem.objects.create(
        venta=venta,
        producto=prod,
        descripcion=desc,
        cantidad=cantidad,
        precio_unitario=precio,
    )
    venta.recomputar_total(save=True)

    # Asentamos movimiento de caja por la venta (sirve para totales por medio)
    MovimientoCaja.objects.create(
        caja=caja,
        tipo='VENTA',
        medio_pago=medio_pago,
        monto=venta.total,
        descripcion=f'VentaPOS #{venta.id} - {desc} x{cantidad}',
        venta=venta,
        usuario=request.user
    )

    messages.success(request, f'Venta registrada: {desc} x{cantidad} (${venta.total}).')
    return redirect('pos_panel')

@user_passes_test(es_staff)
@login_required
@transaction.atomic
def pos_movimiento(request):
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido')
    caja = _caja_abierta()
    if not caja:
        messages.error(request, 'Abrí una caja antes de registrar movimientos.')
        return redirect('pos_panel')

    tipo = request.POST.get('tipo')  # INGRESO / EGRESO / AJUSTE / RETIRO
    medio = request.POST.get('medio_pago') or 'EFECTIVO'
    try:
        monto = Decimal(request.POST.get('monto', '0') or '0')
    except:
        monto = Decimal('0')
    desc = request.POST.get('descripcion', '').strip()

    if tipo not in ['INGRESO', 'EGRESO', 'AJUSTE', 'RETIRO']:
        messages.error(request, 'Tipo de movimiento inválido.')
        return redirect('pos_panel')
    if monto <= 0:
        messages.error(request, 'El monto debe ser mayor a 0.')
        return redirect('pos_panel')

    MovimientoCaja.objects.create(
        caja=caja,
        tipo=tipo,
        medio_pago=medio,
        monto=monto,
        descripcion=desc,
        usuario=request.user
    )
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
        messages.warning(request, 'No hay caja ABIERTA.')
        return redirect('pos_panel')

    try:
        contado = Decimal(request.POST.get('saldo_cierre_efectivo', '0') or '0')
    except:
        contado = Decimal('0')

    caja.estado = 'CERRADA'
    caja.usuario_cierre = request.user
    caja.fecha_cierre = timezone.now()
    caja.saldo_cierre_efectivo = contado
    caja.save(update_fields=['estado','usuario_cierre','fecha_cierre','saldo_cierre_efectivo'])

    messages.success(request, 'Caja CERRADA. Podés revisar la diferencia de efectivo en el listado.')
    return redirect('pos_panel')
