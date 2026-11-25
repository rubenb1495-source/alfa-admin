from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import Sucursal
from app.modelos_finanzas import InstrumentoFinanciero, MonedaInstrumento
from app.rutas.tasas import obtener_fecha_hoy
from app.semilla import ejecutar_semilla
from app.semilla_contabilidad import ejecutar_semilla_contabilidad
from app.semilla_finanzas import ejecutar_semilla_finanzas
from app.servicios.cashea import calcular_desglose_cashea


def test_formula_exacta_cashea_ejemplo_300_120_180():
    """
    Ejemplo oficial:
      - Precio Regular: $300.00
      - Inicial: $120.00
      - Financiado: $180.00
      - 4% de $300.00 = $12.00
      - 4% de $180.00 = $7.20
      - 16% IVA de $12.00 = $1.92
      - 2% ISLR de $12.00 = $0.24
      - Total Cargos Cashea = $21.36
      - Neto Real por Cobrar = $180.00 - $21.36 = $158.64
    """
    res = calcular_desglose_cashea(
        total_precio_regular_usd=Decimal("300.00"),
        inicial_cobrada_usd=Decimal("120.00"),
        tasa_bcv=Decimal("52.50"),
        tasa_usdt=Decimal("54.00"),
    )
    assert res["total_precio_regular_usd"] == Decimal("300.00")
    assert res["inicial_cobrada_usd"] == Decimal("120.00")
    assert res["monto_financiado_usd"] == Decimal("180.00")
    assert res["cashea_comision_venta_usd"] == Decimal("12.00")
    assert res["cashea_comision_financiado_usd"] == Decimal("7.20")
    assert res["cashea_iva_usd"] == Decimal("1.92")
    assert res["cashea_islr_usd"] == Decimal("0.24")
    assert res["cashea_total_cargos_usd"] == Decimal("21.36")
    assert res["cashea_neto_por_cobrar_usd"] == Decimal("158.64")
    assert res["total_precio_regular_bs"] == Decimal("15750.00")
    assert res["total_precio_regular_usdt"] == Decimal("291.67")


@pytest.fixture()
def entorno():
    motor = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=motor)
    Sesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    bd = Sesion()
    ejecutar_semilla(bd)
    ejecutar_semilla_finanzas(bd)
    ejecutar_semilla_contabilidad(bd)
    bd.close()

    def _override_bd():
        s = Sesion()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[obtener_bd] = _override_bd
    client = TestClient(app)
    yield client, Sesion
    app.dependency_overrides.clear()


