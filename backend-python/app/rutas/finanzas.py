from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import extract, func
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.esquemas_finanzas import (
    AbonoCxcEntrada,
    AbonoPagoItem,
    CasheaLiquidarEntrada,
    CierreMensualEntrada,
    CruceManualEntrada,
    LiquidacionAnularEntrada,
    LiquidacionCrearEntrada,
    PagoConfirmarEntrada,
)
from app.modelos import RolUsuario, TasaDiaria, TipoArticulo, Usuario
from app.modelos_finanzas import (
    CierreMensual,
    CuentaPorCobrar,
    EstadoComision,
    EstadoCuentaPorCobrar,
    EstadoLiquidacionComision,
    EstadoVenta,
    EstadoVerificacionPago,
    ExtractoBancario,
    InstrumentoFinanciero,
    LiquidacionComision,
    MonedaInstrumento,
    OrigenVenta,
    Pago,
    TipoCuentaPorCobrar,
    TipoDocumentoPago,
    TipoMovimientoPago,
    Venta,
    VentaDetalle,
)
from app.servicios.pdf_documentos import generar_pdf_liquidacion_comision
from app.modelos_taller import (
    CasoPostventa,
    EstadoCasoPostventa,
    Preparacion,
    TipoCasoPostventa,
)
from app.rutas.logistica import _leer_filas_archivo
from app.rutas.tasas import obtener_fecha_hoy
from app.rutas.ventas import redondear_usd, verificar_mes_abierto
from app.seguridad import ROLES_ADMINISTRATIVOS, es_administrador, obtener_usuario_actual, requerir_admin, requerir_roles


enrutador = APIRouter(prefix="/api/finanzas", tags=["Finanzas, Conciliación y Cierres"])
enrutador_comisiones = APIRouter(prefix="/api/comisiones", tags=["Reporte de Comisiones"])


# ---------------- Instrumentos y Pagos ----------------

@enrutador.get("/instrumentos")
def listar_instrumentos(
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    filas = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.activo.is_(True))
        .order_by(InstrumentoFinanciero.id.asc())
        .all()
    )
    incluir_saldos = es_administrador(usuario_actual.rol) or usuario_actual.rol == RolUsuario.DIRECTOR.value
    neto_por_inst: dict[int, Decimal] = {}
    if incluir_saldos:
        pagos_activos = bd.query(Pago).filter(Pago.anulado.is_(False)).all()
        for p in pagos_activos:
            signo = Decimal("-1") if p.tipo_movimiento == TipoMovimientoPago.EGRESO.value else Decimal("1")
            neto_por_inst[p.instrumento_id] = neto_por_inst.get(p.instrumento_id, Decimal("0")) + (
                p.monto_moneda_origen * signo
            )

    return [
        {
            "id": i.id,
            "nombre": i.nombre,
            "moneda": i.moneda,
            "tipo_precio": i.tipo_precio,
            "tipo_instrumento": i.tipo_instrumento or "",
            "cuenta_contable": i.cuenta_contable or "",
            "sucursal_id": i.sucursal_id,
            "requiere_verificacion": i.requiere_verificacion,
            "liquida_en_bs": i.liquida_en_bs,
            **(
                {
                    "saldo_inicial": redondear_usd(i.saldo_inicial or Decimal("0")),
                    "saldo_actual": redondear_usd(
                        (i.saldo_inicial or Decimal("0")) + neto_por_inst.get(i.id, Decimal("0"))
                    ),
                }
                if incluir_saldos
                else {}
            ),
        }
        for i in filas
    ]


class SaldoInicialInstrumentoEntrada(BaseModel):
    saldo_inicial: Decimal = Field(ge=0)


class SaldoInicialMasivoItem(BaseModel):
    instrumento_id: int
    saldo_inicial: Decimal = Field(ge=0)


class SaldosInicialesMasivoEntrada(BaseModel):
    saldos: list[SaldoInicialMasivoItem] = Field(min_length=1)


@enrutador.patch("/instrumentos/{instrumento_id}/saldo-inicial")
def actualizar_saldo_inicial_instrumento(
    instrumento_id: int,
    datos: SaldoInicialInstrumentoEntrada,
    _usuario_actual: Usuario = Depends(requerir_roles(RolUsuario.DIRECCION.value, RolUsuario.ADMINISTRACION.value)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Actualiza el saldo inicial de apertura de un instrumento financiero."""
    inst = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.id == instrumento_id).first()
    if inst is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instrumento financiero no encontrado.")
    inst.saldo_inicial = datos.saldo_inicial.quantize(Decimal("0.01"))
    bd.commit()
    bd.refresh(inst)
    return {
        "id": inst.id,
        "nombre": inst.nombre,
        "moneda": inst.moneda,
        "saldo_inicial": redondear_usd(inst.saldo_inicial),
    }


@enrutador.put("/instrumentos/saldos-iniciales")
def cargar_saldos_iniciales_masivo(
    datos: SaldosInicialesMasivoEntrada,
    _usuario_actual: Usuario = Depends(requerir_roles(RolUsuario.DIRECCION.value, RolUsuario.ADMINISTRACION.value)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Carga masiva de saldos iniciales de apertura sobre los instrumentos financieros."""
    actualizados: list[dict[str, Any]] = []
    for item in datos.saldos:
        inst = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.id == item.instrumento_id).first()
        if inst is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Instrumento financiero #{item.instrumento_id} no encontrado.",
            )
        inst.saldo_inicial = item.saldo_inicial.quantize(Decimal("0.01"))
        actualizados.append(
            {
                "id": inst.id,
                "nombre": inst.nombre,
                "moneda": inst.moneda,
                "saldo_inicial": redondear_usd(inst.saldo_inicial),
            }
        )
    bd.commit()
    return {"actualizados": len(actualizados), "instrumentos": actualizados}


