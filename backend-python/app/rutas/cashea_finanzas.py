from __future__ import annotations

import io
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.modelos import TasaDiaria, Usuario
from app.modelos_finanzas import (
    CuentaPorCobrar,
    EstadoCuentaPorCobrar,
    EstadoVerificacionPago,
    InstrumentoFinanciero,
    MonedaInstrumento,
    Pago,
    TipoDocumentoPago,
    TipoMovimientoPago,
    VentaCasheaFinanzas,
)
from app.modelos_logistica import Tercero
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import requerir_admin, requerir_direccion_lectura
from app.servicios.contabilidad import crear_asiento_contable

enrutador = APIRouter(prefix="/api/finanzas/cashea", tags=["Administración y Finanzas · Cashea"])


def _q2(v: Decimal | float | int) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _r2(v: Decimal | float | int) -> float:
    return float(_q2(v))


def _consultar_registros(
    bd: Session,
    fecha_inicio: date | None,
    fecha_fin: date | None,
    sucursal_id: int | None,
    estado: str | None,
    q: str | None,
) -> list[VentaCasheaFinanzas]:
    consulta = bd.query(VentaCasheaFinanzas).options(
        joinedload(VentaCasheaFinanzas.sucursal),
        joinedload(VentaCasheaFinanzas.cliente),
        joinedload(VentaCasheaFinanzas.instrumento_cobro),
    )
    if fecha_inicio is not None:
        consulta = consulta.filter(VentaCasheaFinanzas.fecha_venta >= fecha_inicio)
    if fecha_fin is not None:
        consulta = consulta.filter(VentaCasheaFinanzas.fecha_venta <= fecha_fin)
    if sucursal_id is not None:
        consulta = consulta.filter(VentaCasheaFinanzas.sucursal_id == sucursal_id)
    if estado and estado.strip():
        consulta = consulta.filter(VentaCasheaFinanzas.estado == estado.strip().upper())
    if q and q.strip():
        patron = f"%{q.strip()}%"
        consulta = consulta.outerjoin(Tercero, VentaCasheaFinanzas.cliente_id == Tercero.id).filter(
            or_(
                VentaCasheaFinanzas.numero_nota.ilike(patron),
                VentaCasheaFinanzas.referencia_cobro.ilike(patron),
                Tercero.nombre.ilike(patron),
            )
        )
    return consulta.order_by(VentaCasheaFinanzas.fecha_venta.desc(), VentaCasheaFinanzas.id.desc()).all()


def _serializar_item(r: VentaCasheaFinanzas) -> dict[str, Any]:
    pendiente_neto = max(Decimal("0"), _q2(Decimal(r.cashea_neto_por_cobrar_usd or 0) - Decimal(r.monto_cobrado_usd or 0)))
    return {
        "id": r.id,
        "venta_id": r.venta_id,
        "cxc_id": r.cxc_id,
        "fecha_venta": r.fecha_venta.isoformat(),
        "numero_nota": r.numero_nota,
        "sucursal_id": r.sucursal_id,
        "sucursal": r.sucursal.nombre if r.sucursal else "",
        "cliente": r.cliente.nombre if r.cliente else "Cliente general",
        "tasa_bcv_aplicada": float(r.tasa_bcv_aplicada or 0),
        "tasa_usdt_aplicada": float(r.tasa_usdt_aplicada or 0),
        "total_precio_regular_usd": _r2(r.total_precio_regular_usd),
        "total_precio_regular_usdt": _r2(r.total_precio_regular_usdt),
        "total_precio_regular_bs": _r2(r.total_precio_regular_bs),
        "inicial_cobrada_usd": _r2(r.inicial_cobrada_usd),
        "monto_financiado_usd": _r2(r.monto_financiado_usd),
        "cashea_comision_venta_usd": _r2(r.cashea_comision_venta_usd),
        "cashea_comision_financiado_usd": _r2(r.cashea_comision_financiado_usd),
        "cashea_iva_usd": _r2(r.cashea_iva_usd),
        "cashea_islr_usd": _r2(r.cashea_islr_usd),
        "cashea_total_cargos_usd": _r2(r.cashea_total_cargos_usd),
        "cashea_neto_por_cobrar_usd": _r2(r.cashea_neto_por_cobrar_usd),
        "cashea_neto_usdt": _r2(r.cashea_neto_usdt),
        "cashea_neto_bs": _r2(r.cashea_neto_bs),
        "monto_cobrado_usd": _r2(r.monto_cobrado_usd),
        "saldo_neto_pendiente_usd": _r2(pendiente_neto),
        "estado": r.estado,
        "fecha_cobro": r.fecha_cobro.isoformat() if r.fecha_cobro else None,
        "instrumento_cobro": r.instrumento_cobro.nombre if r.instrumento_cobro else "",
        "referencia_cobro": r.referencia_cobro or "",
    }


