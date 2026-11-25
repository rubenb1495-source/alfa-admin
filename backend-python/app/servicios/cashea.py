from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def _q2(val: Decimal | float | int | str) -> Decimal:
    return Decimal(str(val or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_desglose_cashea(
    total_precio_regular_usd: Decimal | float,
    inicial_cobrada_usd: Decimal | float,
    tasa_bcv: Decimal | float = Decimal("0"),
    tasa_usdt: Decimal | float = Decimal("0"),
) -> dict[str, Any]:
    """
    Calcula con precisión Decimal (2 decimales) las conversiones de Precio Regular
    y todas las comisiones e impuestos que descuenta Cashea:
      - 4% sobre el total de la venta (Precio Regular)
      - 4% sobre el monto financiado
      - 16% IVA sobre el 4% de la venta
      - 2% ISLR sobre el 4% de la venta
      - Neto real por cobrar = monto_financiado - total_cargos
    """
    total_reg = _q2(total_precio_regular_usd)
    inicial = _q2(inicial_cobrada_usd)
    financiado = max(Decimal("0.00"), _q2(total_reg - inicial))

    bcv = Decimal(str(tasa_bcv or 0))
    usdt = Decimal(str(tasa_usdt or 0))

    total_bs = _q2(total_reg * bcv) if bcv > 0 else Decimal("0.00")
    total_usdt = _q2(total_bs / usdt) if (bcv > 0 and usdt > 0) else total_reg

    com_venta = _q2(total_reg * Decimal("0.04"))
    com_fin = _q2(financiado * Decimal("0.04"))
    iva = _q2(com_venta * Decimal("0.16"))
    islr = _q2(com_venta * Decimal("0.02"))
    total_cargos = _q2(com_venta + com_fin + iva + islr)
    neto_por_cobrar = max(Decimal("0.00"), _q2(financiado - total_cargos))

    neto_bs = _q2(neto_por_cobrar * bcv) if bcv > 0 else Decimal("0.00")
    neto_usdt = _q2(neto_bs / usdt) if (bcv > 0 and usdt > 0) else neto_por_cobrar

    return {
        "total_precio_regular_usd": total_reg,
        "total_precio_regular_bs": total_bs,
        "total_precio_regular_usdt": total_usdt,
        "inicial_cobrada_usd": inicial,
        "monto_financiado_usd": financiado,
        "cashea_comision_venta_usd": com_venta,
        "cashea_comision_financiado_usd": com_fin,
        "cashea_iva_usd": iva,
        "cashea_islr_usd": islr,
        "cashea_total_cargos_usd": total_cargos,
        "cashea_neto_por_cobrar_usd": neto_por_cobrar,
        "cashea_neto_bs": neto_bs,
        "cashea_neto_usdt": neto_usdt,
        "tasa_bcv_aplicada": bcv,
        "tasa_usdt_aplicada": usdt,
    }


def serializar_desglose_cashea(d: dict[str, Any]) -> dict[str, float]:
    return {k: float(v) for k, v in d.items()}