@enrutador.get("/pagos")
def listar_pagos(
    estado_verificacion: EstadoVerificacionPago | None = Query(default=None),
    instrumento_id: int | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    consulta = (
        bd.query(Pago)
        .options(
            joinedload(Pago.instrumento),
            joinedload(Pago.venta),
            joinedload(Pago.verificado_por),
        )
        .filter(Pago.anulado.is_(False))
    )
    if estado_verificacion is not None:
        consulta = consulta.filter(Pago.estado_verificacion == estado_verificacion.value)
    if instrumento_id is not None:
        consulta = consulta.filter(Pago.instrumento_id == instrumento_id)

    pagos = consulta.order_by(Pago.id.desc()).limit(150).all()
    return [
        {
            "id": p.id,
            "venta_id": p.venta_id,
            "numero_venta": p.venta.numero_venta if p.venta else None,
            "instrumento_id": p.instrumento_id,
            "instrumento": p.instrumento.nombre if p.instrumento else None,
            "fecha": p.fecha.isoformat(),
            "tipo_movimiento": p.tipo_movimiento,
            "tipo_documento": p.tipo_documento,
            "categoria": getattr(p, "categoria", "") or "",
            "origen_tipo": getattr(p, "origen_tipo", "") or "",
            "origen_id": getattr(p, "origen_id", None),
            "monto_moneda_origen": redondear_usd(p.monto_moneda_origen),
            "moneda": p.moneda,
            "usd_nominal": redondear_usd(p.usd_nominal),
            "usd_real": redondear_usd(p.usd_real),
            "referencia": p.referencia,
            "estado_verificacion": p.estado_verificacion,
            "verificado_por": p.verificado_por.nombre if p.verificado_por else None,
            "conciliado": p.conciliado,
            "nota": p.nota,
        }
        for p in pagos
    ]


@enrutador.patch("/pagos/{pago_id}/confirmar")
def confirmar_pago_digital(
    pago_id: int,
    datos: PagoConfirmarEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    pago = bd.query(Pago).filter(Pago.id == pago_id).first()
    if pago is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pago no encontrado.")
    if getattr(pago, "origen_tipo", "") == "LIQUIDACION_COMISION":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este egreso fue generado por una liquidación de comisiones. Debe gestionarse desde el Historial de Liquidaciones.",
        )

    verificar_mes_abierto(bd, pago.fecha)

    pago.estado_verificacion = (
        EstadoVerificacionPago.CONFIRMADO.value
        if datos.aprobado
        else EstadoVerificacionPago.PENDIENTE.value
    )
    pago.verificado_por_id = usuario_actual.id
    if datos.nota.strip():
        pago.nota = datos.nota.strip()
    bd.commit()

    return {
        "id": pago.id,
        "estado_verificacion": pago.estado_verificacion,
        "verificado_por": usuario_actual.nombre,
    }


@enrutador.delete("/pagos/{pago_id}")
def eliminar_movimiento_financiero(
    pago_id: int,
    _usuario: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Anula un movimiento financiero manual, bloqueando egresos generados por liquidaciones de comisiones."""
    pago = bd.query(Pago).filter(Pago.id == pago_id).first()
    if pago is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movimiento financiero no encontrado.")
    if getattr(pago, "origen_tipo", "") == "LIQUIDACION_COMISION":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes eliminar manualmente un egreso generado por liquidación de comisiones. Anúlalo desde el Historial de Liquidaciones.",
        )

    verificar_mes_abierto(bd, pago.fecha)
    pago.anulado = True
    bd.commit()
    return {"id": pago.id, "anulado": True}


# ---------------- Cuentas por Cobrar y Cashea ----------------

ROLES_COBROS_TIENDA = (
    RolUsuario.DIRECCION,
    RolUsuario.ADMINISTRACION,
    RolUsuario.ENCARGADO_TIENDA,
    RolUsuario.LIDER,
    RolUsuario.ASESORA,
)


@enrutador.get("/cuentas-por-cobrar")
def listar_cuentas_por_cobrar(
    tipo: TipoCuentaPorCobrar | None = Query(default=None),
    estado: EstadoCuentaPorCobrar | None = Query(default=None),
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_COBROS_TIENDA)),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    es_admin = usuario_actual.rol in (RolUsuario.DIRECCION.value, RolUsuario.ADMINISTRACION.value)
    tipo_efectivo = tipo if es_admin else TipoCuentaPorCobrar.CLIENTE

    consulta = bd.query(CuentaPorCobrar).options(
        joinedload(CuentaPorCobrar.venta).joinedload(Venta.sucursal),
        joinedload(CuentaPorCobrar.cliente),
    )
    if tipo_efectivo is not None:
        consulta = consulta.filter(CuentaPorCobrar.tipo == tipo_efectivo.value)
    if estado is not None:
        consulta = consulta.filter(CuentaPorCobrar.estado == estado.value)

    filas = consulta.order_by(CuentaPorCobrar.id.desc()).all()
    if not es_admin and usuario_actual.sucursal_id is not None:
        filas = [
            c
            for c in filas
            if c.venta is not None and c.venta.sucursal_id == usuario_actual.sucursal_id
        ]
    filas = [
        c
        for c in filas
        if c.venta is None or c.venta.estado not in (EstadoVenta.ANULADA.value, EstadoVenta.DEVUELTA.value)
    ]
    return [
        {
            "id": c.id,
            "venta_id": c.venta_id,
            "numero_venta": c.venta.numero_venta if c.venta else None,
            "sucursal_id": c.venta.sucursal_id if c.venta else None,
            "sucursal": c.venta.sucursal.nombre if c.venta and c.venta.sucursal else None,
            "fecha_venta": c.venta.fecha.isoformat() if c.venta else None,
            "tipo": c.tipo,
            "cliente": c.cliente.nombre if c.cliente else "Cliente general",
            "monto_original_usd": redondear_usd(c.monto_original_usd),
            "monto_abonado_usd": redondear_usd(
                max(Decimal("0"), Decimal(c.monto_original_usd or 0) - Decimal(c.saldo_pendiente_usd or 0))
            ),
            "saldo_pendiente_usd": redondear_usd(c.saldo_pendiente_usd),
            "cashea_comision_venta_usd": redondear_usd(c.venta.cashea_comision_venta_usd) if c.venta else 0.0,
            "cashea_comision_financiado_usd": redondear_usd(c.venta.cashea_comision_financiado_usd) if c.venta else 0.0,
            "cashea_iva_usd": redondear_usd(c.venta.cashea_iva_usd) if c.venta else 0.0,
            "cashea_islr_usd": redondear_usd(c.venta.cashea_islr_usd) if c.venta else 0.0,
            "cashea_total_cargos_usd": redondear_usd(c.venta.cashea_total_cargos_usd) if c.venta else 0.0,
            "cashea_neto_por_cobrar_usd": (
                redondear_usd(c.venta.cashea_neto_por_cobrar_usd)
                if (c.venta and c.tipo == TipoCuentaPorCobrar.CASHEA.value and c.venta.cashea_neto_por_cobrar_usd > 0)
                else redondear_usd(c.saldo_pendiente_usd)
            ),
            "estado": c.estado,
        }
        for c in filas
    ]


@enrutador.post("/cuentas-por-cobrar/{cxc_id}/abono")
def registrar_abono_cxc(
    cxc_id: int,
    datos: AbonoCxcEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_COBROS_TIENDA)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    fecha_op = datos.fecha or obtener_fecha_hoy()
    verificar_mes_abierto(bd, fecha_op)

    cxc = (
        bd.query(CuentaPorCobrar)
        .options(joinedload(CuentaPorCobrar.venta))
        .filter(CuentaPorCobrar.id == cxc_id)
        .first()
    )
    if cxc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta por cobrar no encontrada.")
    if cxc.estado != EstadoCuentaPorCobrar.PENDIENTE.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta cuenta ya no está pendiente.")

    es_admin = usuario_actual.rol in (RolUsuario.DIRECCION.value, RolUsuario.ADMINISTRACION.value)
    if not es_admin:
        if cxc.tipo != TipoCuentaPorCobrar.CLIENTE.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo Dirección o Administración pueden liquidar cuentas Cashea.",
            )
        if (
            usuario_actual.sucursal_id is not None
            and cxc.venta is not None
            and cxc.venta.sucursal_id != usuario_actual.sucursal_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes registrar abonos de notas emitidas en tu sucursal.",
            )

    items_pago: list[AbonoPagoItem] = []
    if datos.pagos and len(datos.pagos) > 0:
        items_pago = list(datos.pagos)
    elif datos.instrumento_id is not None and datos.monto_moneda_origen is not None:
        items_pago = [
            AbonoPagoItem(
                instrumento_id=datos.instrumento_id,
                monto_moneda_origen=datos.monto_moneda_origen,
                referencia=datos.referencia,
            )
        ]
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debes indicar al menos un método de pago y un monto mayor a cero.",
        )

    tasa = bd.query(TasaDiaria).filter(TasaDiaria.fecha == fecha_op).first()
    tasa_bcv = tasa.tasa_bcv if tasa else Decimal("0")
    tasa_usdt = tasa.tasa_usdt if tasa else Decimal("0")

    total_usd_nominal = Decimal("0.00")
    pagos_registrados: list[dict[str, Any]] = []

    for item in items_pago:
        inst = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.id == item.instrumento_id).first()
        if inst is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Instrumento #{item.instrumento_id} no encontrado.",
            )
        nom_low = (inst.nombre or "").lower()
        if "cuenta por cobrar" in nom_low or "cashea" in nom_low:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se puede registrar un abono usando el instrumento '{inst.nombre}'.",
            )
        if inst.moneda == MonedaInstrumento.BS.value and (tasa is None or tasa_bcv <= 0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No existe tasa BCV del día para registrar abonos en bolívares.",
            )

        if inst.moneda == MonedaInstrumento.BS.value:
            usd_nominal = (item.monto_moneda_origen / tasa_bcv).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            usd_real = (
                (item.monto_moneda_origen / tasa_usdt).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if tasa_usdt > 0
                else usd_nominal
            )
        else:
            usd_nominal = item.monto_moneda_origen.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            usd_real = usd_nominal

        ref_limpia = (item.referencia or "").strip()
        bd.add(
            Pago(
                venta_id=cxc.venta_id,
                instrumento_id=inst.id,
                fecha=fecha_op,
                tipo_movimiento=TipoMovimientoPago.INGRESO.value,
                tipo_documento=TipoDocumentoPago.ABONO.value,
                monto_moneda_origen=item.monto_moneda_origen,
                moneda=inst.moneda,
                tasa_bcv_dia=tasa_bcv,
                tasa_usdt_dia=tasa_usdt,
                usd_nominal=usd_nominal,
                usd_real=usd_real,
                cubre_promo_usd=usd_nominal,
                referencia=ref_limpia,
                estado_verificacion=(
                    EstadoVerificacionPago.PENDIENTE.value
                    if inst.requiere_verificacion
                    else EstadoVerificacionPago.CONFIRMADO.value
                ),
            )
        )
        total_usd_nominal += usd_nominal
        pagos_registrados.append(
            {
                "instrumento_id": inst.id,
                "instrumento": inst.nombre,
                "moneda": inst.moneda,
                "monto_moneda_origen": redondear_usd(item.monto_moneda_origen),
                "usd_nominal": redondear_usd(usd_nominal),
                "referencia": ref_limpia,
            }
        )

    saldo_anterior = Decimal(cxc.saldo_pendiente_usd or 0)
    if total_usd_nominal > saldo_anterior + Decimal("0.50"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"El total abonado (${total_usd_nominal:.2f}) excede el saldo pendiente "
                f"(${saldo_anterior:.2f})."
            ),
        )

    cxc.saldo_pendiente_usd = max(Decimal("0"), saldo_anterior - total_usd_nominal)
    liquidada = False
    if cxc.saldo_pendiente_usd <= Decimal("0.50"):
        cxc.saldo_pendiente_usd = Decimal("0")
        cxc.estado = EstadoCuentaPorCobrar.PAGADA.value
        liquidada = True
        venta = bd.query(Venta).filter(Venta.id == cxc.venta_id).first()
        if venta and venta.estado == EstadoVenta.CON_SALDO.value:
            venta.estado = EstadoVenta.CUADRADA.value

    bd.commit()
    return {
        "id": cxc.id,
        "venta_id": cxc.venta_id,
        "saldo_pendiente_usd": redondear_usd(cxc.saldo_pendiente_usd),
        "total_abonado_usd": redondear_usd(total_usd_nominal),
        "estado": cxc.estado,
        "liquidada": liquidada,
        "pagos_registrados": pagos_registrados,
    }


@enrutador.post("/cashea/liquidar")
def liquidar_cashea(
    datos: CasheaLiquidarEntrada,
    _usuario: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    verificar_mes_abierto(bd, datos.fecha_pago)

    tasa = bd.query(TasaDiaria).filter(TasaDiaria.fecha == datos.fecha_pago).first()
    if tasa is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No existe tasa BCV registrada para la fecha de pago de Cashea.",
        )

    destino = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.id == datos.instrumento_destino_id)
        .first()
    )
    if destino is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instrumento destino no encontrado.")

    cuentas = (
        bd.query(CuentaPorCobrar)
        .filter(
            CuentaPorCobrar.id.in_(datos.cuentas_cashea_ids),
            CuentaPorCobrar.tipo == TipoCuentaPorCobrar.CASHEA.value,
            CuentaPorCobrar.estado == EstadoCuentaPorCobrar.PENDIENTE.value,
        )
        .all()
    )
    if not cuentas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontraron cuentas Cashea pendientes con los IDs indicados.",
        )

    total_bruto_usd = sum((c.saldo_pendiente_usd for c in cuentas), Decimal("0"))
    neto_usd = max(Decimal("0"), total_bruto_usd - datos.comision_usd - datos.impuestos_usd)

    if destino.moneda == MonedaInstrumento.BS.value:
        monto_origen = (neto_usd * tasa.tasa_bcv).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        usd_real = (monto_origen / tasa.tasa_usdt).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if tasa.tasa_usdt > 0 else neto_usd
    else:
        monto_origen = neto_usd
        usd_real = neto_usd

    bd.add(
        Pago(
            venta_id=None,
            instrumento_id=destino.id,
            fecha=datos.fecha_pago,
            tipo_movimiento=TipoMovimientoPago.TRASLADO.value,
            tipo_documento=TipoDocumentoPago.CASHEA.value,
            monto_moneda_origen=monto_origen,
            moneda=destino.moneda,
            tasa_bcv_dia=tasa.tasa_bcv,
            tasa_usdt_dia=tasa.tasa_usdt,
            usd_nominal=neto_usd,
            usd_real=usd_real,
            cubre_promo_usd=neto_usd,
            referencia=datos.referencia.strip(),
            estado_verificacion=EstadoVerificacionPago.CONFIRMADO.value,
            nota=(
                f"Liquidación Cashea ({len(cuentas)} notas) · Bruto ${redondear_usd(total_bruto_usd):.2f} "
                f"- Com ${redondear_usd(datos.comision_usd):.2f} - Imp ${redondear_usd(datos.impuestos_usd):.2f}"
            ),
        )
    )

    for c in cuentas:
        c.saldo_pendiente_usd = Decimal("0")
        c.estado = EstadoCuentaPorCobrar.PAGADA.value

    bd.commit()
    return {
        "cuentas_liquidadas": len(cuentas),
        "total_bruto_usd": redondear_usd(total_bruto_usd),
        "neto_depositado_usd": redondear_usd(neto_usd),
        "monto_moneda_destino": redondear_usd(monto_origen),
        "moneda_destino": destino.moneda,
    }


# ---------------- Conciliación Bancaria (CSV / Excel) ----------------

@enrutador.post("/conciliacion/importar")
async def importar_conciliacion(
    instrumento_id: int = Form(...),
    archivo: UploadFile = File(...),
    _usuario: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    inst = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.id == instrumento_id).first()
    if inst is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instrumento no encontrado.")

    contenido = await archivo.read()
    filas = _leer_filas_archivo(archivo.filename or "extracto.csv", contenido)

    extractos_creados: list[ExtractoBancario] = []
    for fila in filas:
        raw_fecha = fila.get("fecha") or obtener_fecha_hoy().isoformat()
        try:
            fecha_ext = date.fromisoformat(raw_fecha[:10])
        except ValueError:
            fecha_ext = obtener_fecha_hoy()

        raw_monto = fila.get("monto_con_signo") or fila.get("monto") or fila.get("credito") or "0"
        try:
            monto_dec = Decimal(raw_monto.replace(",", ".")).quantize(Decimal("0.01"))
        except Exception:
            monto_dec = Decimal("0")

        ext = ExtractoBancario(
            instrumento_id=instrumento_id,
            fecha=fecha_ext,
            referencia=(fila.get("referencia") or fila.get("ref") or "").strip(),
            descripcion=(fila.get("descripcion") or fila.get("concepto") or "").strip(),
            monto_con_signo=monto_dec,
            conciliado=False,
        )
        bd.add(ext)
        bd.flush()
        extractos_creados.append(ext)

    # Cruce automático por instrumento + referencia + monto exacto
    pagos_pendientes = (
        bd.query(Pago)
        .filter(
            Pago.instrumento_id == instrumento_id,
            Pago.anulado.is_(False),
            Pago.conciliado.is_(False),
        )
        .all()
    )

    cuadrados = []
    for ext in extractos_creados:
        if not ext.referencia:
            continue
        match = next(
            (
                p
                for p in pagos_pendientes
                if not p.conciliado
                and p.referencia.strip().lower() == ext.referencia.strip().lower()
                and abs(p.monto_moneda_origen - abs(ext.monto_con_signo)) <= Decimal("0.05")
            ),
            None,
        )
        if match is not None:
            match.conciliado = True
            match.extracto_id = ext.id
            ext.conciliado = True
            cuadrados.append(
                {
                    "pago_id": match.id,
                    "extracto_id": ext.id,
                    "referencia": ext.referencia,
                    "monto": redondear_usd(match.monto_moneda_origen),
                }
            )

    bd.commit()

    sin_banco = [
        {
            "pago_id": p.id,
            "fecha": p.fecha.isoformat(),
            "referencia": p.referencia,
            "monto": redondear_usd(p.monto_moneda_origen),
        }
        for p in pagos_pendientes
        if not p.conciliado
    ]
    sin_sistema = [
        {
            "extracto_id": e.id,
            "fecha": e.fecha.isoformat(),
            "referencia": e.referencia,
            "descripcion": e.descripcion,
            "monto": redondear_usd(e.monto_con_signo),
        }
        for e in extractos_creados
        if not e.conciliado
    ]

    return {
        "cuadrados": cuadrados,
        "registrados_sin_banco": sin_banco,
        "en_banco_sin_registrar": sin_sistema,
    }


@enrutador.post("/conciliacion/cruzar-manual")
def cruzar_conciliacion_manual(
    datos: CruceManualEntrada,
    _usuario: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    pago = bd.query(Pago).filter(Pago.id == datos.pago_id).first()
    extracto = bd.query(ExtractoBancario).filter(ExtractoBancario.id == datos.extracto_id).first()
    if pago is None or extracto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pago o extracto no encontrado.")

    pago.conciliado = True
    pago.extracto_id = extracto.id
    extracto.conciliado = True
    bd.commit()
    return {"pago_id": pago.id, "extracto_id": extracto.id, "conciliado": True}


# ---------------- Comisiones, Tablero y Cierre Mensual ----------------

def calcular_reporte_comisiones(
    bd: Session, mes: int, anio: int, sucursal_id: int | None = None
) -> list[dict[str, Any]]:
    usuarios = bd.query(Usuario).filter(Usuario.activo.is_(True)).all()
    usuarios_map = {u.id: u for u in usuarios}

    consulta_ventas_globales = (
        bd.query(Venta)
        .options(joinedload(Venta.detalles).joinedload(VentaDetalle.articulo))
        .filter(
            Venta.estado.notin_([EstadoVenta.ANULADA.value, EstadoVenta.DEVUELTA.value]),
            extract("month", Venta.fecha) == mes,
            extract("year", Venta.fecha) == anio,
        )
    )
    ventas_globales = consulta_ventas_globales.all()
    ventas = (
        [v for v in ventas_globales if v.sucursal_id == sucursal_id]
        if sucursal_id is not None
        else ventas_globales
    )

    # Reglas oficiales de Comisiones Alfa Importaciones (SIEMPRE sobre Precio Promo USD, incluso en ventas Cashea/Regular,
    # excluyendo ventas ANULADA / DEVUELTA):
    # - Asesor (ASESORA / TECNICO / otros no encargados): PASILLO -> 1%, LEAD -> 8%.
    # - Encargado de Tienda (ENCARGADO_TIENDA / compatibilidad LIDER): PASILLO -> 5%, LEAD -> 8%.
    # - Tienda (asesor_id is None): 0% en cualquier origen.
    # - Servicio Técnico / Mano de Obra (TipoArticulo.SERVICIO): 50% al tecnico_id (excluido de comisión por ventas).
    ventas_pasillo_por_asesor: dict[int, Decimal] = {}
    ventas_leads_por_asesor: dict[int, Decimal] = {}
    st_por_tecnico: dict[int, Decimal] = {}

    for v in ventas:
        es_lead = (getattr(v, "origen_venta", OrigenVenta.PASILLO.value) or OrigenVenta.PASILLO.value).upper() == OrigenVenta.LEAD.value
        mapa_origen = ventas_leads_por_asesor if es_lead else ventas_pasillo_por_asesor

        if not v.detalles:
            if v.asesor_id is not None:
                mapa_origen[v.asesor_id] = mapa_origen.get(v.asesor_id, Decimal("0")) + v.total_promo_usd
            continue

        for det in v.detalles:
            subtotal_promo = det.precio_promo_usd * Decimal(det.cantidad)
            es_servicio = det.articulo is not None and det.articulo.tipo == TipoArticulo.SERVICIO.value
            if es_servicio:
                if v.tecnico_id is not None:
                    com_50 = (subtotal_promo * Decimal("0.50")).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    st_por_tecnico[v.tecnico_id] = st_por_tecnico.get(v.tecnico_id, Decimal("0")) + com_50
            else:
                if v.asesor_id is not None:
                    mapa_origen[v.asesor_id] = mapa_origen.get(v.asesor_id, Decimal("0")) + subtotal_promo

    # Ajustes de comisión por cambios Upgrade (+) y Downgrade (-) del período
    from app.modelos_operaciones import DevolucionGarantia, TipoResolucionDevolucion

    ajustes_dev = (
        bd.query(DevolucionGarantia)
        .options(joinedload(DevolucionGarantia.venta))
        .filter(
            DevolucionGarantia.tipo_resolucion.in_(
                [
                    TipoResolucionDevolucion.CAMBIO_UPGRADE.value,
                    TipoResolucionDevolucion.CAMBIO_DOWNGRADE.value,
                ]
            ),
            extract("month", DevolucionGarantia.fecha) == mes,
            extract("year", DevolucionGarantia.fecha) == anio,
        )
        .all()
    )
    for dev in ajustes_dev:
        vta = dev.venta
        if vta is None or vta.asesor_id is None:
            continue
        if vta.estado in (EstadoVenta.ANULADA.value, EstadoVenta.DEVUELTA.value):
            continue
        dif = dev.diferencia_promo_usd or Decimal("0")
        if sucursal_id is None or vta.sucursal_id == sucursal_id:
            es_lead_dev = (getattr(vta, "origen_venta", OrigenVenta.PASILLO.value) or OrigenVenta.PASILLO.value).upper() == OrigenVenta.LEAD.value
            mapa_dev = ventas_leads_por_asesor if es_lead_dev else ventas_pasillo_por_asesor
            mapa_dev[vta.asesor_id] = max(
                Decimal("0"),
                mapa_dev.get(vta.asesor_id, Decimal("0")) + dif,
            )

    # Preparaciones y servicios técnicos del mes
    preparaciones = (
        bd.query(Preparacion)
        .filter(
            extract("month", Preparacion.fecha) == mes,
            extract("year", Preparacion.fecha) == anio,
        )
        .all()
    )
    prep_por_tecnico: dict[int, Decimal] = {}
    for p in preparaciones:
        prep_por_tecnico[p.tecnico_id] = prep_por_tecnico.get(p.tecnico_id, Decimal("0")) + p.pago_tecnico_usd

    estados_st = {
        EstadoCasoPostventa.TERMINADO.value,
        EstadoCasoPostventa.LISTO_PARA_ENTREGAR.value,
        EstadoCasoPostventa.ENTREGADO.value,
    }
    casos_st = (
        bd.query(CasoPostventa)
        .options(joinedload(CasoPostventa.presupuestos))
        .filter(
            CasoPostventa.tipo == TipoCasoPostventa.SERVICIO.value,
            CasoPostventa.estado.in_(estados_st),
            extract("month", CasoPostventa.fecha_ingreso) == mes,
            extract("year", CasoPostventa.fecha_ingreso) == anio,
        )
        .all()
    )
    for c in casos_st:
        if c.tecnico_id is None:
            continue
        pres_aprob = next((pr for pr in c.presupuestos if pr.aprobado_cliente is True), None)
        if pres_aprob is not None:
            com_50 = (pres_aprob.mano_obra_usd * Decimal("0.50")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            st_por_tecnico[c.tecnico_id] = st_por_tecnico.get(c.tecnico_id, Decimal("0")) + com_50

    reporte: list[dict[str, Any]] = []
    for uid, u in usuarios_map.items():
        ventas_pasillo = ventas_pasillo_por_asesor.get(uid, Decimal("0"))
        ventas_leads = ventas_leads_por_asesor.get(uid, Decimal("0"))
        ventas_propias = ventas_pasillo + ventas_leads

        es_encargado = u.rol in (RolUsuario.ENCARGADO_TIENDA.value, RolUsuario.LIDER.value)
        tasa_pasillo = Decimal("0.05") if es_encargado else Decimal("0.01")
        tasa_leads = Decimal("0.08")

        com_pasillo = (ventas_pasillo * tasa_pasillo).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        com_leads = (ventas_leads * tasa_leads).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        com_ventas_total = com_pasillo + com_leads

        com_servicios = st_por_tecnico.get(uid, Decimal("0"))
        pago_preps = prep_por_tecnico.get(uid, Decimal("0"))
        total_persona = com_ventas_total + com_servicios + pago_preps

        if total_persona > 0 or u.rol in (
            RolUsuario.ASESORA.value,
            RolUsuario.ENCARGADO_TIENDA.value,
            RolUsuario.LIDER.value,
            RolUsuario.TECNICO.value,
        ):
            reporte.append(
                {
                    "usuario_id": uid,
                    "nombre": u.nombre,
                    "rol": u.rol,
                    "es_encargado": es_encargado,
                    "ventas_pasillo_usd": redondear_usd(ventas_pasillo),
                    "porcentaje_pasillo": 5 if es_encargado else 1,
                    "comision_pasillo_usd": redondear_usd(com_pasillo),
                    "ventas_leads_usd": redondear_usd(ventas_leads),
                    "porcentaje_leads": 8,
                    "comision_leads_usd": redondear_usd(com_leads),
                    "ventas_promo_usd": redondear_usd(ventas_propias),
                    "comision_ventas_1_usd": redondear_usd(com_ventas_total),
                    "comision_lider_05_usd": 0.0,
                    "comision_servicios_50_usd": redondear_usd(com_servicios),
                    "pago_preparaciones_usd": redondear_usd(pago_preps),
                    "total_comision_usd": redondear_usd(total_persona),
                }
            )

    return reporte


@enrutador.get("/comisiones")
def obtener_comisiones(
    mes: int | None = Query(default=None, ge=1, le=12),
    anio: int | None = Query(default=None, ge=2020, le=2100),
    sucursal_id: int | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    hoy = obtener_fecha_hoy()
    mes_obj = mes or hoy.month
    anio_obj = anio or hoy.year
    reporte = calcular_reporte_comisiones(bd, mes_obj, anio_obj, sucursal_id)
    cierre = (
        bd.query(CierreMensual)
        .filter(CierreMensual.anio == anio_obj, CierreMensual.mes == mes_obj)
        .first()
    )
    return {
        "mes": mes_obj,
        "anio": anio_obj,
        "mes_cerrado": bool(cierre and cierre.bloqueado),
        "comisiones": reporte,
    }


@enrutador.get("/tablero")
def obtener_tablero_financiero(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    sucursal_id: int | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    hoy = obtener_fecha_hoy()
    f_desde = desde or date(hoy.year, hoy.month, 1)
    f_hasta = hasta or hoy

    consulta_ventas = (
        bd.query(Venta)
        .options(joinedload(Venta.detalles), joinedload(Venta.pagos))
        .filter(
            Venta.estado.notin_([EstadoVenta.ANULADA.value, EstadoVenta.DEVUELTA.value]),
            Venta.fecha >= f_desde,
            Venta.fecha <= f_hasta,
        )
    )
    if sucursal_id is not None:
        consulta_ventas = consulta_ventas.filter(Venta.sucursal_id == sucursal_id)
    ventas = consulta_ventas.all()

    venta_promo = sum((v.total_promo_usd for v in ventas), Decimal("0"))
    usd_nominal = Decimal("0")
    usd_real = Decimal("0")
    costo_total = Decimal("0")

    for v in ventas:
        for d in v.detalles:
            costo_total += d.costo_total_snapshot_usd
        for p in v.pagos:
            if not p.anulado:
                usd_nominal += p.usd_nominal
                usd_real += p.usd_real

    diferencial = usd_nominal - usd_real
    utilidad_real = usd_real - costo_total

    cashea_pendiente = sum(
        (
            c.saldo_pendiente_usd
            for c in bd.query(CuentaPorCobrar)
            .filter(
                CuentaPorCobrar.tipo == TipoCuentaPorCobrar.CASHEA.value,
                CuentaPorCobrar.estado == EstadoCuentaPorCobrar.PENDIENTE.value,
            )
            .all()
        ),
        Decimal("0"),
    )

    return {
        "desde": f_desde.isoformat(),
        "hasta": f_hasta.isoformat(),
        "cantidad_ventas": len(ventas),
        "venta_promo_usd": redondear_usd(venta_promo),
        "usd_nominal": redondear_usd(usd_nominal),
        "usd_real": redondear_usd(usd_real),
        "diferencial_cambiario_usd": redondear_usd(diferencial),
        "cashea_por_cobrar_usd": redondear_usd(cashea_pendiente),
        "costo_total_usd": redondear_usd(costo_total),
        "utilidad_real_neta_usd": redondear_usd(utilidad_real),
    }


@enrutador.post("/cierres-mensuales", status_code=status.HTTP_201_CREATED)
def cerrar_mes(
    datos: CierreMensualEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(RolUsuario.DIRECCION.value)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    existente = (
        bd.query(CierreMensual)
        .filter(CierreMensual.anio == datos.anio, CierreMensual.mes == datos.mes)
        .first()
    )
    if existente is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El mes {datos.mes:02d}/{datos.anio} ya fue cerrado.",
        )

    comisiones = calcular_reporte_comisiones(bd, datos.mes, datos.anio)
    resumen = {
        "mes": datos.mes,
        "anio": datos.anio,
        "comisiones": comisiones,
    }
    cierre = CierreMensual(
        anio=datos.anio,
        mes=datos.mes,
        cerrado_por_id=usuario_actual.id,
        resumen_json=json.dumps(resumen, ensure_ascii=False),
        bloqueado=True,
    )
    bd.add(cierre)
    bd.commit()
    bd.refresh(cierre)
    return {
        "id": cierre.id,
        "anio": cierre.anio,
        "mes": cierre.mes,
        "bloqueado": cierre.bloqueado,
        "cerrado_por": usuario_actual.nombre,
    }


@enrutador_comisiones.get("/reporte")
def obtener_reporte_comisiones_avanzado(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    personal_id: int | None = Query(default=None),
    rol: str | None = Query(default=None),
    origen: str | None = Query(default=None),
    estado_comision: str | None = Query(default="TODOS"),
    sucursal_id: int | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """
    Reporte avanzado de comisiones Alfa por rango de fechas, asesor/encargado (con o sin acceso), origen y estado.
    Calcula estrictamente sobre Precio Promo USD excluyendo ventas ANULADA / DEVUELTA y Tienda (asesor_id=None).
    """
    hoy = obtener_fecha_hoy()
    f_inicio = fecha_inicio or date(hoy.year, hoy.month, 1 if hoy.day <= 15 else 16)
    f_fin = fecha_fin or hoy
    if f_inicio > f_fin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha_inicio no puede ser mayor que fecha_fin.",
        )

    origen_norm = origen.strip().upper() if origen and origen.strip() else None
    if origen_norm and origen_norm not in (OrigenVenta.PASILLO.value, OrigenVenta.LEAD.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El filtro origen debe ser PASILLO o LEAD.",
        )

    estado_com_norm = (estado_comision or "TODOS").strip().upper()
    if estado_com_norm not in ("TODOS", EstadoComision.PENDIENTE.value, EstadoComision.PAGADA.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El filtro estado_comision debe ser TODOS, PENDIENTE o PAGADA.",
        )

    rol_norm = rol.strip().upper() if rol and rol.strip() else None

    def _coincide_rol(u_rol: str) -> bool:
        if not rol_norm:
            return True
        if rol_norm in ("ENCARGADO", "ENCARGADO_TIENDA", "LIDER"):
            return u_rol in (RolUsuario.ENCARGADO_TIENDA.value, RolUsuario.LIDER.value)
        if rol_norm in ("ASESOR", "ASESORA"):
            return u_rol == RolUsuario.ASESORA.value
        return u_rol == rol_norm

    usuarios = bd.query(Usuario).all()
    usuarios_map = {u.id: u for u in usuarios}

    consulta_ventas = (
        bd.query(Venta)
        .options(
            joinedload(Venta.cliente),
            joinedload(Venta.asesor),
            joinedload(Venta.detalles).joinedload(VentaDetalle.articulo),
        )
        .filter(
            Venta.estado.notin_([EstadoVenta.ANULADA.value, EstadoVenta.DEVUELTA.value]),
            Venta.asesor_id.isnot(None),
            Venta.fecha >= f_inicio,
            Venta.fecha <= f_fin,
        )
    )
    if personal_id is not None:
        consulta_ventas = consulta_ventas.filter(Venta.asesor_id == personal_id)
    if sucursal_id is not None:
        consulta_ventas = consulta_ventas.filter(Venta.sucursal_id == sucursal_id)
    if origen_norm is not None:
        consulta_ventas = consulta_ventas.filter(Venta.origen_venta == origen_norm)
    if estado_com_norm in (EstadoComision.PENDIENTE.value, EstadoComision.PAGADA.value):
        consulta_ventas = consulta_ventas.filter(Venta.estado_comision == estado_com_norm)

    ventas = consulta_ventas.order_by(Venta.fecha.desc(), Venta.id.desc()).all()

    acumulado: dict[int, dict[str, Any]] = {}
    detalle_ventas: list[dict[str, Any]] = []

    def _asegurar_persona(u: Usuario) -> dict[str, Any]:
        if u.id not in acumulado:
            es_enc = u.rol in (RolUsuario.ENCARGADO_TIENDA.value, RolUsuario.LIDER.value)
            acumulado[u.id] = {
                "personal_id": u.id,
                "nombre": u.nombre,
                "rol": u.rol,
                "es_encargado": es_enc,
                "modalidad": getattr(u, "modalidad", "PRESENCIAL") or "PRESENCIAL",
                "telefono": getattr(u, "telefono", "") or "",
                "porcentaje_pasillo": 5 if es_enc else 1,
                "porcentaje_lead": 8,
                "cantidad_pasillo": 0,
                "base_pasillo_usd": Decimal("0"),
                "comision_pasillo_usd": Decimal("0"),
                "cantidad_lead": 0,
                "base_lead_usd": Decimal("0"),
                "comision_lead_usd": Decimal("0"),
                "pendiente_usd": Decimal("0"),
                "pagado_usd": Decimal("0"),
                "total_ventas": 0,
                "total_comision_usd": Decimal("0"),
            }
        return acumulado[u.id]

    for v in ventas:
        if v.asesor_id is None or v.asesor_id not in usuarios_map:
            continue
        u = usuarios_map[v.asesor_id]
        if not _coincide_rol(u.rol):
            continue

        # Calcular base Precio Promo USD excluyendo Servicio Técnico
        if not v.detalles:
            base_promo = v.total_promo_usd
            productos_txt = "Venta general"
        else:
            base_promo = Decimal("0")
            nombres_prod: list[str] = []
            for det in v.detalles:
                es_serv = det.articulo is not None and det.articulo.tipo == TipoArticulo.SERVICIO.value
                if not es_serv:
                    base_promo += det.precio_promo_usd * Decimal(det.cantidad)
                    desc = det.descripcion or (det.articulo.descripcion if det.articulo else "Producto")
                    nombres_prod.append(f"{det.cantidad}x {desc}" if det.cantidad > 1 else desc)
            productos_txt = ", ".join(nombres_prod) if nombres_prod else "Servicio Técnico"

        if base_promo <= 0:
            continue

        origen_vta = (getattr(v, "origen_venta", OrigenVenta.PASILLO.value) or OrigenVenta.PASILLO.value).upper()
        estado_com_vta = (getattr(v, "estado_comision", EstadoComision.PENDIENTE.value) or EstadoComision.PENDIENTE.value).upper()
        es_lead = origen_vta == OrigenVenta.LEAD.value
        es_enc = u.rol in (RolUsuario.ENCARGADO_TIENDA.value, RolUsuario.LIDER.value)
        pct = 8 if es_lead else (5 if es_enc else 1)
        comision = (base_promo * Decimal(pct) / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        acc = _asegurar_persona(u)
        acc["total_ventas"] += 1
        if es_lead:
            acc["cantidad_lead"] += 1
            acc["base_lead_usd"] += base_promo
            acc["comision_lead_usd"] += comision
        else:
            acc["cantidad_pasillo"] += 1
            acc["base_pasillo_usd"] += base_promo
            acc["comision_pasillo_usd"] += comision

        if estado_com_vta == EstadoComision.PAGADA.value:
            acc["pagado_usd"] += comision
        else:
            acc["pendiente_usd"] += comision
        acc["total_comision_usd"] += comision

        detalle_ventas.append(
            {
                "venta_id": v.id,
                "personal_id": u.id,
                "asesor": u.nombre,
                "fecha": v.fecha.isoformat(),
                "numero_venta": v.numero_venta,
                "cliente": v.cliente.nombre if v.cliente else "Cliente general",
                "producto": productos_txt,
                "origen": origen_vta,
                "estado_comision": estado_com_vta,
                "liquidacion_id": getattr(v, "liquidacion_id", None),
                "base_promo_usd": redondear_usd(base_promo),
                "porcentaje_aplicado": pct,
                "comision_usd": redondear_usd(comision),
            }
        )

    por_persona_lista = sorted(
        acumulado.values(),
        key=lambda x: (-float(x["pendiente_usd"]), -float(x["total_comision_usd"]), x["nombre"]),
    )
    por_persona_serializado = [
        {
            "personal_id": p["personal_id"],
            "nombre": p["nombre"],
            "rol": p["rol"],
            "es_encargado": p["es_encargado"],
            "modalidad": p["modalidad"],
            "telefono": p["telefono"],
            "porcentaje_pasillo": p["porcentaje_pasillo"],
            "porcentaje_lead": p["porcentaje_lead"],
            "cantidad_pasillo": p["cantidad_pasillo"],
            "base_pasillo_usd": redondear_usd(p["base_pasillo_usd"]),
            "comision_pasillo_usd": redondear_usd(p["comision_pasillo_usd"]),
            "cantidad_lead": p["cantidad_lead"],
            "base_lead_usd": redondear_usd(p["base_lead_usd"]),
            "comision_lead_usd": redondear_usd(p["comision_lead_usd"]),
            "pendiente_usd": redondear_usd(p["pendiente_usd"]),
            "pagado_usd": redondear_usd(p["pagado_usd"]),
            "total_ventas": p["total_ventas"],
            "total_comision_usd": redondear_usd(p["total_comision_usd"]),
        }
        for p in por_persona_lista
    ]

    total_ventas_gen = sum(p["total_ventas"] for p in por_persona_lista)
    vol_promo_gen = sum(
        (p["base_pasillo_usd"] + p["base_lead_usd"] for p in por_persona_lista),
        Decimal("0"),
    )
    pasillo_gen = sum((p["comision_pasillo_usd"] for p in por_persona_lista), Decimal("0"))
    lead_gen = sum((p["comision_lead_usd"] for p in por_persona_lista), Decimal("0"))
    pendiente_gen = sum((p["pendiente_usd"] for p in por_persona_lista), Decimal("0"))
    pagado_gen = sum((p["pagado_usd"] for p in por_persona_lista), Decimal("0"))
    total_com_gen = pasillo_gen + lead_gen

    ultima_tasa = bd.query(TasaDiaria).order_by(TasaDiaria.fecha.desc()).first()
    tasa_bcv_ref = float(ultima_tasa.tasa_bcv) if ultima_tasa and ultima_tasa.tasa_bcv > 0 else None

    return {
        "fecha_inicio": f_inicio.isoformat(),
        "fecha_fin": f_fin.isoformat(),
        "estado_comision": estado_com_norm,
        "tasa_bcv_referencia": tasa_bcv_ref,
        "resumen_general": {
            "total_ventas": total_ventas_gen,
            "volumen_promo_usd": redondear_usd(vol_promo_gen),
            "pasillo_usd": redondear_usd(pasillo_gen),
            "lead_usd": redondear_usd(lead_gen),
            "pendiente_usd": redondear_usd(pendiente_gen),
            "pagado_usd": redondear_usd(pagado_gen),
            "total_comisiones_usd": redondear_usd(total_com_gen),
        },
        "por_persona": por_persona_serializado,
        "detalle_ventas": detalle_ventas,
    }


def _calcular_comision_venta_individual(venta: Venta, usuario: Usuario) -> tuple[Decimal, str, int, Decimal, str]:
    """Devuelve (base_promo_usd, origen, porcentaje, comision_usd, descripcion_producto)."""
    if not venta.detalles:
        base_promo = venta.total_promo_usd
        productos_txt = "Venta general"
    else:
        base_promo = Decimal("0")
        nombres: list[str] = []
        for det in venta.detalles:
            es_serv = det.articulo is not None and det.articulo.tipo == TipoArticulo.SERVICIO.value
            if not es_serv:
                base_promo += det.precio_promo_usd * Decimal(det.cantidad)
                desc = det.descripcion or (det.articulo.descripcion if det.articulo else "Producto")
                nombres.append(f"{det.cantidad}x {desc}" if det.cantidad > 1 else desc)
        productos_txt = ", ".join(nombres) if nombres else "Servicio Técnico"

    origen_vta = (getattr(venta, "origen_venta", OrigenVenta.PASILLO.value) or OrigenVenta.PASILLO.value).upper()
    es_lead = origen_vta == OrigenVenta.LEAD.value
    es_enc = usuario.rol in (RolUsuario.ENCARGADO_TIENDA.value, RolUsuario.LIDER.value)
    pct = 8 if es_lead else (5 if es_enc else 1)
    comision = (base_promo * Decimal(pct) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return base_promo, origen_vta, pct, comision, productos_txt


def _serializar_liquidacion(liq: LiquidacionComision, incluir_ventas: bool = False) -> dict[str, Any]:
    personal = liq.personal
    inst = getattr(liq, "instrumento_pago", None)
    mov = getattr(liq, "movimiento_financiero", None)
    datos: dict[str, Any] = {
        "id": liq.id,
        "codigo": liq.codigo,
        "personal_id": liq.personal_id,
        "personal_nombre": personal.nombre if personal else f"Personal #{liq.personal_id}",
        "personal_rol": personal.rol if personal else "",
        "personal_telefono": getattr(personal, "telefono", "") if personal else "",
        "personal_modalidad": getattr(personal, "modalidad", "PRESENCIAL") if personal else "PRESENCIAL",
        "fecha_inicio": liq.fecha_inicio.isoformat(),
        "fecha_fin": liq.fecha_fin.isoformat(),
        "cantidad_ventas": liq.cantidad_ventas,
        "cantidad_pasillo": liq.cantidad_pasillo,
        "cantidad_lead": liq.cantidad_lead,
        "monto_pasillo_usd": redondear_usd(liq.monto_pasillo_usd),
        "monto_lead_usd": redondear_usd(liq.monto_lead_usd),
        "monto_total_usd": redondear_usd(liq.monto_total_usd),
        "metodo_pago": liq.metodo_pago,
        "instrumento_pago_id": getattr(liq, "instrumento_pago_id", None),
        "instrumento_pago_nombre": inst.nombre if inst else liq.metodo_pago,
        "instrumento_pago_moneda": inst.moneda if inst else ("BS" if liq.monto_bs else "USD"),
        "movimiento_financiero_id": getattr(liq, "movimiento_financiero_id", None),
        "egreso_registrado": bool(
            getattr(liq, "movimiento_financiero_id", None)
            and (mov is None or not mov.anulado)
            and liq.estado == EstadoLiquidacionComision.PAGADA.value
        ),
        "tasa_bcv_aplicada": float(liq.tasa_bcv_aplicada) if liq.tasa_bcv_aplicada is not None else None,
        "monto_bs": redondear_usd(liq.monto_bs) if liq.monto_bs is not None else None,
        "referencia": liq.referencia,
        "observaciones": liq.observaciones,
        "estado": liq.estado,
        "motivo_anulacion": liq.motivo_anulacion,
        "pagado_por": liq.pagado_por.nombre if liq.pagado_por else None,
        "created_at": liq.created_at.isoformat() if liq.created_at else None,
    }
    if incluir_ventas and personal is not None:
        ventas_det: list[dict[str, Any]] = []
        for v in liq.ventas:
            base_promo, origen_vta, pct, comision, prod_txt = _calcular_comision_venta_individual(v, personal)
            ventas_det.append(
                {
                    "venta_id": v.id,
                    "fecha": v.fecha.isoformat(),
                    "numero_venta": v.numero_venta,
                    "cliente": v.cliente.nombre if v.cliente else "Cliente general",
                    "producto": prod_txt,
                    "origen": origen_vta,
                    "base_promo_usd": redondear_usd(base_promo),
                    "porcentaje_aplicado": pct,
                    "comision_usd": redondear_usd(comision),
                }
            )
        datos["ventas"] = ventas_det
    return datos


def _generar_codigo_liquidacion(bd: Session, anio: int) -> str:
    prefijo = f"LIQ-{anio}-"
    cantidad = (
        bd.query(func.count(LiquidacionComision.id))
        .filter(LiquidacionComision.codigo.like(f"{prefijo}%"))
        .scalar()
        or 0
    )
    secuencia = int(cantidad) + 1
    while True:
        candidato = f"{prefijo}{secuencia:04d}"
        if not bd.query(LiquidacionComision.id).filter(LiquidacionComision.codigo == candidato).first():
            return candidato
        secuencia += 1


@enrutador_comisiones.post("/liquidaciones", status_code=status.HTTP_201_CREATED)
def crear_liquidacion_comisiones(
    datos: LiquidacionCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Registra una liquidación quincenal en una transacción atómica, evitando cualquier doble pago (409)."""
    personal = bd.query(Usuario).filter(Usuario.id == datos.personal_id).first()
    if personal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Colaborador no encontrado.")

    ids_unicos = list(dict.fromkeys(datos.venta_ids))
    ventas = (
        bd.query(Venta)
        .options(
            joinedload(Venta.cliente),
            joinedload(Venta.detalles).joinedload(VentaDetalle.articulo),
        )
        .filter(Venta.id.in_(ids_unicos))
        .all()
    )
    if len(ventas) != len(ids_unicos):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Una o más ventas seleccionadas no existen.",
        )

    cantidad_pasillo = 0
    cantidad_lead = 0
    monto_pasillo = Decimal("0")
    monto_lead = Decimal("0")

    for v in ventas:
        if v.asesor_id != personal.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"La venta {v.numero_venta} no pertenece a {personal.nombre}.",
            )
        if v.estado in (EstadoVenta.ANULADA.value, EstadoVenta.DEVUELTA.value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"La venta {v.numero_venta} está {v.estado} y no puede liquidarse.",
            )
        estado_com = (getattr(v, "estado_comision", EstadoComision.PENDIENTE.value) or EstadoComision.PENDIENTE.value).upper()
        if estado_com == EstadoComision.PAGADA.value or getattr(v, "liquidacion_id", None) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La venta {v.numero_venta} ya fue liquidada anteriormente (doble pago bloqueado).",
            )

        base_promo, origen_vta, _pct, comision, _prod = _calcular_comision_venta_individual(v, personal)
        if base_promo <= 0:
            continue
        if origen_vta == OrigenVenta.LEAD.value:
            cantidad_lead += 1
            monto_lead += comision
        else:
            cantidad_pasillo += 1
            monto_pasillo += comision

    monto_total = monto_pasillo + monto_lead
    if monto_total <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las ventas seleccionadas no generan comisión pendiente mayor a $0.00.",
        )

    # Resolver y validar instrumento financiero de pago
    instrumento: InstrumentoFinanciero | None = None
    if datos.instrumento_pago_id is not None:
        instrumento = (
            bd.query(InstrumentoFinanciero)
            .filter(
                InstrumentoFinanciero.id == datos.instrumento_pago_id,
                InstrumentoFinanciero.activo.is_(True),
            )
            .first()
        )
        if instrumento is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El instrumento financiero seleccionado no existe o está inactivo.",
            )
    else:
        # Compatibilidad si se envía solo metodo_pago (ej. PAGO_MOVIL / ZELLE / EFECTIVO_USD)
        metodo_up = (datos.metodo_pago or "").strip().upper()
        quiere_bs = metodo_up in ("PAGO_MOVIL", "TRANSFERENCIA_BS", "EFECTIVO_BS") or "BS" in metodo_up
        consulta_inst = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.activo.is_(True))
        if quiere_bs:
            instrumento = consulta_inst.filter(InstrumentoFinanciero.moneda == MonedaInstrumento.BS.value).first()
        else:
            instrumento = consulta_inst.filter(InstrumentoFinanciero.moneda != MonedaInstrumento.BS.value).first()
        if instrumento is None:
            instrumento = consulta_inst.first()
        if instrumento is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No hay instrumentos financieros activos disponibles para registrar el egreso.",
            )

    hoy = obtener_fecha_hoy()
    es_bs = instrumento.moneda == MonedaInstrumento.BS.value
    tasa_bcv = datos.tasa_bcv_aplicada
    if es_bs and tasa_bcv is None:
        tasa_dia = bd.query(TasaDiaria).order_by(TasaDiaria.fecha.desc()).first()
        if tasa_dia and tasa_dia.tasa_bcv > 0:
            tasa_bcv = tasa_dia.tasa_bcv
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes indicar una tasa BCV válida para pagos en bolívares.",
            )

    monto_bs = (
        (monto_total * tasa_bcv).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if es_bs and tasa_bcv is not None
        else None
    )

    codigo = _generar_codigo_liquidacion(bd, hoy.year)
    metodo_etiqueta = datos.metodo_pago.strip() or instrumento.nombre

    try:
        liq = LiquidacionComision(
            codigo=codigo,
            personal_id=personal.id,
            fecha_inicio=datos.fecha_inicio,
            fecha_fin=datos.fecha_fin,
            cantidad_ventas=cantidad_pasillo + cantidad_lead,
            cantidad_pasillo=cantidad_pasillo,
            cantidad_lead=cantidad_lead,
            monto_pasillo_usd=monto_pasillo,
            monto_lead_usd=monto_lead,
            monto_total_usd=monto_total,
            metodo_pago=metodo_etiqueta,
            instrumento_pago_id=instrumento.id,
            tasa_bcv_aplicada=tasa_bcv if es_bs else None,
            monto_bs=monto_bs,
            referencia=datos.referencia.strip(),
            observaciones=datos.observaciones.strip(),
            estado=EstadoLiquidacionComision.PAGADA.value,
            pagado_por_id=usuario_actual.id,
        )
        bd.add(liq)
        bd.flush()

        # Registrar automáticamente el EGRESO en Caja/Finanzas en la misma transacción
        descripcion_egreso = (
            f"Pago de comisiones {codigo} - {personal.nombre} "
            f"({datos.fecha_inicio.isoformat()} al {datos.fecha_fin.isoformat()})"
        )
        pago_egreso = Pago(
            venta_id=None,
            instrumento_id=instrumento.id,
            fecha=hoy,
            tipo_movimiento=TipoMovimientoPago.EGRESO.value,
            tipo_documento=TipoDocumentoPago.COMISION.value,
            monto_moneda_origen=monto_bs if es_bs and monto_bs is not None else monto_total,
            moneda=instrumento.moneda,
            tasa_bcv_dia=tasa_bcv if es_bs and tasa_bcv is not None else Decimal("0"),
            tasa_usdt_dia=Decimal("0"),
            usd_nominal=monto_total,
            usd_real=monto_total,
            cubre_promo_usd=Decimal("0"),
            referencia=datos.referencia.strip() or codigo,
            estado_verificacion=EstadoVerificacionPago.CONFIRMADO.value,
            verificado_por_id=usuario_actual.id,
            conciliado=False,
            anulado=False,
            categoria="Pago de Comisiones",
            origen_tipo="LIQUIDACION_COMISION",
            origen_id=liq.id,
            nota=descripcion_egreso,
        )
        bd.add(pago_egreso)
        bd.flush()

        liq.movimiento_financiero_id = pago_egreso.id

        for v in ventas:
            v.estado_comision = EstadoComision.PAGADA.value
            v.liquidacion_id = liq.id

        # Asiento contable: Debe 2.1.02 Comisiones por Pagar / Haber 1.1.01 Cajas y Bancos
        from app.servicios.contabilidad import crear_asiento_contable

        crear_asiento_contable(
            bd=bd,
            usuario=usuario_actual,
            fecha_op=hoy,
            descripcion=f"Liquidación de Comisiones {codigo} - {personal.nombre} {datos.observaciones[:60]}",
            origen_tipo="LIQUIDACION_COMISION",
            origen_id=liq.id,
            lineas=[
                {"cuenta_codigo": "2.1.02", "debe_usd": monto_total, "haber_usd": 0, "nota": f"Cancelación comisiones {personal.nombre}"},
                {"cuenta_codigo": "1.1.01", "debe_usd": 0, "haber_usd": monto_total, "nota": f"Egreso {instrumento.nombre} ({codigo})"},
            ],
        )

        bd.commit()
    except HTTPException:
        bd.rollback()
        raise
    except Exception as exc:
        bd.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al registrar la liquidación y su egreso financiero: {exc}",
        ) from exc

    liq_completa = (
        bd.query(LiquidacionComision)
        .options(
            joinedload(LiquidacionComision.personal),
            joinedload(LiquidacionComision.pagado_por),
            joinedload(LiquidacionComision.instrumento_pago),
            joinedload(LiquidacionComision.movimiento_financiero),
            joinedload(LiquidacionComision.ventas).joinedload(Venta.cliente),
            joinedload(LiquidacionComision.ventas).joinedload(Venta.detalles).joinedload(VentaDetalle.articulo),
        )
        .filter(LiquidacionComision.id == liq.id)
        .first()
    )
    return _serializar_liquidacion(liq_completa, incluir_ventas=True)


