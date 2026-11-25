from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.modelos import TasaDiaria, Usuario
from app.modelos_contabilidad import AsientoContable, AsientoDetalle, PlanCuenta
from app.semilla_contabilidad import ejecutar_semilla_contabilidad


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _obtener_tasa_bcv(bd: Session, fecha_op: date) -> Decimal:
    t = bd.query(TasaDiaria).filter(TasaDiaria.fecha <= fecha_op).order_by(TasaDiaria.fecha.desc()).first()
    if t and t.tasa_bcv and t.tasa_bcv > 0:
        return Decimal(t.tasa_bcv)
    return Decimal("1")


def obtener_cuenta_por_codigo(bd: Session, codigo: str) -> PlanCuenta:
    cuenta = bd.query(PlanCuenta).filter(PlanCuenta.codigo == codigo).first()
    if cuenta is None:
        ejecutar_semilla_contabilidad(bd)
        cuenta = bd.query(PlanCuenta).filter(PlanCuenta.codigo == codigo).first()
    if cuenta is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cuenta contable '{codigo}' no encontrada en el Plan de Cuentas.",
        )
    return cuenta


def crear_asiento_contable(
    bd: Session,
    usuario: Usuario | None,
    fecha_op: date,
    descripcion: str,
    origen_tipo: str,
    origen_id: int | str,
    lineas: list[dict[str, Any]],
) -> AsientoContable:
    """
    Crea un asiento contable de partida doble dentro de la transacción actual (sin hacer commit).
    Cada línea acepta:
      - cuenta_codigo (str) o cuenta_contable_id (int)
      - debe_usd (Decimal | float | str)
      - haber_usd (Decimal | float | str)
      - moneda_origen (opcional, default 'USD')
      - monto_origen (opcional)
      - nota (opcional)
    Valida estrictamente que SUM(debe_usd) == SUM(haber_usd).
    """
    if not lineas or len(lineas) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un asiento contable requiere al menos 2 líneas (Debe y Haber).",
        )

    tasa_bcv = _obtener_tasa_bcv(bd, fecha_op)
    total_debe = Decimal("0")
    total_haber = Decimal("0")
    detalles_obj: list[AsientoDetalle] = []

    for lin in lineas:
        debe = _q2(Decimal(str(lin.get("debe_usd", 0) or 0)))
        haber = _q2(Decimal(str(lin.get("haber_usd", 0) or 0)))
        if debe < 0 or haber < 0:
            raise HTTPException(status_code=400, detail="Los montos de Debe y Haber no pueden ser negativos.")
        if debe == 0 and haber == 0:
            continue

        if lin.get("cuenta_contable_id"):
            cta = bd.query(PlanCuenta).filter(PlanCuenta.id == int(lin["cuenta_contable_id"])).first()
            if cta is None:
                raise HTTPException(status_code=404, detail=f"Cuenta contable ID {lin['cuenta_contable_id']} no existe.")
        elif lin.get("cuenta_codigo"):
            cta = obtener_cuenta_por_codigo(bd, str(lin["cuenta_codigo"]))
        else:
            raise HTTPException(status_code=400, detail="Cada línea requiere cuenta_codigo o cuenta_contable_id.")

        total_debe += debe
        total_haber += haber
        monto_orig = _q2(Decimal(str(lin.get("monto_origen", debe if debe > 0 else haber))))
        detalles_obj.append(
            AsientoDetalle(
                cuenta_contable_id=cta.id,
                debe_usd=debe,
                haber_usd=haber,
                moneda_origen=str(lin.get("moneda_origen", "USD")),
                monto_origen=monto_orig,
                tasa_bcv=tasa_bcv,
                nota=str(lin.get("nota", ""))[:255],
            )
        )

    if not detalles_obj:
        raise HTTPException(status_code=400, detail="El asiento contable no tiene movimientos con monto > 0.")

    if abs(total_debe - total_haber) > Decimal("0.01"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Asiento descuadrado: Debe (${total_debe:.2f}) != Haber (${total_haber:.2f}).",
        )

    asiento = AsientoContable(
        fecha=fecha_op,
        descripcion=descripcion[:255],
        origen_tipo=origen_tipo.upper(),
        origen_id=str(origen_id),
        estado="CONTABILIZADO",
        creado_por=usuario.nombre if usuario else "Sistema",
    )
    bd.add(asiento)
    bd.flush()

    for det in detalles_obj:
        det.asiento_id = asiento.id
        bd.add(det)

    return asiento


def reversar_asiento_origen(
    bd: Session,
    usuario: Usuario | None,
    origen_tipo: str,
    origen_id: int | str,
    fecha_op: date,
    motivo: str = "Anulación",
) -> AsientoContable | None:
    """Genera un contra-asiento automático invirtiendo Debe y Haber del asiento original."""
    original = (
        bd.query(AsientoContable)
        .filter(
            AsientoContable.origen_tipo == origen_tipo.upper(),
            AsientoContable.origen_id == str(origen_id),
            AsientoContable.estado == "CONTABILIZADO",
        )
        .order_by(AsientoContable.id.desc())
        .first()
    )
    if original is None or not original.detalles:
        return None

    original.estado = "REVERSADO"
    lineas_inversas = [
        {
            "cuenta_contable_id": d.cuenta_contable_id,
            "debe_usd": d.haber_usd,
            "haber_usd": d.debe_usd,
            "moneda_origen": d.moneda_origen,
            "monto_origen": d.monto_origen,
            "nota": f"Reverso: {motivo}",
        }
        for d in original.detalles
    ]
    return crear_asiento_contable(
        bd=bd,
        usuario=usuario,
        fecha_op=fecha_op,
        descripcion=f"Contra-asiento ({motivo}): {original.descripcion}",
        origen_tipo=f"REVERSO_{origen_tipo.upper()}",
        origen_id=origen_id,
        lineas=lineas_inversas,
    )
