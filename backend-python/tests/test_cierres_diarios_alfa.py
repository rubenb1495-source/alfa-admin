from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import RolUsuario, Sucursal, Usuario
from app.modelos_finanzas import (
    EstadoVerificacionPago,
    InstrumentoFinanciero,
    Pago,
    TipoDocumentoPago,
    TipoMovimientoPago,
)
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import crear_token_acceso, generar_hash_clave
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

    sucs = {s.nombre: s for s in bd.query(Sucursal).all()}
    alm = sucs["Almacén Guaparo Norte"]
    sede1 = sucs["Local T38"]
    sede2 = sucs["Local V30-V31"]

    # Sembrar saldos iniciales en cajas/bancos para probar cuadre exacto
    for inst in bd.query(InstrumentoFinanciero).all():
        if inst.nombre == "Efectivo divisas":
            inst.saldo_inicial = Decimal("500.00")
        elif inst.nombre == "Zelle":
            inst.saldo_inicial = Decimal("1000.00")
        elif inst.nombre == "Bancamiga (Bs)":
            inst.saldo_inicial = Decimal("20000.00")

    admin_user = bd.query(Usuario).filter(Usuario.correo == "direccion@alfaimportaciones.com").first()
    enc1 = Usuario(
        nombre="Encargado Sede 1",
        usuario="encargado_sede1",
        correo="enc1@alfa.test",
        clave_hash=generar_hash_clave("Clave123!"),
        rol=RolUsuario.ENCARGADO_TIENDA.value,
        sucursal_id=sede1.id,
        tiene_acceso=True,
        activo=True,
    )
    enc2 = Usuario(
        nombre="Encargado Sede 2",
        usuario="encargado_sede2",
        correo="enc2@alfa.test",
        clave_hash=generar_hash_clave("Clave123!"),
        rol=RolUsuario.ENCARGADO_TIENDA.value,
        sucursal_id=sede2.id,
        tiene_acceso=True,
        activo=True,
    )
    director = Usuario(
        nombre="Director Ejecutivo",
        usuario="director_cierre",
        correo="director@alfa.test",
        clave_hash=generar_hash_clave("Clave123!"),
        rol=RolUsuario.DIRECTOR.value,
        sucursal_id=None,
        tiene_acceso=True,
        activo=True,
    )
    bd.add_all([enc1, enc2, director])
    bd.commit()
    for u in (admin_user, enc1, enc2, director):
        bd.refresh(u)

    tokens = {
        "ADMIN": crear_token_acceso(admin_user),
        "ENC1": crear_token_acceso(enc1),
        "ENC2": crear_token_acceso(enc2),
        "DIRECTOR": crear_token_acceso(director),
    }
    ids = {
        "alm_id": alm.id,
        "sede1_id": sede1.id,
        "sede2_id": sede2.id,
        "enc1_id": enc1.id,
        "enc2_id": enc2.id,
    }
    bd.close()

    def _override_bd():
        s = Sesion()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[obtener_bd] = _override_bd
    with TestClient(app) as client:
        yield client, Sesion, tokens, ids
    app.dependency_overrides.clear()


