from __future__ import annotations

import io
import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pydantic import BaseModel, Field
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.core.brand import dibujar_encabezado_y_marca_agua_alfa
from app.modelos import Sucursal, TasaDiaria, Usuario
from app.modelos_admin import (
    ActivoFijo,
    AuditLog,
    ConciliacionBancaria,
    ContratoPoliza,
    FacturaGastoFiscal,
    Nomina,
    NominaDetalle,
    ObligacionLegal,
    RetencionFiscal,
)
from app.modelos_finanzas import (
    EstadoLiquidacionComision,
    EstadoMovimientoTesoreria,
    EstadoVenta,
    EstadoVerificacionPago,
    ExtractoBancario,
    InstrumentoFinanciero,
    LiquidacionComision,
    MonedaInstrumento,
    MovimientoTesoreria,
    Pago,
    TipoDocumentoPago,
    TipoMovimientoPago,
    Venta,
    VentaDetalle,
)
from app.rutas.logistica import generar_correlativo
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import requerir_admin, requerir_direccion_lectura


enrutador = APIRouter(prefix="/api/admin", tags=["Departamento de Administración y Finanzas"])


def _q2(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _r2(valor: Decimal) -> float:
    return float(_q2(valor))


def _tasa_bcv_fecha(bd: Session, fecha_ref: date) -> Decimal:
    t = bd.query(TasaDiaria).filter(TasaDiaria.fecha <= fecha_ref).order_by(TasaDiaria.fecha.desc()).first()
    if t and t.tasa_bcv and t.tasa_bcv > 0:
        return Decimal(t.tasa_bcv)
    return Decimal("1")


def registrar_auditoria(
    bd: Session,
    usuario: Usuario,
    modulo: str,
    accion: str,
    entidad_id: int | str,
    datos_anteriores: dict[str, Any] | None = None,
    datos_nuevos: dict[str, Any] | None = None,
) -> None:
    """Registra una entrada inmutable en audit_logs."""
    bd.add(
        AuditLog(
            usuario_id=usuario.id,
            usuario_nombre=usuario.nombre,
            rol=usuario.rol,
            modulo=modulo.upper(),
            accion=accion.upper(),
            entidad_id=str(entidad_id),
            datos_anteriores_json=json.dumps(datos_anteriores or {}, default=str, ensure_ascii=False),
            datos_nuevos_json=json.dumps(datos_nuevos or {}, default=str, ensure_ascii=False),
        )
    )


def _descontar_en_tesoreria(
    bd: Session,
    usuario: Usuario,
    instrumento_id: int,
    monto_usd: Decimal,
    fecha_op: date,
    categoria: str,
    origen_tipo: str,
    origen_id: int,
    referencia: str,
    nota: str,
) -> Pago:
    inst = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.id == instrumento_id, InstrumentoFinanciero.activo.is_(True))
        .first()
    )
    if inst is None:
        raise HTTPException(status_code=404, detail="Instrumento financiero no encontrado.")

    tasa_bcv = _tasa_bcv_fecha(bd, fecha_op)
    monto_origen = _q2(monto_usd * tasa_bcv) if inst.moneda == MonedaInstrumento.BS.value else _q2(monto_usd)

    pago = Pago(
        instrumento_id=inst.id,
        fecha=fecha_op,
        tipo_movimiento=TipoMovimientoPago.EGRESO.value,
        tipo_documento=TipoDocumentoPago.GASTO.value,
        monto_moneda_origen=monto_origen,
        moneda=inst.moneda,
        tasa_bcv_dia=tasa_bcv,
        tasa_usdt_dia=tasa_bcv,
        usd_nominal=_q2(monto_usd),
        usd_real=_q2(monto_usd),
        cubre_promo_usd=_q2(monto_usd),
        referencia=referencia.strip(),
        estado_verificacion=EstadoVerificacionPago.CONFIRMADO.value,
        verificado_por_id=usuario.id,
        anulado=False,
        categoria=categoria,
        origen_tipo=origen_tipo,
        origen_id=origen_id,
        nota=nota,
    )
    bd.add(pago)
    bd.flush()
    return pago


# ---------------- 1. Gastos Operativos, Servicios y CxP ----------------


class FacturaGastoCrearEntrada(BaseModel):
    rif_proveedor: str = Field(default="", max_length=40)
    razon_social: str = Field(min_length=2, max_length=180)
    numero_factura: str = Field(default="", max_length=60)
    numero_control: str = Field(default="", max_length=60)
    fecha_emision: date | None = None
    fecha_vencimiento: date | None = None
    categoria: str = Field(default="Varios", max_length=80)
    es_deducible: bool = True
    es_recurrente: bool = False
    base_imponible_bs: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    monto_exento_bs: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    alicuota_iva: Decimal = Field(default=Decimal("16.00"), ge=Decimal("0"))
    igtf_bs: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    tasa_bcv_fecha: Decimal | None = Field(default=None, gt=Decimal("0"))
    observaciones: str = Field(default="", max_length=500)


class PagarGastoEntrada(BaseModel):
    instrumento_pago_id: int
    monto_usd: Decimal = Field(gt=Decimal("0"))
    referencia: str = Field(default="", max_length=120)
    nota: str = Field(default="", max_length=255)


