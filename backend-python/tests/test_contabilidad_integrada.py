from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import CatalogoArticulo, CatalogoPrecio, Sucursal, TasaDiaria, TipoArticulo
from app.modelos_finanzas import InstrumentoFinanciero, MonedaInstrumento
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
    Sesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)
    Base.metadata.create_all(bind=motor)

    bd_seed = Sesion()
    try:
        ejecutar_semilla(bd_seed)
        ejecutar_semilla_finanzas(bd_seed)
        ejecutar_semilla_contabilidad(bd_seed)
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

        # Crear SKU equipo y SKU RAM con costo de referencia $25
        eq_art = CatalogoArticulo(
            sku="LP-CONTAB-01",
            descripcion="Dell Latitude 5420 Contab",
            categoria="Laptops",
            tipo=TipoArticulo.EQUIPO.value,
            activo=True,
        )
        ram_art = CatalogoArticulo(
            sku="CO-RAM-16GB",
            descripcion="Memoria RAM 16GB DDR4",
            categoria="Componentes",
            tipo=TipoArticulo.COMPONENTE.value,
            activo=True,
        )
        bd_seed.add_all([eq_art, ram_art])
        bd_seed.flush()
        bd_seed.add(
            CatalogoPrecio(
                articulo_id=eq_art.id,
                precio_promo_usd=Decimal("350.00"),
                costo_referencia_usd=Decimal("200.00"),
                fecha_vigencia=hoy,
            )
        )
        bd_seed.add(
            CatalogoPrecio(
                articulo_id=ram_art.id,
                precio_promo_usd=Decimal("40.00"),
                costo_referencia_usd=Decimal("25.00"),
                fecha_vigencia=hoy,
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


def test_1_plan_cuentas_y_validacion_partida_doble(entorno):
    client, _Sesion = entorno
    h = _login(client, "direccion@alfaimportaciones.com", "Alfa2026!")

    plan = client.get("/api/contabilidad/plan-cuentas", headers=h)
    assert plan.status_code == 200
    codigos = {c["codigo"] for c in plan.json()}
    for requerido in ["1.1.01", "1.1.03", "1.1.05", "2.2.01", "4.1.01", "5.1.01", "6.1.01", "8.1.02", "8.1.03"]:
        assert requerido in codigos

    # Asiento descuadrado -> 400 Bad Request
    bad = client.post(
        "/api/contabilidad/asientos",
        headers=h,
        json={
            "descripcion": "Asiento descuadrado",
            "lineas": [
                {"cuenta_codigo": "1.1.01", "debe_usd": "100.00", "haber_usd": "0"},
                {"cuenta_codigo": "3.1.01", "debe_usd": "0", "haber_usd": "90.00"},
            ],
        },
    )
    assert bad.status_code == 400

    # Asiento cuadrado -> 201 Created
    ok = client.post(
        "/api/contabilidad/asientos",
        headers=h,
        json={
            "descripcion": "Aporte inicial de capital",
            "lineas": [
                {"cuenta_codigo": "1.1.01", "debe_usd": "1000.00", "haber_usd": "0"},
                {"cuenta_codigo": "3.1.01", "debe_usd": "0", "haber_usd": "1000.00"},
            ],
        },
    )
    assert ok.status_code == 201, ok.text


def test_2_costeo_real_preparacion_venta_y_rentabilidad_post_comision(entorno):
    client, Sesion = entorno
    h = _login(client, "direccion@alfaimportaciones.com", "Alfa2026!")

    bd = Sesion()
    suc = bd.query(Sucursal).first()
    ram = bd.query(CatalogoArticulo).filter(CatalogoArticulo.sku == "CO-RAM-16GB").first()
    cta_usd = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.moneda == MonedaInstrumento.USD.value).first()
    bd.close()

    # Crear asesor (comisión 8% en LEAD)
    as_r = client.post(
        "/api/usuarios",
        headers=h,
        json={"nombre": "Asesor Contab", "rol": "ASESORA", "tiene_acceso": False},
    )
    assert as_r.status_code == 201
    asesor_id = as_r.json()["id"]

    # Ingresar 1 laptop ($200) y 2 memorias RAM ($25 c/u)
    ing = client.post(
        "/api/logistica/ingresos",
        headers=h,
        json={
            "tipo_ingreso": "COMPRA_NACIONAL",
            "proveedor_nombre": "Mayorista Tech",
            "almacen_destino_id": suc.id,
            "items": [
                {"sku": "LP-CONTAB-01", "serial": "SN-CTB-001", "cantidad": 1, "costo_unitario_usd": "200.00", "precio_venta_usd": "350.00"},
                {"sku": "CO-RAM-16GB", "cantidad": 2, "costo_unitario_usd": "25.00"},
            ],
        },
    )
    assert ing.status_code == 201, ing.text

    eq = client.get("/api/logistica/inventario/equipos?busqueda=SN-CTB-001", headers=h).json()[0]

    # Preparación: instalar 1 RAM ($25) y pasar a DISPONIBLE -> costo_total_usd debe ser $225 y generar asiento 1.1.03 vs 1.1.05
    prep = client.patch(
        "/api/preparaciones/estado-masivo",
        headers=h,
        json={
            "equipo_ids": [eq["id"]],
            "nuevo_estado": "DISPONIBLE",
            "observacion": "Upgrade RAM 16GB",
            "componentes_usados": [{"articulo_id": ram.id, "cantidad": 1}],
        },
    )
    assert prep.status_code == 200, prep.text
    eq_prep = prep.json()["equipos"][0]
    assert eq_prep["costo_taller_usd"] == 25.0
    assert eq_prep["costo_total_usd"] == 225.0

    # Vender el equipo en $350 (LEAD -> comisión 8% = $28)
    vta = client.post(
        "/api/ventas",
        headers=h,
        json={
            "sucursal_id": suc.id,
            "asesor_id": asesor_id,
            "origen_venta": "LEAD",
            "items": [{"equipo_id": eq["id"], "cantidad": 1, "precio_promo_usd": "350.00"}],
            "pagos": [{"instrumento_id": cta_usd.id, "monto_moneda_origen": "350.00"}],
        },
    )
    assert vta.status_code == 201, vta.text

    # Rentabilidad real: Venta $350 - Costo Real $225 ($200 base + $25 prep) - Comisión $28 = Utilidad Neta $97
    rent = client.get("/api/contabilidad/rentabilidad-ventas", headers=h).json()
    v_row = rent["ventas"][0]
    assert v_row["precio_venta_usd"] == 350.0
    assert v_row["costo_preparacion_usd"] == 25.0
    assert v_row["costo_total_real_usd"] == 225.0
    assert v_row["comision_usd"] == 28.0
    assert v_row["utilidad_neta_usd"] == 97.0


def test_3_prestamos_balance_y_rbac(entorno):
    client, Sesion = entorno
    h_admin = _login(client, "direccion@alfaimportaciones.com", "Alfa2026!")

    bd = Sesion()
    cta_usd = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.moneda == MonedaInstrumento.USD.value).first()
    cta_id = cta_usd.id
    bd.close()

    # Registrar préstamo $1000
    pre = client.post(
        "/api/contabilidad/prestamos",
        headers=h_admin,
        json={"acreedor": "Banco Mercantil", "concepto": "Capital de trabajo", "capital_usd": "1000.00", "instrumento_ingreso_id": cta_id},
    )
    assert pre.status_code == 201, pre.text
    pre_id = pre.json()["id"]

    # Pagar $200 capital + $50 interés -> saldo capital $800, intereses pagados $50, asiento 2.2.01 + 8.1.02 vs 1.1.01
    pago = client.post(
        f"/api/contabilidad/prestamos/{pre_id}/pagar",
        headers=h_admin,
        json={"monto_capital_usd": "200.00", "monto_interes_usd": "50.00", "instrumento_pago_id": cta_id},
    )
    assert pago.status_code == 200, pago.text
    assert pago.json()["saldo_capital_usd"] == 800.0
    assert pago.json()["total_intereses_pagados_usd"] == 50.0

    # Balance General refleja los $800 en 2.2.01
    bal = client.get("/api/contabilidad/balance-general", headers=h_admin).json()
    p2201 = next(x for x in bal["pasivos"]["detalle"] if x["codigo"] == "2.2.01")
    assert p2201["saldo_usd"] == 800.0

    # RBAC: DIRECTOR lee (200) pero no escribe (403); ENCARGADO y TECNICO reciben 403 en todo
    for nombre, rol, correo in [
        ("Director Contab", "DIRECTOR", "dir.ctb@alfaimportaciones.com"),
        ("Encargado Contab", "ENCARGADO_TIENDA", "enc.ctb@alfaimportaciones.com"),
        ("Tecnico Contab", "TECNICO", "tec.ctb@alfaimportaciones.com"),
    ]:
        client.post(
            "/api/usuarios",
            headers=h_admin,
            json={"nombre": nombre, "rol": rol, "tiene_acceso": True, "correo": correo, "clave": "Password123!", "debe_cambiar_clave": False},
        )

    h_dir = _login(client, "dir.ctb@alfaimportaciones.com", "Password123!")
    h_enc = _login(client, "enc.ctb@alfaimportaciones.com", "Password123!")
    h_tec = _login(client, "tec.ctb@alfaimportaciones.com", "Password123!")

    assert client.get("/api/contabilidad/balance-general", headers=h_dir).status_code == 200
    assert client.get("/api/contabilidad/rentabilidad-ventas", headers=h_dir).status_code == 200
    assert client.post("/api/contabilidad/prestamos", headers=h_dir, json={"acreedor": "X", "capital_usd": "10", "instrumento_ingreso_id": cta_id}).status_code == 403
    assert client.get("/api/contabilidad/balance-general", headers=h_enc).status_code == 403
    assert client.get("/api/contabilidad/balance-general", headers=h_tec).status_code == 403
