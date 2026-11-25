from __future__ import annotations

import io
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import TasaDiaria, Usuario
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
    token = resp.json().get("token") or resp.json().get("access_token")
    return {"Authorization": f"Bearer {token}"}


def _excel_bytes(headers: list[str], rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Datos"
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_1_libro_iva_excel_y_retenciones_pdf(entorno):
    client, _Sesion = entorno
    headers = _login(client, "direccion@alfaimportaciones.com", "Alfa2026!")
    hoy_str = obtener_fecha_hoy().isoformat()

    # Registrar factura de gasto deducible con IVA 16% (Base 5000 Bs -> IVA 800 Bs -> Total 5800 Bs)
    g = client.post(
        "/api/admin/gastos",
        headers=headers,
        json={
            "rif_proveedor": "J-30112233-4",
            "razon_social": "Servicios Corp CA",
            "numero_factura": "FAC-9001",
            "numero_control": "00-9001",
            "fecha_emision": hoy_str,
            "categoria": "Electricidad/Agua/Internet",
            "es_deducible": True,
            "base_imponible_bs": "5000.00",
            "alicuota_iva": "16.00",
            "tasa_bcv_fecha": "50.00",
        },
    )
    assert g.status_code == 201, g.text
    assert g.json()["monto_iva_bs"] == 800.0
    assert g.json()["monto_total_bs"] == 5800.0

    # Consultar Libros IVA y exportar Excel
    lib = client.get("/api/admin/fiscal/libros", headers=headers)
    assert lib.status_code == 200, lib.text
    assert lib.json()["resumen"]["credito_fiscal_bs"] == 800.0

    xls = client.get("/api/admin/fiscal/libros/excel?tipo=COMPRAS", headers=headers)
    assert xls.status_code == 200
    assert "spreadsheetml" in xls.headers["content-type"]

    # Crear Retención IVA 75% sobre 800 Bs -> 600 Bs y descargar PDF
    ret = client.post(
        "/api/admin/fiscal/retenciones",
        headers=headers,
        json={
            "tipo": "IVA",
            "factura_gasto_id": g.json()["id"],
            "rif_sujeto": "J-30112233-4",
            "razon_social": "Servicios Corp CA",
            "numero_factura_ref": "FAC-9001",
            "base_imponible_bs": "800.00",
            "porcentaje_retencion": "75.00",
        },
    )
    assert ret.status_code == 201, ret.text
    assert ret.json()["monto_retenido_bs"] == 600.0

    pdf = client.get(f"/api/admin/fiscal/retenciones/{ret.json()['id']}/pdf", headers=headers)
    assert pdf.status_code == 200
    assert "pdf" in pdf.headers["content-type"]


def test_2_pago_nomina_y_obligacion_descuentan_tesoreria_y_auditan(entorno):
    client, Sesion = entorno
    headers = _login(client, "direccion@alfaimportaciones.com", "Alfa2026!")
    hoy_str = obtener_fecha_hoy().isoformat()

    bd = Sesion()
    cta_usd = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.moneda == MonedaInstrumento.USD.value)
        .first()
    )
    usr = bd.query(Usuario).first()
    usr.salario_base_usd = Decimal("400.00")
    usr.bono_alimentacion_usd = Decimal("40.00")
    bd.commit()
    cta_id, usr_id = cta_usd.id, usr.id
    bd.close()

    def _saldo_cta() -> float:
        r = client.get("/api/finanzas/instrumentos", headers=headers).json()
        return next(i["saldo_actual"] for i in r if i["id"] == cta_id)

    saldo_ini = _saldo_cta()

    # 1. Crear y pagar Nómina quincenal (salario 200 + cesta 20 = 220; deducciones LOTTT 5.5% de 200 = 11 -> neto 209)
    nom = client.post(
        "/api/admin/nominas",
        headers=headers,
        json={
            "tipo_periodo": "QUINCENAL",
            "fecha_inicio": hoy_str,
            "fecha_fin": hoy_str,
            "items": [{"personal_id": usr_id}],
        },
    )
    assert nom.status_code == 201, nom.text
    assert nom.json()["total_neto_usd"] == 209.0

    pago_nom = client.post(
        f"/api/admin/nominas/{nom.json()['id']}/pagar",
        headers=headers,
        json={"instrumento_pago_id": cta_id, "referencia_pago": "NOM-REF-01"},
    )
    assert pago_nom.status_code == 200, pago_nom.text
    assert _saldo_cta() == round(saldo_ini - 209.0, 2)

    # 2. Crear y pagar Obligación Fiscal SENIAT ($100)
    ob = client.post(
        "/api/admin/fiscal/obligaciones",
        headers=headers,
        json={
            "organismo": "SENIAT",
            "tipo_obligacion": "Declaración IVA",
            "periodo": "2026-11",
            "fecha_vencimiento": hoy_str,
            "monto_estimado_usd": "100.00",
        },
    )
    assert ob.status_code == 201, ob.text
    pago_ob = client.post(
        f"/api/admin/fiscal/obligaciones/{ob.json()['id']}/pagar",
        headers=headers,
        json={"instrumento_pago_id": cta_id, "monto_pagado_usd": "100.00", "referencia_pago": "SENIAT-01"},
    )
    assert pago_ob.status_code == 200, pago_ob.text
    assert _saldo_cta() == round(saldo_ini - 309.0, 2)

    # 3. Verificar registro automático en audit_logs
    logs = client.get("/api/admin/auditoria?accion=PAGAR", headers=headers).json()
    modulos_pagados = {l["modulo"] for l in logs}
    assert "NOMINA" in modulos_pagados
    assert "OBLIGACIONES_LEGALES" in modulos_pagados