@enrutador.get("")
def listar_ventas_cashea_finanzas(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    sucursal_id: int | None = Query(default=None),
    estado: str | None = Query(default=None),
    q: str | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Lista operaciones Cashea alimentadas desde POS con conversiones, 4%+4%+IVA+ISLR y neto real. Solo ADMIN/DIRECTOR."""
    filas = _consultar_registros(bd, fecha_inicio, fecha_fin, sucursal_id, estado, q)

    tot_reg_usd = sum((Decimal(r.total_precio_regular_usd or 0) for r in filas), Decimal("0"))
    tot_reg_usdt = sum((Decimal(r.total_precio_regular_usdt or 0) for r in filas), Decimal("0"))
    tot_reg_bs = sum((Decimal(r.total_precio_regular_bs or 0) for r in filas), Decimal("0"))
    tot_fin = sum((Decimal(r.monto_financiado_usd or 0) for r in filas), Decimal("0"))
    tot_com_vta = sum((Decimal(r.cashea_comision_venta_usd or 0) for r in filas), Decimal("0"))
    tot_com_fin = sum((Decimal(r.cashea_comision_financiado_usd or 0) for r in filas), Decimal("0"))
    tot_iva = sum((Decimal(r.cashea_iva_usd or 0) for r in filas), Decimal("0"))
    tot_islr = sum((Decimal(r.cashea_islr_usd or 0) for r in filas), Decimal("0"))
    tot_cargos = sum((Decimal(r.cashea_total_cargos_usd or 0) for r in filas), Decimal("0"))
    tot_neto = sum((Decimal(r.cashea_neto_por_cobrar_usd or 0) for r in filas), Decimal("0"))
    tot_cobrado = sum((Decimal(r.monto_cobrado_usd or 0) for r in filas), Decimal("0"))

    pend_usd = Decimal("0")
    pend_usdt = Decimal("0")
    pend_bs = Decimal("0")
    for r in filas:
        if r.estado != "COBRADO":
            saldo_r = max(Decimal("0"), Decimal(r.cashea_neto_por_cobrar_usd or 0) - Decimal(r.monto_cobrado_usd or 0))
            pend_usd += saldo_r
            bcv = Decimal(r.tasa_bcv_aplicada or 0)
            usdt = Decimal(r.tasa_usdt_aplicada or 0)
            bs_r = _q2(saldo_r * bcv) if bcv > 0 else Decimal("0")
            pend_bs += bs_r
            pend_usdt += _q2(bs_r / usdt) if (bcv > 0 and usdt > 0) else saldo_r

    return {
        "resumen": {
            "cantidad_operaciones": len(filas),
            "total_precio_regular_usd": _r2(tot_reg_usd),
            "total_precio_regular_usdt": _r2(tot_reg_usdt),
            "total_precio_regular_bs": _r2(tot_reg_bs),
            "total_financiado_usd": _r2(tot_fin),
            "total_comision_venta_usd": _r2(tot_com_vta),
            "total_comision_financiado_usd": _r2(tot_com_fin),
            "total_iva_usd": _r2(tot_iva),
            "total_islr_usd": _r2(tot_islr),
            "total_cargos_usd": _r2(tot_cargos),
            "total_neto_por_cobrar_usd": _r2(tot_neto),
            "total_cobrado_usd": _r2(tot_cobrado),
            "neto_pendiente_usd": _r2(pend_usd),
            "neto_pendiente_usdt": _r2(pend_usdt),
            "neto_pendiente_bs": _r2(pend_bs),
        },
        "items": [_serializar_item(r) for r in filas],
    }


class RegistrarCobroCasheaEntrada(BaseModel):
    instrumento_destino_id: int
    monto_cobrado_usd: Decimal | None = Field(default=None, gt=Decimal("0"))
    fecha_cobro: date | None = None
    referencia: str = Field(default="", max_length=120)
    nota: str = Field(default="", max_length=255)


@enrutador.post("/{registro_id}/registrar-cobro")
def registrar_cobro_cashea(
    registro_id: int,
    datos: RegistrarCobroCasheaEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Registra el depósito recibido de Cashea en Tesorería y genera el asiento 1.1.01 vs 1.1.02. Solo ADMIN."""
    reg = bd.query(VentaCasheaFinanzas).filter(VentaCasheaFinanzas.id == registro_id).first()
    if reg is None:
        raise HTTPException(status_code=404, detail="Operación Cashea no encontrada.")
    if reg.estado == "COBRADO":
        raise HTTPException(status_code=400, detail="Esta operación Cashea ya fue cobrada en su totalidad.")

    inst = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.id == datos.instrumento_destino_id, InstrumentoFinanciero.activo.is_(True))
        .first()
    )
    if inst is None:
        raise HTTPException(status_code=404, detail="Cuenta bancaria / instrumento de destino no encontrado.")

    pendiente = max(Decimal("0"), _q2(Decimal(reg.cashea_neto_por_cobrar_usd or 0) - Decimal(reg.monto_cobrado_usd or 0)))
    monto_cobro = _q2(datos.monto_cobrado_usd) if datos.monto_cobrado_usd is not None else pendiente
    if monto_cobro <= 0:
        raise HTTPException(status_code=400, detail="No hay saldo neto pendiente por cobrar.")
    if monto_cobro > pendiente + Decimal("0.01"):
        raise HTTPException(
            status_code=400,
            detail=f"El monto (${monto_cobro:.2f}) excede el neto pendiente (${pendiente:.2f}).",
        )

    fecha_op = datos.fecha_cobro or obtener_fecha_hoy()
    tasa_row = bd.query(TasaDiaria).order_by(TasaDiaria.fecha.desc()).first()
    tasa_bcv = Decimal(tasa_row.tasa_bcv) if (tasa_row and tasa_row.tasa_bcv) else Decimal(reg.tasa_bcv_aplicada or 1)
    es_bs = inst.moneda == MonedaInstrumento.BS.value
    monto_origen = _q2(monto_cobro * tasa_bcv) if es_bs else monto_cobro

    pago = Pago(
        venta_id=reg.venta_id,
        instrumento_id=inst.id,
        fecha=fecha_op,
        tipo_movimiento=TipoMovimientoPago.INGRESO.value,
        tipo_documento=TipoDocumentoPago.CASHEA.value,
        monto_moneda_origen=monto_origen,
        moneda=inst.moneda,
        tasa_bcv_dia=tasa_bcv if es_bs else Decimal("0"),
        tasa_usdt_dia=Decimal("0"),
        usd_nominal=monto_cobro,
        usd_real=monto_cobro,
        cubre_promo_usd=Decimal("0"),
        referencia=datos.referencia.strip() or f"COBRO-CASHEA-{reg.numero_nota}",
        estado_verificacion=EstadoVerificacionPago.CONFIRMADO.value,
        verificado_por_id=usuario_actual.id,
        conciliado=False,
        anulado=False,
        categoria="Cobro Cashea",
        origen_tipo="COBRO_CASHEA",
        origen_id=reg.id,
        nota=datos.nota.strip() or f"Depósito neto Cashea nota {reg.numero_nota}",
    )
    bd.add(pago)
    bd.flush()

    reg.monto_cobrado_usd = _q2(Decimal(reg.monto_cobrado_usd or 0) + monto_cobro)
    reg.estado = (
        "COBRADO"
        if reg.monto_cobrado_usd >= Decimal(reg.cashea_neto_por_cobrar_usd or 0) - Decimal("0.01")
        else "PARCIAL"
    )
    reg.fecha_cobro = fecha_op
    reg.instrumento_cobro_id = inst.id
    reg.pago_cobro_id = pago.id
    reg.referencia_cobro = datos.referencia.strip() or pago.referencia

    if reg.cxc_id is not None:
        cxc = bd.query(CuentaPorCobrar).filter(CuentaPorCobrar.id == reg.cxc_id).first()
        if cxc is not None:
            cxc.saldo_pendiente_usd = max(Decimal("0"), _q2(Decimal(cxc.saldo_pendiente_usd or 0) - monto_cobro))
            if cxc.saldo_pendiente_usd <= Decimal("0.01"):
                cxc.saldo_pendiente_usd = Decimal("0")
                cxc.estado = EstadoCuentaPorCobrar.PAGADA.value

    asiento = crear_asiento_contable(
        bd=bd,
        usuario=usuario_actual,
        fecha_op=fecha_op,
        descripcion=f"Cobro Depósito Cashea · Nota {reg.numero_nota} ({inst.nombre})",
        origen_tipo="COBRO_CASHEA",
        origen_id=reg.id,
        lineas=[
            {"cuenta_codigo": "1.1.01", "debe_usd": monto_cobro, "haber_usd": 0, "nota": f"Depósito en {inst.nombre}"},
            {"cuenta_codigo": "1.1.02", "debe_usd": 0, "haber_usd": monto_cobro, "nota": f"Cancelación CxC Cashea {reg.numero_nota}"},
        ],
    )
    bd.commit()

    return {
        "id": reg.id,
        "numero_nota": reg.numero_nota,
        "estado": reg.estado,
        "monto_cobrado_usd": _r2(reg.monto_cobrado_usd),
        "pago_id": pago.id,
        "asiento_id": asiento.id,
    }


