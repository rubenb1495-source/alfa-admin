from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import Sucursal
from app.rutas.tasas import obtener_fecha_hoy
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


def test_hoja_traslado_pdf_y_recepcion_item_por_item(entorno):
    client, Sesion = entorno
    r_login = client.post(
        "/api/auth/login",
        json={"usuario": "Dirección General Alfa", "clave": "Alfa2026!"},
    )
    assert r_login.status_code == 200, r_login.text
    headers = {"Authorization": f"Bearer {r_login.json()['token']}"}
    hoy_str = obtener_fecha_hoy().isoformat()

    bd = Sesion()
    origen_id = bd.query(Sucursal).filter(Sucursal.nombre == "Almacén Guaparo Norte").first().id
    destino_id = bd.query(Sucursal).filter(Sucursal.nombre == "Local T38").first().id
    bd.close()

    art_eq = client.post(
        "/api/catalogo",
        headers=headers,
        json={
            "sku": "TRS-LAP-01",
            "descripcion": "Laptop Traslado Test",
            "tipo": "EQUIPO",
            "categoria": "Laptop",
            "costo_referencia_usd": 200.0,
            "precio_promo_usd": 350.0,
        },
    ).json()
    art_comp = client.post(
        "/api/catalogo",
        headers=headers,
        json={
            "sku": "TRS-CARG-01",
            "descripcion": "Cargador USB-C 65W",
            "tipo": "ACCESORIO",
            "categoria": "Accesorios",
            "costo_referencia_usd": 10.0,
            "precio_promo_usd": 25.0,
        },
    ).json()

    ing = client.post(
        "/api/logistica/ingresos",
        headers=headers,
        json={
            "tipo_ingreso": "COMPRA_NACIONAL",
            "proveedor_nombre": "Prov Traslado",
            "almacen_destino_id": origen_id,
            "fecha": hoy_str,
            "items": [
                {
                    "tipo_item": "EQUIPO",
                    "sku": "TRS-LAP-01",
                    "descripcion": "Laptop Traslado Test",
                    "serial": "TRS-SER-001",
                    "cantidad": 1,
                    "costo_unitario_usd": 200.0,
                    "precio_promo_usd": 350.0,
                    "estado_inicial": "DISPONIBLE",
                },
                {
                    "tipo_item": "ACCESORIO",
                    "sku": "TRS-CARG-01",
                    "descripcion": "Cargador USB-C 65W",
                    "cantidad": 5,
                    "costo_unitario_usd": 10.0,
                    "precio_promo_usd": 25.0,
                },
            ],
        },
    )
    assert ing.status_code == 201, ing.text

    eqs = client.get(f"/api/logistica/inventario/equipos?sucursal_id={origen_id}", headers=headers).json()
    eq_id = next(e["id"] for e in eqs if e["serial"] == "TRS-SER-001")

    # Crear traslado mixto
    trs = client.post(
        "/api/logistica/traslados",
        headers=headers,
        json={
            "origen_id": origen_id,
            "destino_id": destino_id,
            "equipos_ids": [eq_id],
            "componentes": [{"articulo_id": art_comp["id"], "cantidad": 4}],
            "nota": "Despacho de reposición",
        },
    )
    assert trs.status_code == 201, trs.text
    trs_id = trs.json()["id"]

    # Descargar Hoja de Traslado PDF en estado EN_TRANSITO
    pdf_resp = client.get(f"/api/logistica/traslados/{trs_id}/pdf", headers=headers)
    assert pdf_resp.status_code == 200, pdf_resp.text
    assert pdf_resp.headers["content-type"].startswith("application/pdf")
    assert pdf_resp.content.startswith(b"%PDF-")
    assert len(pdf_resp.content) > 1500

    # Obtener detalles del traslado para chequeo ítem por ítem
    lista = client.get("/api/logistica/traslados", headers=headers).json()
    trs_obj = next(t for t in lista if t["id"] == trs_id)
    assert len(trs_obj["detalles"]) == 2
    det_eq = next(d for d in trs_obj["detalles"] if d["equipo_id"] == eq_id)
    det_comp = next(d for d in trs_obj["detalles"] if d["articulo_id"] == art_comp["id"])

    # Confirmar recepción con chequeo ítem por ítem (4 enviados, 3 recibidos con novedad)
    conf = client.post(
        f"/api/logistica/traslados/{trs_id}/confirmar",
        headers=headers,
        json={
            "nota_recepcion": "Verificado en tienda",
            "items_verificados": [
                {"detalle_id": det_eq["id"], "verificado": True, "observacion_recepcion": "Equipo OK"},
                {
                    "detalle_id": det_comp["id"],
                    "verificado": True,
                    "cantidad_recibida": 3,
                    "observacion_recepcion": "Faltó 1 cargador en la caja",
                },
            ],
        },
    )
    assert conf.status_code == 200, conf.text
    assert conf.json()["estado"] == "RECIBIDO"
    assert conf.json()["novedades"] == 1

    # Verificar que los detalles guardaron el chequeo y el PDF post-recepción también se genera
    lista2 = client.get("/api/logistica/traslados", headers=headers).json()
    trs_post = next(t for t in lista2 if t["id"] == trs_id)
    det_c_post = next(d for d in trs_post["detalles"] if d["id"] == det_comp["id"])
    assert det_c_post["verificado"] is True
    assert det_c_post["cantidad_recibida"] == 3
    assert "Faltó 1 cargador" in det_c_post["observacion_recepcion"]

    pdf_post = client.get(f"/api/logistica/traslados/{trs_id}/pdf", headers=headers)
    assert pdf_post.status_code == 200
    assert pdf_post.content.startswith(b"%PDF-")
