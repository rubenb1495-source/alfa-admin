from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import CatalogoArticulo, CatalogoPrecio, RolUsuario, Sucursal, TipoArticulo, Usuario
from app.modelos_finanzas import InstrumentoFinanciero, MonedaInstrumento
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import generar_hash_clave
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

    suc = bd.query(Sucursal).filter(Sucursal.nombre == "Local T38").first()
    enc = Usuario(
        nombre="Encargado Prueba T38",
        correo="encargado.test@alfadigitalstore.com",
        clave_hash=generar_hash_clave("Encargado2026!"),
        rol=RolUsuario.ENCARGADO_TIENDA.value,
        sucursal_id=suc.id,
        activo=True,
    )
    tec = Usuario(
        nombre="Técnico Prueba Alfa",
        correo="tecnico.test@alfadigitalstore.com",
        clave_hash=generar_hash_clave("Tecnico2026!"),
        rol=RolUsuario.TECNICO.value,
        sucursal_id=suc.id,
        telefono="04141112233",
        activo=True,
    )
    bd.add_all([enc, tec])
    bd.commit()
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


def _login(client: TestClient, correo: str, clave: str) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"correo": correo, "clave": clave})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_recepcion_garantia_servicio_tecnico_pdf_y_cierre_diario(entorno):
    client, Sesion = entorno
    h_admin = _login(client, "direccion@alfaimportaciones.com", "Alfa2026!")
    h_enc = _login(client, "encargado.test@alfadigitalstore.com", "Encargado2026!")
    h_tec = _login(client, "tecnico.test@alfadigitalstore.com", "Tecnico2026!")
    hoy_str = obtener_fecha_hoy().isoformat()

    # Preparar tasa, equipo y 1 venta para respaldar la garantía
    r_tasa = client.post(
        "/api/tasas/hoy/confirmar",
        headers=h_admin,
        json={"tasa_bcv": 52.0, "tasa_usdt": 53.5, "porcentaje_recargo": 20.0},
    )
    assert r_tasa.status_code == 200, r_tasa.text

    bd = Sesion()
    suc = bd.query(Sucursal).filter(Sucursal.nombre == "Local T38").first()
    tec = bd.query(Usuario).filter(Usuario.correo == "tecnico.test@alfadigitalstore.com").first()
    inst_usd = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.moneda == MonedaInstrumento.USD.value).first()
    suc_id, tec_id, inst_id = suc.id, tec.id, inst_usd.id
    bd.close()

    art = client.post(
        "/api/catalogo",
        headers=h_admin,
        json={
            "sku": "REC-LAP-01",
            "descripcion": "Laptop Alfa Pro 14",
            "tipo": "EQUIPO",
            "categoria": "Laptop",
            "costo_referencia_usd": 200.0,
            "precio_promo_usd": 380.0,
        },
    ).json()

    ing = client.post(
        "/api/logistica/ingresos",
        headers=h_admin,
        json={
            "tipo_ingreso": "COMPRA_NACIONAL",
            "proveedor_nombre": "Proveedor Demo",
            "almacen_destino_id": suc_id,
            "fecha": hoy_str,
            "items": [
                {
                    "tipo_item": "EQUIPO",
                    "sku": "REC-LAP-01",
                    "descripcion": "Laptop Alfa Pro 14",
                    "serial": "GAR-TEST-001",
                    "cantidad": 1,
                    "costo_unitario_usd": 200.0,
                    "precio_promo_usd": 380.0,
                    "estado_inicial": "DISPONIBLE",
                }
            ],
        },
    )
    assert ing.status_code == 201, ing.text

    eqs = client.get(f"/api/logistica/inventario/equipos?sucursal_id={suc_id}", headers=h_admin).json()
    eq = next(e for e in eqs if e["serial"] == "GAR-TEST-001")

    cli = client.post(
        "/api/clientes",
        headers=h_enc,
        json={
            "nombre": "María Pérez",
            "tipo_persona": "NATURAL",
            "tipo_documento": "V",
            "documento": "20123456",
            "telefono": "04129998877",
        },
    ).json()

    vta = client.post(
        "/api/ventas",
        headers=h_enc,
        json={
            "sucursal_id": suc_id,
            "cliente_id": cli["id"],
            "origen_venta": "PASILLO",
            "items": [{"articulo_id": art["id"], "equipo_id": eq["id"], "cantidad": 1}],
            "pagos": [{"instrumento_id": inst_id, "monto_moneda_origen": 380.0, "referencia": "EFE-1"}],
        },
    )
    assert vta.status_code == 201, vta.text
    vta_data = vta.json()

    # 1. Buscar nota de venta por serial
    busq = client.get("/api/recepcion-tecnica/buscar-ventas?q=GAR-TEST-001", headers=h_enc)
    assert busq.status_code == 200
    assert len(busq.json()) >= 1
    assert busq.json()[0]["numero_nota_venta"] == vta_data["numero_venta"]

    # Crear recepción de GARANTÍA por ENCARGADO y asignada al TECNICO
    r_gar = client.post(
        "/api/recepcion-tecnica",
        headers=h_enc,
        json={
            "tipo_orden": "GARANTIA",
            "sucursal_id": suc_id,
            "tecnico_asignado_id": tec_id,
            "enviar_a_tecnico": True,
            "venta_id": vta_data["id"],
            "equipo_id": eq["id"],
            "marca": "Alfa",
            "modelo": "Laptop Alfa Pro 14",
            "serial": "GAR-TEST-001",
            "especificaciones": "16GB RAM / 512GB SSD",
            "falla_declarada_cliente": "Parpadeo intermitente en pantalla",
            "accesorios_entregados": ["Cargador", "Cable de poder"],
            "detalles_esteticos": "Sin rayones visibles, carcasa en buen estado",
            "detalles_sistema_recepcion": "Enciende normal, entra a Windows",
            "equipo_llega_apagado": False,
        },
    )
    assert r_gar.status_code == 201, r_gar.text
    gar = r_gar.json()
    assert gar["codigo"].startswith("GAR-")
    assert gar["venta_id"] == vta_data["id"]
    assert gar["numero_nota_venta"] == vta_data["numero_venta"]
    assert gar["estado"] == "ENVIADO_A_TECNICO"
    assert gar["costo_revision_usd"] == 0.0

    # El TECNICO puede ver y actualizar su caso, pero NO entregarlo directamente
    r_tec_bad = client.patch(
        f"/api/recepcion-tecnica/{gar['id']}",
        headers=h_tec,
        json={"estado": "RESUELTO_ENTREGADO"},
    )
    assert r_tec_bad.status_code == 403

    r_tec_ok = client.patch(
        f"/api/recepcion-tecnica/{gar['id']}",
        headers=h_tec,
        json={
            "estado": "LISTO_PARA_ENTREGA",
            "diagnostico_tecnico": "Flex de pantalla flojo, reajustado y probado.",
            "solucion_aplicada": "Reconexión y prueba de estrés 2h",
        },
    )
    assert r_tec_ok.status_code == 200, r_tec_ok.text
    assert r_tec_ok.json()["estado"] == "LISTO_PARA_ENTREGA"

    # ENCARGADO marca la entrega final (RESUELTO_ENTREGADO)
    r_ent = client.patch(
        f"/api/recepcion-tecnica/{gar['id']}",
        headers=h_enc,
        json={"estado": "RESUELTO_ENTREGADO"},
    )
    assert r_ent.status_code == 200
    assert r_ent.json()["estado"] == "RESUELTO_ENTREGADO"

    # 2. Recepción de SERVICIO_TECNICO sin Nota de Venta, equipo apagado, costo $10 y exoneración al aprobar
    r_st = client.post(
        "/api/recepcion-tecnica",
        headers=h_enc,
        json={
            "tipo_orden": "SERVICIO_TECNICO",
            "sucursal_id": suc_id,
            "tecnico_asignado_id": tec_id,
            "cliente_nombre": "Carlos Gómez",
            "cliente_documento": "V-18999888",
            "cliente_telefono": "04148887766",
            "marca": "HP",
            "modelo": "Pavilion 15",
            "serial": "HP-EXT-999",
            "especificaciones": "8GB RAM / 256GB SSD",
            "falla_declarada_cliente": "No enciende tras bajón eléctrico",
            "accesorios_entregados": ["Cargador", "Bolso/Funda"],
            "detalles_esteticos": "Rayón leve en tapa superior",
            "detalles_sistema_recepcion": "APAGADO - No da señal de carga ni video",
            "equipo_llega_apagado": True,
            "condiciones_aceptadas": True,
        },
    )
    assert r_st.status_code == 201, r_st.text
    st = r_st.json()
    assert st["codigo"].startswith("ST-")
    assert st["venta_id"] is None
    assert st["numero_nota_venta"] is None
    assert st["equipo_llega_apagado"] is True
    assert st["costo_revision_usd"] == 10.0
    assert st["costo_revision_efectivo_usd"] == 10.0

    # Aprobar reparación -> exonera automáticamente el costo de revisión ($10 -> $0)
    r_apr = client.patch(
        f"/api/recepcion-tecnica/{st['id']}",
        headers=h_enc,
        json={"reparacion_aprobada": True, "estado": "EN_REPARACION"},
    )
    assert r_apr.status_code == 200, r_apr.text
    assert r_apr.json()["reparacion_aprobada"] is True
    assert r_apr.json()["costo_revision_usd"] == 0.0
    assert r_apr.json()["costo_revision_efectivo_usd"] == 0.0

    # 3. Generación exitosa de PDF para ambos tipos de orden
    pdf_gar = client.get(f"/api/recepcion-tecnica/{gar['id']}/pdf", headers=h_enc)
    assert pdf_gar.status_code == 200
    assert pdf_gar.headers["content-type"].startswith("application/pdf")
    assert pdf_gar.content.startswith(b"%PDF-")
    assert len(pdf_gar.content) > 1500

    pdf_st = client.get(f"/api/recepcion-tecnica/{st['id']}/pdf", headers=h_enc)
    assert pdf_st.status_code == 200
    assert pdf_st.headers["content-type"].startswith("application/pdf")
    assert pdf_st.content.startswith(b"%PDF-")
    assert len(pdf_st.content) > 1500

    # 4. Aparición en Cierre Diario de Tienda
    cierre = client.get(f"/api/cierre-diario?fecha={hoy_str}&sucursal_id={suc_id}", headers=h_enc)
    assert cierre.status_code == 200, cierre.text
    g_cierre = cierre.json()["garantias_casos"]
    cods_rec = {x["numero_caso"] for x in g_cierre["recibidas_hoy"]}
    cods_res = {x["numero"] for x in g_cierre["resueltas_hoy"]}
    cods_pend = {x["numero_caso"] for x in g_cierre["pendientes"]["items"]}
    assert gar["codigo"] in cods_rec
    assert st["codigo"] in cods_rec
    assert gar["codigo"] in cods_res
    assert st["codigo"] in cods_pend
