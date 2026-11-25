from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import RolUsuario, Sucursal, Usuario
from app.seguridad import generar_hash_clave
from app.semilla import ejecutar_semilla
from app.semilla_contabilidad import ejecutar_semilla_contabilidad
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
    ejecutar_semilla_contabilidad(bd)

    suc = bd.query(Sucursal).filter(Sucursal.nombre == "Local T38").first()
    enc = Usuario(
        nombre="Carlos Mendoza",
        usuario="Carlos Mendoza",
        correo=None,
        clave_hash=generar_hash_clave("ClaveInicial2026!"),
        rol=RolUsuario.ENCARGADO_TIENDA.value,
        sucursal_id=suc.id,
        tiene_acceso=True,
        activo=True,
    )
    bd.add(enc)
    bd.commit()
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


def test_login_por_nombre_bloqueo_5_intentos_alerta_desbloqueo_y_cambio_clave(entorno):
    client, Sesion = entorno

    # 1. Login exitoso usando el nombre del usuario (case-insensitive y sin correo)
    r_ok = client.post(
        "/api/auth/login",
        json={"usuario": "  cArLoS mEnDoZa  ", "password": "ClaveInicial2026!"},
    )
    assert r_ok.status_code == 200, r_ok.text
    token_enc = r_ok.json()["token"]
    enc_id = r_ok.json()["usuario"]["id"]
    assert r_ok.json()["usuario"]["usuario"] == "Carlos Mendoza"

    # 2. 4 intentos fallidos -> 401 con intentos_restantes exactos (4, 3, 2, 1)
    for restantes_esperados in (4, 3, 2, 1):
        r_fail = client.post(
            "/api/auth/login",
            json={"usuario": "Carlos Mendoza", "password": "ClaveMala!"},
        )
        assert r_fail.status_code == 401, r_fail.text
        assert r_fail.json()["intentos_restantes"] == restantes_esperados
        assert r_fail.json()["cuenta_bloqueada"] is False

    # 5to intento fallido -> bloquea cuenta (423 Locked)
    r_lock = client.post(
        "/api/auth/login",
        json={"usuario": "Carlos Mendoza", "password": "ClaveMala!"},
    )
    assert r_lock.status_code == 423, r_lock.text
    assert r_lock.json()["cuenta_bloqueada"] is True
    assert "bloqueado" in r_lock.json()["detail"].lower()

    # 3. 6to intento bloqueado incluso con la contraseña correcta
    r_6 = client.post(
        "/api/auth/login",
        json={"usuario": "Carlos Mendoza", "password": "ClaveInicial2026!"},
    )
    assert r_6.status_code == 423, r_6.text

    # Verificar Alerta de Seguridad en /api/alertas/resumen como ADMIN
    r_adm = client.post(
        "/api/auth/login",
        json={"usuario": "Dirección General Alfa", "clave": "Alfa2026!"},
    )
    assert r_adm.status_code == 200, r_adm.text
    h_adm = {"Authorization": f"Bearer {r_adm.json()['token']}"}

    al = client.get("/api/alertas/resumen", headers=h_adm)
    assert al.status_code == 200, al.text
    al_data = al.json()
    assert al_data["contadores"]["seguridad_bloqueos"] >= 1
    assert any(s["usuario_id"] == enc_id for s in al_data["seguridad"])

    # ADMIN desbloquea la cuenta en /api/personal/{id}/desbloquear
    r_un = client.post(f"/api/personal/{enc_id}/desbloquear", headers=h_adm)
    assert r_un.status_code == 200, r_un.text
    assert r_un.json()["cuenta_bloqueada"] is False
    assert r_un.json()["intentos_fallidos"] == 0

    # Alerta de seguridad resuelta
    al2 = client.get("/api/alertas/resumen", headers=h_adm).json()
    assert not any(s["usuario_id"] == enc_id for s in al2["seguridad"])

    # Login vuelve a funcionar con la clave original
    r_re = client.post(
        "/api/auth/login",
        json={"usuario": "Carlos Mendoza", "password": "ClaveInicial2026!"},
    )
    assert r_re.status_code == 200, r_re.text
    h_enc = {"Authorization": f"Bearer {r_re.json()['token']}"}

    # 4. Cambio de clave por el propio usuario + login posterior con la nueva clave
    r_chg_bad = client.post(
        "/api/auth/cambiar-clave",
        headers=h_enc,
        json={
            "clave_actual": "ClaveInicial2026!",
            "nueva_clave": "NuevaClave2026!",
            "confirmar_clave": "OtraClave!",
        },
    )
    assert r_chg_bad.status_code == 400

    r_chg = client.post(
        "/api/auth/cambiar-clave",
        headers=h_enc,
        json={
            "clave_actual": "ClaveInicial2026!",
            "nueva_clave": "NuevaClave2026!",
            "confirmar_clave": "NuevaClave2026!",
        },
    )
    assert r_chg.status_code == 200, r_chg.text

    # Login con la nueva clave funciona y con la vieja falla
    r_new = client.post(
        "/api/auth/login",
        json={"usuario": "carlos mendoza", "password": "NuevaClave2026!"},
    )
    assert r_new.status_code == 200, r_new.text
