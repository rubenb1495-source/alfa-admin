from __future__ import annotations

import io
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
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

    ref_limpia = datos.referencia.strip()
    if ref_limpia:
        duplicado = (
            bd.query(Pago)
            .filter(
                Pago.anulado.is_(False),
                Pago.origen_tipo == "COBRO_CASHEA",
                Pago.referencia == ref_limpia,
            )
            .first()
        )
        if duplicado is not None:
            raise HTTPException(
                status_code=409,
                detail=f"La referencia/orden Cashea '{ref_limpia}' ya fue liquidada anteriormente (Pago #{duplicado.id}).",
            )

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


def _leer_filas_cashea(contenido: bytes, nombre_archivo: str) -> tuple[list[str], list[dict[str, Any]]]:
    import csv

    nombre_l = (nombre_archivo or "").lower()
    if nombre_l.endswith(".csv"):
        texto = contenido.decode("utf-8-sig", errors="replace")
        lector = csv.DictReader(io.StringIO(texto))
        cols = [str(c).strip() for c in (lector.fieldnames or []) if c]
        filas = [{str(k).strip(): v for k, v in row.items() if k} for row in lector]
        return cols, filas

    wb = load_workbook(io.BytesIO(contenido), data_only=True)
    ws = wb.active
    raw_rows = list(ws.iter_rows(values_only=True))
    if not raw_rows:
        return [], []
    cols = [str(c or "").strip() for c in raw_rows[0]]
    filas: list[dict[str, Any]] = []
    for row in raw_rows[1:]:
        if not any(v is not None and str(v).strip() != "" for v in row):
            continue
        filas.append({cols[i]: (row[i] if i < len(row) else None) for i in range(len(cols)) if cols[i]})
    return [c for c in cols if c], filas