def test_3_carga_masiva_gastos_y_extracto_con_validacion(entorno):
    client, Sesion = entorno
    headers = _login(client, "direccion@alfaimportaciones.com", "Alfa2026!")
    hoy_str = obtener_fecha_hoy().isoformat()

    bd = Sesion()
    cta_id = bd.query(InstrumentoFinanciero).first().id
    bd.close()

    # Descargar las 5 plantillas administrativas
    for tipo in [
        "FACTURAS_GASTOS_CXP",
        "EXTRACTO_BANCARIO",
        "NOMINA_PERSONAL",
        "OBLIGACIONES_FISCALES",
        "ACTIVOS_FIJOS",
    ]:
        r = client.get(f"/api/admin/plantilla/{tipo}", headers=headers)
        assert r.status_code == 200, r.text

    # Gastos con 1 fila mala (sin razon_social y monto 0) -> preview detecta error y confirmar rechaza con 400
    xls_err = _excel_bytes(
        ["rif_proveedor", "razon_social", "numero_factura", "fecha_emision", "base_imponible_bs", "alicuota_iva"],
        [["J-1", "", "F-1", hoy_str, 0, 16]],
    )
    prev = client.post(
        "/api/admin/importar/FACTURAS_GASTOS_CXP/preview",
        headers=headers,
        files={"archivo": ("gastos.xlsx", xls_err, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert prev.status_code == 200
    assert prev.json()["errores_count"] == 1
    assert (
        client.post(
            "/api/admin/importar/FACTURAS_GASTOS_CXP/confirmar",
            headers=headers,
            files={"archivo": ("gastos.xlsx", xls_err, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        ).status_code
        == 400
    )

    # Extracto bancario válido -> confirma atómicamente y aparece en conciliación
    xls_ext = _excel_bytes(
        ["fecha", "referencia", "descripcion", "debito", "credito", "saldo"],
        [[hoy_str, "REF-BCO-99", "Abono cliente", 0, 250.0, 250.0]],
    )
    conf_ext = client.post(
        "/api/admin/importar/EXTRACTO_BANCARIO/confirmar",
        headers=headers,
        data={"instrumento_id": str(cta_id)},
        files={"archivo": ("extracto.xlsx", xls_ext, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert conf_ext.status_code == 201, conf_ext.text
    conc = client.get(f"/api/admin/conciliacion?instrumento_id={cta_id}", headers=headers).json()
    assert len(conc["extractos_banco"]) == 1


def test_4_rbac_admin_director_encargado_en_administracion(entorno):
    client, _Sesion = entorno
    h_admin = _login(client, "direccion@alfaimportaciones.com", "Alfa2026!")

    client.post(
        "/api/usuarios",
        headers=h_admin,
        json={
            "nombre": "Director Finanzas",
            "rol": "DIRECTOR",
            "tiene_acceso": True,
            "correo": "dir.fin@alfaimportaciones.com",
            "clave": "Password123!",
        },
    )
    client.post(
        "/api/usuarios",
        headers=h_admin,
        json={
            "nombre": "Encargado Tienda",
            "rol": "ENCARGADO_TIENDA",
            "tiene_acceso": True,
            "correo": "enc.fin@alfaimportaciones.com",
            "clave": "Password123!",
        },
    )
    h_dir = _login(client, "dir.fin@alfaimportaciones.com", "Password123!")
    h_enc = _login(client, "enc.fin@alfaimportaciones.com", "Password123!")

    # GET: ADMIN 200, DIRECTOR 200, ENCARGADO 403
    for ruta in [
        "/api/admin/estado-resultados",
        "/api/admin/fiscal/libros",
        "/api/admin/gastos",
        "/api/admin/nominas",
        "/api/admin/activos",
        "/api/admin/auditoria",
    ]:
        assert client.get(ruta, headers=h_admin).status_code == 200
        assert client.get(ruta, headers=h_dir).status_code == 200
        assert client.get(ruta, headers=h_enc).status_code == 403

    # POST: DIRECTOR y ENCARGADO reciben 403
    hoy_str = obtener_fecha_hoy().isoformat()
    payload_ob = {
        "organismo": "ALCALDIA",
        "tipo_obligacion": "ISAE",
        "fecha_vencimiento": hoy_str,
        "monto_estimado_usd": "50.00",
    }
    assert client.post("/api/admin/fiscal/obligaciones", headers=h_dir, json=payload_ob).status_code == 403
    assert client.post("/api/admin/fiscal/obligaciones", headers=h_enc, json=payload_ob).status_code == 403
    assert client.post("/api/admin/fiscal/obligaciones", headers=h_admin, json=payload_ob).status_code == 201