@enrutador.get("/gastos")
def listar_gastos(
    estado: str | None = Query(default=None),
    categoria: str | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    q = bd.query(FacturaGastoFiscal).order_by(FacturaGastoFiscal.fecha_emision.desc(), FacturaGastoFiscal.id.desc())
    if estado:
        q = q.filter(FacturaGastoFiscal.estado == estado.upper())
    if categoria:
        q = q.filter(FacturaGastoFiscal.categoria == categoria)
    filas = q.limit(200).all()
    return [
        {
            "id": f.id,
            "rif_proveedor": f.rif_proveedor,
            "razon_social": f.razon_social,
            "numero_factura": f.numero_factura,
            "numero_control": f.numero_control,
            "fecha_emision": f.fecha_emision.isoformat(),
            "fecha_vencimiento": f.fecha_vencimiento.isoformat() if f.fecha_vencimiento else None,
            "categoria": f.categoria,
            "es_deducible": f.es_deducible,
            "es_recurrente": f.es_recurrente,
            "base_imponible_bs": _r2(f.base_imponible_bs),
            "monto_exento_bs": _r2(f.monto_exento_bs),
            "alicuota_iva": float(f.alicuota_iva),
            "monto_iva_bs": _r2(f.monto_iva_bs),
            "igtf_bs": _r2(f.igtf_bs),
            "monto_total_bs": _r2(f.monto_total_bs),
            "tasa_bcv_fecha": float(f.tasa_bcv_fecha),
            "monto_total_usd": _r2(f.monto_total_usd),
            "monto_pagado_usd": _r2(f.monto_pagado_usd),
            "saldo_pendiente_usd": _r2(max(Decimal("0"), f.monto_total_usd - f.monto_pagado_usd)),
            "estado": f.estado,
            "observaciones": f.observaciones,
        }
        for f in filas
    ]


@enrutador.post("/gastos", status_code=status.HTTP_201_CREATED)
def crear_factura_gasto(
    datos: FacturaGastoCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    fecha_em = datos.fecha_emision or obtener_fecha_hoy()
    tasa = datos.tasa_bcv_fecha or _tasa_bcv_fecha(bd, fecha_em)
    iva_bs = _q2(datos.base_imponible_bs * (datos.alicuota_iva / Decimal("100")))
    total_bs = _q2(datos.base_imponible_bs + datos.monto_exento_bs + iva_bs + datos.igtf_bs)
    total_usd = _q2(total_bs / tasa) if tasa > 0 else Decimal("0")

    gasto = FacturaGastoFiscal(
        rif_proveedor=datos.rif_proveedor.strip().upper(),
        razon_social=datos.razon_social.strip(),
        numero_factura=datos.numero_factura.strip(),
        numero_control=datos.numero_control.strip(),
        fecha_emision=fecha_em,
        fecha_vencimiento=datos.fecha_vencimiento,
        categoria=datos.categoria.strip(),
        es_deducible=datos.es_deducible,
        es_recurrente=datos.es_recurrente,
        base_imponible_bs=_q2(datos.base_imponible_bs),
        monto_exento_bs=_q2(datos.monto_exento_bs),
        alicuota_iva=datos.alicuota_iva,
        monto_iva_bs=iva_bs,
        igtf_bs=_q2(datos.igtf_bs),
        monto_total_bs=total_bs,
        tasa_bcv_fecha=tasa,
        monto_total_usd=total_usd,
        monto_pagado_usd=Decimal("0"),
        estado="PENDIENTE",
        observaciones=datos.observaciones.strip(),
        registrado_por_id=usuario_actual.id,
    )
    bd.add(gasto)
    bd.flush()
    registrar_auditoria(
        bd,
        usuario_actual,
        "GASTOS_CXP",
        "CREAR",
        gasto.id,
        datos_nuevos={"razon_social": gasto.razon_social, "monto_total_usd": float(total_usd)},
    )
    bd.commit()
    return {
        "id": gasto.id,
        "razon_social": gasto.razon_social,
        "monto_iva_bs": _r2(iva_bs),
        "monto_total_bs": _r2(total_bs),
        "monto_total_usd": _r2(total_usd),
        "estado": gasto.estado,
    }


@enrutador.post("/gastos/{gasto_id}/pagar")
def pagar_factura_gasto(
    gasto_id: int,
    datos: PagarGastoEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    gasto = bd.query(FacturaGastoFiscal).filter(FacturaGastoFiscal.id == gasto_id).first()
    if gasto is None:
        raise HTTPException(status_code=404, detail="Factura de gasto no encontrada.")
    if gasto.estado == "PAGADA":
        raise HTTPException(status_code=400, detail="Esta factura ya está pagada en su totalidad.")

    pendiente = gasto.monto_total_usd - gasto.monto_pagado_usd
    if datos.monto_usd > pendiente + Decimal("0.01"):
        raise HTTPException(
            status_code=400,
            detail=f"El monto excede el saldo pendiente (${_r2(pendiente):.2f}).",
        )

    estado_ant = gasto.estado
    pago = _descontar_en_tesoreria(
        bd=bd,
        usuario=usuario_actual,
        instrumento_id=datos.instrumento_pago_id,
        monto_usd=datos.monto_usd,
        fecha_op=obtener_fecha_hoy(),
        categoria=f"Gasto · {gasto.categoria}",
        origen_tipo="FACTURA_GASTO",
        origen_id=gasto.id,
        referencia=datos.referencia or gasto.numero_factura,
        nota=datos.nota or f"Pago a {gasto.razon_social} ({gasto.numero_factura})",
    )
    gasto.monto_pagado_usd = _q2(gasto.monto_pagado_usd + datos.monto_usd)
    gasto.estado = "PAGADA" if gasto.monto_pagado_usd >= gasto.monto_total_usd - Decimal("0.01") else "PARCIAL"

    registrar_auditoria(
        bd,
        usuario_actual,
        "GASTOS_CXP",
        "PAGAR",
        gasto.id,
        datos_anteriores={"estado": estado_ant},
        datos_nuevos={"estado": gasto.estado, "monto_pagado_usd": float(gasto.monto_pagado_usd), "pago_id": pago.id},
    )
    bd.commit()
    return {
        "id": gasto.id,
        "estado": gasto.estado,
        "monto_pagado_usd": _r2(gasto.monto_pagado_usd),
        "pago_id": pago.id,
    }


# ---------------- 2. Fiscal y Tributario (Libros IVA, Retenciones, Obligaciones) ----------------


@enrutador.get("/fiscal/libros")
def obtener_libros_iva(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    hoy = obtener_fecha_hoy()
    f_fin = fecha_fin or hoy
    f_ini = fecha_inicio or date(f_fin.year, f_fin.month, 1)

    compras = (
        bd.query(FacturaGastoFiscal)
        .filter(
            FacturaGastoFiscal.es_deducible.is_(True),
            FacturaGastoFiscal.fecha_emision >= f_ini,
            FacturaGastoFiscal.fecha_emision <= f_fin,
            FacturaGastoFiscal.estado != "ANULADA",
        )
        .order_by(FacturaGastoFiscal.fecha_emision.asc())
        .all()
    )
    ventas = (
        bd.query(Venta)
        .options(joinedload(Venta.cliente))
        .filter(
            Venta.es_factura.is_(True),
            Venta.fecha >= f_ini,
            Venta.fecha <= f_fin,
            Venta.estado.notin_([EstadoVenta.ANULADA.value, EstadoVenta.DEVUELTA.value]),
        )
        .order_by(Venta.fecha.asc())
        .all()
    )

    libro_compras = [
        {
            "fecha": c.fecha_emision.isoformat(),
            "rif": c.rif_proveedor,
            "razon_social": c.razon_social,
            "numero_factura": c.numero_factura,
            "numero_control": c.numero_control,
            "base_imponible_bs": _r2(c.base_imponible_bs),
            "exento_bs": _r2(c.monto_exento_bs),
            "alicuota": float(c.alicuota_iva),
            "iva_bs": _r2(c.monto_iva_bs),
            "igtf_bs": _r2(c.igtf_bs),
            "total_bs": _r2(c.monto_total_bs),
            "tasa_bcv": float(c.tasa_bcv_fecha),
            "total_usd": _r2(c.monto_total_usd),
        }
        for c in compras
    ]

    libro_ventas: list[dict[str, Any]] = []
    for v in ventas:
        tasa_v = Decimal(v.tasa_bcv_snapshot or 1)
        total_bs_v = _q2(Decimal(v.total_promo_usd or 0) * tasa_v)
        base_bs_v = _q2(total_bs_v / Decimal("1.16"))
        iva_bs_v = _q2(total_bs_v - base_bs_v)
        libro_ventas.append(
            {
                "fecha": v.fecha.isoformat(),
                "rif": v.cliente.rif_cedula if v.cliente else "V-00000000",
                "razon_social": v.cliente.nombre if v.cliente else "Consumidor Final",
                "numero_factura": v.numero_venta,
                "numero_control": v.numero_venta,
                "base_imponible_bs": _r2(base_bs_v),
                "exento_bs": 0.0,
                "alicuota": 16.0,
                "iva_bs": _r2(iva_bs_v),
                "total_bs": _r2(total_bs_v),
                "tasa_bcv": float(tasa_v),
                "total_usd": _r2(Decimal(v.total_promo_usd or 0)),
            }
        )

    credito_fiscal_bs = sum((Decimal(str(x["iva_bs"])) for x in libro_compras), Decimal("0"))
    debito_fiscal_bs = sum((Decimal(str(x["iva_bs"])) for x in libro_ventas), Decimal("0"))
    cuota_tributaria_bs = _q2(debito_fiscal_bs - credito_fiscal_bs)

    return {
        "periodo": {"fecha_inicio": f_ini.isoformat(), "fecha_fin": f_fin.isoformat()},
        "resumen": {
            "debito_fiscal_bs": _r2(debito_fiscal_bs),
            "credito_fiscal_bs": _r2(credito_fiscal_bs),
            "cuota_tributaria_bs": _r2(cuota_tributaria_bs),
            "facturas_compras": len(libro_compras),
            "facturas_ventas": len(libro_ventas),
        },
        "libro_compras": libro_compras,
        "libro_ventas": libro_ventas,
    }


@enrutador.get("/fiscal/libros/excel")
def exportar_libro_iva_excel(
    tipo: str = Query(pattern="^(COMPRAS|VENTAS)$"),
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> StreamingResponse:
    datos = obtener_libros_iva(fecha_inicio, fecha_fin, usuario, bd)
    filas = datos["libro_compras"] if tipo == "COMPRAS" else datos["libro_ventas"]

    wb = Workbook()
    ws = wb.active
    ws.title = f"Libro_{tipo}"
    ws.append([f"ALFA IMPORTACIONES, C.A. — RIF J-50793794-1 — LIBRO DE {tipo} (IVA)"])
    ws.append([f"Periodo: {datos['periodo']['fecha_inicio']} al {datos['periodo']['fecha_fin']}"])
    ws.append([])
    headers = [
        "Fecha",
        "RIF",
        "Razón Social",
        "Nro. Factura",
        "Nro. Control",
        "Base Imponible (Bs)",
        "Exento (Bs)",
        "Alícuota (%)",
        "IVA (Bs)",
        "Total (Bs)",
        "Tasa BCV",
        "Equivalente USD",
    ]
    ws.append(headers)
    fill = PatternFill(start_color="003566", end_color="003566", fill_type="solid")
    for idx in range(1, len(headers) + 1):
        c = ws.cell(row=4, column=idx)
        c.fill = fill
        c.font = Font(color="FFFFFF", bold=True)
        c.alignment = Alignment(horizontal="center")

    for r in filas:
        ws.append([
            r["fecha"],
            r["rif"],
            r["razon_social"],
            r["numero_factura"],
            r["numero_control"],
            r["base_imponible_bs"],
            r["exento_bs"],
            r["alicuota"],
            r["iva_bs"],
            r["total_bs"],
            r["tasa_bcv"],
            r["total_usd"],
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="libro_{tipo.lower()}_iva.xlsx"'},
    )


class RetencionCrearEntrada(BaseModel):
    tipo: str = Field(pattern="^(IVA|ISLR)$")
    factura_gasto_id: int | None = None
    rif_sujeto: str = Field(min_length=4, max_length=40)
    razon_social: str = Field(min_length=2, max_length=180)
    numero_factura_ref: str = Field(default="", max_length=60)
    numero_control_ref: str = Field(default="", max_length=60)
    fecha_emision: date | None = None
    base_imponible_bs: Decimal = Field(gt=Decimal("0"))
    porcentaje_retencion: Decimal = Field(gt=Decimal("0"), le=Decimal("100"))
    concepto: str = Field(default="", max_length=200)


@enrutador.get("/fiscal/retenciones")
def listar_retenciones(
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    filas = bd.query(RetencionFiscal).order_by(RetencionFiscal.id.desc()).limit(150).all()
    return [
        {
            "id": r.id,
            "numero_comprobante": r.numero_comprobante,
            "tipo": r.tipo,
            "rif_sujeto": r.rif_sujeto,
            "razon_social": r.razon_social,
            "numero_factura_ref": r.numero_factura_ref,
            "fecha_emision": r.fecha_emision.isoformat(),
            "periodo_fiscal": r.periodo_fiscal,
            "base_imponible_bs": _r2(r.base_imponible_bs),
            "porcentaje_retencion": float(r.porcentaje_retencion),
            "monto_retenido_bs": _r2(r.monto_retenido_bs),
            "monto_retenido_usd": _r2(r.monto_retenido_usd),
            "concepto": r.concepto,
            "estado": r.estado,
        }
        for r in filas
    ]


@enrutador.post("/fiscal/retenciones", status_code=status.HTTP_201_CREATED)
def crear_retencion(
    datos: RetencionCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    fecha_em = datos.fecha_emision or obtener_fecha_hoy()
    periodo = fecha_em.strftime("%Y%m")
    count = bd.query(func.count(RetencionFiscal.id)).filter(RetencionFiscal.periodo_fiscal == periodo).scalar() or 0
    num_comp = f"{periodo}{int(count) + 1:08d}"

    tasa = _tasa_bcv_fecha(bd, fecha_em)
    retenido_bs = _q2(datos.base_imponible_bs * (datos.porcentaje_retencion / Decimal("100")))
    retenido_usd = _q2(retenido_bs / tasa) if tasa > 0 else Decimal("0")

    ret = RetencionFiscal(
        numero_comprobante=num_comp,
        tipo=datos.tipo,
        factura_gasto_id=datos.factura_gasto_id,
        rif_sujeto=datos.rif_sujeto.strip().upper(),
        razon_social=datos.razon_social.strip(),
        numero_factura_ref=datos.numero_factura_ref.strip(),
        numero_control_ref=datos.numero_control_ref.strip(),
        fecha_emision=fecha_em,
        periodo_fiscal=periodo,
        base_imponible_bs=_q2(datos.base_imponible_bs),
        porcentaje_retencion=datos.porcentaje_retencion,
        monto_retenido_bs=retenido_bs,
        monto_retenido_usd=retenido_usd,
        concepto=datos.concepto.strip() or f"Retención {datos.tipo}",
        registrado_por_id=usuario_actual.id,
    )
    bd.add(ret)
    bd.flush()
    registrar_auditoria(
        bd,
        usuario_actual,
        "FISCAL",
        "CREAR",
        ret.id,
        datos_nuevos={"comprobante": num_comp, "tipo": ret.tipo, "monto_retenido_bs": float(retenido_bs)},
    )
    bd.commit()
    return {
        "id": ret.id,
        "numero_comprobante": ret.numero_comprobante,
        "tipo": ret.tipo,
        "monto_retenido_bs": _r2(retenido_bs),
        "monto_retenido_usd": _r2(retenido_usd),
    }


@enrutador.get("/fiscal/retenciones/{retencion_id}/pdf")
def descargar_comprobante_retencion_pdf(
    retencion_id: int,
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> Response:
    ret = bd.query(RetencionFiscal).filter(RetencionFiscal.id == retencion_id).first()
    if ret is None:
        raise HTTPException(status_code=404, detail="Comprobante de retención no encontrado.")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = dibujar_encabezado_y_marca_agua_alfa(
        c,
        f"COMPROBANTE DE RETENCIÓN DE {ret.tipo}",
        f"Nro. Comprobante: {ret.numero_comprobante}  |  Fecha: {ret.fecha_emision.isoformat()}  |  Periodo: {ret.periodo_fiscal}",
    )
    c.setFont("Helvetica", 10)
    c.drawString(45, y, f"Sujeto Retenido: {ret.razon_social}")
    c.drawString(45, y - 16, f"RIF Sujeto Retenido: {ret.rif_sujeto}")
    c.drawString(45, y - 32, f"Factura Ref.: {ret.numero_factura_ref or '—'}   Control: {ret.numero_control_ref or '—'}")
    c.drawString(45, y - 48, f"Concepto: {ret.concepto}")

    c.line(45, y - 62, 565, y - 62)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(45, y - 82, f"Base Imponible / Impuesto: Bs. {float(ret.base_imponible_bs):,.2f}")
    c.drawString(45, y - 99, f"Porcentaje de Retención: {float(ret.porcentaje_retencion):.2f}%")
    c.drawString(45, y - 117, f"MONTO RETENIDO: Bs. {float(ret.monto_retenido_bs):,.2f}  (Ref. USD ${float(ret.monto_retenido_usd):,.2f})")

    c.setFont("Helvetica", 9)
    c.drawString(45, y - 180, "_______________________________                    _______________________________")
    c.drawString(45, y - 194, "Firma y Sello Agente de Retención                   Firma y Sello Sujeto Retenido")
    c.showPage()
    c.save()
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="retencion_{ret.numero_comprobante}.pdf"'},
    )


class ObligacionCrearEntrada(BaseModel):
    organismo: str = Field(pattern="^(SENIAT|ALCALDIA|PARAFISCAL|PERMISOLOGIA)$")
    tipo_obligacion: str = Field(min_length=2, max_length=120)
    descripcion: str = Field(default="", max_length=255)
    periodo: str = Field(default="", max_length=40)
    fecha_vencimiento: date
    monto_estimado_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))


class PagarObligacionEntrada(BaseModel):
    instrumento_pago_id: int
    monto_pagado_usd: Decimal = Field(gt=Decimal("0"))
    referencia_pago: str = Field(default="", max_length=120)


@enrutador.get("/fiscal/obligaciones")
def listar_obligaciones(
    organismo: str | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    q = bd.query(ObligacionLegal).order_by(ObligacionLegal.fecha_vencimiento.asc())
    if organismo:
        q = q.filter(ObligacionLegal.organismo == organismo.upper())
    return [
        {
            "id": o.id,
            "organismo": o.organismo,
            "tipo_obligacion": o.tipo_obligacion,
            "descripcion": o.descripcion,
            "periodo": o.periodo,
            "fecha_vencimiento": o.fecha_vencimiento.isoformat(),
            "monto_estimado_usd": _r2(o.monto_estimado_usd),
            "monto_pagado_usd": _r2(o.monto_pagado_usd),
            "estado": o.estado,
            "referencia_pago": o.referencia_pago,
            "fecha_pago": o.fecha_pago.isoformat() if o.fecha_pago else None,
        }
        for o in q.all()
    ]


@enrutador.post("/fiscal/obligaciones", status_code=status.HTTP_201_CREATED)
def crear_obligacion(
    datos: ObligacionCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    ob = ObligacionLegal(
        organismo=datos.organismo,
        tipo_obligacion=datos.tipo_obligacion.strip(),
        descripcion=datos.descripcion.strip(),
        periodo=datos.periodo.strip(),
        fecha_vencimiento=datos.fecha_vencimiento,
        monto_estimado_usd=_q2(datos.monto_estimado_usd),
        estado="PENDIENTE",
    )
    bd.add(ob)
    bd.flush()
    registrar_auditoria(
        bd,
        usuario_actual,
        "OBLIGACIONES_LEGALES",
        "CREAR",
        ob.id,
        datos_nuevos={"organismo": ob.organismo, "tipo": ob.tipo_obligacion, "vencimiento": ob.fecha_vencimiento.isoformat()},
    )
    bd.commit()
    return {"id": ob.id, "organismo": ob.organismo, "tipo_obligacion": ob.tipo_obligacion, "estado": ob.estado}


@enrutador.post("/fiscal/obligaciones/{obligacion_id}/pagar")
def pagar_obligacion(
    obligacion_id: int,
    datos: PagarObligacionEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    ob = bd.query(ObligacionLegal).filter(ObligacionLegal.id == obligacion_id).first()
    if ob is None:
        raise HTTPException(status_code=404, detail="Obligación legal no encontrada.")
    if ob.estado == "PAGADA":
        raise HTTPException(status_code=400, detail="Esta obligación ya fue pagada.")

    hoy = obtener_fecha_hoy()
    pago = _descontar_en_tesoreria(
        bd=bd,
        usuario=usuario_actual,
        instrumento_id=datos.instrumento_pago_id,
        monto_usd=datos.monto_pagado_usd,
        fecha_op=hoy,
        categoria=f"Impuesto/Parafiscal · {ob.organismo}",
        origen_tipo="OBLIGACION_LEGAL",
        origen_id=ob.id,
        referencia=datos.referencia_pago or ob.tipo_obligacion,
        nota=f"Pago {ob.organismo} - {ob.tipo_obligacion} ({ob.periodo})",
    )
    ob.estado = "PAGADA"
    ob.monto_pagado_usd = _q2(datos.monto_pagado_usd)
    ob.instrumento_pago_id = datos.instrumento_pago_id
    ob.pago_id = pago.id
    ob.referencia_pago = datos.referencia_pago.strip()
    ob.fecha_pago = hoy

    registrar_auditoria(
        bd,
        usuario_actual,
        "OBLIGACIONES_LEGALES",
        "PAGAR",
        ob.id,
        datos_anteriores={"estado": "PENDIENTE"},
        datos_nuevos={"estado": "PAGADA", "monto_pagado_usd": float(ob.monto_pagado_usd), "pago_id": pago.id},
    )
    bd.commit()
    return {"id": ob.id, "estado": ob.estado, "pago_id": pago.id, "monto_pagado_usd": _r2(ob.monto_pagado_usd)}


# ---------------- 3. Nómina, RRHH y Parafiscales (LOTTT) ----------------


class NominaItemEntrada(BaseModel):
    personal_id: int
    bonos_extras_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    otras_deducciones_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    observacion: str = Field(default="", max_length=255)


class NominaCrearEntrada(BaseModel):
    tipo_periodo: str = Field(default="QUINCENAL", pattern="^(QUINCENAL|MENSUAL)$")
    fecha_inicio: date
    fecha_fin: date
    observaciones: str = Field(default="", max_length=400)
    items: list[NominaItemEntrada] = Field(min_length=1)


class PagarNominaEntrada(BaseModel):
    instrumento_pago_id: int
    referencia_pago: str = Field(default="", max_length=120)


@enrutador.get("/nominas")
def listar_nominas(
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    nominas = (
        bd.query(Nomina)
        .options(joinedload(Nomina.detalles))
        .order_by(Nomina.id.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": n.id,
            "codigo": n.codigo,
            "tipo_periodo": n.tipo_periodo,
            "fecha_inicio": n.fecha_inicio.isoformat(),
            "fecha_fin": n.fecha_fin.isoformat(),
            "tasa_bcv_aplicada": float(n.tasa_bcv_aplicada),
            "total_asignaciones_usd": _r2(n.total_asignaciones_usd),
            "total_deducciones_usd": _r2(n.total_deducciones_usd),
            "total_neto_usd": _r2(n.total_neto_usd),
            "estado": n.estado,
            "referencia_pago": n.referencia_pago,
            "detalles": [
                {
                    "id": d.id,
                    "personal_id": d.personal_id,
                    "nombre_trabajador": d.nombre_trabajador,
                    "cargo": d.cargo,
                    "salario_periodo_usd": _r2(d.salario_periodo_usd),
                    "cestaticket_usd": _r2(d.cestaticket_usd),
                    "bonos_extras_usd": _r2(d.bonos_extras_usd),
                    "ivss_usd": _r2(d.ivss_usd),
                    "rpe_usd": _r2(d.rpe_usd),
                    "faov_usd": _r2(d.faov_usd),
                    "otras_deducciones_usd": _r2(d.otras_deducciones_usd),
                    "neto_pagar_usd": _r2(d.neto_pagar_usd),
                    "neto_pagar_bs": _r2(d.neto_pagar_bs),
                }
                for d in n.detalles
            ],
        }
        for n in nominas
    ]


@enrutador.post("/nominas", status_code=status.HTTP_201_CREATED)
def crear_nomina(
    datos: NominaCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    factor = Decimal("0.5") if datos.tipo_periodo == "QUINCENAL" else Decimal("1")
    tasa_bcv = _tasa_bcv_fecha(bd, datos.fecha_fin)
    codigo = generar_correlativo(bd, Nomina, Nomina.codigo, "NOM")

    nom = Nomina(
        codigo=codigo,
        tipo_periodo=datos.tipo_periodo,
        fecha_inicio=datos.fecha_inicio,
        fecha_fin=datos.fecha_fin,
        tasa_bcv_aplicada=tasa_bcv,
        estado="BORRADOR",
        observaciones=datos.observaciones.strip(),
        creado_por_id=usuario_actual.id,
    )
    bd.add(nom)
    bd.flush()

    tot_asig = Decimal("0")
    tot_ded = Decimal("0")
    tot_neto = Decimal("0")

    for it in datos.items:
        persona = bd.query(Usuario).filter(Usuario.id == it.personal_id).first()
        if persona is None:
            raise HTTPException(status_code=404, detail=f"Personal ID {it.personal_id} no encontrado.")
        sal_per = _q2(Decimal(persona.salario_base_usd or 0) * factor)
        cesta = _q2(Decimal(persona.bono_alimentacion_usd or 0) * factor)
        bonos = _q2(Decimal(persona.bonos_fijos_usd or 0) * factor + it.bonos_extras_usd)
        asig = sal_per + cesta + bonos

        # Deducciones legales Venezuela (LOTTT) sobre salario base del periodo
        ivss = _q2(sal_per * Decimal("0.04"))
        rpe = _q2(sal_per * Decimal("0.005"))
        faov = _q2(sal_per * Decimal("0.01"))
        ded = ivss + rpe + faov + _q2(it.otras_deducciones_usd)
        neto_usd = max(Decimal("0"), _q2(asig - ded))
        neto_bs = _q2(neto_usd * tasa_bcv)

        bd.add(
            NominaDetalle(
                nomina_id=nom.id,
                personal_id=persona.id,
                nombre_trabajador=persona.nombre,
                cargo=persona.cargo or persona.rol,
                salario_periodo_usd=sal_per,
                cestaticket_usd=cesta,
                bonos_extras_usd=bonos,
                ivss_usd=ivss,
                rpe_usd=rpe,
                faov_usd=faov,
                otras_deducciones_usd=_q2(it.otras_deducciones_usd),
                neto_pagar_usd=neto_usd,
                neto_pagar_bs=neto_bs,
                observacion=it.observacion.strip(),
            )
        )
        tot_asig += asig
        tot_ded += ded
        tot_neto += neto_usd

    nom.total_asignaciones_usd = _q2(tot_asig)
    nom.total_deducciones_usd = _q2(tot_ded)
    nom.total_neto_usd = _q2(tot_neto)

    registrar_auditoria(
        bd,
        usuario_actual,
        "NOMINA",
        "CREAR",
        nom.id,
        datos_nuevos={"codigo": codigo, "total_neto_usd": float(tot_neto)},
    )
    bd.commit()
    return {
        "id": nom.id,
        "codigo": nom.codigo,
        "total_asignaciones_usd": _r2(tot_asig),
        "total_deducciones_usd": _r2(tot_ded),
        "total_neto_usd": _r2(tot_neto),
        "estado": nom.estado,
    }


@enrutador.post("/nominas/{nomina_id}/pagar")
def pagar_nomina(
    nomina_id: int,
    datos: PagarNominaEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    nom = bd.query(Nomina).filter(Nomina.id == nomina_id).first()
    if nom is None:
        raise HTTPException(status_code=404, detail="Nómina no encontrada.")
    if nom.estado == "PAGADA":
        raise HTTPException(status_code=400, detail="Esta nómina ya fue pagada.")

    pago = _descontar_en_tesoreria(
        bd=bd,
        usuario=usuario_actual,
        instrumento_id=datos.instrumento_pago_id,
        monto_usd=nom.total_neto_usd,
        fecha_op=obtener_fecha_hoy(),
        categoria="Nómina y Personal",
        origen_tipo="NOMINA",
        origen_id=nom.id,
        referencia=datos.referencia_pago or nom.codigo,
        nota=f"Pago Nómina {nom.codigo} ({nom.fecha_inicio} al {nom.fecha_fin})",
    )
    nom.estado = "PAGADA"
    nom.instrumento_pago_id = datos.instrumento_pago_id
    nom.pago_id = pago.id
    nom.referencia_pago = datos.referencia_pago.strip()

    registrar_auditoria(
        bd,
        usuario_actual,
        "NOMINA",
        "PAGAR",
        nom.id,
        datos_anteriores={"estado": "BORRADOR"},
        datos_nuevos={"estado": "PAGADA", "pago_id": pago.id, "total_neto_usd": float(nom.total_neto_usd)},
    )
    bd.commit()
    return {"id": nom.id, "codigo": nom.codigo, "estado": nom.estado, "pago_id": pago.id}


@enrutador.get("/nominas/{nomina_id}/recibo/{detalle_id}/pdf")
def descargar_recibo_nomina_pdf(
    nomina_id: int,
    detalle_id: int,
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> Response:
    det = (
        bd.query(NominaDetalle)
        .options(joinedload(NominaDetalle.nomina))
        .filter(NominaDetalle.id == detalle_id, NominaDetalle.nomina_id == nomina_id)
        .first()
    )
    if det is None:
        raise HTTPException(status_code=404, detail="Recibo de nómina no encontrado.")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = dibujar_encabezado_y_marca_agua_alfa(
        c,
        "RECIBO DE PAGO DE NÓMINA",
        f"Nómina: {det.nomina.codigo}  |  Periodo: {det.nomina.fecha_inicio} al {det.nomina.fecha_fin}",
    )
    c.setFont("Helvetica", 10)
    c.drawString(45, y, f"Trabajador: {det.nombre_trabajador}  |  Cargo: {det.cargo}")
    c.drawString(45, y - 20, f"Salario periodo: ${float(det.salario_periodo_usd):,.2f}   |   Cestaticket: ${float(det.cestaticket_usd):,.2f}   |   Bonos: ${float(det.bonos_extras_usd):,.2f}")
    c.drawString(45, y - 40, f"Deducciones LOTTT -> IVSS (4%): -${float(det.ivss_usd):,.2f} | RPE (0.5%): -${float(det.rpe_usd):,.2f} | FAOV (1%): -${float(det.faov_usd):,.2f} | Otras: -${float(det.otras_deducciones_usd):,.2f}")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(45, y - 70, f"NETO A PAGAR: ${float(det.neto_pagar_usd):,.2f} USD  (Bs. {float(det.neto_pagar_bs):,.2f})")
    c.setFont("Helvetica", 9)
    c.drawString(45, y - 135, "Firma del Trabajador: ___________________________   C.I.: _______________")
    c.showPage()
    c.save()
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="recibo_{det.nomina.codigo}_{det.id}.pdf"'},
    )


@enrutador.get("/nominas/provisiones")
def calcular_provisiones_laborales(
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    hoy = obtener_fecha_hoy()
    personal = bd.query(Usuario).filter(Usuario.activo.is_(True), Usuario.salario_base_usd > 0).all()
    filas: list[dict[str, Any]] = []
    tot_pasivo = Decimal("0")
    for p in personal:
        sal_mensual = Decimal(p.salario_base_usd or 0)
        sal_diario = sal_mensual / Decimal("30")
        meses_serv = max(1, int((hoy - p.fecha_ingreso).days / 30)) if p.fecha_ingreso else 1
        trimestres = max(1, meses_serv // 3)
        prestaciones = _q2(sal_diario * Decimal(15 * trimestres))
        vacaciones = _q2(sal_diario * Decimal("15") * (Decimal(min(12, meses_serv)) / Decimal("12")))
        utilidades = _q2(sal_diario * Decimal("30") * (Decimal(min(12, meses_serv)) / Decimal("12")))
        subtotal = prestaciones + vacaciones + utilidades
        tot_pasivo += subtotal
        filas.append(
            {
                "personal_id": p.id,
                "nombre": p.nombre,
                "cargo": p.cargo or p.rol,
                "fecha_ingreso": p.fecha_ingreso.isoformat() if p.fecha_ingreso else None,
                "salario_base_usd": _r2(sal_mensual),
                "prestaciones_usd": _r2(prestaciones),
                "vacaciones_usd": _r2(vacaciones),
                "utilidades_usd": _r2(utilidades),
                "total_pasivo_usd": _r2(subtotal),
            }
        )
    return {"total_pasivo_laboral_usd": _r2(tot_pasivo), "trabajadores": filas}


# ---------------- 4. Conciliación Bancaria ----------------


class ConciliacionCerrarEntrada(BaseModel):
    instrumento_id: int
    fecha_inicio: date
    fecha_fin: date
    saldo_banco: Decimal
    observaciones: str = Field(default="", max_length=400)


@enrutador.get("/conciliacion")
def obtener_conciliacion_bancaria(
    instrumento_id: int = Query(...),
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    hoy = obtener_fecha_hoy()
    f_fin = fecha_fin or hoy
    f_ini = fecha_inicio or date(f_fin.year, f_fin.month, 1)

    inst = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.id == instrumento_id).first()
    if inst is None:
        raise HTTPException(status_code=404, detail="Instrumento no encontrado.")

    pagos = (
        bd.query(Pago)
        .filter(
            Pago.instrumento_id == instrumento_id,
            Pago.anulado.is_(False),
            Pago.fecha >= f_ini,
            Pago.fecha <= f_fin,
        )
        .order_by(Pago.fecha.asc(), Pago.id.asc())
        .all()
    )
    extractos = (
        bd.query(ExtractoBancario)
        .filter(
            ExtractoBancario.instrumento_id == instrumento_id,
            ExtractoBancario.fecha >= f_ini,
            ExtractoBancario.fecha <= f_fin,
        )
        .order_by(ExtractoBancario.fecha.asc(), ExtractoBancario.id.asc())
        .all()
    )

    # Saldo en libros acumulado hasta fecha_fin
    pagos_hasta = (
        bd.query(Pago)
        .filter(Pago.instrumento_id == instrumento_id, Pago.anulado.is_(False), Pago.fecha <= f_fin)
        .all()
    )
    neto = sum(
        (
            Decimal(p.monto_moneda_origen) * (Decimal("-1") if p.tipo_movimiento == TipoMovimientoPago.EGRESO.value else Decimal("1"))
            for p in pagos_hasta
        ),
        Decimal("0"),
    )
    saldo_libros = _q2(Decimal(inst.saldo_inicial or 0) + neto)
    conciliados = sum(1 for p in pagos if p.conciliado)

    return {
        "instrumento": {"id": inst.id, "nombre": inst.nombre, "moneda": inst.moneda},
        "periodo": {"fecha_inicio": f_ini.isoformat(), "fecha_fin": f_fin.isoformat()},
        "saldo_libros": _r2(saldo_libros),
        "movimientos_sistema": len(pagos),
        "movimientos_conciliados": conciliados,
        "partidas_transito": len(pagos) - conciliados,
        "extractos_banco": [
            {
                "id": e.id,
                "fecha": e.fecha.isoformat(),
                "referencia": e.referencia,
                "descripcion": e.descripcion,
                "monto_con_signo": _r2(e.monto_con_signo),
                "conciliado": e.conciliado,
            }
            for e in extractos
        ],
    }


@enrutador.post("/conciliacion/cerrar", status_code=status.HTTP_201_CREATED)
def cerrar_conciliacion(
    datos: ConciliacionCerrarEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    res = obtener_conciliacion_bancaria(
        datos.instrumento_id, datos.fecha_inicio, datos.fecha_fin, usuario_actual, bd
    )
    saldo_lib = Decimal(str(res["saldo_libros"]))
    diferencia = _q2(datos.saldo_banco - saldo_lib)

    cierre = ConciliacionBancaria(
        instrumento_id=datos.instrumento_id,
        fecha_inicio=datos.fecha_inicio,
        fecha_fin=datos.fecha_fin,
        saldo_libros=saldo_lib,
        saldo_banco=_q2(datos.saldo_banco),
        diferencia=diferencia,
        movimientos_conciliados=res["movimientos_conciliados"],
        partidas_transito=res["partidas_transito"],
        observaciones=datos.observaciones.strip(),
        cerrado_por_id=usuario_actual.id,
    )
    bd.add(cierre)
    bd.flush()
    registrar_auditoria(
        bd,
        usuario_actual,
        "CONCILIACION",
        "CONCILIAR",
        cierre.id,
        datos_nuevos={"instrumento_id": datos.instrumento_id, "diferencia": float(diferencia)},
    )
    bd.commit()
    return {
        "id": cierre.id,
        "saldo_libros": _r2(saldo_lib),
        "saldo_banco": _r2(datos.saldo_banco),
        "diferencia": _r2(diferencia),
        "estado": cierre.estado,
    }


# ---------------- 5. Activos Fijos y Contratos ----------------


class ActivoFijoCrearEntrada(BaseModel):
    codigo_activo: str = Field(min_length=2, max_length=40)
    descripcion: str = Field(min_length=2, max_length=255)
    categoria: str = Field(default="Mobiliario", max_length=80)
    sucursal_id: int | None = None
    responsable: str = Field(default="", max_length=150)
    fecha_compra: date
    costo_usd: Decimal = Field(gt=Decimal("0"))
    vida_util_meses: int = Field(default=60, ge=1, le=600)
    estado: str = Field(default="ACTIVO", pattern="^(ACTIVO|EN_REPARACION|DESINCORPORADO)$")


@enrutador.get("/activos")
def listar_activos_fijos(
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    hoy = obtener_fecha_hoy()
    activos = bd.query(ActivoFijo).options(joinedload(ActivoFijo.sucursal)).order_by(ActivoFijo.id.desc()).all()
    resultado: list[dict[str, Any]] = []
    for a in activos:
        dep_mensual = _q2(a.costo_usd / Decimal(a.vida_util_meses))
        meses_trans = max(0, int((hoy - a.fecha_compra).days / 30))
        dep_acum = min(a.costo_usd, _q2(dep_mensual * Decimal(meses_trans)))
        valor_libros = max(Decimal("0"), _q2(a.costo_usd - dep_acum))
        resultado.append(
            {
                "id": a.id,
                "codigo_activo": a.codigo_activo,
                "descripcion": a.descripcion,
                "categoria": a.categoria,
                "sucursal": a.sucursal.nombre if a.sucursal else "General",
                "responsable": a.responsable,
                "fecha_compra": a.fecha_compra.isoformat(),
                "costo_usd": _r2(a.costo_usd),
                "vida_util_meses": a.vida_util_meses,
                "depreciacion_mensual_usd": _r2(dep_mensual),
                "depreciacion_acumulada_usd": _r2(dep_acum),
                "valor_libros_usd": _r2(valor_libros),
                "estado": a.estado,
            }
        )
    return resultado


@enrutador.post("/activos", status_code=status.HTTP_201_CREATED)
def crear_activo_fijo(
    datos: ActivoFijoCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    cod = datos.codigo_activo.strip().upper()
    if bd.query(ActivoFijo).filter(ActivoFijo.codigo_activo == cod).first():
        raise HTTPException(status_code=409, detail=f"El código de activo '{cod}' ya existe.")
    activo = ActivoFijo(
        codigo_activo=cod,
        descripcion=datos.descripcion.strip(),
        categoria=datos.categoria.strip(),
        sucursal_id=datos.sucursal_id,
        responsable=datos.responsable.strip(),
        fecha_compra=datos.fecha_compra,
        costo_usd=_q2(datos.costo_usd),
        vida_util_meses=datos.vida_util_meses,
        estado=datos.estado,
    )
    bd.add(activo)
    bd.flush()
    registrar_auditoria(bd, usuario_actual, "ACTIVOS_FIJOS", "CREAR", activo.id, datos_nuevos={"codigo": cod})
    bd.commit()
    return {"id": activo.id, "codigo_activo": activo.codigo_activo, "estado": activo.estado}


class ContratoCrearEntrada(BaseModel):
    tipo: str = Field(default="ARRENDAMIENTO", max_length=50)
    proveedor_contraparte: str = Field(min_length=2, max_length=160)
    descripcion: str = Field(min_length=2, max_length=255)
    fecha_inicio: date
    fecha_vencimiento: date
    canon_mensual_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    sucursal_id: int | None = None


@enrutador.get("/contratos")
def listar_contratos(
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    hoy = obtener_fecha_hoy()
    contratos = bd.query(ContratoPoliza).options(joinedload(ContratoPoliza.sucursal)).order_by(ContratoPoliza.fecha_vencimiento.asc()).all()
    return [
        {
            "id": c.id,
            "tipo": c.tipo,
            "proveedor_contraparte": c.proveedor_contraparte,
            "descripcion": c.descripcion,
            "fecha_inicio": c.fecha_inicio.isoformat(),
            "fecha_vencimiento": c.fecha_vencimiento.isoformat(),
            "canon_mensual_usd": _r2(c.canon_mensual_usd),
            "dias_para_vencer": (c.fecha_vencimiento - hoy).days,
            "alerta_vencimiento": (c.fecha_vencimiento - hoy).days <= 30,
            "estado": c.estado,
            "sucursal": c.sucursal.nombre if c.sucursal else "General",
        }
        for c in contratos
    ]


@enrutador.post("/contratos", status_code=status.HTTP_201_CREATED)
def crear_contrato(
    datos: ContratoCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    ct = ContratoPoliza(
        tipo=datos.tipo.strip().upper(),
        proveedor_contraparte=datos.proveedor_contraparte.strip(),
        descripcion=datos.descripcion.strip(),
        fecha_inicio=datos.fecha_inicio,
        fecha_vencimiento=datos.fecha_vencimiento,
        canon_mensual_usd=_q2(datos.canon_mensual_usd),
        sucursal_id=datos.sucursal_id,
    )
    bd.add(ct)
    bd.flush()
    registrar_auditoria(bd, usuario_actual, "CONTRATOS", "CREAR", ct.id, datos_nuevos={"contraparte": ct.proveedor_contraparte})
    bd.commit()
    return {"id": ct.id, "tipo": ct.tipo, "estado": ct.estado}


# ---------------- 6. Auditoría Inmutable y Estado de Resultados (P&L) ----------------


@enrutador.get("/auditoria")
def listar_auditoria(
    modulo: str | None = Query(default=None),
    accion: str | None = Query(default=None),
    usuario_id: int | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    q = bd.query(AuditLog).order_by(AuditLog.id.desc())
    if modulo:
        q = q.filter(AuditLog.modulo == modulo.upper())
    if accion:
        q = q.filter(AuditLog.accion == accion.upper())
    if usuario_id is not None:
        q = q.filter(AuditLog.usuario_id == usuario_id)
    return [
        {
            "id": a.id,
            "usuario_id": a.usuario_id,
            "usuario_nombre": a.usuario_nombre,
            "rol": a.rol,
            "fecha_hora": a.fecha_hora.isoformat() if a.fecha_hora else None,
            "modulo": a.modulo,
            "accion": a.accion,
            "entidad_id": a.entidad_id,
            "datos_anteriores": json.loads(a.datos_anteriores_json or "{}"),
            "datos_nuevos": json.loads(a.datos_nuevos_json or "{}"),
        }
        for a in q.limit(200).all()
    ]


@enrutador.get("/estado-resultados")
def obtener_estado_resultados(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    sucursal_id: int | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    hoy = obtener_fecha_hoy()
    f_fin = fecha_fin or hoy
    f_ini = fecha_inicio or date(f_fin.year, f_fin.month, 1)

    ventas_q = (
        bd.query(Venta)
        .options(joinedload(Venta.detalles))
        .filter(
            Venta.fecha >= f_ini,
            Venta.fecha <= f_fin,
            Venta.estado.notin_([EstadoVenta.ANULADA.value, EstadoVenta.DEVUELTA.value]),
        )
    )
    if sucursal_id is not None:
        ventas_q = ventas_q.filter(Venta.sucursal_id == sucursal_id)
    ventas = ventas_q.all()

    ingresos_ventas = sum((Decimal(v.total_promo_usd or 0) for v in ventas), Decimal("0"))
    costo_ventas = sum(
        (Decimal(d.costo_total_snapshot_usd or 0) for v in ventas for d in v.detalles),
        Decimal("0"),
    )
    utilidad_bruta = ingresos_ventas - costo_ventas

    gastos_operativos = sum(
        (
            Decimal(g.monto_total_usd or 0)
            for g in bd.query(FacturaGastoFiscal)
            .filter(
                FacturaGastoFiscal.fecha_emision >= f_ini,
                FacturaGastoFiscal.fecha_emision <= f_fin,
                FacturaGastoFiscal.estado != "ANULADA",
            )
            .all()
        ),
        Decimal("0"),
    )
    nomina_pagada = sum(
        (
            Decimal(n.total_neto_usd or 0)
            for n in bd.query(Nomina)
            .filter(
                Nomina.fecha_fin >= f_ini,
                Nomina.fecha_fin <= f_fin,
                Nomina.estado == "PAGADA",
            )
            .all()
        ),
        Decimal("0"),
    )
    comisiones_pagadas = sum(
        (
            Decimal(l.monto_total_usd or 0)
            for l in bd.query(LiquidacionComision)
            .filter(
                LiquidacionComision.fecha_fin >= f_ini,
                LiquidacionComision.fecha_fin <= f_fin,
                LiquidacionComision.estado == EstadoLiquidacionComision.PAGADA.value,
            )
            .all()
        ),
        Decimal("0"),
    )
    impuestos_pagados = sum(
        (
            Decimal(o.monto_pagado_usd or 0)
            for o in bd.query(ObligacionLegal)
            .filter(
                ObligacionLegal.fecha_pago >= f_ini,
                ObligacionLegal.fecha_pago <= f_fin,
                ObligacionLegal.estado == "PAGADA",
            )
            .all()
        ),
        Decimal("0"),
    )
    resultado_cambiario = sum(
        (
            Decimal(m.diferencial_usd or 0)
            for m in bd.query(MovimientoTesoreria)
            .filter(
                MovimientoTesoreria.fecha >= f_ini,
                MovimientoTesoreria.fecha <= f_fin,
                MovimientoTesoreria.estado == EstadoMovimientoTesoreria.CONFIRMADO.value,
            )
            .all()
        ),
        Decimal("0"),
    )

    utilidad_neta = (
        utilidad_bruta
        - gastos_operativos
        - nomina_pagada
        - comisiones_pagadas
        - impuestos_pagados
        + resultado_cambiario
    )

    return {
        "periodo": {"fecha_inicio": f_ini.isoformat(), "fecha_fin": f_fin.isoformat()},
        "ingresos_ventas_usd": _r2(ingresos_ventas),
        "costo_ventas_usd": _r2(costo_ventas),
        "utilidad_bruta_usd": _r2(utilidad_bruta),
        "gastos_operativos_usd": _r2(gastos_operativos),
        "nomina_usd": _r2(nomina_pagada),
        "comisiones_pagadas_usd": _r2(comisiones_pagadas),
        "impuestos_parafiscales_usd": _r2(impuestos_pagados),
        "resultado_cambiario_usd": _r2(resultado_cambiario),
        "utilidad_neta_operativa_usd": _r2(utilidad_neta),
    }


@enrutador.get("/estado-resultados/excel")
def exportar_pnl_excel(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> StreamingResponse:
    pnl = obtener_estado_resultados(fecha_inicio, fecha_fin, None, usuario, bd)
    wb = Workbook()
    ws = wb.active
    ws.title = "Estado_Resultados"
    ws.append(["ALFA IMPORTACIONES, C.A. — ESTADO DE RESULTADOS (P&L)"])
    ws.append([f"Periodo: {pnl['periodo']['fecha_inicio']} al {pnl['periodo']['fecha_fin']}"])
    ws.append([])
    ws.append(["Concepto", "Monto USD"])
    for etiqueta, clave in [
        ("Ingresos por Ventas", "ingresos_ventas_usd"),
        ("(-) Costo de Ventas (COGS)", "costo_ventas_usd"),
        ("= Utilidad Bruta", "utilidad_bruta_usd"),
        ("(-) Gastos Operativos", "gastos_operativos_usd"),
        ("(-) Nómina Pagada", "nomina_usd"),
        ("(-) Comisiones Pagadas", "comisiones_pagadas_usd"),
        ("(-) Impuestos y Parafiscales", "impuestos_parafiscales_usd"),
        ("(+/-) Resultado Cambiario (Tesorería)", "resultado_cambiario_usd"),
        ("= UTILIDAD NETA OPERATIVA", "utilidad_neta_operativa_usd"),
    ]:
        ws.append([etiqueta, pnl[clave]])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="estado_resultados_alfa.xlsx"'},
    )


@enrutador.get("/estado-resultados/pdf")
def exportar_pnl_pdf(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> Response:
    pnl = obtener_estado_resultados(fecha_inicio, fecha_fin, None, usuario, bd)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = dibujar_encabezado_y_marca_agua_alfa(
        c,
        "ESTADO DE RESULTADOS GERENCIAL (P&L)",
        f"Periodo: {pnl['periodo']['fecha_inicio']} al {pnl['periodo']['fecha_fin']}",
    )
    for etiqueta, clave, negrita in [
        ("Ingresos por Ventas", "ingresos_ventas_usd", False),
        ("(-) Costo de Ventas (COGS)", "costo_ventas_usd", False),
        ("= Utilidad Bruta", "utilidad_bruta_usd", True),
        ("(-) Gastos Operativos", "gastos_operativos_usd", False),
        ("(-) Nómina Pagada", "nomina_usd", False),
        ("(-) Comisiones Pagadas", "comisiones_pagadas_usd", False),
        ("(-) Impuestos y Parafiscales", "impuestos_parafiscales_usd", False),
        ("(+/-) Resultado Cambiario (Tesorería)", "resultado_cambiario_usd", False),
        ("= UTILIDAD NETA OPERATIVA", "utilidad_neta_operativa_usd", True),
    ]:
        c.setFont("Helvetica-Bold" if negrita else "Helvetica", 11 if negrita else 10)
        c.drawString(45, y, etiqueta)
        c.drawRightString(555, y, f"$ {pnl[clave]:,.2f}")
        y -= 22
    c.showPage()
    c.save()
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="estado_resultados_alfa.pdf"'},
    )