def test_venta_cashea_impacta_cxc_rentabilidad_y_contabilidad_cuadrada(entorno):
    client, Sesion = entorno
    r_login = client.post(
        "/api/auth/login",
        json={"usuario": "Dirección General Alfa", "clave": "Alfa2026!"},
    )
    assert r_login.status_code == 200, r_login.text
    headers = {"Authorization": f"Bearer {r_login.json()['token']}"}
    hoy_str = obtener_fecha_hoy().isoformat()

    # Tasa con 20% recargo: Promo $250.00 -> Regular $300.00
    r_tasa = client.post(
        "/api/tasas/hoy/confirmar",
        headers=headers,
        json={"tasa_bcv": 52.50, "tasa_usdt": 54.00, "porcentaje_recargo": 20.0},
    )
    assert r_tasa.status_code == 200, r_tasa.text

    bd = Sesion()
    suc_id = bd.query(Sucursal).filter(Sucursal.nombre == "Local T38").first().id
    inst_efe = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.moneda == MonedaInstrumento.USD.value)
        .first()
        .id
    )
    inst_cashea = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.nombre.ilike("%cashea%"))
        .first()
        .id
    )
    bd.close()

    art = client.post(
        "/api/catalogo",
        headers=headers,
        json={
            "sku": "CASH-LAP-01",
            "descripcion": "Laptop Cashea Test",
            "tipo": "EQUIPO",
            "categoria": "Laptop",
            "costo_referencia_usd": 150.0,
            "precio_promo_usd": 250.0,
        },
    ).json()

    client.post(
        "/api/logistica/ingresos",
        headers=headers,
        json={
            "tipo_ingreso": "COMPRA_NACIONAL",
            "proveedor_nombre": "Prov Cashea",
            "almacen_destino_id": suc_id,
            "fecha": hoy_str,
            "items": [
                {
                    "tipo_item": "EQUIPO",
                    "sku": "CASH-LAP-01",
                    "descripcion": "Laptop Cashea Test",
                    "serial": "CASH-SER-001",
                    "cantidad": 1,
                    "costo_unitario_usd": 150.0,
                    "precio_promo_usd": 250.0,
                    "estado_inicial": "DISPONIBLE",
                }
            ],
        },
    )
    eqs = client.get(f"/api/logistica/inventario/equipos?sucursal_id={suc_id}", headers=headers).json()
    eq_id = next(e["id"] for e in eqs if e["serial"] == "CASH-SER-001")

    cli = client.post(
        "/api/clientes",
        headers=headers,
        json={
            "nombre": "Cliente Cashea",
            "tipo_persona": "NATURAL",
            "tipo_documento": "V",
            "documento": "19555444",
            "telefono": "04141234567",
        },
    ).json()

    # Registrar venta con Cashea: Regular $300.00, Inicial $120.00, Financiado $180.00
    vta = client.post(
        "/api/ventas",
        headers=headers,
        json={
            "sucursal_id": suc_id,
            "cliente_id": cli["id"],
            "origen_venta": "PASILLO",
            "items": [{"articulo_id": art["id"], "equipo_id": eq_id, "cantidad": 1}],
            "pagos": [
                {"instrumento_id": inst_efe, "monto_moneda_origen": 120.0, "referencia": "INI-1"},
                {"instrumento_id": inst_cashea, "monto_moneda_origen": 180.0, "referencia": "CASHEA-1"},
            ],
        },
    )
    assert vta.status_code == 201, vta.text
    vta_data = vta.json()
    assert vta_data["es_cashea"] is True
    dc = vta_data["desglose_cashea"]
    assert dc["cashea_comision_venta_usd"] == 12.0
    assert dc["cashea_comision_financiado_usd"] == 7.2
    assert dc["cashea_iva_usd"] == 1.92
    assert dc["cashea_islr_usd"] == 0.24
    assert dc["cashea_total_cargos_usd"] == 21.36
    assert dc["cashea_neto_por_cobrar_usd"] == 158.64

    # Verificar CxC Cashea refleja bruto $180 y neto $158.64
    cxc = client.get("/api/finanzas/cuentas-por-cobrar?tipo=CASHEA", headers=headers).json()
    assert len(cxc) == 1
    assert cxc[0]["monto_original_usd"] == 180.0
    assert cxc[0]["cashea_total_cargos_usd"] == 21.36
    assert cxc[0]["cashea_neto_por_cobrar_usd"] == 158.64
    assert cxc[0]["saldo_pendiente_usd"] == 158.64

    # Verificar Rentabilidad Real descuenta los $21.36 de Cashea ($250 - $150 - $21.36 = $78.64)
    rent = client.get(f"/api/contabilidad/rentabilidad-ventas?fecha_inicio={hoy_str}&fecha_fin={hoy_str}", headers=headers).json()
    fila = next(f for f in rent["ventas"] if f["venta_id"] == vta_data["id"])
    assert fila["cashea_total_cargos_usd"] == 21.36
    assert fila["utilidad_neta_usd"] == 78.64

    # Verificar asiento contable cuadrado (Debe == Haber) con 8.1.01 ($19.20) y 9.1.01 ($2.16)
    asientos = client.get("/api/contabilidad/asientos?origen_tipo=VENTA", headers=headers).json()
    assert len(asientos) >= 1
    as_v = asientos[0]
    assert as_v["total_debe_usd"] == as_v["total_haber_usd"]
    cods = {d["cuenta_codigo"]: d["debe_usd"] for d in as_v["detalles"]}
    assert cods.get("8.1.01") == 19.2
    assert cods.get("9.1.01") == 2.16
