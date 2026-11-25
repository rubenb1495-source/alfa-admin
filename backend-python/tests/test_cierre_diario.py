from __future__ import annotations

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


def test_cierre_diario_excluye_comisiones_y_consolida_operacion(cliente: TestClient) -> None:
    cab = _login_dir(cliente)
    hoy = obtener_fecha_hoy()
    sucs = {s["nombre"]: s["id"] for s in cliente.get("/api/sucursales", headers=cab).json()}
    t38_id = sucs["Local T38"]

    # Crear Encargado de Tienda y Asesora Online sin acceso
    encargado = cliente.post(
        "/api/usuarios",
        headers=cab,
        json={
            "nombre": "Carlos Encargado",
            "rol": "ENCARGADO_TIENDA",
            "sucursal_id": t38_id,
            "tiene_acceso": False,
        },
    ).json()
    asesora = cliente.post(
        "/api/usuarios",
        headers=cab,
        json={
            "nombre": "Elena Online",
            "rol": "ASESORA",
            "modalidad": "ONLINE",
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
            "recargo_porcentaje": 20.0,
        },
    )

    # Ingresar 3 equipos LISTO hoy en Local T38 (se cuentan como recepciones y stock disponible)
    cliente.post(
        "/api/logistica/compras",
        headers=cab,
        json={
            "origen": "NACIONAL",
            "fecha": hoy.isoformat(),
            "llega_preparada": True,
            "equipos": [
                {"serial": "CIE-1", "modelo": "Dell 5410", "ubicacion_id": t38_id, "costo_compra_usd": 140.0, "precio_promo_usd": 200.0},
                {"serial": "CIE-2", "modelo": "Dell 5420", "ubicacion_id": t38_id, "costo_compra_usd": 200.0, "precio_promo_usd": 300.0},
                {"serial": "CIE-3", "modelo": "Dell 5420", "ubicacion_id": t38_id, "costo_compra_usd": 200.0, "precio_promo_usd": 300.0},
            ],
        },
    )
    eqs = {
        e["serial"]: e
        for e in cliente.get("/api/logistica/inventario/equipos?busqueda=CIE-", headers=cab).json()
    }
    insts = cliente.get("/api/finanzas/instrumentos", headers=cab).json()
    inst_usd = next(i for i in insts if i["moneda"] == "USD" and i["tipo_precio"] == "PROMO")

    # Vender 2 equipos hoy: CIE-1 (PASILLO, Encargado, $200) y CIE-2 (LEAD, Elena Online, $300)
    v1 = cliente.post(
        "/api/ventas",
        headers=cab,
        json={
            "sucursal_id": t38_id,
            "asesor_id": encargado["id"],
            "canal_visita": "Tienda",
            "origen_venta": "PASILLO",
            "entrega": "Tienda",
            "items": [{"equipo_id": eqs["CIE-1"]["id"], "cantidad": 1}],
            "pagos": [{"instrumento_id": inst_usd["id"], "monto_moneda_origen": 200.0}],
        },
    ).json()
    v2 = cliente.post(
        "/api/ventas",
        headers=cab,
        json={
            "sucursal_id": t38_id,
            "asesor_id": asesora["id"],
            "canal_visita": "WhatsApp",
            "origen_venta": "LEAD",
            "entrega": "Tienda",
            "items": [{"equipo_id": eqs["CIE-2"]["id"], "cantidad": 1}],
            "pagos": [{"instrumento_id": inst_usd["id"], "monto_moneda_origen": 300.0}],
        },
    ).json()

    # Liquidar comisiones de Elena Online ($24 USD) el MISMO DÍA -> NO debe afectar el Cierre Diario
    resp_liq = cliente.post(
        "/api/comisiones/liquidaciones",
        headers=cab,
        json={
            "personal_id": asesora["id"],
            "venta_ids": [v2["id"]],
            "fecha_inicio": hoy.isoformat(),
            "fecha_fin": hoy.isoformat(),
            "instrumento_pago_id": inst_usd["id"],
            "referencia": "LIQ-TEST",
        },
    )
    assert resp_liq.status_code == 201, resp_liq.text

    # Registrar 1 caso de garantía hoy (queda pendiente)
    resp_caso = cliente.post(
        "/api/taller/casos",
        headers=cab,
        json={
            "tipo": "GARANTIA",
            "sucursal_id": t38_id,
            "serial_o_codigo": "CIE-1",
            "descripcion_equipo": "Dell 5410",
            "falla_reportada": "Teclado no responde",
        },
    )
    assert resp_caso.status_code == 201, resp_caso.text

    # Consultar Cierre Diario en vivo
    resp_cierre = cliente.get(
        f"/api/cierre-diario?fecha={hoy.isoformat()}&sucursal_id={t38_id}",
        headers=cab,
    )
    assert resp_cierre.status_code == 200, resp_cierre.text
    d = resp_cierre.json()

    # 1. Ventas del día: 2 ventas ($500 total; 1 Pasillo $200, 1 Lead $300)
    assert d["ventas_dia"]["cantidad_total"] == 2
    assert d["ventas_dia"]["total_promo_usd"] == pytest.approx(500.0)
    assert d["ventas_dia"]["pasillo_cantidad"] == 1
    assert d["ventas_dia"]["lead_cantidad"] == 1

    # 2. Recibido por instrumento: exactamente $500.00 (NO restó ni incluyó los $24 de liquidación de comisiones)
    assert d["recibido_por_instrumento"]["total_usd"] == pytest.approx(500.0)
    assert len(d["recibido_por_instrumento"]["items"]) == 1
    assert d["recibido_por_instrumento"]["items"][0]["total_usd"] == pytest.approx(500.0)

    # 3. Inventario: 2 salidas hoy (CIE-1 y CIE-2) y 1 equipo disponible al cierre (CIE-3)
    assert d["inventario"]["salidas_hoy"]["total_unidades"] == 2
    assert d["inventario"]["disponible_cierre"]["total_equipos"] == 1

    # 4. Garantías: 1 recibida hoy y 1 pendiente
    assert len(d["garantias_casos"]["recibidas_hoy"]) == 1
    assert d["garantias_casos"]["pendientes"]["total"] == 1

    # 5. Resumen aparte de ventas por asesor (sin comisiones)
    asesores = {a["nombre"]: a for a in d["ventas_por_asesor"]}
    assert "Elena Online" in asesores
    assert asesores["Elena Online"]["total_usd"] == pytest.approx(300.0)
    assert "comision" not in str(asesores["Elena Online"]).lower()
    assert asesores["Carlos Encargado"]["total_usd"] == pytest.approx(200.0)

    # 6. Guardar cierre oficial con nombre del Encargado de Tienda y verificar historial
    resp_guardar = cliente.post(
        "/api/cierre-diario/cerrar",
        headers=cab,
        json={
            "fecha": hoy.isoformat(),
            "sucursal_id": t38_id,
            "encargado_tienda_id": encargado["id"],
            "observaciones": "Jornada sin novedades",
        },
    )
    assert resp_guardar.status_code == 201, resp_guardar.text
    guardado = resp_guardar.json()
    assert guardado["encargado_tienda_nombre"] == "Carlos Encargado"
    assert guardado["observaciones"] == "Jornada sin novedades"

    hist = cliente.get("/api/cierre-diario/historial", headers=cab).json()
    assert len(hist) == 1
    assert hist[0]["encargado_tienda_nombre"] == "Carlos Encargado"
