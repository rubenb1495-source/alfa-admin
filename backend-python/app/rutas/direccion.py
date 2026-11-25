from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.modelos import CatalogoArticulo, EstadoSucursal, Sucursal, TasaDiaria, Usuario
from app.modelos_finanzas import (
    CuentaPorCobrar,
    EstadoComision,
    EstadoCuentaPorCobrar,
    EstadoVenta,
    InstrumentoFinanciero,
    MonedaInstrumento,
    OrigenVenta,
    Pago,
    TipoCuentaPorCobrar,
    TipoMovimientoPago,
    Venta,
    VentaDetalle,
)
from app.modelos_logistica import (
    Compra,
    Equipo,
    EstadoCompra,
    EstadoEquipo,
    EstadoTraslado,
    MovimientoInventario,
    Traslado,
)
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import requerir_direccion_lectura


enrutador = APIRouter(prefix="/api/direccion", tags=["Panel Ejecutivo de Dirección"])


def _r2(valor: Decimal) -> float:
    return float(valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@enrutador.get("/resumen")
def obtener_resumen_direccion(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    sucursal_id: int | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    hoy = obtener_fecha_hoy()
    f_fin = fecha_fin or hoy
    f_inicio = fecha_inicio or date(f_fin.year, f_fin.month, 1)

    tasa_row = (
        bd.query(TasaDiaria)
        .filter(TasaDiaria.fecha <= hoy)
        .order_by(TasaDiaria.fecha.desc())
        .first()
    )
    tasa_bcv = Decimal(tasa_row.tasa_bcv) if tasa_row and tasa_row.tasa_bcv else Decimal("0")
    tasa_usdt = Decimal(tasa_row.tasa_usdt) if tasa_row and tasa_row.tasa_usdt else Decimal("0")

    # 1. Disponible en Cajas y Cuentas
    instrumentos = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.activo.is_(True))
        .order_by(InstrumentoFinanciero.id.asc())
        .all()
    )
    pagos_activos = bd.query(Pago).filter(Pago.anulado.is_(False)).all()
    neto_inst: dict[int, Decimal] = {}
    for p in pagos_activos:
        signo = Decimal("-1") if p.tipo_movimiento == TipoMovimientoPago.EGRESO.value else Decimal("1")
        neto_inst[p.instrumento_id] = neto_inst.get(p.instrumento_id, Decimal("0")) + (
            Decimal(p.monto_moneda_origen or 0) * signo
        )

    cuentas_lista: list[dict[str, Any]] = []
    total_disponible_usd = Decimal("0")
    for inst in instrumentos:
        saldo_nativo = Decimal(inst.saldo_inicial or 0) + neto_inst.get(inst.id, Decimal("0"))
        if inst.moneda == MonedaInstrumento.BS.value:
            saldo_usd = (saldo_nativo / tasa_bcv) if tasa_bcv > 0 else Decimal("0")
        else:
            saldo_usd = saldo_nativo
        total_disponible_usd += saldo_usd
        cuentas_lista.append(
            {
                "id": inst.id,
                "nombre": inst.nombre,
                "moneda": inst.moneda,
                "saldo_nativo": _r2(saldo_nativo),
                "saldo_usd": _r2(saldo_usd),
            }
        )

    # 2. Inventario Físico y en Tránsito
    sucursales = (
        bd.query(Sucursal)
        .filter(Sucursal.estado == EstadoSucursal.ACTIVA.value)
        .order_by(Sucursal.id.asc())
        .all()
    )
    mapa_suc = {s.id: s.nombre for s in sucursales}

    equipos_q = bd.query(Equipo).filter(
        Equipo.estado.notin_([EstadoEquipo.VENDIDO.value, EstadoEquipo.CEMENTERIO.value])
    )
    if sucursal_id is not None:
        equipos_q = equipos_q.filter(Equipo.ubicacion_id == sucursal_id)
    equipos_activos = equipos_q.all()

    fisico_por_suc: dict[int, dict[str, Any]] = {
        s.id: {
            "sucursal_id": s.id,
            "sucursal": s.nombre,
            "equipos": 0,
            "productos": 0,
            "valor_costo_usd": Decimal("0"),
            "valor_promo_usd": Decimal("0"),
        }
        for s in sucursales
        if sucursal_id is None or s.id == sucursal_id
    }

    transito_equipos = 0
    transito_costo = Decimal("0")
    transito_promo = Decimal("0")

    for eq in equipos_activos:
        costo_eq = (
            Decimal(eq.costo_compra_usd or 0)
            + Decimal(eq.costo_flete_usd or 0)
            + Decimal(eq.costo_taller_usd or 0)
        )
        promo_eq = Decimal(eq.precio_promo_usd or 0)
        if eq.estado == EstadoEquipo.EN_TRANSITO.value:
            transito_equipos += 1
            transito_costo += costo_eq
            transito_promo += promo_eq
        else:
            bucket = fisico_por_suc.setdefault(
                eq.ubicacion_id,
                {
                    "sucursal_id": eq.ubicacion_id,
                    "sucursal": mapa_suc.get(eq.ubicacion_id, f"Sucursal #{eq.ubicacion_id}"),
                    "equipos": 0,
                    "productos": 0,
                    "valor_costo_usd": Decimal("0"),
                    "valor_promo_usd": Decimal("0"),
                },
            )
            bucket["equipos"] += 1
            bucket["valor_costo_usd"] += costo_eq
            bucket["valor_promo_usd"] += promo_eq

    # Stock por cantidad (componentes / accesorios)
    movs_prod = (
        bd.query(
            MovimientoInventario.sucursal_id,
            MovimientoInventario.articulo_id,
            func.coalesce(func.sum(MovimientoInventario.cantidad), 0).label("stock"),
        )
        .filter(MovimientoInventario.equipo_id.is_(None))
        .group_by(MovimientoInventario.sucursal_id, MovimientoInventario.articulo_id)
        .all()
    )
    articulos_map = {
        a.id: a
        for a in bd.query(CatalogoArticulo).options(joinedload(CatalogoArticulo.precios)).all()
    }
    for suc_id_m, art_id_m, stock_m in movs_prod:
        stock_int = int(stock_m or 0)
        if stock_int <= 0:
            continue
        if sucursal_id is not None and suc_id_m != sucursal_id:
            continue
        art = articulos_map.get(art_id_m)
        precio_p = (
            Decimal(art.precios[0].precio_promo_usd)
            if (art and art.precios)
            else Decimal("0")
        )
        costo_p = (
            Decimal(art.precios[0].costo_referencia_usd or 0)
            if (art and art.precios)
            else Decimal("0")
        )
        bucket = fisico_por_suc.setdefault(
            suc_id_m,
            {
                "sucursal_id": suc_id_m,
                "sucursal": mapa_suc.get(suc_id_m, f"Sucursal #{suc_id_m}"),
                "equipos": 0,
                "productos": 0,
                "valor_costo_usd": Decimal("0"),
                "valor_promo_usd": Decimal("0"),
            },
        )
        bucket["productos"] += stock_int
        bucket["valor_costo_usd"] += costo_p * stock_int
        bucket["valor_promo_usd"] += precio_p * stock_int

    fisico_lista = [
        {
            "sucursal_id": b["sucursal_id"],
            "sucursal": b["sucursal"],
            "equipos": b["equipos"],
            "productos": b["productos"],
            "valor_costo_usd": _r2(b["valor_costo_usd"]),
            "valor_promo_usd": _r2(b["valor_promo_usd"]),
        }
        for b in fisico_por_suc.values()
    ]
    total_fisico_equipos = sum(b["equipos"] for b in fisico_por_suc.values())
    total_fisico_productos = sum(b["productos"] for b in fisico_por_suc.values())
    total_fisico_costo = sum((b["valor_costo_usd"] for b in fisico_por_suc.values()), Decimal("0"))
    total_fisico_promo = sum((b["valor_promo_usd"] for b in fisico_por_suc.values()), Decimal("0"))

    traslados_transito = (
        bd.query(func.count(Traslado.id))
        .filter(Traslado.estado == EstadoTraslado.EN_TRANSITO.value)
        .scalar()
        or 0
    )
    compras_pendientes = (
        bd.query(Compra)
        .filter(Compra.estado.in_([EstadoCompra.PENDIENTE.value, EstadoCompra.RECIBIDA_PARCIAL.value]))
        .all()
    )
    compras_pendientes_usd = sum(
        (
            Decimal(c.monto_mercancia_usd or 0)
            + Decimal(c.envio_usd or 0)
            + Decimal(c.otros_gastos_usd or 0)
            for c in compras_pendientes
        ),
        Decimal("0"),
    )

    # 3. Cuentas por Cobrar (CxC) y Cuentas por Pagar (CxP)
    cxc_pendientes = (
        bd.query(CuentaPorCobrar)
        .options(joinedload(CuentaPorCobrar.venta), joinedload(CuentaPorCobrar.cliente))
        .filter(CuentaPorCobrar.estado == EstadoCuentaPorCobrar.PENDIENTE.value)
        .order_by(CuentaPorCobrar.id.desc())
        .all()
    )
    cxc_clientes = Decimal("0")
    cxc_cashea = Decimal("0")
    cxc_listado: list[dict[str, Any]] = []
    for c in cxc_pendientes:
        saldo_c = Decimal(c.saldo_pendiente_usd or 0)
        if c.tipo == TipoCuentaPorCobrar.CASHEA.value:
            cxc_cashea += saldo_c
        else:
            cxc_clientes += saldo_c
        if len(cxc_listado) < 15:
            cxc_listado.append(
                {
                    "id": c.id,
                    "tipo": c.tipo,
                    "cliente": c.cliente.nombre if c.cliente else "Cliente / Cashea",
                    "numero_venta": c.venta.numero_venta if c.venta else "—",
                    "saldo_pendiente_usd": _r2(saldo_c),
                    "fecha_vencimiento": c.venta.fecha.isoformat() if (c.venta and c.venta.fecha) else None,
                }
            )

    # CxP: Consignaciones vendidas + Comisiones pendientes + Compras pendientes
    equipos_consignacion_vendidos = (
        bd.query(Equipo)
        .filter(
            Equipo.es_consignacion.is_(True),
            Equipo.estado == EstadoEquipo.VENDIDO.value,
        )
        .all()
    )
    consignaciones_por_pagar = sum(
        (Decimal(e.costo_acordado_usd or e.costo_compra_usd or 0) for e in equipos_consignacion_vendidos),
        Decimal("0"),
    )

    ventas_comision_pend = (
        bd.query(Venta)
        .options(joinedload(Venta.asesor))
        .filter(
            Venta.estado.notin_([EstadoVenta.ANULADA.value, EstadoVenta.DEVUELTA.value]),
            Venta.estado_comision == EstadoComision.PENDIENTE.value,
            Venta.asesor_id.isnot(None),
        )
        .all()
    )
    comisiones_pendientes_usd = Decimal("0")
    for v in ventas_comision_pend:
        rol_a = v.asesor.rol if v.asesor else ""
        base_v = Decimal(v.total_promo_usd or 0)
        if v.origen_venta == OrigenVenta.LEAD.value:
            pct = Decimal("0.08")
        elif rol_a == "ENCARGADO_TIENDA":
            pct = Decimal("0.05")
        elif rol_a == "ASESORA":
            pct = Decimal("0.01")
        else:
            pct = Decimal("0")
        comisiones_pendientes_usd += base_v * pct

    total_cxp_usd = consignaciones_por_pagar + comisiones_pendientes_usd + compras_pendientes_usd

    # 4, 5 y 6. Ventas del Periodo (Top 10, Por Asesor, Por Tienda)
    ventas_q = (
        bd.query(Venta)
        .options(
            joinedload(Venta.sucursal),
            joinedload(Venta.asesor),
            joinedload(Venta.detalles).joinedload(VentaDetalle.articulo),
            joinedload(Venta.detalles).joinedload(VentaDetalle.equipo),
        )
        .filter(
            Venta.fecha >= f_inicio,
            Venta.fecha <= f_fin,
            Venta.estado.notin_([EstadoVenta.ANULADA.value, EstadoVenta.DEVUELTA.value]),
        )
    )
    if sucursal_id is not None:
        ventas_q = ventas_q.filter(Venta.sucursal_id == sucursal_id)
    ventas_periodo = ventas_q.all()

    productos_rank: dict[str, dict[str, Any]] = {}
    asesores_map: dict[int, dict[str, Any]] = {}
    tiendas_map: dict[int, dict[str, Any]] = {}
    total_facturado_periodo = Decimal("0")

    for v in ventas_periodo:
        monto_v = Decimal(v.total_promo_usd or 0)
        total_facturado_periodo += monto_v

        # Por tienda
        t_bucket = tiendas_map.setdefault(
            v.sucursal_id,
            {
                "sucursal_id": v.sucursal_id,
                "sucursal": v.sucursal.nombre if v.sucursal else f"Sucursal #{v.sucursal_id}",
                "cantidad_ventas": 0,
                "monto_usd": Decimal("0"),
            },
        )
        t_bucket["cantidad_ventas"] += 1
        t_bucket["monto_usd"] += monto_v

        # Por asesor
        a_id = v.asesor_id or 0
        a_bucket = asesores_map.setdefault(
            a_id,
            {
                "asesor_id": v.asesor_id,
                "nombre": v.asesor.nombre if v.asesor else "Tienda (Sin asesor)",
                "rol": v.asesor.rol if v.asesor else "TIENDA",
                "modalidad": getattr(v.asesor, "modalidad", "PRESENCIAL") if v.asesor else "PRESENCIAL",
                "ventas_pasillo": 0,
                "ventas_lead": 0,
                "total_ventas": 0,
                "monto_usd": Decimal("0"),
            },
        )
        if v.origen_venta == OrigenVenta.LEAD.value:
            a_bucket["ventas_lead"] += 1
        else:
            a_bucket["ventas_pasillo"] += 1
        a_bucket["total_ventas"] += 1
        a_bucket["monto_usd"] += monto_v

        # Top productos
        for det in v.detalles:
            sku_key = (
                det.articulo.sku
                if det.articulo
                else (det.equipo.modelo if det.equipo else det.descripcion_servicio or "OTRO")
            )
            desc_prod = (
                det.articulo.descripcion
                if det.articulo
                else (det.equipo.modelo if det.equipo else det.descripcion_servicio or "Producto")
            )
            p_bucket = productos_rank.setdefault(
                sku_key,
                {
                    "sku": sku_key,
                    "descripcion": desc_prod,
                    "unidades": 0,
                    "monto_usd": Decimal("0"),
                },
            )
            cant_d = int(det.cantidad or 1)
            p_bucket["unidades"] += cant_d
            p_bucket["monto_usd"] += Decimal(det.precio_promo_usd or 0) * cant_d

    top_vendidos = sorted(
        productos_rank.values(),
        key=lambda x: (x["unidades"], x["monto_usd"]),
        reverse=True,
    )[:10]

    ventas_por_asesor = sorted(
        [
            {**a, "monto_usd": _r2(a["monto_usd"])}
            for a in asesores_map.values()
        ],
        key=lambda x: x["monto_usd"],
        reverse=True,
    )

    ventas_por_tienda = sorted(
        [
            {
                "sucursal_id": t["sucursal_id"],
                "sucursal": t["sucursal"],
                "cantidad_ventas": t["cantidad_ventas"],
                "monto_usd": _r2(t["monto_usd"]),
                "ticket_promedio_usd": _r2(
                    t["monto_usd"] / Decimal(t["cantidad_ventas"])
                    if t["cantidad_ventas"] > 0
                    else Decimal("0")
                ),
            }
            for t in tiendas_map.values()
        ],
        key=lambda x: x["monto_usd"],
        reverse=True,
    )

    return {
        "periodo": {
            "fecha_inicio": f_inicio.isoformat(),
            "fecha_fin": f_fin.isoformat(),
            "sucursal_id": sucursal_id,
            "total_ventas": len(ventas_periodo),
            "facturacion_usd": _r2(total_facturado_periodo),
        },
        "tasas": {
            "tasa_bcv": float(tasa_bcv),
            "tasa_usdt": float(tasa_usdt),
        },
        "disponible_cuentas": {
            "total_consolidado_usd": _r2(total_disponible_usd),
            "cuentas": cuentas_lista,
        },
        "inventario": {
            "fisico": {
                "equipos": total_fisico_equipos,
                "productos": total_fisico_productos,
                "valor_costo_usd": _r2(total_fisico_costo),
                "valor_promo_usd": _r2(total_fisico_promo),
                "por_sucursal": fisico_lista,
            },
            "en_transito": {
                "equipos": transito_equipos,
                "valor_costo_usd": _r2(transito_costo),
                "valor_promo_usd": _r2(transito_promo),
                "traslados_en_transito": int(traslados_transito),
                "compras_pendientes": len(compras_pendientes),
                "compras_pendientes_usd": _r2(compras_pendientes_usd),
            },
        },
        "cuentas_por_cobrar": {
            "total_cxc_usd": _r2(cxc_clientes + cxc_cashea),
            "clientes_usd": _r2(cxc_clientes),
            "cashea_usd": _r2(cxc_cashea),
            "listado": cxc_listado,
        },
        "cuentas_por_pagar": {
            "total_cxp_usd": _r2(total_cxp_usd),
            "consignaciones_usd": _r2(consignaciones_por_pagar),
            "comisiones_pendientes_usd": _r2(comisiones_pendientes_usd),
            "compras_pendientes_usd": _r2(compras_pendientes_usd),
        },
        "mas_vendidos": [
            {
                "sku": p["sku"],
                "descripcion": p["descripcion"],
                "unidades": p["unidades"],
                "monto_usd": _r2(p["monto_usd"]),
            }
            for p in top_vendidos
        ],
        "ventas_por_asesor": ventas_por_asesor,
        "ventas_por_tienda": ventas_por_tienda,
    }
