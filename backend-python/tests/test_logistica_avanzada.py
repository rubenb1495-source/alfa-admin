from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import CatalogoArticulo, Sucursal, TipoArticulo
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
        # Asegurar un SKU de equipo y uno de componente para pruebas
        if not bd_seed.query(CatalogoArticulo).filter(CatalogoArticulo.sku == "LP-DELL-5420-TEST").first():
            bd_seed.add(
                CatalogoArticulo(
                    sku="LP-DELL-5420-TEST",
                    descripcion="Dell Latitude 5420 i5 16GB/256GB",
                    categoria="Laptops",
                    tipo=TipoArticulo.EQUIPO.value,
                    activo=True,
                )
            )
        if not bd_seed.query(CatalogoArticulo).filter(CatalogoArticulo.sku == "CO-CARG-TEST").first():
            bd_seed.add(
                CatalogoArticulo(
                    sku="CO-CARG-TEST",
                    descripcion="Cargador Dell Tipo C 65W",
                    categoria="Cargadores",
                    tipo=TipoArticulo.COMPONENTE.value,
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


def _login_admin(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/auth/login",
        json={"correo": "direccion@alfaimportaciones.com", "clave": "Alfa2026!"},
    )
    assert resp.status_code == 200, resp.text
    datos = resp.json()
    token = datos.get("access_token") or datos.get("token") or datos.get("token_acceso")
    return {"Authorization": f"Bearer {token}"}


def _crear_excel_bytes(encabezados: list[str], filas: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Datos"
    ws.append(encabezados)
    for fila in filas:
        ws.append(fila)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_1_compra_internacional_prorrateo_automatico(entorno):
    client, Sesion = entorno
    headers = _login_admin(client)
    bd = Sesion()
    suc = bd.query(Sucursal).first()
    bd.close()

    resp = client.post(
        "/api/logistica/ingresos",
        headers=headers,
        json={
            "tipo_ingreso": "COMPRA_INTERNACIONAL",
            "proveedor_nombre": "Miami Tech Wholesale",
            "almacen_destino_id": suc.id,
            "referencia_factura": "INV-USA-881",
            "costo_flete_usd": "60.00",
            "costo_aduana_otros_usd": "40.00",
            "tracking_guia": "1Z999AA10123",
            "items": [
                {
                    "sku": "LP-DELL-5420-TEST",
                    "serial": "SN-IMP-001",
                    "cantidad": 1,
                    "costo_unitario_usd": "200.00",
                    "precio_venta_usd": "310.00",
                },
                {
                    "sku": "LP-DELL-5420-TEST",
                    "serial": "SN-IMP-002",
                    "cantidad": 1,
                    "costo_unitario_usd": "200.00",
                    "precio_venta_usd": "310.00",
                },
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["codigo"].startswith("CI-")
    # 100 USD de gastos / 2 unidades = 50 USD prorrateados por equipo
    assert data["prorrateo_unitario_usd"] == 50.0
    assert data["total_compra_usd"] == 500.0

    inv = client.get("/api/logistica/inventario/equipos?busqueda=SN-IMP-001", headers=headers)
    assert inv.status_code == 200
    eq = inv.json()[0]
    assert eq["costo_compra_usd"] == 200.0
    assert eq["costo_flete_usd"] == 50.0
    assert eq["costo_total_usd"] == 250.0


def test_2_recepcion_consignacion_marcada(entorno):
    client, Sesion = entorno
    headers = _login_admin(client)
    bd = Sesion()
    suc = bd.query(Sucursal).first()
    bd.close()

    resp = client.post(
        "/api/logistica/ingresos",
        headers=headers,
        json={
            "tipo_ingreso": "CONSIGNACION",
            "proveedor_nombre": "Importadora Aliada CA",
            "almacen_destino_id": suc.id,
            "items": [
                {
                    "sku": "LP-DELL-5420-TEST",
                    "serial": "SN-CONS-900",
                    "cantidad": 1,
                    "costo_unitario_usd": "220.00",
                    "precio_venta_usd": "295.00",
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["codigo"].startswith("CON-")

    inv = client.get("/api/logistica/inventario/equipos?busqueda=SN-CONS-900", headers=headers)
    assert inv.status_code == 200
    eq = inv.json()[0]
    assert eq["es_consignacion"] is True
    assert eq["consignante_nombre"] == "Importadora Aliada CA"
    assert eq["costo_acordado_usd"] == 220.0


def test_3_traslado_mixto_equipo_y_productos_cantidad(entorno):
    client, Sesion = entorno
    headers = _login_admin(client)
    bd = Sesion()
    sucursales = bd.query(Sucursal).all()
    assert len(sucursales) >= 2
    origen, destino = sucursales[0], sucursales[1]
    art_comp = bd.query(CatalogoArticulo).filter(CatalogoArticulo.sku == "CO-CARG-TEST").first()
    bd.close()

    # Ingresar 1 laptop + 10 cargadores en origen
    ing = client.post(
        "/api/logistica/ingresos",
        headers=headers,
        json={
            "tipo_ingreso": "COMPRA_NACIONAL",
            "proveedor_nombre": "Proveedor Local",
            "almacen_destino_id": origen.id,
            "items": [
                {
                    "sku": "LP-DELL-5420-TEST",
                    "serial": "SN-TRS-MIX-1",
                    "cantidad": 1,
                    "costo_unitario_usd": "190.00",
                    "estado_inicial": "DISPONIBLE",
                },
                {
                    "sku": "CO-CARG-TEST",
                    "cantidad": 10,
                    "costo_unitario_usd": "10.00",
                },
            ],
        },
    )
    assert ing.status_code == 201, ing.text

    eq = client.get("/api/logistica/inventario/equipos?busqueda=SN-TRS-MIX-1", headers=headers).json()[0]

    # Crear traslado mixto: 1 equipo + 5 cargadores
    trs = client.post(
        "/api/logistica/traslados",
        headers=headers,
        json={
            "origen_id": origen.id,
            "destino_id": destino.id,
            "equipos_ids": [eq["id"]],
            "componentes": [{"articulo_id": art_comp.id, "cantidad": 5}],
            "nota": "Envío mixto a tienda",
        },
    )
    assert trs.status_code == 201, trs.text
    trs_data = trs.json()
    assert trs_data["equipos_en_transito"] == 1
    assert trs_data["componentes_en_transito"] == 5

    # Verificar equipo EN_TRANSITO
    eq_trans = client.get("/api/logistica/inventario/equipos?busqueda=SN-TRS-MIX-1", headers=headers).json()[0]
    assert eq_trans["estado"] == "EN_TRANSITO"

    # Confirmar recepción en destino
    conf = client.post(
        f"/api/logistica/traslados/{trs_data['id']}/confirmar",
        headers=headers,
        json={"nota_recepcion": "Todo completo"},
    )
    assert conf.status_code == 200, conf.text
    assert conf.json()["estado"] == "RECIBIDO"

    # Equipo ahora en destino y LISTO; cargadores: 5 en origen y 5 en destino
    eq_dest = client.get("/api/logistica/inventario/equipos?busqueda=SN-TRS-MIX-1", headers=headers).json()[0]
    assert eq_dest["ubicacion_id"] == destino.id
    assert eq_dest["estado"] == "LISTO"

    kardex = client.get("/api/logistica/inventario/kardex", headers=headers).json()
    saldos = {
        (s["sku"], s["sucursal_id"]): s["stock_actual"]
        for s in kardex["saldos"]
    }
    assert saldos[("CO-CARG-TEST", origen.id)] == 5
    assert saldos[("CO-CARG-TEST", destino.id)] == 5


def test_4_preparaciones_cambio_estado_masivo_y_historial(entorno):
    client, Sesion = entorno
    headers = _login_admin(client)
    bd = Sesion()
    suc = bd.query(Sucursal).first()
    bd.close()

    client.post(
        "/api/logistica/ingresos",
        headers=headers,
        json={
            "tipo_ingreso": "COMPRA_NACIONAL",
            "proveedor_nombre": "Local Tech",
            "almacen_destino_id": suc.id,
            "items": [
                {"sku": "LP-DELL-5420-TEST", "serial": "SN-PREP-01", "cantidad": 1, "costo_unitario_usd": "180"},
                {"sku": "LP-DELL-5420-TEST", "serial": "SN-PREP-02", "cantidad": 1, "costo_unitario_usd": "180"},
            ],
        },
    )

    resp_masivo = client.patch(
        "/api/preparaciones/estado-masivo",
        headers=headers,
        json={
            "seriales": ["SN-PREP-01", "SN-PREP-02"],
            "nuevo_estado": "DISPONIBLE",
            "observacion": "Windows 11 + pruebas de batería OK",
        },
    )
    assert resp_masivo.status_code == 200, resp_masivo.text
    data = resp_masivo.json()
    assert data["actualizados"] == 2
    assert data["estado_aplicado"] == "LISTO"

    eq_id = data["equipos"][0]["id"]
    hist = client.get(f"/api/preparaciones/equipos/{eq_id}/historial", headers=headers)
    assert hist.status_code == 200
    registros = hist.json()
    assert len(registros) >= 2
    assert registros[0]["estado_nuevo"] == "LISTO"
    assert "Windows 11" in registros[0]["observacion"]


def test_5_plantillas_excel_y_carga_masiva_validaciones(entorno):
    client, Sesion = entorno
    headers = _login_admin(client)
    bd = Sesion()
    sucursales = bd.query(Sucursal).all()
    origen, destino = sucursales[0], sucursales[1]
    bd.close()

    # 1. Descargar las 5 plantillas .xlsx
    for tipo in [
        "COMPRA_NACIONAL",
        "COMPRA_INTERNACIONAL",
        "CONSIGNACION",
        "TRASLADO",
        "PREPARACION_ESTADOS",
    ]:
        r = client.get(f"/api/logistica/plantilla/{tipo}", headers=headers)
        assert r.status_code == 200, f"Falló plantilla {tipo}: {r.text}"
        assert "spreadsheetml" in r.headers["content-type"]

    # 2. Carga masiva de compra con serial duplicado dentro del archivo -> preview detecta error
    excel_dup = _crear_excel_bytes(
        ["sku", "serial", "cantidad", "costo_unitario_usd", "precio_venta_usd", "estado_inicial", "nota"],
        [
            ["LP-DELL-5420-TEST", "SN-BULK-01", 1, 185, 290, "DISPONIBLE", "Ok"],
            ["LP-DELL-5420-TEST", "SN-BULK-01", 1, 185, 290, "DISPONIBLE", "Duplicado"],
        ],
    )
    prev = client.post(
        "/api/logistica/importar/COMPRA_NACIONAL/preview",
        headers=headers,
        files={"archivo": ("compra.xlsx", excel_dup, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert prev.status_code == 200, prev.text
    assert prev.json()["validas_count"] == 1
    assert prev.json()["errores_count"] == 1
    assert "duplicado" in prev.json()["filas_con_error"][0]["errores"][0].lower()

    # Confirmar con errores debe ser rechazado con 400
    conf_err = client.post(
        "/api/logistica/importar/COMPRA_NACIONAL/confirmar",
        headers=headers,
        data={"almacen_destino_id": str(origen.id), "proveedor_nombre": "Prov Masivo"},
        files={"archivo": ("compra.xlsx", excel_dup, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert conf_err.status_code == 400

    # 3. Carga masiva válida -> confirma atómicamente
    excel_ok = _crear_excel_bytes(
        ["sku", "serial", "cantidad", "costo_unitario_usd", "precio_venta_usd", "estado_inicial", "nota"],
        [
            ["LP-DELL-5420-TEST", "SN-BULK-OK1", 1, 185, 290, "DISPONIBLE", "Ok"],
            ["CO-CARG-TEST", "", 3, 10, 25, "DISPONIBLE", "Cargadores"],
        ],
    )
    conf_ok = client.post(
        "/api/logistica/importar/COMPRA_NACIONAL/confirmar",
        headers=headers,
        data={"almacen_destino_id": str(origen.id), "proveedor_nombre": "Prov Masivo"},
        files={"archivo": ("compra_ok.xlsx", excel_ok, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert conf_ok.status_code == 201, conf_ok.text
    assert conf_ok.json()["filas_procesadas"] == 2

    # 4. Traslado masivo con stock insuficiente -> preview rechaza
    excel_trs_err = _crear_excel_bytes(
        ["sku", "serial", "cantidad", "nota"],
        [
            ["CO-CARG-TEST", "", 99, "Excede stock disponible (solo hay 3)"],
        ],
    )
    prev_trs = client.post(
        "/api/logistica/importar/TRASLADO/preview",
        headers=headers,
        data={"almacen_origen_id": str(origen.id), "almacen_destino_id": str(destino.id)},
        files={"archivo": ("traslado.xlsx", excel_trs_err, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert prev_trs.status_code == 200, prev_trs.text
    assert prev_trs.json()["errores_count"] == 1
    assert "stock insuficiente" in prev_trs.json()["filas_con_error"][0]["errores"][0].lower()


def test_6_ingreso_tolera_strings_vacios_y_comas_sin_422(entorno):
    client, Sesion = entorno
    headers = _login_admin(client)
    bd = Sesion()
    suc = bd.query(Sucursal).first()
    bd.close()

    resp = client.post(
        "/api/logistica/ingresos",
        headers=headers,
        json={
            "tipo_ingreso": "COMPRA_NACIONAL",
            "proveedor_nombre": "Proveedor Flexible",
            "almacen_destino_id": suc.id,
            "referencia_factura": None,
            "observaciones": None,
            "costo_flete_usd": "",
            "costo_aduana_otros_usd": None,
            "tracking_guia": None,
            "items": [
                {
                    "sku": "CO-CARG-TEST",
                    "serial": "",
                    "cantidad": 4,
                    "costo_unitario_usd": "12,50",
                    "precio_venta_usd": "",
                    "estado_inicial": "",
                    "nota": None,
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["productos_creados"] == 4
    assert resp.json()["total_compra_usd"] == 50.0
