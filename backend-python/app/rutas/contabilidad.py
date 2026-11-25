from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.modelos import CatalogoArticulo, RolUsuario, TasaDiaria, Usuario
from app.modelos_admin import ActivoFijo, FacturaGastoFiscal, Nomina, ObligacionLegal
from app.modelos_contabilidad import (
    AsientoContable,
    AsientoDetalle,
    EquipoComponenteInstalado,
    PlanCuenta,
    PrestamoFinanciamiento,
    PrestamoPago,
)
from app.modelos_finanzas import (
    CuentaPorCobrar,
    EstadoComision,
    EstadoCuentaPorCobrar,
    EstadoVenta,
    EstadoVerificacionPago,
    InstrumentoFinanciero,
    MonedaInstrumento,
    OrigenVenta,
    Pago,
    TipoDocumentoPago,
    TipoMovimientoPago,
    Venta,
    VentaDetalle,
)
from app.modelos_logistica import Equipo, EstadoEquipo, MovimientoInventario
from app.rutas.administracion import registrar_auditoria
from app.rutas.logistica import generar_correlativo
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import requerir_admin, requerir_direccion_lectura
from app.semilla_contabilidad import ejecutar_semilla_contabilidad
from app.servicios.contabilidad import crear_asiento_contable


enrutador = APIRouter(prefix="/api/contabilidad", tags=["Motor Contable Integrado"])


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _r2(v: Decimal) -> float:
    return float(_q2(v))


def _tasa_bcv_hoy(bd: Session) -> Decimal:
    t = bd.query(TasaDiaria).order_by(TasaDiaria.fecha.desc()).first()
    if t and t.tasa_bcv and t.tasa_bcv > 0:
        return Decimal(t.tasa_bcv)
    return Decimal("1")


# ---------------- 1. Plan de Cuentas ----------------


class CuentaCrearEntrada(BaseModel):
    codigo: str = Field(min_length=2, max_length=20)
    nombre: str = Field(min_length=2, max_length=160)
    tipo: str = Field(
        pattern="^(ACTIVO|PASIVO|PATRIMONIO|INGRESO|COSTO|GASTO_FIJO|GASTO_VARIABLE|GASTO_FINANCIERO|IMPUESTO)$"
    )
    naturaleza: str = Field(pattern="^(DEUDORA|ACREEDORA)$")
    cuenta_padre_id: int | None = None


