from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import CatalogoArticulo, CatalogoPrecio, Sucursal, TipoArticulo
from app.modelos_finanzas import InstrumentoFinanciero, MonedaInstrumento
from app.rutas.tasas import obtener_fecha_hoy
from app.semilla import ejecutar_semilla
from app.semilla_contabilidad import ejecutar_semilla_contabilidad
from app.semilla_finanzas import ejecutar_semilla_finanzas


@pytest.fixture()
def entorno_e2e():
    """Base de datos SQLite en memoria aislada: cero impacto sobre Neon PostgreSQL."""
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

        laptop_art = CatalogoArticulo(
            sku="LP-TEST-ALFA",
            descripcion="Laptop Test Alfa i5",
            categoria="Laptops",
            tipo=TipoArticulo.EQUIPO.value,
            activo=True,
        )
        ssd_art = CatalogoArticulo(
            sku="CO-SSD-256-TEST",
            descripcion="SSD 256GB NVMe",
            categoria="Componentes",
            tipo=TipoArticulo.COMPONENTE.value,
            activo=True,
        )
        bd_seed.add_all([laptop_art, ssd_art])
        bd_seed.flush()
        bd_seed.add(
            CatalogoPrecio(
                articulo_id=laptop_art.id,
                precio_promo_usd=Decimal("200.00"),
                precio_regular_fijo_usd=Decimal("240.00"),
                costo_referencia_usd=Decimal("100.00"),
                fecha_vigencia=hoy,
            )
        )
        bd_seed.add(
            CatalogoPrecio(
                articulo_id=ssd_art.id,
                precio_promo_usd=Decimal("35.00"),
                costo_referencia_usd=Decimal("20.00"),
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


def _login_admin(client: TestClient) -> dict[str, str]:
    r = client.post(
        "/api/auth/login",
        json={"correo": "direccion@alfaimportaciones.com", "clave": "Alfa2026!"},
    )
    assert r.status_code == 200, r.text
    token = r.json().get("token") or r.json().get("access_token")
    return {"Authorization": f"Bearer {token}"}


def test_flujo_integral_completo_alfa(entorno_e2e):
    client, Sesion = entorno_e2e
    headers = _login_admin(client)
    hoy_str = obtener_fecha_hoy().isoformat()

    # =========================================================================
    # PASO 1: Configuración inicial de jornada (tasas + tienda + caja + asesor sin acceso)
    # =========================================================================
    r_tasa = client.post(
        "/api/tasas/hoy/confirmar",
        headers=headers,
        json={
            "tasa_bcv": "50.0000",
            "tasa_usdt": "60.0000",
            "porcentaje_recargo": "20.00",
            "nota": "Apertura E2E",
        },
    )
    assert r_tasa.status_code == 200, r_tasa.text
    assert r_tasa.json()["recargo_confirmado"] is True

    bd = Sesion()
    suc = bd.query(Sucursal).first()
    ssd_art = bd.query(CatalogoArticulo).filter(CatalogoArticulo.sku == "CO-SSD-256-TEST").first()
    cta_usd = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.moneda == MonedaInstrumento.USD.value)
        .first()
    )
    assert suc is not None and ssd_art is not None and cta_usd is not None
    suc_id, ssd_id, cta_usd_id = suc.id, ssd_art.id, cta_usd.id
    bd.close()

    # Saldo inicial en Efectivo USD
    insts_ini = client.get("/api/finanzas/instrumentos", headers=headers).json()
    saldo_usd_inicial = next(i["saldo_actual"] for i in insts_ini if i["id"] == cta_usd_id)

    # Crear Asesor sin acceso al sistema (sin correo ni clave)
    r_asesor = client.post(
        "/api/usuarios",
        headers=headers,
        json={
            "nombre": "Carlos Asesor Online",
            "rol": "ASESORA",
            "modalidad": "ONLINE",
            "tiene_acceso": False,
        },
    )
    assert r_asesor.status_code == 201, r_asesor.text
    asesor_id = r_asesor.json()["id"]
    assert r_asesor.json()["correo"] is None

    # =========================================================================
    # PASO 2: Ingreso de Inventario (1 Equipo + 5 SSD 256GB)
    # =========================================================================
    r_ing = client.post(
        "/api/logistica/ingresos",
        headers=headers,
        json={
            "tipo_ingreso": "COMPRA_NACIONAL",
            "proveedor_nombre": "Importadora Alfa Proveedor",
            "almacen_destino_id": suc_id,
            "items": [
                {
                    "sku": "LP-TEST-ALFA",
                    "serial": "TEST-ALFA-001",
                    "cantidad": 1,
                    "costo_unitario_usd": "100.00",
                    "precio_venta_usd": "200.00",
                    "estado_inicial": "PENDIENTE_REVISION",
                },
                {
                    "sku": "CO-SSD-256-TEST",
                    "cantidad": 5,
                    "costo_unitario_usd": "20.00",
                },
            ],
        },
    )
    assert r_ing.status_code == 201, r_ing.text

    # Verificar equipo creado en PENDIENTE_REVISION y NO disponible para venta
    eq = client.get("/api/logistica/inventario/equipos?busqueda=TEST-ALFA-001", headers=headers).json()[0]
    assert eq["estado"] == "PENDIENTE_REVISION"
    assert eq["costo_total_usd"] == 100.0

    disp_antes = client.get(
        "/api/logistica/inventario/equipos?estado=DISPONIBLE&busqueda=TEST-ALFA-001",
        headers=headers,
    ).json()
    assert len(disp_antes) == 0

    # Intentar vender en PENDIENTE_REVISION debe rechazarse (400 o 409)
    r_vta_fail = client.post(
        "/api/ventas",
        headers=headers,
        json={
            "sucursal_id": suc_id,
            "asesor_id": asesor_id,
            "origen_venta": "LEAD",
            "sin_cargador": True, "items": [{"equipo_id": eq["id"], "cantidad": 1, "precio_promo_usd": "200.00"}],
            "pagos": [{"instrumento_id": cta_usd_id, "monto_moneda_origen": "200.00"}],
        },
    )
    assert r_vta_fail.status_code in (400, 409), r_vta_fail.text

    # Stock inicial del SSD debe ser 5
    kardex_antes = client.get("/api/logistica/inventario/kardex", headers=headers).json()
    stock_ssd_antes = next(
        s["stock_actual"]
        for s in kardex_antes["saldos"]
        if s["sku"] == "CO-SSD-256-TEST" and s["sucursal_id"] == suc_id
    )
    assert stock_ssd_antes == 5

    # =========================================================================
    # PASO 3: Preparación con Componentes (1 SSD $20) y Cambio a DISPONIBLE
    # =========================================================================
    r_en_prep = client.patch(
        "/api/preparaciones/estado-masivo",
        headers=headers,
        json={
            "equipo_ids": [eq["id"]],
            "nuevo_estado": "EN_PREPARACION",
            "observacion": "Inicio de alistamiento",
        },
    )
    assert r_en_prep.status_code == 200, r_en_prep.text

    r_listo = client.patch(
        "/api/preparaciones/estado-masivo",
        headers=headers,
        json={
            "equipo_ids": [eq["id"]],
            "nuevo_estado": "DISPONIBLE",
            "observacion": "Instalado SSD 256GB y probado OK",
            "componentes_usados": [{"articulo_id": ssd_id, "cantidad": 1}],
        },
    )
    assert r_listo.status_code == 200, r_listo.text
    eq_listo = r_listo.json()["equipos"][0]
    assert eq_listo["estado"] == "LISTO"
    assert eq_listo["costo_compra_usd"] == 100.0
    assert eq_listo["costo_taller_usd"] == 20.0
    assert eq_listo["costo_total_usd"] == 120.0

    # Stock del SSD bajó de 5 a 4
    kardex_desp = client.get("/api/logistica/inventario/kardex", headers=headers).json()
    stock_ssd_desp = next(
        s["stock_actual"]
        for s in kardex_desp["saldos"]
        if s["sku"] == "CO-SSD-256-TEST" and s["sucursal_id"] == suc_id
    )
    assert stock_ssd_desp == 4

    # Historial de estados registrado
    hist = client.get(f"/api/preparaciones/equipos/{eq['id']}/historial", headers=headers).json()
    estados_hist = [h["estado_nuevo"] for h in hist]
    assert "PENDIENTE_REVISION" in estados_hist
    assert "EN_PREPARACION" in estados_hist
    assert "LISTO" in estados_hist

    # Asiento contable cuadrado ($20 de 1.1.05 -> 1.1.03)
    asientos_prep = client.get("/api/contabilidad/asientos?origen_tipo=PREPARACION", headers=headers).json()
    assert len(asientos_prep) >= 1
    as_p = asientos_prep[0]
    assert as_p["total_debe_usd"] == 20.0
    assert as_p["total_haber_usd"] == 20.0
    cods_p = {d["cuenta_codigo"] for d in as_p["detalles"]}
    assert {"1.1.03", "1.1.05"}.issubset(cods_p)

    # =========================================================================
    # PASO 4: Venta en POS (Asesor sin acceso + origen LEAD + Efectivo USD)
    # =========================================================================
    r_vta = client.post(
        "/api/ventas",
        headers=headers,
        json={
            "sucursal_id": suc_id,
            "asesor_id": asesor_id,
            "origen_venta": "LEAD",
            "sin_cargador": True, "items": [{"equipo_id": eq["id"], "cantidad": 1, "precio_promo_usd": "200.00"}],
            "pagos": [{"instrumento_id": cta_usd_id, "monto_moneda_origen": "200.00"}],
        },
    )
    assert r_vta.status_code == 201, r_vta.text

    # Equipo pasa a VENDIDO y no se puede volver a vender
    eq_vend = client.get("/api/logistica/inventario/equipos?busqueda=TEST-ALFA-001", headers=headers).json()[0]
    assert eq_vend["estado"] == "VENDIDO"

    r_vta_dup = client.post(
        "/api/ventas",
        headers=headers,
        json={
            "sucursal_id": suc_id,
            "asesor_id": asesor_id,
            "origen_venta": "LEAD",
            "sin_cargador": True, "items": [{"equipo_id": eq["id"], "cantidad": 1, "precio_promo_usd": "200.00"}],
            "pagos": [{"instrumento_id": cta_usd_id, "monto_moneda_origen": "200.00"}],
        },
    )
    assert r_vta_dup.status_code in (400, 409)

    # Comisión de Alfa: 8% sobre Precio Promo USD ($200) = $16.00 en PENDIENTE
    rep_com = client.get(
        f"/api/comisiones/reporte?fecha_inicio={hoy_str}&fecha_fin={hoy_str}&personal_id={asesor_id}",
        headers=headers,
    ).json()
    assert rep_com["resumen_general"]["total_comisiones_usd"] == 16.0
    assert rep_com["resumen_general"]["lead_usd"] == 16.0

    # Costeo y Rentabilidad Real: Venta $200 - Costo $120 = Bruta $80 - Comisión $16 = Neta $64
    rent = client.get(
        f"/api/contabilidad/rentabilidad-ventas?fecha_inicio={hoy_str}&fecha_fin={hoy_str}",
        headers=headers,
    ).json()
    v_rent = rent["ventas"][0]
    assert v_rent["precio_venta_usd"] == 200.0
    assert v_rent["costo_total_real_usd"] == 120.0
    assert round(v_rent["precio_venta_usd"] - v_rent["costo_total_real_usd"], 2) == 80.0
    assert v_rent["comision_usd"] == 16.0
    assert v_rent["utilidad_neta_usd"] == 64.0

    # Saldo de Caja (Efectivo USD) subió exactamente +$200.00
    insts_fin = client.get("/api/finanzas/instrumentos", headers=headers).json()
    saldo_usd_final = next(i["saldo_actual"] for i in insts_fin if i["id"] == cta_usd_id)
    assert round(saldo_usd_final - saldo_usd_inicial, 2) == 200.0

    # Asiento contable de la venta cuadrado (Debe == Haber)
    asientos_vta = client.get("/api/contabilidad/asientos?origen_tipo=VENTA", headers=headers).json()
    assert len(asientos_vta) >= 1
    as_v = asientos_vta[0]
    assert as_v["total_debe_usd"] == as_v["total_haber_usd"]
    assert as_v["total_debe_usd"] == 336.0  # $200 cobro + $120 COGS + $16 comisión

    # Balance General cuadrado
    bal = client.get("/api/contabilidad/balance-general", headers=headers).json()
    assert bal["ecuacion_cuadrada"] is True
    p2102 = next(x for x in bal["pasivos"]["detalle"] if x["codigo"] == "2.1.02")
    assert p2102["saldo_usd"] >= 16.0

    # Cierre Diario refleja la venta del día
    cierre = client.get(f"/api/cierre-diario?fecha={hoy_str}", headers=headers)
    assert cierre.status_code == 200, cierre.text
    cierre_data = cierre.json()
    assert cierre_data["ventas_dia"]["cantidad_total"] >= 1
    assert cierre_data["ventas_dia"]["total_promo_usd"] >= 200.0
    assert cierre_data["ventas_dia"]["lead_cantidad"] >= 1
    assert cierre_data["recibido_por_instrumento"]["total_usd"] >= 200.0
