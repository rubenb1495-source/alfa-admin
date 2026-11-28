from __future__ import annotations

import base64
import zlib

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


def _extraer_texto_pdf(pdf_bytes: bytes) -> str:
    """Extrae texto descomprimiendo flujos FlateDecode de ReportLab para aserciones en tests."""
    partes = [pdf_bytes.decode("latin-1", errors="ignore")]
    inicio = 0
    while True:
        s = pdf_bytes.find(b"stream", inicio)
        if s == -1:
            break
        e = pdf_bytes.find(b"endstream", s)
        if e == -1:
            break
        datos = pdf_bytes[s + 6 : e].strip(b"\r\n")
        for cand in (datos,):
            try:
                partes.append(zlib.decompress(cand).decode("latin-1", errors="ignore"))
                continue
            except Exception:
                pass
            try:
                a85 = base64.a85decode(cand, adobe=True)
                partes.append(zlib.decompress(a85).decode("latin-1", errors="ignore"))
            except Exception:
                pass
        inicio = e + 9
    return "\n".join(partes)


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


def test_alerta_obligatoria_cargador_tres_casos(entorno):
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
        json={
            "fecha": hoy.isoformat(),
            "tasa_bcv": 100.0,
            "tasa_usdt": 120.0,
            "recargo_porcentaje": 20.0,
            "recargo_confirmado": True,
        },
    )

    # Crear artículo cargador en catálogo (AC-CARG-65W) e ingresar stock
    r_cat = client.post(
        "/api/catalogo",
        headers=h,
        json={
            "sku": "AC-CARG-65W",
            "descripcion": "Cargador USB-C 65W Original",
            "tipo": "ACCESORIO",
            "categoria": "Cargadores",
            "costo_referencia_usd": 10.0,
            "precio_promo_usd": 20.0,
        },
    )
    assert r_cat.status_code == 201, r_cat.text
    cargador_id = r_cat.json()["id"]

    # Ingresar 2 equipos LISTO y 2 cargadores en Local T38
    r_cmp = client.post(
        "/api/logistica/compras",
        headers=h,
        json={
            "origen": "NACIONAL",
            "fecha": hoy.isoformat(),
            "llega_preparada": True,
            "equipos": [
                {"serial": "CRG-EQ-1", "modelo": "Dell Latitude 5420", "ubicacion_id": sede_id, "costo_compra_usd": 200.0, "precio_promo_usd": 300.0},
                {"serial": "CRG-EQ-2", "modelo": "HP EliteBook 840", "ubicacion_id": sede_id, "costo_compra_usd": 200.0, "precio_promo_usd": 300.0},
            ],
            "componentes": [
                {"articulo_id": cargador_id, "cantidad": 2, "costo_unitario_usd": 10.0, "ubicacion_id": sede_id},
            ],
        },
    )
    assert r_cmp.status_code == 201, r_cmp.text

    eqs = {
        e["serial"]: e
        for e in client.get("/api/logistica/inventario/equipos?busqueda=CRG-EQ-", headers=h).json()
    }
    insts = {
        i["nombre"]: i
        for i in client.get("/api/finanzas/instrumentos", headers=h).json()
    }
    inst_usd = insts["Efectivo divisas"]["id"]

    # CASO (a): Equipo solo SIN cargador y SIN desbloqueo -> HTTP 422
    r_bloq = client.post(
        "/api/ventas",
        headers=h,
        json={
            "sucursal_id": sede_id,
            "canal_visita": "Tienda",
            "origen_venta": "PASILLO",
            "entrega": "Tienda",
            "items": [{"equipo_id": eqs["CRG-EQ-1"]["id"], "cantidad": 1}],
            "pagos": [{"instrumento_id": inst_usd, "monto_moneda_origen": 300.0}],
        },
    )
    assert r_bloq.status_code == 422, r_bloq.text
    assert "cargador" in r_bloq.json()["detail"].lower()

    # CASO (b): Equipo + cargador en el carrito -> 201 directo sin alerta
    r_con_carg = client.post(
        "/api/ventas",
        headers=h,
        json={
            "sucursal_id": sede_id,
            "canal_visita": "Tienda",
            "origen_venta": "PASILLO",
            "entrega": "Tienda",
            "items": [
                {"equipo_id": eqs["CRG-EQ-1"]["id"], "cantidad": 1},
                {"articulo_id": cargador_id, "cantidad": 1},
            ],
            "pagos": [{"instrumento_id": inst_usd, "monto_moneda_origen": 320.0}],
        },
    )
    assert r_con_carg.status_code == 201, r_con_carg.text
    assert r_con_carg.json()["sin_cargador"] is False

    # CASO (c): Equipo solo CON desbloqueo (sin_cargador: true) -> 201 + constancia en Nota PDF
    r_sin_carg = client.post(
        "/api/ventas",
        headers=h,
        json={
            "sucursal_id": sede_id,
            "canal_visita": "Tienda",
            "origen_venta": "PASILLO",
            "entrega": "Tienda",
            "sin_cargador": True,
            "motivo_sin_cargador": "Cliente ya tiene cargador",
            "items": [{"equipo_id": eqs["CRG-EQ-2"]["id"], "cantidad": 1}],
            "pagos": [{"instrumento_id": inst_usd, "monto_moneda_origen": 300.0}],
        },
    )
    assert r_sin_carg.status_code == 201, r_sin_carg.text
    v_sin = r_sin_carg.json()
    assert v_sin["sin_cargador"] is True
    assert v_sin["motivo_sin_cargador"] == "Cliente ya tiene cargador"

    # Verificar que la Nota de Entrega PDF refleja "Equipo entregado SIN cargador"
    r_pdf = client.get(f"/api/ventas/{v_sin['id']}/nota-pdf", headers=h)
    assert r_pdf.status_code == 200
    assert r_pdf.content.startswith(b"%PDF-")
    texto_pdf = _extraer_texto_pdf(r_pdf.content)
    assert "Equipo entregado SIN cargador" in texto_pdf
    assert "Cliente ya tiene cargador" in texto_pdf
