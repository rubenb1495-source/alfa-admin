from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import OrigenTasa, TasaDiaria
from app.rutas import tasas as ruta_tasas
from app.rutas.tasas import obtener_fecha_hoy
from app.semilla import ejecutar_semilla


@pytest.fixture()
def entorno_pruebas():
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
        yield client, Sesion
    app.dependency_overrides.clear()


def _login_dir(cliente: TestClient) -> dict[str, str]:
    resp = cliente.post(
        "/api/auth/login",
        json={"correo": "direccion@alfaimportaciones.com", "clave": "Alfa2026!"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def test_apertura_diaria_api_vivo_confirmacion_y_sincronizacion(
    entorno_pruebas, monkeypatch: pytest.MonkeyPatch
) -> None:
    cliente, Sesion = entorno_pruebas
    cab = _login_dir(cliente)
    hoy = obtener_fecha_hoy()

    # Sembrar tasa del día anterior con recargo 18%
    bd = Sesion()
    try:
        bd.add(
            TasaDiaria(
                fecha=hoy - timedelta(days=1),
                tasa_bcv=Decimal("50.0000"),
                tasa_usdt=Decimal("60.0000"),
                recargo_porcentaje=Decimal("18.00"),
                recargo_confirmado=True,
                origen=OrigenTasa.MANUAL.value,
                fuente_tasa="MANUAL",
            )
        )
        bd.commit()
    finally:
        bd.close()

    # Simular respuesta exitosa de DolarAPI
    monkeypatch.setattr(
        ruta_tasas,
        "consultar_tasas_automaticas",
        lambda timeout_segundos=5.0: {
            "tasa_bcv": Decimal("52.5000"),
            "tasa_usdt": Decimal("65.0000"),
            "fuente_tasa": "API_VIVO",
        },
    )

    # 1. GET /api/tasas/hoy crea el registro del día SIN confirmar el recargo
    resp_hoy = cliente.get("/api/tasas/hoy", headers=cab)
    assert resp_hoy.status_code == 200, resp_hoy.text
    datos = resp_hoy.json()
    assert datos["tasa_bcv"] == pytest.approx(52.5)
    assert datos["tasa_usdt"] == pytest.approx(65.0)
    assert datos["fuente_tasa"] == "API_VIVO"
    assert datos["recargo_confirmado"] is False
    assert datos["permite_bolivares"] is False
    assert datos["ultimo_recargo_usado"] == pytest.approx(18.0)

    # 2. POST /api/tasas/hoy/confirmar confirma el recargo del día (22%)
    resp_conf = cliente.post(
        "/api/tasas/hoy/confirmar",
        headers=cab,
        json={"porcentaje_recargo": 22.0},
    )
    assert resp_conf.status_code == 200, resp_conf.text
    conf = resp_conf.json()
    assert conf["recargo_confirmado"] is True
    assert conf["permite_bolivares"] is True
    assert conf["recargo_porcentaje"] == pytest.approx(22.0)
    assert conf["porcentaje_recargo"] == pytest.approx(22.0)

    # 3. POST /api/tasas/sincronizar actualiza BCV/USDT sin borrar ni desconfirmar el 22%
    monkeypatch.setattr(
        ruta_tasas,
        "consultar_tasas_automaticas",
        lambda timeout_segundos=5.0: {
            "tasa_bcv": Decimal("53.1000"),
            "tasa_usdt": Decimal("66.2000"),
            "fuente_tasa": "API_VIVO",
        },
    )
    resp_sync = cliente.post("/api/tasas/sincronizar", headers=cab)
    assert resp_sync.status_code == 200, resp_sync.text
    sync = resp_sync.json()
    assert sync["tasa_bcv"] == pytest.approx(53.1)
    assert sync["tasa_usdt"] == pytest.approx(66.2)
    assert sync["recargo_confirmado"] is True
    assert sync["recargo_porcentaje"] == pytest.approx(22.0)


def test_fallback_cuando_falla_api_externa(
    entorno_pruebas, monkeypatch: pytest.MonkeyPatch
) -> None:
    cliente, Sesion = entorno_pruebas
    cab = _login_dir(cliente)
    hoy = obtener_fecha_hoy()

    # Sembrar última tasa en BD como respaldo
    bd = Sesion()
    try:
        bd.add(
            TasaDiaria(
                fecha=hoy - timedelta(days=1),
                tasa_bcv=Decimal("49.7500"),
                tasa_usdt=Decimal("61.2500"),
                recargo_porcentaje=Decimal("15.00"),
                recargo_confirmado=True,
                origen=OrigenTasa.MANUAL.value,
                fuente_tasa="MANUAL",
            )
        )
        bd.commit()
    finally:
        bd.close()

    # Simular caída / timeout de la API externa
    monkeypatch.setattr(
        ruta_tasas,
        "consultar_tasas_automaticas",
        lambda timeout_segundos=5.0: None,
    )

    resp = cliente.get("/api/tasas/hoy", headers=cab)
    assert resp.status_code == 200, resp.text
    datos = resp.json()
    assert datos["fuente_tasa"] == "RESPALDO_MANUAL"
    assert datos["tasa_bcv"] == pytest.approx(49.75)
    assert datos["tasa_usdt"] == pytest.approx(61.25)
    assert datos["recargo_confirmado"] is False
    assert datos["ultimo_recargo_usado"] == pytest.approx(15.0)