def _parse_monto_cashea(val: Any) -> Decimal:
    if val is None:
        return Decimal("0")
    s = str(val).strip().replace("$", "").replace("USD", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return _q2(Decimal(s))
    except Exception:
        return Decimal("0")


@enrutador.post("/importar-reporte/preview")
async def preview_liquidacion_cashea_lote(
    archivo: UploadFile = File(...),
    col_orden: str | None = Form(default=None),
    col_neto: str | None = Form(default=None),
    _usuario: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Analiza un reporte .xlsx/.csv de liquidación Cashea y lo cruza con las CxC Cashea pendientes."""
    contenido = await archivo.read()
    nombre = archivo.filename or "liquidacion_cashea.xlsx"
    columnas, filas_raw = _leer_filas_cashea(contenido, nombre)
    if not columnas:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El archivo está vacío o no tiene encabezados.")

    def _detectar(preferido: str | None, pistas: tuple[str, ...]) -> str:
        if preferido and preferido in columnas:
            return preferido
        for c in columnas:
            cl = c.lower()
            if any(p in cl for p in pistas):
                return c
        return columnas[0]

    c_orden = _detectar(col_orden, ("orden", "nota", "referencia", "order", "ref", "id"))
    c_neto = _detectar(col_neto, ("neto", "pagado", "deposito", "depósito", "liquidado", "monto", "amount"))

    # Mapa de registros VentaCasheaFinanzas por numero_nota y por referencia de pago Cashea
    todos_cashea = (
        bd.query(VentaCasheaFinanzas)
        .options(joinedload(VentaCasheaFinanzas.cliente))
        .all()
    )
    mapa_por_clave: dict[str, VentaCasheaFinanzas] = {}
    for reg in todos_cashea:
        mapa_por_clave[reg.numero_nota.strip().upper()] = reg
        if reg.referencia_cobro:
            mapa_por_clave[reg.referencia_cobro.strip().upper()] = reg

    pagos_cashea = (
        bd.query(Pago)
        .filter(Pago.tipo_documento == TipoDocumentoPago.CASHEA.value, Pago.anulado.is_(False))
        .all()
    )
    por_venta_id = {reg.venta_id: reg for reg in todos_cashea}
    for p in pagos_cashea:
        if p.referencia and p.venta_id in por_venta_id:
            mapa_por_clave[p.referencia.strip().upper()] = por_venta_id[p.venta_id]

    filas_out: list[dict[str, Any]] = []
    listas = 0
    ya_cobradas = 0
    no_encontradas = 0

    for idx, row in enumerate(filas_raw, start=2):
        clave_raw = str(row.get(c_orden) or "").strip()
        if not clave_raw:
            continue
        monto_pagado = _parse_monto_cashea(row.get(c_neto))
        reg = mapa_por_clave.get(clave_raw.upper())
        if reg is None:
            no_encontradas += 1
            filas_out.append(
                {
                    "fila": idx,
                    "cashea_id": None,
                    "venta_id": None,
                    "cashea_numero_orden": clave_raw,
                    "numero_nota": "",
                    "cliente": "No encontrada",
                    "neto_esperado_usd": 0.0,
                    "monto_pagado_real_usd": _r2(monto_pagado),
                    "diferencia_usd": 0.0,
                    "estado_cruce": "NO_ENCONTRADA",
                }
            )
            continue

        esperado = max(Decimal("0"), _q2(Decimal(reg.cashea_neto_por_cobrar_usd or 0) - Decimal(reg.monto_cobrado_usd or 0)))
        if reg.estado == "COBRADO" or esperado <= Decimal("0.01"):
            ya_cobradas += 1
            estado_cruce = "YA_COBRADA"
        else:
            listas += 1
            estado_cruce = "LISTA_PARA_CONCILIAR"

        filas_out.append(
            {
                "fila": idx,
                "cashea_id": reg.id,
                "venta_id": reg.venta_id,
                "cashea_numero_orden": clave_raw,
                "numero_nota": reg.numero_nota,
                "cliente": reg.cliente.nombre if reg.cliente else "Cliente general",
                "neto_esperado_usd": _r2(esperado),
                "monto_pagado_real_usd": _r2(monto_pagado if monto_pagado > 0 else esperado),
                "diferencia_usd": _r2((monto_pagado if monto_pagado > 0 else esperado) - esperado),
                "estado_cruce": estado_cruce,
            }
        )

    return {
        "nombre_archivo": nombre,
        "columnas": columnas,
        "mapeo_detectado": {"col_orden": c_orden, "col_neto": c_neto},
        "resumen": {
            "total_filas": len(filas_out),
            "listas_para_conciliar": listas,
            "ya_cobradas": ya_cobradas,
            "no_encontradas": no_encontradas,
        },
        "filas": filas_out,
    }


class OrdenCasheaLoteItem(BaseModel):
    cashea_id: int
    cashea_numero_orden: str = ""
    monto_pagado_real_usd: Decimal = Field(gt=Decimal("0"))


class ConfirmarLiquidacionCasheaLoteEntrada(BaseModel):
    nombre_archivo: str = ""
    instrumento_destino_id: int
    fecha_deposito: date | None = None
    referencia_bancaria: str = Field(default="", max_length=120)
    ordenes: list[OrdenCasheaLoteItem] = Field(min_length=1)


@enrutador.post("/importar-reporte/confirmar")
def confirmar_liquidacion_cashea_lote(
    datos: ConfirmarLiquidacionCasheaLoteEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Liquida en lote las órdenes Cashea seleccionadas, ingresa 1 depósito en banco y genera asiento contable."""
    inst = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.id == datos.instrumento_destino_id, InstrumentoFinanciero.activo.is_(True))
        .first()
    )
    if inst is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instrumento destino no encontrado.")

    fecha_op = datos.fecha_deposito or obtener_fecha_hoy()
    tasa = bd.query(TasaDiaria).filter(TasaDiaria.fecha == fecha_op).first() or bd.query(TasaDiaria).order_by(TasaDiaria.fecha.desc()).first()
    tasa_bcv = Decimal(tasa.tasa_bcv) if tasa else Decimal("1")
    tasa_usdt = Decimal(tasa.tasa_usdt) if tasa else Decimal("1")

    total_pagado = Decimal("0")
    total_cxc_cancelado = Decimal("0")
    notas_conciliadas = 0
    notas_lista: list[str] = []

    for ord_item in datos.ordenes:
        reg = bd.query(VentaCasheaFinanzas).filter(VentaCasheaFinanzas.id == ord_item.cashea_id).first()
        if reg is None or reg.estado == "COBRADO":
            continue
        pendiente = max(Decimal("0"), _q2(Decimal(reg.cashea_neto_por_cobrar_usd or 0) - Decimal(reg.monto_cobrado_usd or 0)))
        pagado = _q2(ord_item.monto_pagado_real_usd)
        reg.monto_cobrado_usd = _q2(Decimal(reg.monto_cobrado_usd or 0) + pagado)
        reg.estado = "COBRADO"
        reg.fecha_cobro = fecha_op
        reg.instrumento_cobro_id = inst.id
        reg.referencia_cobro = datos.referencia_bancaria.strip() or f"LOTE-CASHEA-{fecha_op.isoformat()}"

        if reg.cxc_id is not None:
            cxc = bd.query(CuentaPorCobrar).filter(CuentaPorCobrar.id == reg.cxc_id).first()
            if cxc is not None:
                cxc.saldo_pendiente_usd = Decimal("0")
                cxc.estado = EstadoCuentaPorCobrar.PAGADA.value

        total_pagado += pagado
        total_cxc_cancelado += pendiente
        notas_conciliadas += 1
        notas_lista.append(reg.numero_nota)

    if notas_conciliadas == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No hay órdenes pendientes válidas para conciliar.")

    monto_origen = _q2(total_pagado * tasa_bcv) if inst.moneda == MonedaInstrumento.BS.value else total_pagado
    pago = Pago(
        venta_id=None,
        instrumento_id=inst.id,
        fecha=fecha_op,
        tipo_movimiento=TipoMovimientoPago.INGRESO.value,
        tipo_documento=TipoDocumentoPago.CASHEA.value,
        monto_moneda_origen=monto_origen,
        moneda=inst.moneda,
        tasa_bcv_dia=tasa_bcv,
        tasa_usdt_dia=tasa_usdt,
        usd_nominal=total_pagado,
        usd_real=total_pagado,
        cubre_promo_usd=Decimal("0"),
        referencia=datos.referencia_bancaria.strip() or f"LOTE-CASHEA-{notas_conciliadas}",
        estado_verificacion=EstadoVerificacionPago.CONFIRMADO.value,
        verificado_por_id=usuario_actual.id,
        categoria="Cobro Cashea Lote",
        origen_tipo="CASHEA_LOTE",
        nota=f"Liquidación en lote Cashea ({notas_conciliadas} notas: {', '.join(notas_lista[:8])})",
    )
    bd.add(pago)
    bd.flush()

    lineas_asiento: list[dict[str, Any]] = [
        {"cuenta_codigo": "1.1.01", "debe_usd": total_pagado, "haber_usd": 0, "nota": f"Depósito lote Cashea en {inst.nombre}"},
        {"cuenta_codigo": "1.1.02", "debe_usd": 0, "haber_usd": total_cxc_cancelado, "nota": f"Cancelación CxC Cashea ({notas_conciliadas} notas)"},
    ]
    diff = _q2(total_cxc_cancelado - total_pagado)
    if diff > Decimal("0"):
        lineas_asiento.append({"cuenta_codigo": "8.1.01", "debe_usd": diff, "haber_usd": 0, "nota": "Ajuste diferencial liquidación Cashea"})
    elif diff < Decimal("0"):
        lineas_asiento.append({"cuenta_codigo": "4.2.01", "debe_usd": 0, "haber_usd": abs(diff), "nota": "Excedente liquidación Cashea"})

    asiento = crear_asiento_contable(
        bd=bd,
        usuario=usuario_actual,
        fecha_op=fecha_op,
        descripcion=f"Liquidación en Lote Cashea ({notas_conciliadas} notas · {inst.nombre})",
        origen_tipo="COBRO_CASHEA_LOTE",
        origen_id=pago.id,
        lineas=lineas_asiento,
    )
    bd.commit()

    return {
        "pago_id": pago.id,
        "asiento_id": asiento.id,
        "notas_conciliadas": notas_conciliadas,
        "total_pagado_real_usd": _r2(total_pagado),
        "diferencia_usd": _r2(total_pagado - total_cxc_cancelado),
    }
