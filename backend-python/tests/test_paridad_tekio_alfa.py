from __future__ import annotations

import io
import zipfile

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
    sede = bd.query(Sucursal).filter(Sucursal.nombre == "Local T38").first()
    sede_id = sede.id
    bd.close()

    def _override_bd():
        s = Sesion()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[obtener_bd] = _override_bd
    with TestClient(app) as client:
        yield client, sede_id
    app.dependency_overrides.clear()


def test_paridad_tekio_etiqueta_fragil_cashea_lote_y_apertura(entorno):
    client, sede_id = entorno
    r_adm = client.post(
        "/api/auth/login",
        json={"usuario": "direccion@alfaimportaciones.com", "clave": "Alfa2026!"},
    )
    assert r_adm.status_code == 200
    h = {"Authorization": f"Bearer {r_adm.json()['token']}"}
    hoy = obtener_fecha_hoy()

    # Tasa del día
    client.post(
        "/api/tasas",
        headers=h,
        json={"fecha": hoy.isoformat(), "tasa_bcv": 100.0, "tasa_usdt": 120.0, "recargo_porcentaje": 20.0, "recargo_confirmado": True},
    )

    # Cargar 2 equipos
    client.post(
        "/api/logistica/compras",
        headers=h,
        json={
            "origen": "NACIONAL",
            "fecha": hoy.isoformat(),
            "llega_preparada": True,
            "equipos": [
                {"serial": "PAR-1", "modelo": "Dell 5420", "ubicacion_id": sede_id, "costo_compra_usd": 200.0, "precio_promo_usd": 300.0},
                {"serial": "PAR-2", "modelo": "HP 840", "ubicacion_id": sede_id, "costo_compra_usd": 200.0, "precio_promo_usd": 300.0},
            ],
        },
    )
    eqs = {e["serial"]: e for e in client.get("/api/logistica/inventario/equipos?busqueda=PAR-", headers=h).json()}
    insts = {i["nombre"]: i for i in client.get("/api/finanzas/instrumentos", headers=h).json()}

    # 1. Venta con Envío Nacional -> Etiqueta FRÁGIL PDF válida
    v_env = client.post(
        "/api/ventas",
        headers=h,
        json={
            "sucursal_id": sede_id,
            "canal_visita": "WhatsApp",
            "origen_venta": "LEAD",
            "entrega": "Envío Nacional",
            "datos_entrega": {
                "destinatario": "Carlos Pérez",
                "cedula": "V-18123456",
                "telefono": "0414-5551234",
                "empresa_envio": "MRW",
                "estado_ciudad": "Caracas",
                "agencia_oficina": "MRW Chacao",
                "modalidad": "Cobro en Destino",
            },
            "items": [{"equipo_id": eqs["PAR-1"]["id"], "cantidad": 1}],
            "pagos": [{"instrumento_id": insts["Efectivo divisas"]["id"], "monto_moneda_origen": 300.0}],
        },
    )
    assert v_env.status_code == 201, v_env.text
    r_pdf = client.get(f"/api/ventas/{v_env.json()['id']}/etiqueta-envio", headers=h)
    assert r_pdf.status_code == 200
    assert r_pdf.headers["content-type"].startswith("application/pdf")
    assert r_pdf.content.startswith(b"%PDF-")

    # 2. Venta Cashea -> Importar liquidación en lote (CSV preview + confirmar)
    v_csh = client.post(
        "/api/ventas",
        headers=h,
        json={
            "sucursal_id": sede_id,
            "canal_visita": "Tienda",
            "origen_venta": "PASILLO",
            "entrega": "Tienda",
            "items": [{"equipo_id": eqs["PAR-2"]["id"], "cantidad": 1}],
            "pagos": [
                {"instrumento_id": insts["Efectivo divisas"]["id"], "monto_moneda_origen": 120.0},
                {"instrumento_id": insts["Cashea · financiado"]["id"], "monto_moneda_origen": 24000.0, "referencia": "ORD-CSH-999"},
            ],
        },
    )
    assert v_csh.status_code == 201, v_csh.text
    # Retiro en tienda debe rechazar etiqueta FRÁGIL (400)
    assert client.get(f"/api/ventas/{v_csh.json()['id']}/etiqueta-envio", headers=h).status_code == 400

    csv_data = b"Orden,Monto Neto Pagado USD\nORD-CSH-999,215.00\nORD-INEXISTENTE,50.00\n"
    r_prev = client.post(
        "/api/finanzas/cashea/importar-reporte/preview",
        headers=h,
        files={"archivo": ("liquidacion.csv", csv_data, "text/csv")},
    )
    assert r_prev.status_code == 200, r_prev.text
    prev = r_prev.json()
    assert prev["resumen"]["listas_para_conciliar"] == 1
    assert prev["resumen"]["no_encontradas"] == 1
    fila_ok = next(f for f in prev["filas"] if f["estado_cruce"] == "LISTA_PARA_CONCILIAR")

    r_conf = client.post(
        "/api/finanzas/cashea/importar-reporte/confirmar",
        headers=h,
        json={
            "nombre_archivo": "liquidacion.csv",
            "instrumento_destino_id": insts["Zelle"]["id"],
            "referencia_bancaria": "TRF-LOTE-1",
            "ordenes": [
                {
                    "cashea_id": fila_ok["cashea_id"],
                    "cashea_numero_orden": "ORD-CSH-999",
                    "monto_pagado_real_usd": 215.0,
                }
            ],
        },
    )
    assert r_conf.status_code == 200, r_conf.text
    assert r_conf.json()["notas_conciliadas"] == 1

    # 3. Apertura 01/12: 6 plantillas .zip, reset en cero y carga de saldos iniciales
    r_zip = client.get("/api/apertura/plantillas-zip", headers=h)
    assert r_zip.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r_zip.content), "r") as zf:
        assert len(zf.namelist()) == 6

    # Reset en cero con frase incorrecta -> 400
    assert client.post(
        "/api/apertura/reset-cero",
        headers=h,
        json={"password": "Alfa2026!", "frase_confirmacion": "OTRA"},
    ).status_code == 400

    # Reset en cero válido -> limpia data operativa
    r_res = client.post(
        "/api/apertura/reset-cero",
        headers=h,
        json={"password": "Alfa2026!", "frase_confirmacion": "REINICIAR ALFA DESDE CERO"},
    )
    assert r_res.status_code == 200, r_res.text
    assert client.get("/api/apertura/estado", headers=h).json()["en_cero"] is True

    # Cargar saldos iniciales de apertura
    r_sal = client.post(
        "/api/apertura/cargar-saldos-iniciales",
        headers=h,
        json={
            "saldos": [
                {"instrumento_id": insts["Efectivo divisas"]["id"], "saldo_inicial": 1500.0},
                {"instrumento_id": insts["Zelle"]["id"], "saldo_inicial": 2500.0},
            ]
        },
    )
    assert r_sal.status_code == 200, r_sal.text
    assert r_sal.json()["total_usd"] == 4000.0
    assert r_sal.json()["asiento_id"] is not None