@enrutador_comisiones.get("/liquidaciones")
def listar_liquidaciones_comisiones(
    personal_id: int | None = Query(default=None),
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    estado: str | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    consulta = bd.query(LiquidacionComision).options(
        joinedload(LiquidacionComision.personal),
        joinedload(LiquidacionComision.pagado_por),
        joinedload(LiquidacionComision.instrumento_pago),
        joinedload(LiquidacionComision.movimiento_financiero),
    )
    if personal_id is not None:
        consulta = consulta.filter(LiquidacionComision.personal_id == personal_id)
    if fecha_inicio is not None:
        consulta = consulta.filter(LiquidacionComision.fecha_fin >= fecha_inicio)
    if fecha_fin is not None:
        consulta = consulta.filter(LiquidacionComision.fecha_inicio <= fecha_fin)
    if estado and estado.strip():
        consulta = consulta.filter(LiquidacionComision.estado == estado.strip().upper())

    filas = consulta.order_by(LiquidacionComision.id.desc()).limit(200).all()
    return [_serializar_liquidacion(f, incluir_ventas=False) for f in filas]


@enrutador_comisiones.get("/liquidaciones/{liq_id}")
def obtener_liquidacion_detalle(
    liq_id: int,
    _usuario: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    liq = (
        bd.query(LiquidacionComision)
        .options(
            joinedload(LiquidacionComision.personal),
            joinedload(LiquidacionComision.pagado_por),
            joinedload(LiquidacionComision.instrumento_pago),
            joinedload(LiquidacionComision.movimiento_financiero),
            joinedload(LiquidacionComision.ventas).joinedload(Venta.cliente),
            joinedload(LiquidacionComision.ventas).joinedload(Venta.detalles).joinedload(VentaDetalle.articulo),
        )
        .filter(LiquidacionComision.id == liq_id)
        .first()
    )
    if liq is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liquidación no encontrada.")
    return _serializar_liquidacion(liq, incluir_ventas=True)


@enrutador_comisiones.post("/liquidaciones/{liq_id}/anular")
def anular_liquidacion_comision(
    liq_id: int,
    datos: LiquidacionAnularEntrada,
    _usuario: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Anula una liquidación, devuelve sus ventas a PENDIENTE y revierte automáticamente el egreso en Finanzas."""
    liq = (
        bd.query(LiquidacionComision)
        .options(
            joinedload(LiquidacionComision.personal),
            joinedload(LiquidacionComision.pagado_por),
            joinedload(LiquidacionComision.instrumento_pago),
            joinedload(LiquidacionComision.movimiento_financiero),
            joinedload(LiquidacionComision.ventas),
        )
        .filter(LiquidacionComision.id == liq_id)
        .first()
    )
    if liq is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liquidación no encontrada.")
    if liq.estado == EstadoLiquidacionComision.ANULADA.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta liquidación ya fue anulada.",
        )

    ventas_asociadas = bd.query(Venta).filter(Venta.liquidacion_id == liq.id).all()
    for v in ventas_asociadas:
        v.estado_comision = EstadoComision.PENDIENTE.value
        v.liquidacion_id = None

    # Revertir automáticamente el egreso vinculado en Caja/Finanzas para restaurar el saldo
    if liq.movimiento_financiero_id is not None:
        pago_egreso = bd.query(Pago).filter(Pago.id == liq.movimiento_financiero_id).first()
        if pago_egreso is not None:
            pago_egreso.anulado = True

    liq.estado = EstadoLiquidacionComision.ANULADA.value
    liq.motivo_anulacion = datos.motivo.strip()
    bd.commit()
    bd.refresh(liq)
    return _serializar_liquidacion(liq, incluir_ventas=False)


@enrutador_comisiones.get("/liquidaciones/{liq_id}/pdf")
def descargar_pdf_liquidacion(
    liq_id: int,
    _usuario: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> Response:
    liq = (
        bd.query(LiquidacionComision)
        .options(
            joinedload(LiquidacionComision.personal),
            joinedload(LiquidacionComision.pagado_por),
            joinedload(LiquidacionComision.ventas).joinedload(Venta.cliente),
            joinedload(LiquidacionComision.ventas).joinedload(Venta.detalles).joinedload(VentaDetalle.articulo),
        )
        .filter(LiquidacionComision.id == liq_id)
        .first()
    )
    if liq is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liquidación no encontrada.")

    serializada = _serializar_liquidacion(liq, incluir_ventas=True)
    pdf_bytes = generar_pdf_liquidacion_comision(liq, serializada.get("ventas", []))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{liq.codigo}.pdf"'},
    )
