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


def _login(cliente: TestClient, correo: str, clave: str) -> tuple[dict[str, str], dict]:
    resp = cliente.post("/api/auth/login", json={"correo": correo, "clave": clave})
    assert resp.status_code == 200, resp.text
    d = resp.json()
    return {"Authorization": f"Bearer {d['token']}"}, d["usuario"]


def test_rbac_admin_vs_encargado_de_tienda_y_sanitizacion_costos(cliente: TestClient) -> None:
    cab_admin, admin_u = _login(cliente, "direccion@alfaimportaciones.com", "Alfa2026!")
    hoy = obtener_fecha_hoy()
    sucs = {s["nombre"]: s["id"] for s in cliente.get("/api/sucursales", headers=cab_admin).json()}
    t38_id = sucs["Local T38"]

    # Verificar /api/auth/me para ADMIN
    me_admin = cliente.get("/api/auth/me", headers=cab_admin).json()
    assert "admin:all" in me_admin["permisos"]
    assert "costos:read" in me_admin["permisos"]

    # Crear Encargado de Tienda con acceso al sistema
    resp_enc = cliente.post(
        "/api/usuarios",
        headers=cab_admin,
        json={
            "nombre": "Marcos Encargado",
            "rol": "ENCARGADO_TIENDA",
            "sucursal_id": t38_id,
            "tiene_acceso": True,
            "correo": "marcos@alfaimportaciones.com",
            "clave": "ClaveEncargado123!", "debe_cambiar_clave": False,
        },
    )
    assert resp_enc.status_code == 201, resp_enc.text
    encargado_id = resp_enc.json()["id"]
    cab_enc, _ = _login(cliente, "marcos@alfaimportaciones.com", "ClaveEncargado123!")

    # Verificar /api/auth/me para ENCARGADO
    me_enc = cliente.get("/api/auth/me", headers=cab_enc).json()
    assert "pos:write" in me_enc["permisos"]
    assert "cierre:write" in me_enc["permisos"]
    assert "inventario:read_no_cost" in me_enc["permisos"]
    assert "admin:all" not in me_enc["permisos"]
    assert "costos:read" not in me_enc["permisos"]

    # 1. ENCARGADO SÍ puede confirmar la apertura del día
    resp_ap = cliente.post(
        "/api/tasas/hoy/confirmar",
        headers=cab_enc,
        json={"porcentaje_recargo": 15.0, "tasa_bcv": 100.0, "tasa_usdt": 120.0},
    )
    assert resp_ap.status_code == 200, resp_ap.text
    assert resp_ap.json()["recargo_confirmado"] is True

    # Admin ingresa 1 equipo con costo interno ($140) y precio promo ($220)
    cliente.post(
        "/api/logistica/compras",
        headers=cab_admin,
        json={
            "origen": "NACIONAL",
            "fecha": hoy.isoformat(),
            "llega_preparada": True,
            "equipos": [
                {
                    "serial": "RBAC-EQ-1",
                    "modelo": "Dell Latitude RBAC",
                    "ubicacion_id": t38_id,
                    "costo_compra_usd": 140.0,
                    "precio_promo_usd": 220.0,
                }
            ],
        },
    )

    # 2. Sanitización de costos: ADMIN ve costo_compra_usd; ENCARGADO NO ve costos ni saldos bancarios
    inv_admin = cliente.get("/api/logistica/inventario/equipos?busqueda=RBAC-EQ-1", headers=cab_admin).json()[0]
    assert inv_admin.get("costo_compra_usd") == pytest.approx(140.0)

    inv_enc = cliente.get("/api/logistica/inventario/equipos?busqueda=RBAC-EQ-1", headers=cab_enc).json()[0]
    assert "costo_compra_usd" not in inv_enc
    assert "costo_flete_usd" not in inv_enc
    assert "costo_total_usd" not in inv_enc

    insts_enc = cliente.get("/api/finanzas/instrumentos", headers=cab_enc).json()
    assert all("saldo_actual" not in i for i in insts_enc)
    inst_usd = next(i for i in insts_enc if i["moneda"] == "USD" and i["tipo_precio"] == "PROMO")

    # 3. ENCARGADO SÍ puede registrar venta en el POS (y la respuesta no expone costos ni utilidad)
    resp_vta = cliente.post(
        "/api/ventas",
        headers=cab_enc,
        json={
            "sucursal_id": t38_id,
            "asesor_id": encargado_id,
            "canal_visita": "Tienda",
            "origen_venta": "PASILLO",
            "entrega": "Tienda",
            "items": [{"equipo_id": inv_enc["id"], "cantidad": 1}],
            "pagos": [{"instrumento_id": inst_usd["id"], "monto_moneda_origen": 220.0}],
        },
    )
    assert resp_vta.status_code == 201, resp_vta.text
    vta_enc = resp_vta.json()
    assert "costo_total_usd" not in vta_enc
    assert "utilidad_real_usd" not in vta_enc

    # 4. ENCARGADO SÍ puede guardar el cierre diario de HOY, pero NO reabrirlo ni cerrar fechas pasadas
    resp_cierre = cliente.post(
        "/api/cierre-diario/cerrar",
        headers=cab_enc,
        json={"fecha": hoy.isoformat(), "sucursal_id": t38_id, "encargado_tienda_id": encargado_id},
    )
    assert resp_cierre.status_code == 201, resp_cierre.text

    resp_reabrir = cliente.post(
        "/api/cierre-diario/cerrar",
        headers=cab_enc,
        json={"fecha": hoy.isoformat(), "sucursal_id": t38_id, "encargado_tienda_id": encargado_id},
    )
    assert resp_reabrir.status_code == 403

    resp_pasado = cliente.post(
        "/api/cierre-diario/cerrar",
        headers=cab_enc,
        json={
            "fecha": (hoy - timedelta(days=2)).isoformat(),
            "sucursal_id": t38_id,
            "encargado_tienda_id": encargado_id,
        },
    )
    assert resp_pasado.status_code == 403

    # 5. ENCARGADO recibe 403 Forbidden en TODOS los endpoints administrativos/sensibles
    assert cliente.get("/api/comisiones/reporte", headers=cab_enc).status_code == 403
    assert cliente.get("/api/comisiones/liquidaciones", headers=cab_enc).status_code == 403
    assert cliente.get("/api/finanzas/comisiones", headers=cab_enc).status_code == 403
    assert cliente.get("/api/finanzas/pagos", headers=cab_enc).status_code == 403
    assert cliente.get("/api/finanzas/tablero", headers=cab_enc).status_code == 403
    assert cliente.get("/api/usuarios", headers=cab_enc).status_code == 403
    assert (
        cliente.post(
            f"/api/ventas/{vta_enc['id']}/anular",
            headers=cab_enc,
            json={"motivo": "Intento no autorizado"},
        ).status_code
        == 403
    )

    # 6. ADMIN sí accede sin restricciones a comisiones, finanzas y anulación
    assert cliente.get("/api/comisiones/reporte", headers=cab_admin).status_code == 200
    assert cliente.get("/api/finanzas/pagos", headers=cab_admin).status_code == 200
    assert (
        cliente.post(
            f"/api/ventas/{vta_enc['id']}/anular",
            headers=cab_admin,
            json={"motivo": "Anulación autorizada por admin"},
        ).status_code
        == 200
    )
