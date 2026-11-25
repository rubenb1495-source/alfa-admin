from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import CatalogoArticulo, Sucursal, TipoArticulo
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
        if not bd_seed.query(CatalogoArticulo).filter(CatalogoArticulo.sku == "LP-ALERTA-01").first():
            bd_seed.add(
                CatalogoArticulo(
                    sku="LP-ALERTA-01",
                    descripcion="Laptop Alerta Agotada",
                    categoria="Laptops",
                    tipo=TipoArticulo.EQUIPO.value,
                    stock_minimo=2,
                    activo=True,
                )
            )
        if not bd_seed.query(CatalogoArticulo).filter(CatalogoArticulo.sku == "CO-ALERTA-02").first():
            bd_seed.add(
                CatalogoArticulo(
                    sku="CO-ALERTA-02",
                    descripcion="Cargador Alerta Bajo",
                    categoria="Cargadores",
                    tipo=TipoArticulo.COMPONENTE.value,
                    stock_minimo=3,
                    activo=True,
                )
            )
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
    token = resp.json().get("token") or resp.json().get("access_token")
    return {"Authorization": f"Bearer {token}"}


def test_1_alertas_stock_agotado_bajo_y_en_transito(entorno):
    client, Sesion = entorno
    headers = _login(client, "direccion@alfaimportaciones.com", "Alfa2026!")

    bd = Sesion()
    sucs = bd.query(Sucursal).order_by(Sucursal.id.asc()).all()
    assert len(sucs) >= 2
    origen, destino = sucs[0], sucs[1]
    art_comp = bd.query(CatalogoArticulo).filter(CatalogoArticulo.sku == "CO-ALERTA-02").first()
    bd.close()

    # Ingresar 1 laptop (LP-ALERTA-01) en origen y 5 cargadores (CO-ALERTA-02) en origen
    ing = client.post(
        "/api/logistica/ingresos",
        headers=headers,
        json={
            "tipo_ingreso": "COMPRA_NACIONAL",
            "proveedor_nombre": "Tech Local",
            "almacen_destino_id": origen.id,
            "items": [
                {
                    "sku": "LP-ALERTA-01",
                    "serial": "SN-ALR-001",
                    "cantidad": 1,
                    "costo_unitario_usd": "200",
                    "estado_inicial": "DISPONIBLE",
                },
                {
                    "sku": "CO-ALERTA-02",
                    "cantidad": 5,
                    "costo_unitario_usd": "10",
                },
            ],
        },
    )
    assert ing.status_code == 201, ing.text

    eq = client.get("/api/logistica/inventario/equipos?busqueda=SN-ALR-001", headers=headers).json()[0]

    # Trasladar la laptop y 3 cargadores hacia destino (quedan en tránsito hacia destino; en origen quedan 2 cargadores <= mínimo 3 -> BAJO)
    trs = client.post(
        "/api/logistica/traslados",
        headers=headers,
        json={
            "origen_id": origen.id,
            "destino_id": destino.id,
            "equipos_ids": [eq["id"]],
            "componentes": [{"articulo_id": art_comp.id, "cantidad": 3}],
            "nota": "Reposición hacia tienda",
        },
    )
    assert trs.status_code == 201, trs.text

    res = client.get("/api/alertas/resumen", headers=headers)
    assert res.status_code == 200, res.text
    inv = res.json()["inventario"]

    # En destino: LP-ALERTA-01 está AGOTADO (0) pero con 1 EN_TRANSITO
    alerta_lp_dest = next(
        a for a in inv if a["sku"] == "LP-ALERTA-01" and a["sucursal_id"] == destino.id
    )
    assert alerta_lp_dest["severidad"] == "AGOTADO"
    assert alerta_lp_dest["stock_disponible"] == 0
    assert alerta_lp_dest["cantidad_en_transito"] == 1

    # En origen: CO-ALERTA-02 tiene 2 disponibles (<= mínimo 3) -> BAJO
    alerta_co_orig = next(
        a for a in inv if a["sku"] == "CO-ALERTA-02" and a["sucursal_id"] == origen.id
    )
    assert alerta_co_orig["severidad"] == "BAJO"
    assert alerta_co_orig["stock_disponible"] == 2
    assert alerta_co_orig["stock_minimo"] == 3

    # En destino: CO-ALERTA-02 está AGOTADO (0) pero con 3 EN_TRANSITO
    alerta_co_dest = next(
        a for a in inv if a["sku"] == "CO-ALERTA-02" and a["sucursal_id"] == destino.id
    )
    assert alerta_co_dest["severidad"] == "AGOTADO"
    assert alerta_co_dest["cantidad_en_transito"] == 3


