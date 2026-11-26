from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import TasaDiaria
from app.modelos_finanzas import InstrumentoFinanciero, MonedaInstrumento
from app.rutas.tasas import obtener_fecha_hoy
from app.semilla import ejecutar_semilla
from app.semilla_finanzas import ejecutar_semilla_finanzas


@pytest.fixture()
def entorno():
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
        hoy = obtener_fecha_hoy()
        tasa = bd_seed.query(TasaDiaria).filter(TasaDiaria.fecha == hoy).first()
        if tasa is None:
            bd_seed.add(
                TasaDiaria(
                    fecha=hoy,
                    tasa_bcv=Decimal("50.0000"),
                    tasa_usdt=Decimal("60.0000"),
                    recargo_porcentaje=Decimal("15.00"),
                    recargo_confirmado=True,
                    origen="MANUAL",
                )
            )
        else:
            tasa.tasa_bcv = Decimal("50.0000")
            tasa.tasa_usdt = Decimal("60.0000")
            tasa.recargo_confirmado = True
        bd_seed.commit()
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


def _login(client: TestClient, correo: str, clave: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"correo": correo, "clave": clave})
    assert resp.status_code == 200, resp.text
    datos = resp.json()
    token = datos.get("token") or datos.get("access_token")
    return {"Authorization": f"Bearer {token}"}


def test_1_director_solo_lectura_y_compartir_credenciales(entorno):
    client, _Sesion = entorno
    headers_admin = _login(client, "direccion@alfaimportaciones.com", "Alfa2026!")

    # Admin crea usuario DIRECTOR
    creado = client.post(
        "/api/usuarios",
        headers=headers_admin,
        json={
            "nombre": "Socio Director",
            "rol": "DIRECTOR",
            "tiene_acceso": True,
            "correo": "socio@alfaimportaciones.com",
            "clave": "ClaveInicial123", "debe_cambiar_clave": False,
            "telefono": "04141234567",
        },
    )
    assert creado.status_code == 201, creado.text
    dir_id = creado.json()["id"]

    # Admin restablece clave para compartir acceso por WhatsApp
    reset = client.post(
        f"/api/usuarios/{dir_id}/restablecer-clave",
        headers=headers_admin,
        json={},
    )
    assert reset.status_code == 200, reset.text
    clave_temp = reset.json()["clave_temporal"]
    assert reset.json()["debe_cambiar_clave"] is True
    assert reset.json()["url_app"] == "https://alfa-admin-web.vercel.app"

    # Director inicia sesión con la clave temporal -> bloqueado hasta cambiar clave
    headers_dir = _login(client, "socio@alfaimportaciones.com", clave_temp)
    assert client.get("/api/direccion/resumen", headers=headers_dir).status_code == 403
    r_cc = client.post(
        "/api/auth/cambiar-clave",
        headers=headers_dir,
        json={
            "clave_actual": clave_temp,
            "nueva_clave": "DirectorDefinitiva2026!",
            "confirmar_clave": "DirectorDefinitiva2026!",
        },
    )
    assert r_cc.status_code == 200, r_cc.text

    # Director PUEDE leer Panel Ejecutivo y Tesorería
    res_dir = client.get("/api/direccion/resumen", headers=headers_dir)
    assert res_dir.status_code == 200, res_dir.text
    body = res_dir.json()
    assert "disponible_cuentas" in body
    assert "inventario" in body
    assert "cuentas_por_cobrar" in body
    assert "cuentas_por_pagar" in body
    assert "mas_vendidos" in body
    assert "ventas_por_asesor" in body
    assert "ventas_por_tienda" in body

    res_tes_get = client.get("/api/tesoreria/movimientos", headers=headers_dir)
    assert res_tes_get.status_code == 200

    # Director NO puede crear ventas ni movimientos de tesorería (403 Forbidden)
    res_vta = client.post(
        "/api/ventas",
        headers=headers_dir,
        json={"sucursal_id": 1, "items": [], "pagos": []},
    )
    assert res_vta.status_code == 403

    res_tes_post = client.post(
        "/api/tesoreria/movimientos",
        headers=headers_dir,
        json={"tipo": "INGRESO_ADMIN", "cuenta_destino_id": 1, "monto_entrada": 100},
    )
    assert res_tes_post.status_code == 403

    # Director puede cambiar su propia clave nuevamente cuando desee
    cambio = client.post(
        "/api/auth/cambiar-clave",
        headers=headers_dir,
        json={"clave_actual": "DirectorDefinitiva2026!", "nueva_clave": "MiClavePropia2026!"},
    )
    assert cambio.status_code == 200
    headers_dir_nuevo = _login(client, "socio@alfaimportaciones.com", "MiClavePropia2026!")
    perfil = client.get("/api/auth/me", headers=headers_dir_nuevo).json()
    assert perfil["debe_cambiar_clave"] is False


