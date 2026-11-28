from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.rutas.tasas import obtener_fecha_hoy
from app.semilla import ejecutar_semilla
from app.semilla_finanzas import ejecutar_semilla_finanzas


@pytest.fixture()
def cliente() -> TestClient:
    motor = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Sesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)
    Base.metadata.create_all(bind=motor)

    bd_seed = Sesion()
    try:
        ejecutar_semilla(bd_seed)
        ejecutar_semilla_finanzas(bd_seed)
    finally:
        bd_seed.close()

    def obtener_bd_prueba():
        bd = Sesion()
        try:
            yield bd
        finally:
            bd.close()

    app.dependency_overrides[obtener_bd] = obtener_bd_prueba
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _login_dir(cliente: TestClient) -> dict[str, str]:
    resp = cliente.post(
        "/api/auth/login",
        json={"correo": "direccion@alfaimportaciones.com", "clave": "Alfa2026!"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def test_reporte_comisiones_filtros_personal_rango_fechas_y_origen(cliente: TestClient) -> None:
    cab = _login_dir(cliente)
    hoy = obtener_fecha_hoy()
    ayer = hoy - timedelta(days=1)
    hace_10_dias = hoy - timedelta(days=10)

    sucs = {s["nombre"]: s["id"] for s in cliente.get("/api/sucursales", headers=cab).json()}
    t38_id = sucs["Local T38"]

    # 1. Crear Asesora Online SIN acceso al sistema y Encargado de Tienda
    asesora_online = cliente.post(
        "/api/usuarios",
        headers=cab,
        json={
            "nombre": "Sofía Online",
            "rol": "ASESORA",
            "modalidad": "ONLINE",
            "telefono": "0424-7778899",
            "tiene_acceso": False,
        },
    ).json()
    encargado = cliente.post(
        "/api/usuarios",
        headers=cab,
        json={
            "nombre": "Pedro Encargado",
            "rol": "ENCARGADO_TIENDA",
            "modalidad": "PRESENCIAL",
            "telefono": "0414-5554433",
            "tiene_acceso": False,
        },
    ).json()

    # Tasa del día
    cliente.post(
        "/api/tasas",
        headers=cab,
        json={
            "fecha": hoy.isoformat(),
            "tasa_bcv": 100.0,
            "tasa_usdt": 120.0,
            "recargo_porcentaje": 25.0,
        },
    )

    # Ingresar 4 equipos LISTO
    cliente.post(
        "/api/logistica/compras",
        headers=cab,
        json={
            "origen": "NACIONAL",
            "fecha": hoy.isoformat(),
            "llega_preparada": True,
            "equipos": [
                {"serial": "REP-1", "modelo": "Dell 5410", "ubicacion_id": t38_id, "costo_compra_usd": 140.0, "precio_promo_usd": 200.0},
                {"serial": "REP-2", "modelo": "Dell 5420", "ubicacion_id": t38_id, "costo_compra_usd": 200.0, "precio_promo_usd": 300.0},
                {"serial": "REP-3", "modelo": "HP 840", "ubicacion_id": t38_id, "costo_compra_usd": 260.0, "precio_promo_usd": 400.0},
                {"serial": "REP-4", "modelo": "Lenovo T14", "ubicacion_id": t38_id, "costo_compra_usd": 140.0, "precio_promo_usd": 250.0},
            ],
        },
    )
    eqs = {
        e["serial"]: e
        for e in cliente.get("/api/logistica/inventario/equipos?busqueda=REP-", headers=cab).json()
    }
    insts = cliente.get("/api/finanzas/instrumentos", headers=cab).json()
    inst_usd = next(i for i in insts if i["moneda"] == "USD" and i["tipo_precio"] == "PROMO")

    def vender(serial: str, monto: float, asesor_id: int, origen: str, fecha_vta) -> None:
        r = cliente.post(
            "/api/ventas",
            headers=cab,
            json={
                "sucursal_id": t38_id,
                "fecha": fecha_vta.isoformat(),
                "asesor_id": asesor_id,
                "canal_visita": "WhatsApp" if origen == "LEAD" else "Tienda",
                "origen_venta": origen,
                "entrega": "Tienda",
                "sin_cargador": True, "items": [{"equipo_id": eqs[serial]["id"], "cantidad": 1}],
                "pagos": [{"instrumento_id": inst_usd["id"], "monto_moneda_origen": monto}],
            },
        )
        assert r.status_code == 201, r.text

    # Ventas:
    # - REP-1: Sofía Online, PASILLO, hoy ($200 * 1% = $2.00)
    vender("REP-1", 200.0, asesora_online["id"], "PASILLO", hoy)
    # - REP-2: Sofía Online, LEAD, ayer ($300 * 8% = $24.00)
    vender("REP-2", 300.0, asesora_online["id"], "LEAD", ayer)
    # - REP-3: Pedro Encargado, PASILLO, hoy ($400 * 5% = $20.00)
    vender("REP-3", 400.0, encargado["id"], "PASILLO", hoy)
    # - REP-4: Pedro Encargado, LEAD, hace 10 días ($250 * 8% = $20.00) -> fuera de rango [ayer, hoy]
    vender("REP-4", 250.0, encargado["id"], "LEAD", hace_10_dias)

    # A. Reporte en rango [ayer, hoy] sin filtro de persona
    resp_rango = cliente.get(
        f"/api/comisiones/reporte?fecha_inicio={ayer.isoformat()}&fecha_fin={hoy.isoformat()}",
        headers=cab,
    )
    assert resp_rango.status_code == 200, resp_rango.text
    d_rango = resp_rango.json()
    assert d_rango["resumen_general"]["total_ventas"] == 3
    assert d_rango["resumen_general"]["volumen_promo_usd"] == pytest.approx(900.0)
    assert d_rango["resumen_general"]["pasillo_usd"] == pytest.approx(22.0)  # $2 + $20
    assert d_rango["resumen_general"]["lead_usd"] == pytest.approx(24.0)     # $24
    assert d_rango["resumen_general"]["total_comisiones_usd"] == pytest.approx(46.0)
    assert len(d_rango["detalle_ventas"]) == 3

    # B. Filtro por personal_id (Sofía Online sin acceso al sistema)
    resp_sofia = cliente.get(
        f"/api/comisiones/reporte?fecha_inicio={ayer.isoformat()}&fecha_fin={hoy.isoformat()}&personal_id={asesora_online['id']}",
        headers=cab,
    )
    assert resp_sofia.status_code == 200, resp_sofia.text
    d_sofia = resp_sofia.json()
    assert len(d_sofia["por_persona"]) == 1
    p_sof = d_sofia["por_persona"][0]
    assert p_sof["nombre"] == "Sofía Online"
    assert p_sof["modalidad"] == "ONLINE"
    assert p_sof["telefono"] == "0424-7778899"
    assert p_sof["cantidad_pasillo"] == 1
    assert p_sof["comision_pasillo_usd"] == pytest.approx(2.0)
    assert p_sof["cantidad_lead"] == 1
    assert p_sof["comision_lead_usd"] == pytest.approx(24.0)
    assert p_sof["total_comision_usd"] == pytest.approx(26.0)

    # C. Filtro por rol=ENCARGADO en rango completo [hace_10_dias, hoy]
    resp_enc = cliente.get(
        f"/api/comisiones/reporte?fecha_inicio={hace_10_dias.isoformat()}&fecha_fin={hoy.isoformat()}&rol=ENCARGADO",
        headers=cab,
    )
    assert resp_enc.status_code == 200, resp_enc.text
    d_enc = resp_enc.json()
    assert len(d_enc["por_persona"]) == 1
    p_enc = d_enc["por_persona"][0]
    assert p_enc["comision_pasillo_usd"] == pytest.approx(20.0)
    assert p_enc["comision_lead_usd"] == pytest.approx(20.0)
    assert p_enc["total_comision_usd"] == pytest.approx(40.0)
