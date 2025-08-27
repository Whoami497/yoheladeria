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

from .models import Caja, ProductoPOS, VentaPOS, VentaPOSItem, MovimientoCaja

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
        ventas = VentaPOS.objects.filter(caja=caja).order_by('-id')[:15]  # <-- SOLO de la caja abierta
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
        # Si ya hay abierta, devolvemos JSON (porque en panel usamos fetch)
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
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido')

    caja = _caja_abierta()
    if not caja:
        return JsonResponse({'ok': False, 'error': 'Abrí una caja antes de vender.'}, status=400)

    tipo_comp = request.POST.get('tipo_comprobante') or 'COMANDA'

    # Ítems
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
        return JsonResponse({'ok': False, 'error': 'Elegí al menos un producto.'}, status=400)

    # Crear venta base
    venta = VentaPOS.objects.create(
        usuario=request.user,
        caja=caja,
        tipo_comprobante=tipo_comp,
        medio_pago='MIXTO',  # informativo cuando es multi-medio
        total=Decimal('0'),
        estado='COMPLETADA',
    )

    # Ítems + total
    total_venta = Decimal('0')
    for pid, q in lineas:
        prod = get_object_or_404(ProductoPOS, pk=pid)
        precio = prod.precio or Decimal('0')
        subtotal = (precio or Decimal('0')) * Decimal(q)
        total_venta += subtotal

        VentaPOSItem.objects.create(
            venta=venta,
            producto=prod,
            descripcion=prod.nombre,
            cantidad=q,
            precio_unitario=precio,
            subtotal=subtotal,
        )

    # Pagos
    pagos_medios = request.POST.getlist('pago_medio')  # puede venir 1 o varios
    pagos_montos = request.POST.getlist('pago_monto')

    movimientos_creados = []
    if pagos_medios:
        # Validar sumatoria
        suma = Decimal('0')
        pagos = []
        for medio, monto in zip(pagos_medios, pagos_montos):
            try:
                m = Decimal(monto or '0')
            except Exception:
                m = Decimal('0')
            if m > 0:
                pagos.append((medio, m))
                suma += m

        # Tolerancia de 1 centavo
        if abs(suma - total_venta) > Decimal('0.01'):
            return JsonResponse({'ok': False, 'error': 'La suma de pagos no coincide con el total.'}, status=400)

        for medio, m in pagos:
            mov = MovimientoCaja.objects.create(
                caja=caja,
                tipo='VENTA',
                medio_pago=medio,
                monto=m,
                descripcion=f'VentaPOS #{venta.id}',
                venta=venta,
                usuario=request.user
            )
            movimientos_creados.append(mov)
    else:
        # Fallback: un único pago "medio_pago" por el total
        medio_pago = request.POST.get('medio_pago') or 'EFECTIVO'
        mov = MovimientoCaja.objects.create(
            caja=caja,
            tipo='VENTA',
            medio_pago=medio_pago,
            monto=total_venta,
            descripcion=f'VentaPOS #{venta.id}',
            venta=venta,
            usuario=request.user
        )
        movimientos_creados.append(mov)

    # Setear total una sola vez
    venta.total = total_venta
    venta.save(update_fields=['total'])

    return JsonResponse({'ok': True, 'venta_id': venta.id})

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