def test_cierres_diarios_tienda_vs_general_rbac_y_cuadre_saldos(entorno):
    client, Sesion, tokens, ids = entorno
    h_admin = {"Authorization": f"Bearer {tokens['ADMIN']}"}
    h_enc1 = {"Authorization": f"Bearer {tokens['ENC1']}"}
    h_enc2 = {"Authorization": f"Bearer {tokens['ENC2']}"}
    h_dir = {"Authorization": f"Bearer {tokens['DIRECTOR']}"}

    hoy = obtener_fecha_hoy()
    alm_id = ids["alm_id"]
    sede1_id = ids["sede1_id"]
    sede2_id = ids["sede2_id"]

    # 1. Confirmar tasas del día (BCV=100, USDT=120, Recargo=20%)
    r_tasa = client.post(
        "/api/tasas",
        headers=h_admin,
        json={
            "fecha": hoy.isoformat(),
            "tasa_bcv": 100.0,
            "tasa_usdt": 120.0,
            "recargo_porcentaje": 20.0,
            "recargo_confirmado": True,
        },
    )
    assert r_tasa.status_code in (200, 201), r_tasa.text

    # 2. Cargar equipos en ALM, SEDE-01 y SEDE-02
    r_cmp = client.post(
        "/api/logistica/compras",
        headers=h_admin,
        json={
            "origen": "NACIONAL",
            "fecha": hoy.isoformat(),
            "llega_preparada": True,
            "equipos": [
                {"serial": "CD-S1-1", "modelo": "Dell Latitude 5420", "ubicacion_id": sede1_id, "costo_compra_usd": 200.0, "precio_promo_usd": 300.0},
                {"serial": "CD-S2-1", "modelo": "HP EliteBook 840", "ubicacion_id": sede2_id, "costo_compra_usd": 220.0, "precio_promo_usd": 350.0},
                {"serial": "CD-S2-2", "modelo": "Lenovo ThinkPad T14", "ubicacion_id": sede2_id, "costo_compra_usd": 250.0, "precio_promo_usd": 400.0},
                {"serial": "CD-TR-1", "modelo": "MacBook Air M1", "ubicacion_id": alm_id, "costo_compra_usd": 450.0, "precio_promo_usd": 650.0},
            ],
        },
    )
    assert r_cmp.status_code == 201, r_cmp.text

    eqs = {
        e["serial"]: e
        for e in client.get("/api/logistica/inventario/equipos?busqueda=CD-", headers=h_admin).json()
    }
    insts = {
        i["nombre"]: i
        for i in client.get("/api/finanzas/instrumentos", headers=h_admin).json()
    }

    # 3. Venta en SEDE-01 ($300 Promo): $200 Efectivo divisas + $100 Zelle
    r_v1 = client.post(
        "/api/ventas",
        headers=h_admin,
        json={
            "sucursal_id": sede1_id,
            "asesor_id": ids["enc1_id"],
            "canal_visita": "Tienda",
            "origen_venta": "PASILLO",
            "entrega": "Tienda",
            "sin_cargador": True, "items": [{"equipo_id": eqs["CD-S1-1"]["id"], "cantidad": 1}],
            "pagos": [
                {"instrumento_id": insts["Efectivo divisas"]["id"], "monto_moneda_origen": 200.0},
                {"instrumento_id": insts["Zelle"]["id"], "monto_moneda_origen": 100.0, "referencia": "ZEL-S1"},
            ],
        },
    )
    assert r_v1.status_code == 201, r_v1.text

    # 4. Ventas en SEDE-02:
    #    - Venta 2a ($350 Promo -> Regular $420 = Bs 42,000) pagada con Bancamiga (Bs)
    #    - Venta 2b ($400 Promo -> Regular $480) pagada con Cashea (Inicial $180 Efectivo + Financiado $300 = Bs 30,000)
    r_v2a = client.post(
        "/api/ventas",
        headers=h_admin,
        json={
            "sucursal_id": sede2_id,
            "asesor_id": ids["enc2_id"],
            "canal_visita": "Instagram",
            "origen_venta": "LEAD",
            "entrega": "Tienda",
            "sin_cargador": True, "items": [{"equipo_id": eqs["CD-S2-1"]["id"], "cantidad": 1}],
            "pagos": [
                {"instrumento_id": insts["Bancamiga (Bs)"]["id"], "monto_moneda_origen": 42000.0, "referencia": "BM-S2"},
            ],
        },
    )
    assert r_v2a.status_code == 201, r_v2a.text

    r_v2b = client.post(
        "/api/ventas",
        headers=h_admin,
        json={
            "sucursal_id": sede2_id,
            "asesor_id": ids["enc2_id"],
            "canal_visita": "Tienda",
            "origen_venta": "PASILLO",
            "entrega": "Tienda",
            "sin_cargador": True, "items": [{"equipo_id": eqs["CD-S2-2"]["id"], "cantidad": 1}],
            "pagos": [
                {"instrumento_id": insts["Efectivo divisas"]["id"], "monto_moneda_origen": 180.0},
                {"instrumento_id": insts["Cashea · financiado"]["id"], "monto_moneda_origen": 30000.0, "referencia": "CSH-S2"},
            ],
        },
    )
    assert r_v2b.status_code == 201, r_v2b.text

    # 5. Traslado recibido en SEDE-01 (ALM -> SEDE-01)
    r_tr = client.post(
        "/api/logistica/traslados",
        headers=h_admin,
        json={
            "origen_id": alm_id,
            "destino_id": sede1_id,
            "equipos_ids": [eqs["CD-TR-1"]["id"]],
            "nota": "Reposición Sede 1",
        },
    )
    assert r_tr.status_code == 201, r_tr.text
    tr_id = r_tr.json()["id"]
    r_tr_rec = client.post(
        f"/api/logistica/traslados/{tr_id}/confirmar",
        headers=h_enc1,
        json={"nota_recepcion": "Recibido conforme en Sede 1"},
    )
    assert r_tr_rec.status_code == 200, r_tr_rec.text

    # 6. Garantía recibida en SEDE-02
    r_gar = client.post(
        "/api/taller/casos",
        headers=h_enc2,
        json={
            "tipo": "GARANTIA",
            "sucursal_id": sede2_id,
            "serial_o_codigo": "CD-S2-1",
            "descripcion_equipo": "HP EliteBook 840",
            "falla_reportada": "Pantalla parpadea",
        },
    )
    assert r_gar.status_code == 201, r_gar.text

    # 7. Gasto operativo / envío ($25 Efectivo) y pago administrativo ($150 Zelle) desde ADMIN-GEN (sin venta_id)
    bd = Sesion()
    bd.add_all(
        [
            Pago(
                venta_id=None,
                instrumento_id=insts["Efectivo divisas"]["id"],
                fecha=hoy,
                tipo_movimiento=TipoMovimientoPago.EGRESO.value,
                tipo_documento=TipoDocumentoPago.GASTO.value,
                monto_moneda_origen=Decimal("25.00"),
                moneda="USD",
                tasa_bcv_dia=Decimal("100.0000"),
                tasa_usdt_dia=Decimal("120.0000"),
                usd_nominal=Decimal("25.00"),
                usd_real=Decimal("25.00"),
                referencia="ENV-001",
                estado_verificacion=EstadoVerificacionPago.CONFIRMADO.value,
                categoria="Envío Delivery",
                origen_tipo="FACTURA_GASTO",
                nota="Delivery motorizado pedidos del día",
            ),
            Pago(
                venta_id=None,
                instrumento_id=insts["Zelle"]["id"],
                fecha=hoy,
                tipo_movimiento=TipoMovimientoPago.EGRESO.value,
                tipo_documento=TipoDocumentoPago.GASTO.value,
                monto_moneda_origen=Decimal("150.00"),
                moneda="USD",
                tasa_bcv_dia=Decimal("100.0000"),
                tasa_usdt_dia=Decimal("120.0000"),
                usd_nominal=Decimal("150.00"),
                usd_real=Decimal("150.00"),
                referencia="ADM-001",
                estado_verificacion=EstadoVerificacionPago.CONFIRMADO.value,
                categoria="Alquiler Oficina",
                origen_tipo="FACTURA_GASTO",
                nota="Pago administrativo sede central",
            ),
        ]
    )
    bd.commit()
    bd.close()

    # --- ASERCIONES OBLIGATORIAS ---

    # A. ENCARGADO de SEDE-01: solo SEDE-01, 403 en SEDE-02 y en GENERAL
    r_e1_ok = client.get(f"/api/cierre-diario?fecha={hoy.isoformat()}", headers=h_enc1)
    assert r_e1_ok.status_code == 200, r_e1_ok.text
    d_e1 = r_e1_ok.json()
    assert d_e1["alcance"] == "TIENDA"
    assert d_e1["jornada"]["sucursal_id"] == sede1_id
    assert d_e1["ventas_dia"]["cantidad_total"] == 1
    assert d_e1["recibido_por_instrumento"]["total_usd"] == 300.0
    assert d_e1["saldos_cajas"] is None
    assert d_e1["egresos_dia"] is None
    assert "LOCAL T38" in d_e1["mensaje_whatsapp"].upper()
    assert "ADMINISTRACIÓN GENERAL" not in d_e1["mensaje_whatsapp"].upper()

    assert client.get(f"/api/cierre-diario?fecha={hoy.isoformat()}&sucursal_id={sede2_id}", headers=h_enc1).status_code == 403
    assert client.get(f"/api/cierre-diario?fecha={hoy.isoformat()}&alcance=GENERAL", headers=h_enc1).status_code == 403

    # B. ENCARGADO de SEDE-02: solo SEDE-02, 403 en SEDE-01 y en GENERAL
    r_e2_ok = client.get(f"/api/cierre-diario?fecha={hoy.isoformat()}", headers=h_enc2)
    assert r_e2_ok.status_code == 200, r_e2_ok.text
    d_e2 = r_e2_ok.json()
    assert d_e2["alcance"] == "TIENDA"
    assert d_e2["jornada"]["sucursal_id"] == sede2_id
    assert d_e2["ventas_dia"]["cantidad_total"] == 2
    assert d_e2["ventas_dia"]["cashea_cantidad"] == 1
    assert len(d_e2["garantias_casos"]["recibidas_hoy"]) == 1
    assert d_e2["saldos_cajas"] is None
    assert "LOCAL V30-V31" in d_e2["mensaje_whatsapp"].upper()

    assert client.get(f"/api/cierre-diario?fecha={hoy.isoformat()}&sucursal_id={sede1_id}", headers=h_enc2).status_code == 403
    assert client.get(f"/api/cierre-diario?fecha={hoy.isoformat()}&alcance=GENERAL", headers=h_enc2).status_code == 403

    # C. DIRECTOR: puede ver SEDE-01, SEDE-02 y GENERAL, pero NO puede guardar cierre (403)
    assert client.get(f"/api/cierre-diario?fecha={hoy.isoformat()}&alcance=GENERAL", headers=h_dir).status_code == 200
    assert client.post(
        "/api/cierre-diario/cerrar",
        headers=h_dir,
        json={"fecha": hoy.isoformat(), "sucursal_id": sede1_id, "encargado_tienda_id": ids["enc1_id"]},
    ).status_code == 403

    # D. ADMIN consulta SEDE-01, SEDE-02 y GENERAL -> Cuadre exacto
    d_adm_s1 = client.get(f"/api/cierre-diario?fecha={hoy.isoformat()}&alcance=TIENDA&sucursal_id={sede1_id}", headers=h_admin).json()
    d_adm_s2 = client.get(f"/api/cierre-diario?fecha={hoy.isoformat()}&alcance=TIENDA&sucursal_id={sede2_id}", headers=h_admin).json()
    d_gen = client.get(f"/api/cierre-diario?fecha={hoy.isoformat()}&alcance=GENERAL", headers=h_admin).json()

    assert d_gen["alcance"] == "GENERAL"
    assert d_gen["ventas_dia"]["cantidad_total"] == d_adm_s1["ventas_dia"]["cantidad_total"] + d_adm_s2["ventas_dia"]["cantidad_total"] == 3

    # Total General Ingresos == SEDE-01 + SEDE-02 + ADMIN-GEN
    comp = {c["nombre"]: c for c in d_gen["comparativa_tiendas"]}
    ing_s1 = comp["Local T38"]["ingresos_usd"]
    ing_s2 = comp["Local V30-V31"]["ingresos_usd"]
    ing_adm = comp["Administración General"]["ingresos_usd"]
    assert round(ing_s1 + ing_s2 + ing_adm, 2) == round(d_gen["resumen_financiero"]["ingresos_totales_usd"], 2)
    assert round(ing_s1, 2) == round(d_adm_s1["recibido_por_instrumento"]["total_usd"], 2)
    assert round(ing_s2, 2) == round(d_adm_s2["recibido_por_instrumento"]["total_usd"], 2)

    # Egresos totales == $25 (envío) + $150 (gasto operativo) = $175
    assert d_gen["resumen_financiero"]["egresos_totales_usd"] == 175.0
    assert d_gen["egresos_dia"]["envios_delivery_usd"] == 25.0
    assert d_gen["egresos_dia"]["gastos_operativos_usd"] == 150.0
    assert round(
        d_gen["resumen_financiero"]["ingresos_totales_usd"] - d_gen["resumen_financiero"]["egresos_totales_usd"], 2
    ) == round(d_gen["resumen_financiero"]["flujo_neto_usd"], 2)

    # Cada caja/banco cuadra exactamente: saldo_inicial + entradas - salidas == saldo_final
    assert len(d_gen["saldos_cajas"]) > 0
    for caja in d_gen["saldos_cajas"]:
        assert round(caja["saldo_inicial"] + caja["entradas"] - caja["salidas"], 2) == round(caja["saldo_final"], 2), caja
        assert round(caja["saldo_inicial_usd"] + caja["entradas_usd"] - caja["salidas_usd"], 2) == round(caja["saldo_final_usd"], 2), caja

    # Verificar saldos concretos de Efectivo divisas, Zelle y Bancamiga (Bs)
    cajas_map = {c["nombre"]: c for c in d_gen["saldos_cajas"]}
    # Efectivo divisas: 500 + (200 + 180) - 25 = 855.00
    assert cajas_map["Efectivo divisas"]["saldo_inicial"] == 500.0
    assert cajas_map["Efectivo divisas"]["entradas"] == 380.0
    assert cajas_map["Efectivo divisas"]["salidas"] == 25.0
    assert cajas_map["Efectivo divisas"]["saldo_final"] == 855.0
    # Zelle: 1000 + 100 - 150 = 950.00
    assert cajas_map["Zelle"]["saldo_inicial"] == 1000.0
    assert cajas_map["Zelle"]["entradas"] == 100.0
    assert cajas_map["Zelle"]["salidas"] == 150.0
    assert cajas_map["Zelle"]["saldo_final"] == 950.0
    # Bancamiga (Bs): 20000 + 42000 - 0 = 62000.00 Bs (620.00 USD a BCV 100)
    assert cajas_map["Bancamiga (Bs)"]["saldo_inicial"] == 20000.0
    assert cajas_map["Bancamiga (Bs)"]["entradas"] == 42000.0
    assert cajas_map["Bancamiga (Bs)"]["saldo_final"] == 62000.0
    assert cajas_map["Bancamiga (Bs)"]["saldo_final_usd"] == 620.0

    # Operación general: 1 traslado despachado/recibido + 1 venta Cashea
    assert d_gen["operacion_general"]["traslados_recibidos_hoy"] == 1
    assert d_gen["operacion_general"]["cashea_dia"]["cantidad"] == 1
    assert "ADMINISTRACIÓN GENERAL" in d_gen["mensaje_whatsapp"].upper()
    assert "LIQUIDEZ TOTAL DISPONIBLE" in d_gen["mensaje_whatsapp"].upper()
