from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import Sucursal
from app.modelos_admin import AuditLog
from app.semilla import ejecutar_semilla
from app.semilla_finanzas import ejecutar_semilla_finanzas


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
    sede = bd.query(Sucursal).filter(Sucursal.nombre == "Local T38").first()
    sede_id = sede.id
    bd.close()

    def _override_bd():
        s = Sesion()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[obtener_bd] = _override_bd
    with TestClient(app) as client:
        yield client, Sesion, sede_id
    app.dependency_overrides.clear()


def test_cambio_clave_obligatorio_primer_ingreso_y_reset_admin(entorno):
    client, Sesion, sede_id = entorno

    # Login ADMIN principal (debe tener debe_cambiar_clave == False para no bloquearse)
    r_adm = client.post(
        "/api/auth/login",
        json={"usuario": "direccion@alfaimportaciones.com", "clave": "Alfa2026!"},
    )
    assert r_adm.status_code == 200, r_adm.text
    assert r_adm.json()["debe_cambiar_clave"] is False
    h_adm = {"Authorization": f"Bearer {r_adm.json()['token']}"}

    # 1. ADMIN crea usuario nuevo con clave temporal -> nace con debe_cambiar_clave = True
    r_crear = client.post(
        "/api/usuarios",
        headers=h_adm,
        json={
            "nombre": "Andrea Nuevo Ingreso",
            "rol": "ASESORA",
            "sucursal_id": sede_id,
            "tiene_acceso": True,
            "clave": "Temp-12345!",
        },
    )
    assert r_crear.status_code == 201, r_crear.text
    usr = r_crear.json()
    assert usr["debe_cambiar_clave"] is True

    # Inicia sesión y recibe debe_cambiar_clave: true en /login y /me
    r_login = client.post(
        "/api/auth/login",
        json={"usuario": "Andrea Nuevo Ingreso", "clave": "Temp-12345!"},
    )
    assert r_login.status_code == 200, r_login.text
    body_login = r_login.json()
    assert body_login["debe_cambiar_clave"] is True
    assert body_login["usuario"]["debe_cambiar_clave"] is True
    h_usr = {"Authorization": f"Bearer {body_login['token']}"}

    r_me = client.get("/api/auth/me", headers=h_usr)
    assert r_me.status_code == 200
    assert r_me.json()["debe_cambiar_clave"] is True

    r_logout = client.post("/api/auth/logout", headers=h_usr)
    assert r_logout.status_code == 200

    # 2. Cualquier otro endpoint (ventas, inventario, sucursales) devuelve 403 Forbidden
    for ruta in ("/api/sucursales", "/api/logistica/inventario/equipos", "/api/ventas"):
        r_bloq = client.get(ruta, headers=h_usr)
        assert r_bloq.status_code == 403, f"Esperado 403 en {ruta}, recibido {r_bloq.status_code}"
        assert "Debes cambiar tu contraseña temporal antes de continuar." in r_bloq.json()["detail"]

    # 3. Intentar poner la misma clave temporal como nueva clave es rechazado (400)
    r_misma = client.post(
        "/api/auth/cambiar-clave",
        headers=h_usr,
        json={
            "clave_actual": "Temp-12345!",
            "nueva_clave": "Temp-12345!",
            "confirmar_clave": "Temp-12345!",
        },
    )
    assert r_misma.status_code in (400, 422)

    # Confirmación distinta también es rechazada
    r_diff = client.post(
        "/api/auth/cambiar-clave",
        headers=h_usr,
        json={
            "clave_actual": "Temp-12345!",
            "nueva_clave": "MiClaveNueva2026!",
            "confirmar_clave": "OtraClave2026!",
        },
    )
    assert r_diff.status_code == 400

    # 4. Cambio exitoso -> debe_cambiar_clave = False, audit_logs y acceso desbloqueado
    r_ok = client.post(
        "/api/auth/cambiar-clave",
        headers=h_usr,
        json={
            "clave_actual": "Temp-12345!",
            "nueva_clave": "MiClavePersonal2026!",
            "confirmar_clave": "MiClavePersonal2026!",
        },
    )
    assert r_ok.status_code == 200, r_ok.text
    assert r_ok.json()["debe_cambiar_clave"] is False

    # Verificar AuditLog
    bd = Sesion()
    log = (
        bd.query(AuditLog)
        .filter(
            AuditLog.usuario_id == usr["id"],
            AuditLog.accion == "CAMBIO_CLAVE_PRIMER_INGRESO",
        )
        .first()
    )
    assert log is not None
    bd.close()

    # Acceso normal desbloqueado inmediatamente
    assert client.get("/api/sucursales", headers=h_usr).status_code == 200
    assert client.get("/api/logistica/inventario/equipos", headers=h_usr).status_code == 200

    # 5. Reset de clave por ADMIN vuelve a activar debe_cambiar_clave = True y bloquea de nuevo
    r_reset = client.post(
        f"/api/usuarios/{usr['id']}/restablecer-clave",
        headers=h_adm,
        json={},
    )
    assert r_reset.status_code == 200, r_reset.text
    clave_temp_2 = r_reset.json()["clave_temporal"]
    assert r_reset.json()["debe_cambiar_clave"] is True

    r_login2 = client.post(
        "/api/auth/login",
        json={"usuario": "Andrea Nuevo Ingreso", "clave": clave_temp_2},
    )
    assert r_login2.status_code == 200
    assert r_login2.json()["debe_cambiar_clave"] is True
    h_usr2 = {"Authorization": f"Bearer {r_login2.json()['token']}"}
    assert client.get("/api/sucursales", headers=h_usr2).status_code == 403