def test_2_alertas_cxp_vencida_vence_hoy_y_proxima(entorno):
    client, _Sesion = entorno
    headers = _login(client, "direccion@alfaimportaciones.com", "Alfa2026!")
    hoy = obtener_fecha_hoy()

    facturas = [
        ("Proveedor Vencido", "FAC-VENC", (hoy - timedelta(days=3)).isoformat(), "500.00"),
        ("Proveedor Hoy", "FAC-HOY", hoy.isoformat(), "300.00"),
        ("Proveedor Proximo", "FAC-PROX", (hoy + timedelta(days=4)).isoformat(), "200.00"),
        ("Proveedor Lejano", "FAC-LEJ", (hoy + timedelta(days=20)).isoformat(), "900.00"),
    ]
    for prov, ref, venc, monto in facturas:
        r = client.post(
            "/api/alertas/cxp",
            headers=headers,
            json={
                "proveedor_nombre": prov,
                "concepto": f"Factura {ref}",
                "referencia": ref,
                "fecha_vencimiento": venc,
                "monto_usd": monto,
            },
        )
        assert r.status_code == 201, r.text

    res = client.get("/api/alertas/resumen", headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    cxp = data["cuentas_por_pagar"]

    # Solo deben entrar las 3 dentro del umbral (default 5 días); la de +20 días se excluye
    assert len(cxp) == 3
    assert cxp[0]["urgencia"] == "VENCIDA"
    assert cxp[0]["dias_diferencia"] == 3
    assert cxp[1]["urgencia"] == "VENCE_HOY"
    assert cxp[1]["dias_diferencia"] == 0
    assert cxp[2]["urgencia"] == "PROXIMA"
    assert cxp[2]["dias_diferencia"] == 4
    assert data["contadores"]["monto_total_cxp_alerta_usd"] == 1000.0


def test_3_alertas_rbac_admin_director_vs_encargado(entorno):
    client, _Sesion = entorno
    headers_admin = _login(client, "direccion@alfaimportaciones.com", "Alfa2026!")

    # Crear DIRECTOR y ENCARGADO_TIENDA
    r_dir = client.post(
        "/api/usuarios",
        headers=headers_admin,
        json={
            "nombre": "Director Alertas",
            "rol": "DIRECTOR",
            "tiene_acceso": True,
            "correo": "dir.alertas@alfaimportaciones.com",
            "clave": "Password123!",
        },
    )
    assert r_dir.status_code == 201, r_dir.text

    r_enc = client.post(
        "/api/usuarios",
        headers=headers_admin,
        json={
            "nombre": "Encargado Alertas",
            "rol": "ENCARGADO_TIENDA",
            "tiene_acceso": True,
            "correo": "enc.alertas@alfaimportaciones.com",
            "clave": "Password123!",
        },
    )
    assert r_enc.status_code == 201, r_enc.text

    headers_dir = _login(client, "dir.alertas@alfaimportaciones.com", "Password123!")
    headers_enc = _login(client, "enc.alertas@alfaimportaciones.com", "Password123!")

    # GET /api/alertas/resumen: ADMIN 200, DIRECTOR 200, ENCARGADO 403
    assert client.get("/api/alertas/resumen", headers=headers_admin).status_code == 200
    assert client.get("/api/alertas/resumen", headers=headers_dir).status_code == 200
    assert client.get("/api/alertas/resumen", headers=headers_enc).status_code == 403

    # PATCH /api/alertas/configuracion: solo ADMIN 200; DIRECTOR y ENCARGADO 403
    assert (
        client.patch(
            "/api/alertas/configuracion",
            headers=headers_dir,
            json={"dias_alerta_cxp": 7},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            "/api/alertas/configuracion",
            headers=headers_enc,
            json={"dias_alerta_cxp": 7},
        ).status_code
        == 403
    )
    ok_cfg = client.patch(
        "/api/alertas/configuracion",
        headers=headers_admin,
        json={"stock_minimo_global": 4, "dias_alerta_cxp": 7, "sku": "LP-ALERTA-01", "stock_minimo_sku": 5},
    )
    assert ok_cfg.status_code == 200, ok_cfg.text
    assert ok_cfg.json()["dias_alerta_cxp"] == 7
    assert ok_cfg.json()["sku_actualizado"]["stock_minimo"] == 5
