# pedidos/views_pos.py
from decimal import Decimal
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponseForbidden, JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt  # <— NUEVO

from .models import Caja, ProductoPOS, VentaPOS, VentaPOSItem, MovimientoCaja


def es_staff(user):
    return user.is_authenticated and user.is_staff


def _caja_abierta():
    return Caja.objects.filter(estado='ABIERTA').order_by('-id').first()

@csrf_exempt  # <— BLINDA la ruta /pos/ contra CSRF si por accidente llega un POST
@user_passes_test(es_staff)
@login_required
def pos_panel(request):
    if request.method != 'GET':
        # si algo intenta postear acá, lo cortamos elegante
        return HttpResponseNotAllowed(['GET'])

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
    except Exception:
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
    """
    Registrar venta con múltiples ítems.
    - Crea la Venta y sus Items.
    - Recalcula el total UNA sola vez.
    - Genera/actualiza UN movimiento de caja tipo VENTA (anti-duplicado).
    """
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido')

    caja = _caja_abierta()
    if not caja:
        messages.error(request, 'Abrí una caja antes de vender.')
        return redirect('pos_panel')

    medio_pago = (request.POST.get('medio_pago') or 'EFECTIVO').upper()
    tipo_comp = (request.POST.get('tipo_comprobante') or 'COMANDA').upper()

    # Arrays de productos/cantidades (múltiples filas)
    prod_ids = request.POST.getlist('item_producto')
    cants = request.POST.getlist('item_cantidad')

    lineas = []
    for pid, cnt in zip(prod_ids, cants):
        pid = (pid or '').strip()
        if not pid:
            continue
        try:
            prod = ProductoPOS.objects.get(pk=int(pid), activo=True)
        except (ProductoPOS.DoesNotExist, ValueError):
            continue
        try:
            q = int(cnt or 1)
            if q < 1:
                q = 1
        except Exception:
            q = 1
        lineas.append((prod, q))

    if not lineas:
        messages.error(request, 'Elegí al menos un producto.')
        return redirect('pos_panel')

    # 1) Crear venta (total provisional 0, se recalcula luego)
    venta = VentaPOS.objects.create(
        usuario=request.user,
        caja=caja,
        tipo_comprobante=tipo_comp,
        medio_pago=medio_pago,
        total=Decimal('0'),
        estado='COMPLETADA',
    )

    # 2) Crear ítems (el save() de VentaPOSItem calcula subtotal)
    for prod, q in lineas:
        VentaPOSItem.objects.create(
            venta=venta,
            producto=prod,
            descripcion=prod.nombre,       # snapshot del nombre
            cantidad=q,
            precio_unitario=prod.precio,
        )

    # 3) Recalcular total UNA vez y guardar
    venta.recomputar_total(save=True)  # asegura consistencia

    # 4) Movimiento de caja único por venta (anti-duplicado)
    MovimientoCaja.objects.update_or_create(
        caja=caja,
        venta=venta,
        tipo='VENTA',
        defaults={
            'medio_pago': medio_pago,
            'monto': venta.total,
            'usuario': request.user,
            'descripcion': f'VentaPOS #{venta.id} ({len(lineas)} ítem/s)',
        }
    )

    messages.success(request, f'Venta registrada (${venta.total}).')
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
    if tipo == 'VENTA':
        return HttpResponseForbidden('VENTA sólo se genera al registrar una venta')

    medio = (request.POST.get('medio_pago') or 'EFECTIVO').upper()
    try:
        monto = Decimal(request.POST.get('monto', '0') or '0')
    except Exception:
        monto = Decimal('0')
    desc = (request.POST.get('descripcion', '') or '').strip()

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
    except Exception:
        contado = Decimal('0')

    caja.estado = 'CERRADA'
    caja.usuario_cierre = request.user
    caja.fecha_cierre = timezone.now()
    caja.saldo_cierre_efectivo = contado
    caja.save(update_fields=['estado', 'usuario_cierre', 'fecha_cierre', 'saldo_cierre_efectivo'])

    messages.success(request, 'Caja CERRADA. Podés revisar la diferencia de efectivo en el listado.')
    return redirect('pos_panel')
