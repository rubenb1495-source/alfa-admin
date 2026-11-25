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


def test_personal_sin_acceso_pos_comisiones_y_validaciones(cliente: TestClient) -> None:
    cab = _login_dir(cliente)
    hoy = obtener_fecha_hoy()
    sucs = {s["nombre"]: s["id"] for s in cliente.get("/api/sucursales", headers=cab).json()}
    t38_id = sucs["Local T38"]

    # 1. Crear asesora online SIN correo ni contraseña (tiene_acceso=False)
    resp_online = cliente.post(
        "/api/usuarios",
        headers=cab,
        json={
            "nombre": "Valeria Online",
            "rol": "ASESORA",
            "modalidad": "ONLINE",
            "telefono": "0424-9998877",
            "cedula": "V-26111222",
            "tiene_acceso": False,
        },
    )
    assert resp_online.status_code == 201, resp_online.text
    valeria = resp_online.json()
    assert valeria["correo"] is None
    assert valeria["tiene_acceso"] is False
    assert valeria["modalidad"] == "ONLINE"

    # Confirmar que se puede crear un segundo colaborador sin correo (múltiples NULL permitidos)
    resp_online2 = cliente.post(
        "/api/usuarios",
        headers=cab,
        json={
            "nombre": "Luis Técnico Externo",
            "rol": "TECNICO",
            "modalidad": "PRESENCIAL",
            "tiene_acceso": False,
        },
    )
    assert resp_online2.status_code == 201, resp_online2.text

    # 2. Verificar que aparece en /api/usuarios/operativos para el POS
    ops = cliente.get("/api/usuarios/operativos", headers=cab).json()
    val_op = next((u for u in ops if u["id"] == valeria["id"]), None)
    assert val_op is not None
    assert val_op["modalidad"] == "ONLINE"
    assert val_op["tiene_acceso"] is False

    # Registrar tasa + equipo y vender asignado a Valeria Online (LEAD -> 8% de $250 = $20.00)
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
    cliente.post(
        "/api/logistica/compras",
        headers=cab,
        json={
            "origen": "NACIONAL",
            "fecha": hoy.isoformat(),
            "llega_preparada": True,
            "equipos": [
                {
                    "serial": "ONLINE-EQ-1",
                    "modelo": "Dell Latitude Online",
                    "ubicacion_id": t38_id,
                    "costo_compra_usd": 170.0,
                    "precio_promo_usd": 250.0,
                }
            ],
        },
    )
    eq = cliente.get("/api/logistica/inventario/equipos?busqueda=ONLINE-EQ-1", headers=cab).json()[0]
    insts = cliente.get("/api/finanzas/instrumentos", headers=cab).json()
    inst_usd = next(i for i in insts if i["moneda"] == "USD" and i["tipo_precio"] == "PROMO")

    resp_vta = cliente.post(
        "/api/ventas",
        headers=cab,
        json={
            "sucursal_id": t38_id,
            "asesor_id": valeria["id"],
            "canal_visita": "WhatsApp",
            "origen_venta": "LEAD",
            "entrega": "Tienda",
            "items": [{"equipo_id": eq["id"], "cantidad": 1}],
            "pagos": [{"instrumento_id": inst_usd["id"], "monto_moneda_origen": 250.0}],
        },
    )
    assert resp_vta.status_code == 201, resp_vta.text

    resp_com = cliente.get(f"/api/finanzas/comisiones?mes={hoy.month}&anio={hoy.year}", headers=cab)
    assert resp_com.status_code == 200, resp_com.text
    com_map = {c["usuario_id"]: c for c in resp_com.json()["comisiones"]}
    assert com_map[valeria["id"]]["ventas_leads_usd"] == pytest.approx(250.0)
    assert com_map[valeria["id"]]["comision_leads_usd"] == pytest.approx(20.0)
    assert com_map[valeria["id"]]["total_comision_usd"] == pytest.approx(20.0)

    # 3. Confirmar que un colaborador sin acceso NO puede iniciar sesión en /api/auth/login
    resp_login_fail = cliente.post(
        "/api/auth/login",
        json={"correo": "valeria@alfaimportaciones.com", "clave": "cualquierclave"},
    )
    assert resp_login_fail.status_code in (401, 403)

    # 4. Verificar que tiene_acceso=True SIN correo devuelve error de validación (422)
    resp_invalido = cliente.post(
        "/api/usuarios",
        headers=cab,
        json={
            "nombre": "Usuario Sin Correo",
            "rol": "ADMINISTRACION",
            "tiene_acceso": True,
            "clave": "ClaveSegura123!",
        },
    )
    assert resp_invalido.status_code in (400, 422), resp_invalido.text