@enrutador.get("/excel")
def exportar_cashea_excel(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    sucursal_id: int | None = Query(default=None),
    estado: str | None = Query(default=None),
    q: str | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> StreamingResponse:
    filas = _consultar_registros(bd, fecha_inicio, fecha_fin, sucursal_id, estado, q)
    wb = Workbook()
    ws = wb.active
    ws.title = "Cashea Finanzas"

    headers = [
        "Fecha",
        "# Nota",
        "Cliente",
        "Sucursal",
        "Precio Regular USD",
        "Precio Regular USDT",
        "Precio Regular Bs",
        "Inicial USD",
        "Financiado USD",
        "4% Venta USD",
        "4% Financiado USD",
        "16% IVA USD",
        "2% ISLR USD",
        "Total Cargos USD",
        "Neto por Cobrar USD",
        "Cobrado USD",
        "Estado",
        "Referencia Cobro",
    ]
    ws.append(headers)
    fill_h = PatternFill(start_color="003566", end_color="003566", fill_type="solid")
    font_h = Font(color="FFFFFF", bold=True)
    for cell in ws[1]:
        cell.fill = fill_h
        cell.font = font_h

    for r in filas:
        it = _serializar_item(r)
        ws.append(
            [
                it["fecha_venta"],
                it["numero_nota"],
                it["cliente"],
                it["sucursal"],
                it["total_precio_regular_usd"],
                it["total_precio_regular_usdt"],
                it["total_precio_regular_bs"],
                it["inicial_cobrada_usd"],
                it["monto_financiado_usd"],
                it["cashea_comision_venta_usd"],
                it["cashea_comision_financiado_usd"],
                it["cashea_iva_usd"],
                it["cashea_islr_usd"],
                it["cashea_total_cargos_usd"],
                it["cashea_neto_por_cobrar_usd"],
                it["monto_cobrado_usd"],
                it["estado"],
                it["referencia_cobro"],
            ]
        )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="cashea_finanzas_alfa.xlsx"'},
    )
