from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import Sucursal
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


def test_lote_en_transito_sin_seriales_y_recepcion_flexible_prorrateo_contabilidad(entorno):
    client, Sesion = entorno
    r_login = client.post(
        "/api/auth/login",
        json={"usuario": "Dirección General Alfa", "clave": "Alfa2026!"},
    )
    assert r_login.status_code == 200, r_login.text
    headers = {"Authorization": f"Bearer {r_login.json()['token']}"}

    bd = Sesion()
    alm_id = bd.query(Sucursal).filter(Sucursal.nombre == "Almacén Guaparo Norte").first().id
    bd.close()

    # 1. Registrar Lote en Tránsito SIN seriales (3 Laptops @ $200 + 4 SSD @ $20 + $60 flete + $30 aduana = $770)
    r_lote = client.post(
        "/api/logistica/transito",
        headers=headers,
        json={
            "proveedor_nombre": "Miami Import Tech",
            "almacen_destino_id": alm_id,
            "trackings": "TRK-001, TRK-002",
            "costo_flete_estimado_usd": 60.0,
            "costo_aduana_otros_usd": 30.0,
            "observaciones": "Lote aéreo sin seriales todavía",
            "items": [
                {
                    "tipo_item": "EQUIPO",
                    "sku": "IMP-LAP-I5",
                    "descripcion_esperada": "Laptop Dell Latitude 5420",
                    "especificaciones_esperadas": "i5 / 8GB / 256GB",
                    "cantidad_esperada": 3,
                    "costo_unitario_estimado_usd": 200.0,
                    "precio_promo_usd": 390.0,
                },
                {
                    "tipo_item": "COMPONENTE",
                    "sku": "IMP-SSD-512",
                    "descripcion_esperada": "SSD NVMe 512GB",
                    "cantidad_esperada": 4,
                    "costo_unitario_estimado_usd": 20.0,
                    "precio_promo_usd": 45.0,
                },
            ],
        },
    )
    assert r_lote.status_code == 201, r_lote.text
    lote = r_lote.json()
    assert lote["codigo"].startswith("TRN-")
    assert lote["estado"] == "EN_TRANSITO"
    assert lote["total_en_transito_usd"] == 770.0

    # Asiento 1.1.04 En Tránsito vs 2.1.01 CxP
    as_trn = client.get("/api/contabilidad/asientos?origen_tipo=LOTE_TRANSITO", headers=headers).json()
    assert len(as_trn) == 1
    assert as_trn[0]["total_debe_usd"] == as_trn[0]["total_haber_usd"] == 770.0

    # Balance General incluye el lote en 1.1.04
    bal1 = client.get("/api/contabilidad/balance-general", headers=headers).json()
    a1104 = next(x for x in bal1["activos"]["detalle"] if x["codigo"] == "1.1.04")
    assert a1104["saldo_usd"] >= 770.0

    it_eq = next(i for i in lote["items"] if i["tipo_item"] == "EQUIPO")
    it_comp = next(i for i in lote["items"] if i["tipo_item"] == "COMPONENTE")

    # 2. Recepción Flexible en Almacén:
    # Llegan 2 equipos reales (1 faltante) + 4 SSDs = 6 unidades reales -> flete/aduana $90 / 6 = $15.00 por unidad
    r_rec = client.post(
        f"/api/logistica/transito/{lote['id']}/recibir",
        headers=headers,
        json={
            "almacen_destino_id": alm_id,
            "observaciones": "Llegó 1 laptop menos en la caja",
            "items": [
                {
                    "item_id": it_eq["id"],
                    "descripcion_real": "Laptop Dell Latitude 5420 (16GB RAM)",
                    "especificaciones_reales": "i5 / 16GB / 256GB",
                    "cantidad_recibida": 2,
                    "cantidad_danada_faltante": 1,
                    "observacion_recepcion": "1 equipo faltante en caja",
                    "equipos_recibidos": [
                        {
                            "serial": "TRN-REAL-001",
                            "modelo": "Laptop Dell Latitude 5420",
                            "especificaciones": "i5 / 16GB / 256GB",
                            "estado_inicial": "PENDIENTE_REVISION",
                        },
                        {
                            "serial": "TRN-REAL-002",
                            "modelo": "Laptop Dell Latitude 5420",
                            "especificaciones": "i5 / 16GB / 256GB",
                            "estado_inicial": "POR_INCIDENCIA",
                        },
                    ],
                },
                {
                    "item_id": it_comp["id"],
                    "cantidad_recibida": 4,
                    "cantidad_danada_faltante": 0,
                },
            ],
        },
    )
    assert r_rec.status_code == 200, r_rec.text
    rec = r_rec.json()
    assert rec["estado"] == "RECIBIDO"
    assert rec["equipos_creados"] == 2
    assert rec["componentes_recibidos"] == 4
    assert rec["flete_prorrateado_por_unidad_usd"] == 15.0
    assert rec["total_reclasificado_usd"] == 570.0  # 2*215 + 4*35

    # Verificar equipos creados con serial real, flete $15 y estados
    eqs = client.get(f"/api/logistica/inventario/equipos?sucursal_id={alm_id}", headers=headers).json()
    e1 = next(e for e in eqs if e["serial"] == "TRN-REAL-001")
    e2 = next(e for e in eqs if e["serial"] == "TRN-REAL-002")
    assert e1["costo_flete_usd"] == 15.0
    assert e1["estado"] == "PENDIENTE_REVISION"
    assert e2["estado"] == "DEFECTUOSO"

    # Asiento de reclasificación 1.1.03 ($430) + 1.1.05 ($140) vs 1.1.04 ($570)
    as_rec = client.get("/api/contabilidad/asientos?origen_tipo=RECEPCION_TRANSITO", headers=headers).json()
    assert len(as_rec) == 1
    assert as_rec[0]["total_debe_usd"] == as_rec[0]["total_haber_usd"] == 570.0
    debes = {d["cuenta_codigo"]: d["debe_usd"] for d in as_rec[0]["detalles"]}
    haberes = {d["cuenta_codigo"]: d["haber_usd"] for d in as_rec[0]["detalles"]}
    assert debes.get("1.1.03") == 430.0
    assert debes.get("1.1.05") == 140.0
    assert haberes.get("1.1.04") == 570.0