@enrutador.get("/plan-cuentas")
def listar_plan_cuentas(
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    ejecutar_semilla_contabilidad(bd)
    cuentas = bd.query(PlanCuenta).order_by(PlanCuenta.codigo.asc()).all()
    return [
        {
            "id": c.id,
            "codigo": c.codigo,
            "nombre": c.nombre,
            "tipo": c.tipo,
            "naturaleza": c.naturaleza,
            "cuenta_padre_id": c.cuenta_padre_id,
            "activa": c.activa,
        }
        for c in cuentas
    ]


@enrutador.post("/plan-cuentas", status_code=status.HTTP_201_CREATED)
def crear_cuenta_contable(
    datos: CuentaCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    cod = datos.codigo.strip()
    if bd.query(PlanCuenta).filter(PlanCuenta.codigo == cod).first():
        raise HTTPException(status_code=409, detail=f"La cuenta contable '{cod}' ya existe.")
    cta = PlanCuenta(
        codigo=cod,
        nombre=datos.nombre.strip(),
        tipo=datos.tipo,
        naturaleza=datos.naturaleza,
        cuenta_padre_id=datos.cuenta_padre_id,
        activa=True,
    )
    bd.add(cta)
    bd.flush()
    registrar_auditoria(bd, usuario_actual, "CONTABILIDAD", "CREAR", cta.id, datos_nuevos={"codigo": cod, "nombre": cta.nombre})
    bd.commit()
    return {"id": cta.id, "codigo": cta.codigo, "nombre": cta.nombre, "tipo": cta.tipo}


# ---------------- 2. Libro Diario (Asientos Contables) ----------------


class LineaAsientoEntrada(BaseModel):
    cuenta_codigo: str | None = None
    cuenta_contable_id: int | None = None
    debe_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    haber_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    nota: str = Field(default="", max_length=255)


class AsientoManualCrearEntrada(BaseModel):
    fecha: date | None = None
    descripcion: str = Field(min_length=3, max_length=255)
    lineas: list[LineaAsientoEntrada] = Field(min_length=2)


@enrutador.get("/asientos")
def listar_asientos(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    origen_tipo: str | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    q = (
        bd.query(AsientoContable)
        .options(joinedload(AsientoContable.detalles).joinedload(AsientoDetalle.cuenta))
        .order_by(AsientoContable.fecha.desc(), AsientoContable.id.desc())
    )
    if fecha_inicio:
        q = q.filter(AsientoContable.fecha >= fecha_inicio)
    if fecha_fin:
        q = q.filter(AsientoContable.fecha <= fecha_fin)
    if origen_tipo:
        q = q.filter(AsientoContable.origen_tipo == origen_tipo.upper())
    filas = q.limit(150).all()
    return [
        {
            "id": a.id,
            "fecha": a.fecha.isoformat(),
            "descripcion": a.descripcion,
            "origen_tipo": a.origen_tipo,
            "origen_id": a.origen_id,
            "estado": a.estado,
            "creado_por": a.creado_por,
            "total_debe_usd": _r2(sum((Decimal(d.debe_usd) for d in a.detalles), Decimal("0"))),
            "total_haber_usd": _r2(sum((Decimal(d.haber_usd) for d in a.detalles), Decimal("0"))),
            "detalles": [
                {
                    "id": d.id,
                    "cuenta_codigo": d.cuenta.codigo if d.cuenta else "",
                    "cuenta_nombre": d.cuenta.nombre if d.cuenta else "",
                    "debe_usd": _r2(d.debe_usd),
                    "haber_usd": _r2(d.haber_usd),
                    "nota": d.nota,
                }
                for d in a.detalles
            ],
        }
        for a in filas
    ]


@enrutador.post("/asientos", status_code=status.HTTP_201_CREATED)
def crear_asiento_manual(
    datos: AsientoManualCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    fecha_op = datos.fecha or obtener_fecha_hoy()
    asiento = crear_asiento_contable(
        bd=bd,
        usuario=usuario_actual,
        fecha_op=fecha_op,
        descripcion=datos.descripcion.strip(),
        origen_tipo="MANUAL",
        origen_id="MANUAL",
        lineas=[l.model_dump() for l in datos.lineas],
    )
    registrar_auditoria(bd, usuario_actual, "CONTABILIDAD", "CREAR", asiento.id, datos_nuevos={"descripcion": asiento.descripcion})
    bd.commit()
    return {"id": asiento.id, "fecha": asiento.fecha.isoformat(), "descripcion": asiento.descripcion, "estado": asiento.estado}


# ---------------- 3. Préstamos y Financiamientos ----------------


class PrestamoCrearEntrada(BaseModel):
    acreedor: str = Field(min_length=2, max_length=160)
    concepto: str = Field(default="", max_length=255)
    fecha_desembolso: date | None = None
    fecha_vencimiento: date | None = None
    capital_usd: Decimal = Field(gt=Decimal("0"))
    tasa_interes_mensual_pct: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    instrumento_ingreso_id: int


class PrestamoPagarEntrada(BaseModel):
    fecha: date | None = None
    monto_capital_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    monto_interes_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    instrumento_pago_id: int
    referencia: str = Field(default="", max_length=120)


@enrutador.get("/prestamos")
def listar_prestamos(
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    filas = (
        bd.query(PrestamoFinanciamiento)
        .options(joinedload(PrestamoFinanciamiento.pagos))
        .order_by(PrestamoFinanciamiento.id.desc())
        .all()
    )
    return [
        {
            "id": p.id,
            "codigo": p.codigo,
            "acreedor": p.acreedor,
            "concepto": p.concepto,
            "fecha_desembolso": p.fecha_desembolso.isoformat(),
            "fecha_vencimiento": p.fecha_vencimiento.isoformat() if p.fecha_vencimiento else None,
            "capital_original_usd": _r2(p.capital_original_usd),
            "saldo_capital_usd": _r2(p.saldo_capital_usd),
            "tasa_interes_mensual_pct": float(p.tasa_interes_mensual_pct),
            "total_intereses_pagados_usd": _r2(p.total_intereses_pagados_usd),
            "estado": p.estado,
            "pagos_realizados": len(p.pagos),
        }
        for p in filas
    ]


@enrutador.post("/prestamos", status_code=status.HTTP_201_CREATED)
def crear_prestamo(
    datos: PrestamoCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    inst = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.id == datos.instrumento_ingreso_id).first()
    if inst is None:
        raise HTTPException(status_code=404, detail="Instrumento de ingreso no encontrado.")

    fecha_op = datos.fecha_desembolso or obtener_fecha_hoy()
    tasa = _tasa_bcv_hoy(bd)
    codigo = generar_correlativo(bd, PrestamoFinanciamiento, PrestamoFinanciamiento.codigo, "PRE")
    prest = PrestamoFinanciamiento(
        codigo=codigo,
        acreedor=datos.acreedor.strip(),
        concepto=datos.concepto.strip(),
        fecha_desembolso=fecha_op,
        fecha_vencimiento=datos.fecha_vencimiento,
        capital_original_usd=_q2(datos.capital_usd),
        saldo_capital_usd=_q2(datos.capital_usd),
        tasa_interes_mensual_pct=datos.tasa_interes_mensual_pct,
        instrumento_ingreso_id=inst.id,
        estado="ACTIVO",
        creado_por_id=usuario_actual.id,
    )
    bd.add(prest)
    bd.flush()

    monto_origen = _q2(datos.capital_usd * tasa) if inst.moneda == MonedaInstrumento.BS.value else _q2(datos.capital_usd)
    bd.add(
        Pago(
            instrumento_id=inst.id,
            fecha=fecha_op,
            tipo_movimiento=TipoMovimientoPago.INGRESO.value,
            tipo_documento=TipoDocumentoPago.TESORERIA.value,
            monto_moneda_origen=monto_origen,
            moneda=inst.moneda,
            tasa_bcv_dia=tasa,
            tasa_usdt_dia=tasa,
            usd_nominal=_q2(datos.capital_usd),
            usd_real=_q2(datos.capital_usd),
            cubre_promo_usd=_q2(datos.capital_usd),
            referencia=codigo,
            estado_verificacion=EstadoVerificacionPago.CONFIRMADO.value,
            verificado_por_id=usuario_actual.id,
            anulado=False,
            categoria="Préstamo Recibido",
            origen_tipo="PRESTAMO",
            origen_id=prest.id,
            nota=f"Desembolso préstamo {codigo} ({datos.acreedor})",
        )
    )

    crear_asiento_contable(
        bd=bd,
        usuario=usuario_actual,
        fecha_op=fecha_op,
        descripcion=f"Desembolso préstamo {codigo} - {datos.acreedor}",
        origen_tipo="PRESTAMO",
        origen_id=prest.id,
        lineas=[
            {"cuenta_codigo": "1.1.01", "debe_usd": datos.capital_usd, "haber_usd": Decimal("0")},
            {"cuenta_codigo": "2.2.01", "debe_usd": Decimal("0"), "haber_usd": datos.capital_usd},
        ],
    )
    registrar_auditoria(bd, usuario_actual, "PRESTAMOS", "CREAR", prest.id, datos_nuevos={"codigo": codigo, "capital_usd": float(datos.capital_usd)})
    bd.commit()
    return {"id": prest.id, "codigo": prest.codigo, "saldo_capital_usd": _r2(prest.saldo_capital_usd), "estado": prest.estado}


@enrutador.post("/prestamos/{prestamo_id}/pagar")
def pagar_cuota_prestamo(
    prestamo_id: int,
    datos: PrestamoPagarEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    prest = bd.query(PrestamoFinanciamiento).filter(PrestamoFinanciamiento.id == prestamo_id).first()
    if prest is None:
        raise HTTPException(status_code=404, detail="Préstamo no encontrado.")
    if prest.estado != "ACTIVO":
        raise HTTPException(status_code=400, detail="El préstamo no está activo.")
    total_pago = _q2(datos.monto_capital_usd + datos.monto_interes_usd)
    if total_pago <= 0:
        raise HTTPException(status_code=400, detail="Debes indicar capital o interés mayor a 0.")
    if datos.monto_capital_usd > prest.saldo_capital_usd + Decimal("0.01"):
        raise HTTPException(status_code=400, detail="El abono a capital excede el saldo pendiente.")

    inst = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.id == datos.instrumento_pago_id).first()
    if inst is None:
        raise HTTPException(status_code=404, detail="Instrumento de pago no encontrado.")

    fecha_op = datos.fecha or obtener_fecha_hoy()
    tasa = _tasa_bcv_hoy(bd)
    monto_origen = _q2(total_pago * tasa) if inst.moneda == MonedaInstrumento.BS.value else total_pago

    pago = Pago(
        instrumento_id=inst.id,
        fecha=fecha_op,
        tipo_movimiento=TipoMovimientoPago.EGRESO.value,
        tipo_documento=TipoDocumentoPago.GASTO.value,
        monto_moneda_origen=monto_origen,
        moneda=inst.moneda,
        tasa_bcv_dia=tasa,
        tasa_usdt_dia=tasa,
        usd_nominal=total_pago,
        usd_real=total_pago,
        cubre_promo_usd=total_pago,
        referencia=datos.referencia or prest.codigo,
        estado_verificacion=EstadoVerificacionPago.CONFIRMADO.value,
        verificado_por_id=usuario_actual.id,
        anulado=False,
        categoria="Pago Préstamo (Capital e Intereses)",
        origen_tipo="PRESTAMO_PAGO",
        origen_id=prest.id,
        nota=f"Pago {prest.codigo}: Capital ${datos.monto_capital_usd} + Interés ${datos.monto_interes_usd}",
    )
    bd.add(pago)
    bd.flush()

    bd.add(
        PrestamoPago(
            prestamo_id=prest.id,
            fecha=fecha_op,
            monto_capital_usd=_q2(datos.monto_capital_usd),
            monto_interes_usd=_q2(datos.monto_interes_usd),
            monto_total_usd=total_pago,
            instrumento_pago_id=inst.id,
            pago_id=pago.id,
            referencia=datos.referencia.strip(),
        )
    )

    prest.saldo_capital_usd = max(Decimal("0"), _q2(prest.saldo_capital_usd - datos.monto_capital_usd))
    prest.total_intereses_pagados_usd = _q2(prest.total_intereses_pagados_usd + datos.monto_interes_usd)
    if prest.saldo_capital_usd == 0:
        prest.estado = "PAGADO"

    lineas_p: list[dict[str, Any]] = []
    if datos.monto_capital_usd > 0:
        lineas_p.append({"cuenta_codigo": "2.2.01", "debe_usd": datos.monto_capital_usd, "haber_usd": Decimal("0"), "nota": f"Amortización capital {prest.codigo}"})
    if datos.monto_interes_usd > 0:
        lineas_p.append({"cuenta_codigo": "8.1.02", "debe_usd": datos.monto_interes_usd, "haber_usd": Decimal("0"), "nota": f"Intereses préstamo {prest.codigo}"})
    lineas_p.append({"cuenta_codigo": "1.1.01", "debe_usd": Decimal("0"), "haber_usd": total_pago, "nota": f"Salida caja {prest.codigo}"})

    crear_asiento_contable(
        bd=bd,
        usuario=usuario_actual,
        fecha_op=fecha_op,
        descripcion=f"Pago préstamo {prest.codigo} ({prest.acreedor})",
        origen_tipo="PRESTAMO_PAGO",
        origen_id=pago.id,
        lineas=lineas_p,
    )
    registrar_auditoria(
        bd,
        usuario_actual,
        "PRESTAMOS",
        "PAGAR",
        prest.id,
        datos_nuevos={"capital_usd": float(datos.monto_capital_usd), "interes_usd": float(datos.monto_interes_usd), "saldo_restante": float(prest.saldo_capital_usd)},
    )
    bd.commit()
    return {
        "prestamo_id": prest.id,
        "saldo_capital_usd": _r2(prest.saldo_capital_usd),
        "total_intereses_pagados_usd": _r2(prest.total_intereses_pagados_usd),
        "estado": prest.estado,
    }


# ---------------- 4. Balance General y Estado de Resultados Contable ----------------


@enrutador.get("/balance-general")
def obtener_balance_general(
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    ejecutar_semilla_contabilidad(bd)
    tasa = _tasa_bcv_hoy(bd)

    # 1.1.01 Cajas y Bancos
    insts = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.activo.is_(True)).all()
    pagos = bd.query(Pago).filter(Pago.anulado.is_(False)).all()
    neto_inst: dict[int, Decimal] = {}
    for p in pagos:
        sig = Decimal("-1") if p.tipo_movimiento == TipoMovimientoPago.EGRESO.value else Decimal("1")
        neto_inst[p.instrumento_id] = neto_inst.get(p.instrumento_id, Decimal("0")) + (Decimal(p.monto_moneda_origen) * sig)
    cajas_usd = Decimal("0")
    for i in insts:
        s = Decimal(i.saldo_inicial or 0) + neto_inst.get(i.id, Decimal("0"))
        cajas_usd += (s / tasa) if (i.moneda == MonedaInstrumento.BS.value and tasa > 0) else s

    # 1.1.02 CxC
    cxc_usd = sum(
        (Decimal(c.saldo_pendiente_usd or 0) for c in bd.query(CuentaPorCobrar).filter(CuentaPorCobrar.estado == EstadoCuentaPorCobrar.PENDIENTE.value).all()),
        Decimal("0"),
    )

    # 1.1.03 / 1.1.04 Inventario Equipos
    equipos = bd.query(Equipo).filter(Equipo.estado.notin_([EstadoEquipo.VENDIDO.value, EstadoEquipo.CEMENTERIO.value])).all()
    inv_disp_usd = Decimal("0")
    inv_prep_usd = Decimal("0")
    for e in equipos:
        costo_e = Decimal(e.costo_compra_usd or 0) + Decimal(e.costo_flete_usd or 0) + Decimal(e.costo_taller_usd or 0)
        if e.estado == EstadoEquipo.LISTO.value:
            inv_disp_usd += costo_e
        else:
            inv_prep_usd += costo_e

    # Sumar Lotes en Tránsito (sin serializar aún) a 1.1.04
    from app.modelos_logistica import LoteTransito

    lotes_trn_usd = sum(
        (Decimal(lt.total_en_transito_usd or 0) for lt in bd.query(LoteTransito).filter(LoteTransito.estado == "EN_TRANSITO").all()),
        Decimal("0"),
    )
    inv_prep_usd += lotes_trn_usd

    # 1.1.05 Inventario Componentes
    movs_c = (
        bd.query(MovimientoInventario.articulo_id, func.coalesce(func.sum(MovimientoInventario.cantidad), 0))
        .filter(MovimientoInventario.equipo_id.is_(None))
        .group_by(MovimientoInventario.articulo_id)
        .all()
    )
    art_map = {a.id: a for a in bd.query(CatalogoArticulo).options(joinedload(CatalogoArticulo.precios)).all()}
    inv_comp_usd = Decimal("0")
    for art_id, st in movs_c:
        if int(st or 0) > 0:
            art = art_map.get(art_id)
            c_ref = Decimal(art.precios[0].costo_referencia_usd or 0) if (art and art.precios) else Decimal("0")
            inv_comp_usd += c_ref * int(st)

    # 1.2.01 Activos Fijos netos
    hoy = obtener_fecha_hoy()
    activos_fijos_usd = Decimal("0")
    for af in bd.query(ActivoFijo).filter(ActivoFijo.estado != "DESINCORPORADO").all():
        dep_m = af.costo_usd / Decimal(af.vida_util_meses or 60)
        meses = max(0, int((hoy - af.fecha_compra).days / 30))
        activos_fijos_usd += max(Decimal("0"), af.costo_usd - min(af.costo_usd, dep_m * Decimal(meses)))

    total_activos = cajas_usd + cxc_usd + inv_disp_usd + inv_prep_usd + inv_comp_usd + activos_fijos_usd

    # PASIVOS
    cxp_gastos = sum(
        (max(Decimal("0"), Decimal(g.monto_total_usd) - Decimal(g.monto_pagado_usd)) for g in bd.query(FacturaGastoFiscal).filter(FacturaGastoFiscal.estado.in_(["PENDIENTE", "PARCIAL"])).all()),
        Decimal("0"),
    )
    consignaciones_vend = sum(
        (Decimal(e.costo_acordado_usd or e.costo_compra_usd or 0) for e in bd.query(Equipo).filter(Equipo.es_consignacion.is_(True), Equipo.estado == EstadoEquipo.VENDIDO.value).all()),
        Decimal("0"),
    )
    cxp_total = cxp_gastos + consignaciones_vend

    # 2.1.02 Comisiones por pagar
    com_pend = Decimal("0")
    for v in bd.query(Venta).options(joinedload(Venta.asesor)).filter(Venta.estado.notin_([EstadoVenta.ANULADA.value, EstadoVenta.DEVUELTA.value]), Venta.estado_comision == EstadoComision.PENDIENTE.value, Venta.asesor_id.isnot(None)).all():
        pct = Decimal("0.08") if v.origen_venta == OrigenVenta.LEAD.value else (Decimal("0.05") if (v.asesor and v.asesor.rol == "ENCARGADO_TIENDA") else (Decimal("0.01") if (v.asesor and v.asesor.rol == "ASESORA") else Decimal("0")))
        com_pend += Decimal(v.total_promo_usd or 0) * pct

    # 2.1.03 Impuestos por pagar
    imp_pend = sum(
        (Decimal(o.monto_estimado_usd or 0) for o in bd.query(ObligacionLegal).filter(ObligacionLegal.estado == "PENDIENTE").all()),
        Decimal("0"),
    )
    # 2.2.01 Préstamos por pagar
    prestamos_pend = sum(
        (Decimal(pr.saldo_capital_usd or 0) for pr in bd.query(PrestamoFinanciamiento).filter(PrestamoFinanciamiento.estado == "ACTIVO").all()),
        Decimal("0"),
    )

    total_pasivos = cxp_total + com_pend + imp_pend + prestamos_pend
    patrimonio_neto = total_activos - total_pasivos

    # Desglose de Patrimonio desde asientos en 3.1.01 (Capital Social) y 3.2.01 (Dividendos / Repartición)
    capital_social = Decimal("0")
    reparticion_socios = Decimal("0")
    det_pat = (
        bd.query(AsientoDetalle)
        .join(AsientoContable, AsientoDetalle.asiento_id == AsientoContable.id)
        .join(PlanCuenta, AsientoDetalle.cuenta_contable_id == PlanCuenta.id)
        .options(joinedload(AsientoDetalle.cuenta))
        .filter(
            AsientoContable.estado == "CONTABILIZADO",
            PlanCuenta.codigo.in_(["3.1.01", "3.2.01"]),
        )
        .all()
    )
    for dp in det_pat:
        if dp.cuenta and dp.cuenta.codigo == "3.1.01":
            capital_social += Decimal(dp.haber_usd or 0) - Decimal(dp.debe_usd or 0)
        elif dp.cuenta and dp.cuenta.codigo == "3.2.01":
            reparticion_socios += Decimal(dp.debe_usd or 0) - Decimal(dp.haber_usd or 0)
    resultado_ejercicio = patrimonio_neto - capital_social + reparticion_socios
    detalle_patrimonio = [
        {"codigo": "3.1.01", "nombre": "Capital Social / Aportes de Socios", "saldo_usd": _r2(capital_social)},
        {"codigo": "3.2.01", "nombre": "Resultado del Ejercicio / Utilidades Acumuladas", "saldo_usd": _r2(resultado_ejercicio)},
    ]
    if reparticion_socios != 0:
        detalle_patrimonio.append(
            {"codigo": "3.2.01-DIV", "nombre": "(-) Repartición de Ganancias / Dividendos a Socios", "saldo_usd": _r2(-reparticion_socios)}
        )

    return {
        "fecha_corte": hoy.isoformat(),
        "activos": {
            "total_usd": _r2(total_activos),
            "detalle": [
                {"codigo": "1.1.01", "nombre": "Cajas y Bancos", "saldo_usd": _r2(cajas_usd)},
                {"codigo": "1.1.02", "nombre": "Cuentas por Cobrar (Clientes / Cashea)", "saldo_usd": _r2(cxc_usd)},
                {"codigo": "1.1.03", "nombre": "Inventario de Equipos Disponibles", "saldo_usd": _r2(inv_disp_usd)},
                {"codigo": "1.1.04", "nombre": "Inventario Equipos en Preparación / Tránsito", "saldo_usd": _r2(inv_prep_usd)},
                {"codigo": "1.1.05", "nombre": "Inventario Componentes y Accesorios", "saldo_usd": _r2(inv_comp_usd)},
                {"codigo": "1.2.01", "nombre": "Activos Fijos Netos", "saldo_usd": _r2(activos_fijos_usd)},
            ],
        },
        "pasivos": {
            "total_usd": _r2(total_pasivos),
            "detalle": [
                {"codigo": "2.1.01", "nombre": "Cuentas por Pagar Proveedores y Consignaciones", "saldo_usd": _r2(cxp_total)},
                {"codigo": "2.1.02", "nombre": "Comisiones por Pagar", "saldo_usd": _r2(com_pend)},
                {"codigo": "2.1.03", "nombre": "Impuestos y Obligaciones por Pagar", "saldo_usd": _r2(imp_pend)},
                {"codigo": "2.2.01", "nombre": "Préstamos y Financiamientos por Pagar (Capital)", "saldo_usd": _r2(prestamos_pend)},
            ],
        },
        "patrimonio": {
            "total_usd": _r2(patrimonio_neto),
            "detalle": detalle_patrimonio,
        },
        "diferencia_cuadre_usd": _r2(total_activos - (total_pasivos + patrimonio_neto)),
        "ecuacion_cuadrada": abs(total_activos - (total_pasivos + patrimonio_neto)) <= Decimal("0.01"),
    }


@enrutador.get("/estado-resultados")
def obtener_estado_resultados_contable(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    hoy = obtener_fecha_hoy()
    f_fin = fecha_fin or hoy
    f_ini = fecha_inicio or date(f_fin.year, f_fin.month, 1)

    detalles = (
        bd.query(AsientoDetalle)
        .join(AsientoContable, AsientoDetalle.asiento_id == AsientoContable.id)
        .join(PlanCuenta, AsientoDetalle.cuenta_contable_id == PlanCuenta.id)
        .options(joinedload(AsientoDetalle.cuenta))
        .filter(
            AsientoContable.fecha >= f_ini,
            AsientoContable.fecha <= f_fin,
            AsientoContable.estado == "CONTABILIZADO",
            PlanCuenta.tipo.in_(["INGRESO", "COSTO", "GASTO_VARIABLE", "GASTO_FIJO", "GASTO_FINANCIERO", "IMPUESTO"]),
        )
        .all()
    )

    por_cuenta: dict[str, dict[str, Any]] = {}
    totales_tipo: dict[str, Decimal] = {
        "INGRESO": Decimal("0"),
        "COSTO": Decimal("0"),
        "GASTO_VARIABLE": Decimal("0"),
        "GASTO_FIJO": Decimal("0"),
        "GASTO_FINANCIERO": Decimal("0"),
        "IMPUESTO": Decimal("0"),
    }

    for d in detalles:
        c = d.cuenta
        if c is None:
            continue
        saldo_lin = (Decimal(d.haber_usd) - Decimal(d.debe_usd)) if c.naturaleza == "ACREEDORA" else (Decimal(d.debe_usd) - Decimal(d.haber_usd))
        totales_tipo[c.tipo] = totales_tipo.get(c.tipo, Decimal("0")) + saldo_lin
        bucket = por_cuenta.setdefault(
            c.codigo,
            {"codigo": c.codigo, "nombre": c.nombre, "tipo": c.tipo, "monto_usd": Decimal("0")},
        )
        bucket["monto_usd"] += saldo_lin

    utilidad_bruta = totales_tipo["INGRESO"] - totales_tipo["COSTO"]
    margen_contribucion = utilidad_bruta - totales_tipo["GASTO_VARIABLE"]
    utilidad_operativa_ebit = margen_contribucion - totales_tipo["GASTO_FIJO"]
    utilidad_neta = (
        utilidad_operativa_ebit
        - totales_tipo["GASTO_FINANCIERO"]
        - totales_tipo["IMPUESTO"]
    )

    return {
        "periodo": {"fecha_inicio": f_ini.isoformat(), "fecha_fin": f_fin.isoformat()},
        "ingresos_usd": _r2(totales_tipo["INGRESO"]),
        "costo_ventas_usd": _r2(totales_tipo["COSTO"]),
        "utilidad_bruta_usd": _r2(utilidad_bruta),
        "gastos_variables_usd": _r2(totales_tipo["GASTO_VARIABLE"]),
        "margen_contribucion_usd": _r2(margen_contribucion),
        "gastos_fijos_usd": _r2(totales_tipo["GASTO_FIJO"]),
        "utilidad_operativa_ebit_usd": _r2(utilidad_operativa_ebit),
        "gastos_financieros_usd": _r2(totales_tipo["GASTO_FINANCIERO"]),
        "impuestos_usd": _r2(totales_tipo["IMPUESTO"]),
        "utilidad_neta_usd": _r2(utilidad_neta),
        "cuentas": sorted(
            [{**v, "monto_usd": _r2(v["monto_usd"])} for v in por_cuenta.values()],
            key=lambda x: x["codigo"],
        ),
    }


class MovimientoPatrimonialEntrada(BaseModel):
    tipo: str = Field(pattern="^(APORTE_CAPITAL|REPARTICION_GANANCIAS)$")
    instrumento_pago_id: int
    monto_usd: Decimal = Field(gt=Decimal("0"))
    socio_nombre: str = Field(default="", max_length=160)
    referencia: str = Field(default="", max_length=120)
    descripcion: str = Field(default="", max_length=255)
    fecha: date | None = None


@enrutador.post("/movimiento-patrimonial", status_code=status.HTTP_201_CREATED)
def registrar_movimiento_patrimonial(
    datos: MovimientoPatrimonialEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Registra aportes de capital (3.1.01) o repartición de ganancias/dividendos (3.2.01) con movimiento real en Tesorería."""
    inst = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.id == datos.instrumento_pago_id, InstrumentoFinanciero.activo.is_(True))
        .first()
    )
    if inst is None:
        raise HTTPException(status_code=404, detail="Instrumento financiero no encontrado.")

    fecha_op = datos.fecha or obtener_fecha_hoy()
    tasa = _tasa_bcv_hoy(bd)
    es_bs = inst.moneda == MonedaInstrumento.BS.value
    monto_orig = _q2(datos.monto_usd * tasa) if es_bs else _q2(datos.monto_usd)
    es_aporte = datos.tipo == "APORTE_CAPITAL"

    pago = Pago(
        venta_id=None,
        instrumento_id=inst.id,
        fecha=fecha_op,
        tipo_movimiento=TipoMovimientoPago.INGRESO.value if es_aporte else TipoMovimientoPago.EGRESO.value,
        tipo_documento=TipoDocumentoPago.TESORERIA.value,
        monto_moneda_origen=monto_orig,
        moneda=inst.moneda,
        tasa_bcv_dia=tasa if es_bs else Decimal("0"),
        tasa_usdt_dia=Decimal("0"),
        usd_nominal=_q2(datos.monto_usd),
        usd_real=_q2(datos.monto_usd),
        cubre_promo_usd=Decimal("0"),
        referencia=datos.referencia.strip() or datos.tipo,
        estado_verificacion=EstadoVerificacionPago.CONFIRMADO.value,
        verificado_por_id=usuario_actual.id,
        conciliado=False,
        anulado=False,
        categoria="Aporte de Capital" if es_aporte else "Repartición de Ganancias",
        origen_tipo=datos.tipo,
        origen_id=0,
        nota=datos.descripcion.strip() or f"{datos.tipo} · {datos.socio_nombre}",
    )
    bd.add(pago)
    bd.flush()

    desc_asiento = datos.descripcion.strip() or (
        f"Aporte de Capital Social ({datos.socio_nombre or 'Socios'})"
        if es_aporte
        else f"Repartición de Ganancias / Dividendos ({datos.socio_nombre or 'Socios'})"
    )
    lineas = (
        [
            {"cuenta_codigo": "1.1.01", "debe_usd": datos.monto_usd, "haber_usd": 0, "nota": f"Ingreso a {inst.nombre}"},
            {"cuenta_codigo": "3.1.01", "debe_usd": 0, "haber_usd": datos.monto_usd, "nota": datos.socio_nombre or "Capital Social"},
        ]
        if es_aporte
        else [
            {"cuenta_codigo": "3.2.01", "debe_usd": datos.monto_usd, "haber_usd": 0, "nota": f"Dividendo {datos.socio_nombre or 'Socios'}"},
            {"cuenta_codigo": "1.1.01", "debe_usd": 0, "haber_usd": datos.monto_usd, "nota": f"Egreso de {inst.nombre}"},
        ]
    )
    asiento = crear_asiento_contable(
        bd=bd,
        usuario=usuario_actual,
        fecha_op=fecha_op,
        descripcion=desc_asiento,
        origen_tipo=datos.tipo,
        origen_id=pago.id,
        lineas=lineas,
    )
    bd.commit()
    return {
        "pago_id": pago.id,
        "asiento_id": asiento.id,
        "tipo": datos.tipo,
        "monto_usd": _r2(datos.monto_usd),
        "instrumento": inst.nombre,
    }


@enrutador.get("/rentabilidad-ventas")
def obtener_rentabilidad_real_ventas(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Calcula la rentabilidad real por venta descontando costo base, flete, preparación y comisión."""
    hoy = obtener_fecha_hoy()
    f_fin = fecha_fin or hoy
    f_ini = fecha_inicio or date(f_fin.year, f_fin.month, 1)

    ventas = (
        bd.query(Venta)
        .options(
            joinedload(Venta.sucursal),
            joinedload(Venta.asesor),
            joinedload(Venta.detalles).joinedload(VentaDetalle.equipo),
        )
        .filter(
            Venta.fecha >= f_ini,
            Venta.fecha <= f_fin,
            Venta.estado.notin_([EstadoVenta.ANULADA.value, EstadoVenta.DEVUELTA.value]),
        )
        .order_by(Venta.fecha.desc(), Venta.id.desc())
        .all()
    )

    filas: list[dict[str, Any]] = []
    tot_ventas = Decimal("0")
    tot_costos = Decimal("0")
    tot_comisiones = Decimal("0")
    tot_cargos_cashea = Decimal("0")
    tot_utilidad = Decimal("0")

    for v in ventas:
        precio_v = Decimal(v.total_promo_usd or 0)
        costo_base = Decimal("0")
        costo_flete = Decimal("0")
        costo_prep = Decimal("0")
        for d in v.detalles:
            if d.equipo is not None:
                costo_base += Decimal(d.equipo.costo_compra_usd or 0)
                costo_flete += Decimal(d.equipo.costo_flete_usd or 0)
                costo_prep += Decimal(d.equipo.costo_taller_usd or 0)
            else:
                costo_base += Decimal(d.costo_total_snapshot_usd or 0)

        costo_total = costo_base + costo_flete + costo_prep
        pct_com = Decimal("0")
        if v.asesor is not None:
            if v.origen_venta == OrigenVenta.LEAD.value:
                pct_com = Decimal("0.08")
            elif v.asesor.rol in (RolUsuario.ENCARGADO_TIENDA.value, RolUsuario.LIDER.value):
                pct_com = Decimal("0.05")
            elif v.asesor.rol == RolUsuario.ASESORA.value:
                pct_com = Decimal("0.01")
        com_usd = _q2(precio_v * pct_com)
        cargos_cashea = Decimal(getattr(v, "cashea_total_cargos_usd", 0) or 0)
        utilidad = precio_v - costo_total - com_usd - cargos_cashea
        margen = _q2((utilidad / precio_v) * Decimal("100")) if precio_v > 0 else Decimal("0")

        tot_ventas += precio_v
        tot_costos += costo_total
        tot_comisiones += com_usd
        tot_cargos_cashea += cargos_cashea
        tot_utilidad += utilidad

        filas.append(
            {
                "venta_id": v.id,
                "numero_venta": v.numero_venta,
                "fecha": v.fecha.isoformat(),
                "sucursal": v.sucursal.nombre if v.sucursal else "",
                "asesor": v.asesor.nombre if v.asesor else "Tienda",
                "origen_venta": v.origen_venta,
                "es_cashea": bool(getattr(v, "es_cashea", False)),
                "precio_venta_usd": _r2(precio_v),
                "costo_base_usd": _r2(costo_base),
                "costo_flete_usd": _r2(costo_flete),
                "costo_preparacion_usd": _r2(costo_prep),
                "costo_total_real_usd": _r2(costo_total),
                "comision_usd": _r2(com_usd),
                "cashea_total_cargos_usd": _r2(cargos_cashea),
                "utilidad_neta_usd": _r2(utilidad),
                "margen_neto_pct": float(margen),
            }
        )

    return {
        "periodo": {"fecha_inicio": f_ini.isoformat(), "fecha_fin": f_fin.isoformat()},
        "resumen": {
            "total_ventas_usd": _r2(tot_ventas),
            "total_costos_reales_usd": _r2(tot_costos),
            "total_comisiones_usd": _r2(tot_comisiones),
            "total_cargos_cashea_usd": _r2(tot_cargos_cashea),
            "utilidad_neta_total_usd": _r2(tot_utilidad),
            "margen_neto_promedio_pct": float(
                _q2((tot_utilidad / tot_ventas) * Decimal("100")) if tot_ventas > 0 else Decimal("0")
            ),
        },
        "ventas": filas,
    }
