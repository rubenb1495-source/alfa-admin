from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.modelos import TasaDiaria, Usuario
from app.modelos_finanzas import (
    EstadoMovimientoTesoreria,
    EstadoVerificacionPago,
    InstrumentoFinanciero,
    MonedaInstrumento,
    MovimientoTesoreria,
    Pago,
    ResultadoCambiario,
    TipoDocumentoPago,
    TipoMovimientoPago,
    TipoMovimientoTesoreria,
)
from app.rutas.logistica import generar_correlativo
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import requerir_admin, requerir_direccion_lectura


enrutador = APIRouter(prefix="/api/tesoreria", tags=["Tesorería y Diferencial Cambiario"])


def _q2(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q4(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _obtener_tasas_vigentes(bd: Session, fecha_op: date) -> tuple[Decimal, Decimal]:
    tasa = bd.query(TasaDiaria).filter(TasaDiaria.fecha == fecha_op).first()
    if tasa is None:
        tasa = bd.query(TasaDiaria).order_by(TasaDiaria.fecha.desc()).first()
    if tasa is None:
        return Decimal("0"), Decimal("0")
    return Decimal(tasa.tasa_bcv or 0), Decimal(tasa.tasa_usdt or 0)


def _convertir_a_usd(monto: Decimal, moneda: str, tasa_ref: Decimal) -> Decimal:
    if moneda.upper() == MonedaInstrumento.BS.value:
        if tasa_ref <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No hay una tasa de referencia válida (> 0) para convertir Bolívares a USD.",
            )
        return _q2(monto / tasa_ref)
    return _q2(monto)


class MovimientoTesoreriaCrearEntrada(BaseModel):
    tipo: TipoMovimientoTesoreria
    fecha: date | None = None
    cuenta_origen_id: int | None = None
    monto_salida: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    cuenta_destino_id: int | None = None
    monto_entrada: Decimal | None = Field(default=None, ge=Decimal("0"))
    tasa_operacion: Decimal | None = Field(default=None, gt=Decimal("0"))
    tasa_referencia_tipo: str = Field(default="BCV", pattern="^(BCV|USDT)$")
    comision_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    concepto: str = Field(default="", max_length=200)
    referencia: str = Field(default="", max_length=120)
    observaciones: str = Field(default="", max_length=500)


class MovimientoTesoreriaAnularEntrada(BaseModel):
    motivo: str = Field(min_length=3, max_length=300)


def _serializar_movimiento(m: MovimientoTesoreria) -> dict[str, Any]:
    return {
        "id": m.id,
        "codigo": m.codigo,
        "tipo": m.tipo,
        "fecha": m.fecha.isoformat() if m.fecha else None,
        "estado": m.estado,
        "cuenta_origen_id": m.cuenta_origen_id,
        "cuenta_origen_nombre": m.cuenta_origen.nombre if m.cuenta_origen else None,
        "moneda_origen": m.moneda_origen,
        "monto_salida": float(_q2(m.monto_salida)),
        "cuenta_destino_id": m.cuenta_destino_id,
        "cuenta_destino_nombre": m.cuenta_destino.nombre if m.cuenta_destino else None,
        "moneda_destino": m.moneda_destino,
        "monto_entrada": float(_q2(m.monto_entrada)),
        "comision_usd": float(_q2(m.comision_usd)),
        "tasa_referencia_tipo": m.tasa_referencia_tipo,
        "tasa_bcv_dia": float(_q4(m.tasa_bcv_dia)),
        "tasa_usdt_dia": float(_q4(m.tasa_usdt_dia)),
        "tasa_referencia_aplicada": float(_q4(m.tasa_referencia_aplicada)),
        "tasa_operacion": float(_q4(m.tasa_operacion)) if m.tasa_operacion is not None else None,
        "equivalente_salida_usd": float(_q2(m.equivalente_salida_usd)),
        "equivalente_entrada_usd": float(_q2(m.equivalente_entrada_usd)),
        "diferencial_usd": float(_q2(m.diferencial_usd)),
        "diferencial_porcentaje": float(_q2(m.diferencial_porcentaje)),
        "resultado_tipo": m.resultado_tipo,
        "concepto": m.concepto,
        "referencia": m.referencia,
        "observaciones": m.observaciones,
        "registrado_por": m.registrado_por.nombre if m.registrado_por else "",
        "anulado_por": m.anulado_por.nombre if m.anulado_por else None,
        "motivo_anulacion": m.motivo_anulacion,
        "creado_en": m.creado_en.isoformat() if m.creado_en else None,
    }


@enrutador.get("/movimientos")
def listar_movimientos_tesoreria(
    tipo: TipoMovimientoTesoreria | None = Query(default=None),
    cuenta_id: int | None = Query(default=None),
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    consulta = (
        bd.query(MovimientoTesoreria)
        .options(
            joinedload(MovimientoTesoreria.cuenta_origen),
            joinedload(MovimientoTesoreria.cuenta_destino),
            joinedload(MovimientoTesoreria.registrado_por),
            joinedload(MovimientoTesoreria.anulado_por),
        )
        .order_by(MovimientoTesoreria.fecha.desc(), MovimientoTesoreria.id.desc())
    )
    if tipo is not None:
        consulta = consulta.filter(MovimientoTesoreria.tipo == tipo.value)
    if cuenta_id is not None:
        consulta = consulta.filter(
            (MovimientoTesoreria.cuenta_origen_id == cuenta_id)
            | (MovimientoTesoreria.cuenta_destino_id == cuenta_id)
        )
    if fecha_inicio is not None:
        consulta = consulta.filter(MovimientoTesoreria.fecha >= fecha_inicio)
    if fecha_fin is not None:
        consulta = consulta.filter(MovimientoTesoreria.fecha <= fecha_fin)

    movimientos = consulta.limit(200).all()

    total_ganancia = Decimal("0")
    total_perdida = Decimal("0")
    for m in movimientos:
        if m.estado != EstadoMovimientoTesoreria.CONFIRMADO.value:
            continue
        if m.diferencial_usd > 0:
            total_ganancia += m.diferencial_usd
        elif m.diferencial_usd < 0:
            total_perdida += abs(m.diferencial_usd)

    neto = total_ganancia - total_perdida
    return {
        "resumen": {
            "total_ganancia_usd": float(_q2(total_ganancia)),
            "total_perdida_usd": float(_q2(total_perdida)),
            "resultado_neto_usd": float(_q2(neto)),
            "cantidad_movimientos": len(movimientos),
        },
        "movimientos": [_serializar_movimiento(m) for m in movimientos],
    }


@enrutador.post("/movimientos", status_code=status.HTTP_201_CREATED)
def crear_movimiento_tesoreria(
    datos: MovimientoTesoreriaCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    fecha_op = datos.fecha or obtener_fecha_hoy()
    tasa_bcv, tasa_usdt = _obtener_tasas_vigentes(bd, fecha_op)
    tasa_ref = tasa_usdt if datos.tasa_referencia_tipo == "USDT" else tasa_bcv
    if tasa_ref <= 0:
        tasa_ref = tasa_bcv if tasa_bcv > 0 else tasa_usdt

    origen: InstrumentoFinanciero | None = None
    destino: InstrumentoFinanciero | None = None

    if datos.cuenta_origen_id is not None:
        origen = (
            bd.query(InstrumentoFinanciero)
            .filter(InstrumentoFinanciero.id == datos.cuenta_origen_id, InstrumentoFinanciero.activo.is_(True))
            .first()
        )
        if origen is None:
            raise HTTPException(status_code=404, detail="Cuenta de origen no encontrada.")

    if datos.cuenta_destino_id is not None:
        destino = (
            bd.query(InstrumentoFinanciero)
            .filter(InstrumentoFinanciero.id == datos.cuenta_destino_id, InstrumentoFinanciero.activo.is_(True))
            .first()
        )
        if destino is None:
            raise HTTPException(status_code=404, detail="Cuenta de destino no encontrada.")

    monto_salida = datos.monto_salida
    monto_entrada = datos.monto_entrada if datos.monto_entrada is not None else Decimal("0")
    tasa_op = datos.tasa_operacion

    eq_salida_usd = Decimal("0")
    eq_entrada_usd = Decimal("0")
    diferencial_usd = Decimal("0")
    diferencial_pct = Decimal("0")
    resultado_tipo = ResultadoCambiario.NEUTRO.value

    if datos.tipo in (TipoMovimientoTesoreria.TRASLADO, TipoMovimientoTesoreria.CAMBIO_DIVISA):
        if origen is None or destino is None:
            raise HTTPException(
                status_code=400,
                detail="Debes seleccionar cuenta de origen y cuenta de destino.",
            )
        if origen.id == destino.id:
            raise HTTPException(
                status_code=400,
                detail="La cuenta de origen y la cuenta de destino deben ser distintas.",
            )
        if monto_salida <= 0:
            raise HTTPException(status_code=400, detail="El monto de salida debe ser mayor a 0.")

        # Si no viene monto_entrada explícito, calcularlo con tasa_operacion o paridad
        if datos.monto_entrada is None:
            if tasa_op is not None:
                if origen.moneda != MonedaInstrumento.BS.value and destino.moneda == MonedaInstrumento.BS.value:
                    monto_entrada = _q2(monto_salida * tasa_op)
                elif origen.moneda == MonedaInstrumento.BS.value and destino.moneda != MonedaInstrumento.BS.value:
                    monto_entrada = _q2(monto_salida / tasa_op)
                else:
                    monto_entrada = _q2(monto_salida * tasa_op)
            elif origen.moneda == destino.moneda:
                monto_entrada = _q2(monto_salida)
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Debes indicar monto_entrada o tasa_operacion para cambios entre monedas distintas.",
                )

        if monto_entrada <= 0:
            raise HTTPException(status_code=400, detail="El monto de entrada debe ser mayor a 0.")

        # Calcular tasa efectiva si no se envió explícita y hay cruce BS <-> USD
        if tasa_op is None:
            if origen.moneda != MonedaInstrumento.BS.value and destino.moneda == MonedaInstrumento.BS.value:
                tasa_op = _q4(monto_entrada / monto_salida)
            elif origen.moneda == MonedaInstrumento.BS.value and destino.moneda != MonedaInstrumento.BS.value:
                tasa_op = _q4(monto_salida / monto_entrada)

        eq_salida_usd = _convertir_a_usd(monto_salida, origen.moneda, tasa_ref)
        eq_entrada_usd = _convertir_a_usd(monto_entrada, destino.moneda, tasa_ref)
        diferencial_usd = _q2(eq_entrada_usd - eq_salida_usd - datos.comision_usd)
        if eq_salida_usd > 0:
            diferencial_pct = _q2((diferencial_usd / eq_salida_usd) * Decimal("100"))

        if diferencial_usd > 0:
            resultado_tipo = ResultadoCambiario.GANANCIA.value
        elif diferencial_usd < 0:
            resultado_tipo = ResultadoCambiario.PERDIDA.value
        else:
            resultado_tipo = ResultadoCambiario.NEUTRO.value

    elif datos.tipo == TipoMovimientoTesoreria.INGRESO_ADMIN:
        if destino is None or monto_entrada <= 0:
            raise HTTPException(
                status_code=400,
                detail="Un ingreso administrativo requiere cuenta de destino y monto de entrada > 0.",
            )
        origen = None
        monto_salida = Decimal("0")
        eq_entrada_usd = _convertir_a_usd(monto_entrada, destino.moneda, tasa_ref)

    elif datos.tipo == TipoMovimientoTesoreria.EGRESO_ADMIN:
        if origen is None or monto_salida <= 0:
            raise HTTPException(
                status_code=400,
                detail="Un egreso administrativo requiere cuenta de origen y monto de salida > 0.",
            )
        destino = None
        monto_entrada = Decimal("0")
        eq_salida_usd = _convertir_a_usd(monto_salida, origen.moneda, tasa_ref)

    codigo = generar_correlativo(bd, MovimientoTesoreria, MovimientoTesoreria.codigo, "TES")
    concepto_final = datos.concepto.strip() or f"{datos.tipo.value} {codigo}"

    pago_salida: Pago | None = None
    pago_entrada: Pago | None = None

    if origen is not None and monto_salida > 0:
        pago_salida = Pago(
            instrumento_id=origen.id,
            fecha=fecha_op,
            tipo_movimiento=TipoMovimientoPago.EGRESO.value,
            tipo_documento=TipoDocumentoPago.TESORERIA.value,
            monto_moneda_origen=_q2(monto_salida),
            moneda=origen.moneda,
            tasa_bcv_dia=tasa_bcv,
            tasa_usdt_dia=tasa_usdt,
            usd_nominal=eq_salida_usd,
            usd_real=eq_salida_usd,
            cubre_promo_usd=eq_salida_usd,
            referencia=datos.referencia.strip() or codigo,
            estado_verificacion=EstadoVerificacionPago.CONFIRMADO.value,
            verificado_por_id=usuario_actual.id,
            anulado=False,
            categoria=f"Tesorería · {datos.tipo.value}",
            origen_tipo="TESORERIA",
            nota=concepto_final,
        )
        bd.add(pago_salida)
        bd.flush()

    if destino is not None and monto_entrada > 0:
        pago_entrada = Pago(
            instrumento_id=destino.id,
            fecha=fecha_op,
            tipo_movimiento=TipoMovimientoPago.INGRESO.value,
            tipo_documento=TipoDocumentoPago.TESORERIA.value,
            monto_moneda_origen=_q2(monto_entrada),
            moneda=destino.moneda,
            tasa_bcv_dia=tasa_bcv,
            tasa_usdt_dia=tasa_usdt,
            usd_nominal=eq_entrada_usd,
            usd_real=eq_entrada_usd,
            cubre_promo_usd=eq_entrada_usd,
            referencia=datos.referencia.strip() or codigo,
            estado_verificacion=EstadoVerificacionPago.CONFIRMADO.value,
            verificado_por_id=usuario_actual.id,
            anulado=False,
            categoria=f"Tesorería · {datos.tipo.value}",
            origen_tipo="TESORERIA",
            nota=concepto_final,
        )
        bd.add(pago_entrada)
        bd.flush()

    mov = MovimientoTesoreria(
        codigo=codigo,
        tipo=datos.tipo.value,
        fecha=fecha_op,
        estado=EstadoMovimientoTesoreria.CONFIRMADO.value,
        cuenta_origen_id=origen.id if origen else None,
        moneda_origen=origen.moneda if origen else "",
        monto_salida=_q2(monto_salida),
        cuenta_destino_id=destino.id if destino else None,
        moneda_destino=destino.moneda if destino else "",
        monto_entrada=_q2(monto_entrada),
        comision_usd=_q2(datos.comision_usd),
        tasa_referencia_tipo=datos.tasa_referencia_tipo,
        tasa_bcv_dia=tasa_bcv,
        tasa_usdt_dia=tasa_usdt,
        tasa_referencia_aplicada=tasa_ref,
        tasa_operacion=tasa_op,
        equivalente_salida_usd=eq_salida_usd,
        equivalente_entrada_usd=eq_entrada_usd,
        diferencial_usd=diferencial_usd,
        diferencial_porcentaje=diferencial_pct,
        resultado_tipo=resultado_tipo,
        concepto=concepto_final,
        referencia=datos.referencia.strip(),
        observaciones=datos.observaciones.strip(),
        pago_salida_id=pago_salida.id if pago_salida else None,
        pago_entrada_id=pago_entrada.id if pago_entrada else None,
        registrado_por_id=usuario_actual.id,
    )
    bd.add(mov)
    bd.flush()

    if pago_salida is not None:
        pago_salida.origen_id = mov.id
    if pago_entrada is not None:
        pago_entrada.origen_id = mov.id

    # Asiento automático de Diferencial Cambiario en Tesorería
    if diferencial_usd != 0:
        from app.servicios.contabilidad import crear_asiento_contable

        monto_diff = abs(diferencial_usd)
        if diferencial_usd > 0:
            lineas_tes = [
                {"cuenta_codigo": "1.1.01", "debe_usd": monto_diff, "haber_usd": Decimal("0"), "nota": f"Ganancia cambiaria {codigo}"},
                {"cuenta_codigo": "8.1.03", "debe_usd": Decimal("0"), "haber_usd": monto_diff, "nota": f"Diferencial cambiario {codigo}"},
            ]
        else:
            lineas_tes = [
                {"cuenta_codigo": "8.1.03", "debe_usd": monto_diff, "haber_usd": Decimal("0"), "nota": f"Pérdida cambiaria {codigo}"},
                {"cuenta_codigo": "1.1.01", "debe_usd": Decimal("0"), "haber_usd": monto_diff, "nota": f"Diferencial cambiario {codigo}"},
            ]
        crear_asiento_contable(
            bd=bd,
            usuario=usuario_actual,
            fecha_op=fecha_op,
            descripcion=f"Tesorería {codigo}: {concepto_final}",
            origen_tipo="TESORERIA",
            origen_id=mov.id,
            lineas=lineas_tes,
        )

    bd.commit()
    mov_cargado = (
        bd.query(MovimientoTesoreria)
        .options(
            joinedload(MovimientoTesoreria.cuenta_origen),
            joinedload(MovimientoTesoreria.cuenta_destino),
            joinedload(MovimientoTesoreria.registrado_por),
        )
        .filter(MovimientoTesoreria.id == mov.id)
        .first()
    )
    assert mov_cargado is not None
    return _serializar_movimiento(mov_cargado)


@enrutador.post("/movimientos/{movimiento_id}/anular")
def anular_movimiento_tesoreria(
    movimiento_id: int,
    datos: MovimientoTesoreriaAnularEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    mov = (
        bd.query(MovimientoTesoreria)
        .options(
            joinedload(MovimientoTesoreria.cuenta_origen),
            joinedload(MovimientoTesoreria.cuenta_destino),
            joinedload(MovimientoTesoreria.pago_salida),
            joinedload(MovimientoTesoreria.pago_entrada),
            joinedload(MovimientoTesoreria.registrado_por),
            joinedload(MovimientoTesoreria.anulado_por),
        )
        .filter(MovimientoTesoreria.id == movimiento_id)
        .first()
    )
    if mov is None:
        raise HTTPException(status_code=404, detail="Movimiento de tesorería no encontrado.")
    if mov.estado == EstadoMovimientoTesoreria.ANULADO.value:
        raise HTTPException(status_code=400, detail="Este movimiento ya se encuentra anulado.")

    mov.estado = EstadoMovimientoTesoreria.ANULADO.value
    mov.anulado_por_id = usuario_actual.id
    mov.motivo_anulacion = datos.motivo.strip()

    if mov.pago_salida is not None:
        mov.pago_salida.anulado = True
        mov.pago_salida.nota = f"{mov.pago_salida.nota} | ANULADO: {datos.motivo.strip()}"
    if mov.pago_entrada is not None:
        mov.pago_entrada.anulado = True
        mov.pago_entrada.nota = f"{mov.pago_entrada.nota} | ANULADO: {datos.motivo.strip()}"

    from app.rutas.administracion import registrar_auditoria
    from app.servicios.contabilidad import reversar_asiento_origen

    registrar_auditoria(
        bd,
        usuario_actual,
        "TESORERIA",
        "ANULAR",
        mov.id,
        datos_anteriores={"estado": "CONFIRMADO", "codigo": mov.codigo},
        datos_nuevos={"estado": "ANULADO", "motivo": datos.motivo.strip()},
    )
    reversar_asiento_origen(
        bd=bd,
        usuario=usuario_actual,
        origen_tipo="TESORERIA",
        origen_id=mov.id,
        fecha_op=obtener_fecha_hoy(),
        motivo=datos.motivo.strip(),
    )

    bd.commit()
    bd.refresh(mov)
    return _serializar_movimiento(mov)
