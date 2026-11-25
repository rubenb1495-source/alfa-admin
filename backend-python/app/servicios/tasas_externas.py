from __future__ import annotations

import json
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any


URL_DOLARAPI_VE = "https://ve.dolarapi.com/v1/dolares"


def _a_decimal_positivo(valor: Any) -> Decimal | None:
    if valor is None:
        return None
    try:
        dec = Decimal(str(valor)).quantize(Decimal("0.0001"))
        return dec if dec > 0 else None
    except (InvalidOperation, ValueError):
        return None


def consultar_tasas_automaticas(timeout_segundos: float = 5.0) -> dict[str, Any] | None:
    """
    Consulta las tasas oficiales (BCV) y paralela/USDT en tiempo real desde ve.dolarapi.com.
    Devuelve {"tasa_bcv": Decimal, "tasa_usdt": Decimal, "fuente_tasa": "API_VIVO"}
    o None si ocurre cualquier error de red, timeout o formato (nunca lanza excepción).
    """
    req = urllib.request.Request(
        URL_DOLARAPI_VE,
        headers={
            "Accept": "application/json",
            "User-Agent": "AlfaImportacionesAdmin/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_segundos) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            crudo = resp.read().decode("utf-8", errors="replace")
            datos = json.loads(crudo)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return None

    if not isinstance(datos, list):
        return None

    tasa_bcv: Decimal | None = None
    tasa_usdt: Decimal | None = None

    for item in datos:
        if not isinstance(item, dict):
            continue
        fuente = str(item.get("fuente") or "").strip().lower()
        nombre = str(item.get("nombre") or "").strip().lower()
        valor = _a_decimal_positivo(item.get("promedio")) or _a_decimal_positivo(item.get("venta"))
        if valor is None:
            continue
        if fuente == "oficial" or "bcv" in nombre or "oficial" in nombre:
            tasa_bcv = valor
        elif fuente == "paralelo" or "paralelo" in nombre or "usdt" in nombre:
            tasa_usdt = valor

    if tasa_bcv is None:
        return None
    if tasa_usdt is None:
        tasa_usdt = tasa_bcv

    return {
        "tasa_bcv": tasa_bcv,
        "tasa_usdt": tasa_usdt,
        "fuente_tasa": "API_VIVO",
    }
