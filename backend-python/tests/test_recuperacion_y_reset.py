from __future__ import annotations

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


def test_alfa_recuperacion_clave_y_reset_apertura() -> None:
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

    sede = bd.query(Sucursal).first()
    asesora = Usuario(
        nombre="Ana Prueba",
        usuario="anaprueba",
        correo=None,
        clave_hash=generar_hash_clave("Clave123!"),
        rol=RolUsuario.ASESORA.value,
        sucursal_id=sede.id if sede else None,
        activo=True,
        tiene_acceso=True,
        intentos_fallidos=5,
    )
    bd.add(asesora)
    bd.commit()
    asesora_id = asesora.id
    bd.close()

    def override_bd():
        s = Sesion()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[obtener_bd] = override_bd
    try:
        client = TestClient(app)

        # 1. Solicitar recuperación sin SMTP -> alerta para Dirección
        r_sol = client.post("/api/auth/solicitar-recuperacion", json={"usuario": "anaprueba"})
        assert r_sol.status_code == 200, r_sol.text
        data_sol = r_sol.json()
        assert data_sol.get("enviado_correo") is False

        # 2. Login Dirección y revisar alertas
        r_login = client.post(
            "/api/auth/login",
            json={"usuario": "direccion@alfaimportaciones.com", "clave": "Alfa2026!"},
        )
        assert r_login.status_code == 200, r_login.text
        tok = r_login.json().get("token") or r_login.json().get("access_token")
        headers = {"Authorization": f"Bearer {tok}"}

        r_alertas = client.get("/api/alertas/resumen", headers=headers)
        assert r_alertas.status_code == 200, r_alertas.text

        # 3. Regenerar clave temporal
        r_regen = client.post(f"/api/usuarios/{asesora_id}/regenerar-clave", headers=headers)
        assert r_regen.status_code == 200, r_regen.text
        clave_temp = r_regen.json().get("clave_temporal") or r_regen.json().get("password_temporal")
        assert clave_temp and len(clave_temp) >= 8

        # 4. Login con clave temporal exige cambio de clave
        r_as = client.post("/api/auth/login", json={"usuario": "anaprueba", "clave": clave_temp})
        assert r_as.status_code == 200, r_as.text
        d_as = r_as.json()
        assert (d_as.get("debe_cambiar_clave") or d_as.get("usuario", {}).get("debe_cambiar_clave")) is True

        # 5. Reset en cero + estado apertura
        r_reset = client.post(
            "/api/apertura/reset-cero",
            headers=headers,
            json={"password": "Alfa2026!", "frase_confirmacion": "REINICIAR ALFA DESDE CERO"},
        )
        assert r_reset.status_code == 200, r_reset.text

        r_est = client.get("/api/apertura/estado", headers=headers)
        assert r_est.status_code == 200, r_est.text
        est = r_est.json()
        assert est["en_cero"] is True
        assert est["total_saldos_iniciales_usd"] == 0.0
    finally:
        app.dependency_overrides.clear()