def test_2_tesoreria_cambio_ganancia_perdida_y_anulacion(entorno):
    client, Sesion = entorno
    headers_admin = _login(client, "direccion@alfaimportaciones.com", "Alfa2026!")

    bd = Sesion()
    cta_usd = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.moneda == MonedaInstrumento.USD.value)
        .first()
    )
    cta_bs = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.moneda == MonedaInstrumento.BS.value)
        .first()
    )
    assert cta_usd is not None and cta_bs is not None
    usd_id, bs_id = cta_usd.id, cta_bs.id
    bd.close()

    def _saldos() -> dict[int, float]:
        r = client.get("/api/finanzas/instrumentos", headers=headers_admin)
        assert r.status_code == 200
        return {i["id"]: i["saldo_actual"] for i in r.json()}

    saldos_iniciales = _saldos()

    # Caso A: Cambio USD -> BS con GANANCIA (Tasa BCV hoy = 50; vendemos $100 a tasa 55 -> entran 5500 Bs)
    # Equivalente salida = $100; equivalente entrada a BCV 50 = 5500/50 = $110 -> Ganancia = +$10 (+10%)
    ganancia = client.post(
        "/api/tesoreria/movimientos",
        headers=headers_admin,
        json={
            "tipo": "CAMBIO_DIVISA",
            "cuenta_origen_id": usd_id,
            "monto_salida": "100.00",
            "cuenta_destino_id": bs_id,
            "tasa_operacion": "55.00",
            "tasa_referencia_tipo": "BCV",
            "concepto": "Venta divisas con ganancia",
        },
    )
    assert ganancia.status_code == 201, ganancia.text
    g = ganancia.json()
    assert g["monto_entrada"] == 5500.0
    assert g["equivalente_salida_usd"] == 100.0
    assert g["equivalente_entrada_usd"] == 110.0
    assert g["diferencial_usd"] == 10.0
    assert g["diferencial_porcentaje"] == 10.0
    assert g["resultado_tipo"] == "GANANCIA"

    saldos_post_g = _saldos()
    assert saldos_post_g[usd_id] == round(saldos_iniciales[usd_id] - 100.0, 2)
    assert saldos_post_g[bs_id] == round(saldos_iniciales[bs_id] + 5500.0, 2)

    # Caso B: Cambio BS -> USD con PÉRDIDA (Salen 5500 Bs = $110 a BCV 50; recibimos $100 -> Pérdida -$10 / -9.09%)
    perdida = client.post(
        "/api/tesoreria/movimientos",
        headers=headers_admin,
        json={
            "tipo": "CAMBIO_DIVISA",
            "cuenta_origen_id": bs_id,
            "monto_salida": "5500.00",
            "cuenta_destino_id": usd_id,
            "monto_entrada": "100.00",
            "tasa_referencia_tipo": "BCV",
            "concepto": "Compra divisas sobre BCV",
        },
    )
    assert perdida.status_code == 201, perdida.text
    p = perdida.json()
    assert p["equivalente_salida_usd"] == 110.0
    assert p["equivalente_entrada_usd"] == 100.0
    assert p["diferencial_usd"] == -10.0
    assert p["diferencial_porcentaje"] == -9.09
    assert p["resultado_tipo"] == "PERDIDA"

    # Verificar KPIs consolidados
    hist = client.get("/api/tesoreria/movimientos", headers=headers_admin).json()
    assert hist["resumen"]["total_ganancia_usd"] == 10.0
    assert hist["resumen"]["total_perdida_usd"] == 10.0
    assert hist["resumen"]["resultado_neto_usd"] == 0.0

    # Caso C: Anular el movimiento de pérdida y verificar reversión atómica de saldos
    anul = client.post(
        f"/api/tesoreria/movimientos/{p['id']}/anular",
        headers=headers_admin,
        json={"motivo": "Operación duplicada de prueba"},
    )
    assert anul.status_code == 200, anul.text
    assert anul.json()["estado"] == "ANULADO"

    saldos_finales = _saldos()
    assert saldos_finales[usd_id] == saldos_post_g[usd_id]
    assert saldos_finales[bs_id] == saldos_post_g[bs_id]
