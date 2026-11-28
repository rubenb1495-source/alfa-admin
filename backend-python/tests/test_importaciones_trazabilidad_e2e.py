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
    sucs = {s.nombre: s.id for s in bd.query(Sucursal).all()}
    bd.close()

    def _override_bd():
        s = Sesion()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[obtener_bd] = _override_bd
    with TestClient(app) as client:
        yield client, sucs
    app.dependency_overrides.clear()


def test_ciclo_completo_importacion_recepcion_preparacion_venta_garantia_trazabilidad(entorno):
    client, sucs = entorno
    r_adm = client.post(
        "/api/auth/login",
        json={"usuario": "direccion@alfaimportaciones.com", "clave": "Alfa2026!"},
    )
    assert r_adm.status_code == 200
    h = {"Authorization": f"Bearer {r_adm.json()['token']}"}
    hoy = obtener_fecha_hoy()
    alm_id = sucs["Almacén Guaparo Norte"]
    t38_id = sucs["Local T38"]

    # Tasa del día
    client.post(
        "/api/tasas",
        headers=h,
        json={"fecha": hoy.isoformat(), "tasa_bcv": 100.0, "tasa_usdt": 120.0, "recargo_porcentaje": 20.0, "recargo_confirmado": True},
    )

    # Crear componentes en catálogo (SSD $25 + Batería $35) e ingresar stock en Almacén
    ssd = client.post(
        "/api/catalogo",
        headers=h,
        json={"sku": "COMP-SSD-512", "descripcion": "SSD NVMe 512GB", "tipo": "COMPONENTE", "categoria": "Almacenamiento", "costo_referencia_usd": 25.0, "precio_promo_usd": 45.0},
    ).json()
    bat = client.post(
        "/api/catalogo",
        headers=h,
        json={"sku": "COMP-BAT-DELL", "descripcion": "Batería Dell 5420 Original", "tipo": "COMPONENTE", "categoria": "Baterías", "costo_referencia_usd": 35.0, "precio_promo_usd": 60.0},
    ).json()
    r_stock = client.post(
        "/api/logistica/compras",
        headers=h,
        json={
            "origen": "NACIONAL",
            "fecha": hoy.isoformat(),
            "llega_preparada": True,
            "componentes": [
                {"articulo_id": ssd["id"], "cantidad": 5, "costo_unitario_usd": 25.0, "ubicacion_id": alm_id},
                {"articulo_id": bat["id"], "cantidad": 5, "costo_unitario_usd": 35.0, "ubicacion_id": alm_id},
            ],
        },
    )
    assert r_stock.status_code == 201, r_stock.text

    # 1. Compra Internacional de 3 equipos SIN seriales ($600 + $42 taxes + $18 envío Miami = $660)
    r_lote = client.post(
        "/api/importaciones/lotes",
        headers=h,
        json={
            "proveedor_nombre": "Miami Tech Wholesale",
            "referencia": "INV-MIA-2026-01",
            "descripcion_previa": "Lote 3 Laptops Dell Latitude 5420 i5 11va",
            "cantidad_equipos_esperados": 3,
            "monto_compra_usd": 600.0,
            "taxes_usd": 42.0,
            "envio_miami_usd": 18.0,
        },
    )
    assert r_lote.status_code == 201, r_lote.text
    lote = r_lote.json()
    assert lote["estado"] == "EN_TRANSITO"
    assert lote["subtotal_miami_usd"] == 660.0

    # 2. Recepción en Venezuela con envío Vzla = $90 -> Total Aterrizado = $750 -> Primer Costo = $250 c/u
    r_rec = client.post(
        f"/api/importaciones/lotes/{lote['id']}/recibir",
        headers=h,
        json={
            "gastos_envio_venezuela_usd": 90.0,
            "equipos": [
                {"serial": "TRZ-PREP-01", "modelo": "Dell Latitude 5420", "configuracion": "i5 11va / 16GB", "grado_estetico": "Grado A", "ubicacion_id": alm_id, "proceso_inicial": "PREPARACION", "precio_promo_usd": 450.0},
                {"serial": "TRZ-HOSP-02", "modelo": "Dell Latitude 5420", "configuracion": "i5 11va / 8GB", "grado_estetico": "Grado B", "ubicacion_id": alm_id, "proceso_inicial": "HOSPITAL", "precio_promo_usd": 400.0},
                {"serial": "TRZ-REV-03", "modelo": "Dell Latitude 5420", "configuracion": "i5 11va / 8GB", "grado_estetico": "Grado A", "ubicacion_id": alm_id, "proceso_inicial": "REVISION", "precio_promo_usd": 420.0},
            ],
        },
    )
    assert r_rec.status_code == 200, r_rec.text
    rec_data = r_rec.json()
    assert rec_data["lote"]["estado"] == "RECIBIDO"
    assert rec_data["costo_aterrizado_recepcion_usd"] == 750.0
    eq_map = {e["serial"]: e for e in rec_data["equipos_recibidos"]}
    assert eq_map["TRZ-PREP-01"]["primer_costo_usd"] == 250.0
    assert eq_map["TRZ-HOSP-02"]["estado"] == "HOSPITAL"
    assert eq_map["TRZ-REV-03"]["estado"] == "PENDIENTE_REVISION"

    # 3. Preparación en TRZ-PREP-01: SSD ($25) + Batería ($35) + Comisión ($15) -> Costo Final = $325 y marcar Disponible
    r_prep = client.post(
        f"/api/importaciones/equipos/{eq_map['TRZ-PREP-01']['id']}/preparacion",
        headers=h,
        json={
            "componentes": [
                {"articulo_id": ssd["id"], "cantidad": 1},
                {"articulo_id": bat["id"], "cantidad": 1},
            ],
            "comision_preparacion_usd": 15.0,
            "marcar_disponible": True,
            "precio_promo_usd": 450.0,
            "nota_tecnica": "Instalado SSD 512GB y batería nueva, pruebas OK",
        },
    )
    assert r_prep.status_code == 200, r_prep.text
    prep_res = r_prep.json()
    assert prep_res["primer_costo_usd"] == 250.0
    assert prep_res["costo_componentes_usd"] == 60.0
    assert prep_res["comision_preparacion_usd"] == 15.0
    assert prep_res["costo_final_usd"] == 325.0
    assert prep_res["estado"] == "LISTO"

    # 4. Trasladar TRZ-PREP-01 a Local T38 y confirmar recepción
    r_tr = client.post(
        "/api/logistica/traslados",
        headers=h,
        json={"origen_id": alm_id, "destino_id": t38_id, "equipos_ids": [eq_map["TRZ-PREP-01"]["id"]], "nota": "Envío a tienda"},
    )
    assert r_tr.status_code == 201, r_tr.text
    assert client.post(f"/api/logistica/traslados/{r_tr.json()['id']}/confirmar", headers=h, json={"nota_recepcion": "OK"}).status_code == 200

    # 5. Vender TRZ-PREP-01 en Local T38 por $450.00 -> Utilidad Real = $450 - $325 = $125.00
    insts = {i["nombre"]: i["id"] for i in client.get("/api/finanzas/instrumentos", headers=h).json()}
    r_vta = client.post(
        "/api/ventas",
        headers=h,
        json={
            "sucursal_id": t38_id,
            "canal_visita": "Tienda",
            "origen_venta": "PASILLO",
            "entrega": "Tienda",
            "sin_cargador": True,
            "items": [{"equipo_id": eq_map["TRZ-PREP-01"]["id"], "cantidad": 1}],
            "pagos": [{"instrumento_id": insts["Efectivo divisas"], "monto_moneda_origen": 450.0}],
        },
    )
    assert r_vta.status_code == 201, r_vta.text
    vta = r_vta.json()
    assert vta["costo_total_usd"] == 325.0
    assert vta["utilidad_real_usd"] == 125.0

    # 6. Registrar 1 incidente de garantía posterior sobre TRZ-PREP-01
    r_gar = client.post(
        "/api/taller/casos",
        headers=h,
        json={
            "tipo": "GARANTIA",
            "sucursal_id": t38_id,
            "serial_o_codigo": "TRZ-PREP-01",
            "descripcion_equipo": "Dell Latitude 5420",
            "falla_reportada": "Puerto USB-C intermitente",
        },
    )
    assert r_gar.status_code == 201, r_gar.text

    # 7. Consultar Trazabilidad Total por Serial y validar todos los bloques
    r_trz = client.get("/api/inventario/trazabilidad/TRZ-PREP-01", headers=h)
    assert r_trz.status_code == 200, r_trz.text
    trz = r_trz.json()

    assert trz["equipo"]["serial"] == "TRZ-PREP-01"
    assert trz["equipo"]["primer_costo_usd"] == 250.0
    assert trz["equipo"]["costo_componentes_usd"] == 60.0
    assert trz["equipo"]["comision_preparacion_usd"] == 15.0
    assert trz["equipo"]["costo_final_usd"] == 325.0

    assert trz["compra_internacional"]["codigo"] == lote["codigo"]
    assert trz["compra_internacional"]["taxes_usd"] == 42.0
    assert trz["compra_internacional"]["envio_miami_usd"] == 18.0
    assert trz["compra_internacional"]["gastos_envio_venezuela_usd"] == 90.0

    assert len(trz["preparacion_y_costos"]["componentes"]) == 2
    assert len(trz["traslados"]) == 1
    assert trz["venta"]["numero_venta"] == vta["numero_venta"]
    assert trz["venta"]["ganancia_real_usd"] == 125.0
    assert len(trz["incidentes_postventa"]) == 1
    assert "USB-C" in trz["incidentes_postventa"][0]["falla_reportada"]
    assert len(trz["linea_tiempo"]) >= 6
