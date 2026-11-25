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


def test_liquidacion_exitosa_bloqueo_doble_pago_y_anulacion(cliente: TestClient) -> None:
    cab = _login_dir(cliente)
    hoy = obtener_fecha_hoy()
    sucs = {s["nombre"]: s["id"] for s in cliente.get("/api/sucursales", headers=cab).json()}
    t38_id = sucs["Local T38"]

    # 1. Crear asesora online sin acceso al sistema
    asesora = cliente.post(
        "/api/usuarios",
        headers=cab,
        json={
            "nombre": "Camila Online",
            "rol": "ASESORA",
            "modalidad": "ONLINE",
            "telefono": "0412-8887766",
            "tiene_acceso": False,
        },
    ).json()

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

    # Ingresar 2 equipos LISTO
    cliente.post(
        "/api/logistica/compras",
        headers=cab,
        json={
            "origen": "NACIONAL",
            "fecha": hoy.isoformat(),
            "llega_preparada": True,
            "equipos": [
                {"serial": "LIQ-EQ-1", "modelo": "Dell 5410", "ubicacion_id": t38_id, "costo_compra_usd": 140.0, "precio_promo_usd": 200.0},
                {"serial": "LIQ-EQ-2", "modelo": "Dell 5420", "ubicacion_id": t38_id, "costo_compra_usd": 200.0, "precio_promo_usd": 300.0},
            ],
        },
    )
    eqs = {
        e["serial"]: e
        for e in cliente.get("/api/logistica/inventario/equipos?busqueda=LIQ-EQ-", headers=cab).json()
    }
    insts = cliente.get("/api/finanzas/instrumentos", headers=cab).json()
    inst_usd = next(i for i in insts if i["moneda"] == "USD" and i["tipo_precio"] == "PROMO")

    # Crear 2 ventas pendientes para Camila: Pasillo $200 (1% = $2) y Lead $300 (8% = $24) -> Total = $26.00
    v1 = cliente.post(
        "/api/ventas",
        headers=cab,
        json={
            "sucursal_id": t38_id,
            "asesor_id": asesora["id"],
            "canal_visita": "Tienda",
            "origen_venta": "PASILLO",
            "entrega": "Tienda",
            "items": [{"equipo_id": eqs["LIQ-EQ-1"]["id"], "cantidad": 1}],
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
            "items": [{"equipo_id": eqs["LIQ-EQ-2"]["id"], "cantidad": 1}],
            "pagos": [{"instrumento_id": inst_usd["id"], "monto_moneda_origen": 300.0}],
        },
    ).json()

    # Verificar que ambas salen como PENDIENTE en el reporte
    rep_antes = cliente.get(
        f"/api/comisiones/reporte?fecha_inicio={hoy.isoformat()}&fecha_fin={hoy.isoformat()}&estado_comision=PENDIENTE",
        headers=cab,
    ).json()
    assert rep_antes["resumen_general"]["pendiente_usd"] == pytest.approx(26.0)
    assert rep_antes["resumen_general"]["pagado_usd"] == pytest.approx(0.0)

    # 1. Liquidar ambas ventas (en Pago Móvil Bs a tasa 100 -> 2600 Bs)
    resp_liq = cliente.post(
        "/api/comisiones/liquidaciones",
        headers=cab,
        json={
            "personal_id": asesora["id"],
            "venta_ids": [v1["id"], v2["id"]],
            "fecha_inicio": hoy.isoformat(),
            "fecha_fin": hoy.isoformat(),
            "metodo_pago": "PAGO_MOVIL",
            "tasa_bcv_aplicada": 100.0,
            "referencia": "PM-998877",
            "observaciones": "Pago quincena prueba",
        },
    )
    assert resp_liq.status_code == 201, resp_liq.text
    liq = resp_liq.json()
    assert liq["codigo"].startswith(f"LIQ-{hoy.year}-")
    assert liq["cantidad_ventas"] == 2
    assert liq["monto_pasillo_usd"] == pytest.approx(2.0)
    assert liq["monto_lead_usd"] == pytest.approx(24.0)
    assert liq["monto_total_usd"] == pytest.approx(26.0)
    assert liq["monto_bs"] == pytest.approx(2600.0)
    assert liq["estado"] == "PAGADA"

    # Verificar comprobante PDF generado
    resp_pdf = cliente.get(f"/api/comisiones/liquidaciones/{liq['id']}/pdf", headers=cab)
    assert resp_pdf.status_code == 200
    assert resp_pdf.content.startswith(b"%PDF")

    # 2. Intentar liquidar nuevamente una venta ya PAGADA -> 409 Conflict (cero pagos duplicados)
    resp_dup = cliente.post(
        "/api/comisiones/liquidaciones",
        headers=cab,
        json={
            "personal_id": asesora["id"],
            "venta_ids": [v1["id"]],
            "fecha_inicio": hoy.isoformat(),
            "fecha_fin": hoy.isoformat(),
            "metodo_pago": "ZELLE",
        },
    )
    assert resp_dup.status_code == 409, resp_dup.text

    # Verificar que en filtro PENDIENTE ya no queda saldo
    rep_despues = cliente.get(
        f"/api/comisiones/reporte?fecha_inicio={hoy.isoformat()}&fecha_fin={hoy.isoformat()}&estado_comision=PENDIENTE",
        headers=cab,
    ).json()
    assert rep_despues["resumen_general"]["pendiente_usd"] == pytest.approx(0.0)

    # 3. Anular la liquidación -> ventas vuelven automáticamente a PENDIENTE
    resp_anular = cliente.post(
        f"/api/comisiones/liquidaciones/{liq['id']}/anular",
        headers=cab,
        json={"motivo": "Corrección de referencia bancaria"},
    )
    assert resp_anular.status_code == 200, resp_anular.text
    assert resp_anular.json()["estado"] == "ANULADA"

    rep_rev = cliente.get(
        f"/api/comisiones/reporte?fecha_inicio={hoy.isoformat()}&fecha_fin={hoy.isoformat()}&estado_comision=PENDIENTE",
        headers=cab,
    ).json()
    assert rep_rev["resumen_general"]["pendiente_usd"] == pytest.approx(26.0)
    assert len(rep_rev["detalle_ventas"]) == 2
