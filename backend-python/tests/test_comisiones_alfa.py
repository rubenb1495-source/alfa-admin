from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.rutas.tasas import obtener_fecha_hoy
from app.semilla import ejecutar_semilla
from app.semilla_finanzas import ejecutar_semilla_finanzas


@pytest.fixture()
def cliente() -> TestClient:
    motor_pruebas = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SesionPruebas = sessionmaker(autocommit=False, autoflush=False, bind=motor_pruebas)
    Base.metadata.create_all(bind=motor_pruebas)

    bd_seed = SesionPruebas()
    try:
        ejecutar_semilla(bd_seed)
        ejecutar_semilla_finanzas(bd_seed)
    finally:
        bd_seed.close()

    def obtener_bd_prueba():
        bd = SesionPruebas()
        try:
            yield bd
        finally:
            bd.close()

    app.dependency_overrides[obtener_bd] = obtener_bd_prueba
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _login(cliente: TestClient, correo: str, clave: str) -> tuple[dict[str, str], dict]:
    resp = cliente.post("/api/auth/login", json={"correo": correo, "clave": clave})
    assert resp.status_code == 200, resp.text
    datos = resp.json()
    return {"Authorization": f"Bearer {datos['token']}"}, datos["usuario"]


def _crear_usuario(
    cliente: TestClient,
    cab_dir: dict[str, str],
    nombre: str,
    correo: str,
    rol: str,
    sucursal_id: int,
) -> dict:
    resp = cliente.post(
        "/api/usuarios",
        headers=cab_dir,
        json={
            "nombre": nombre,
            "correo": correo,
            "clave": "ClaveSegura123!",
            "rol": rol,
            "sucursal_id": sucursal_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_comisiones_alfa_cuatro_escenarios_y_exclusiones(cliente: TestClient) -> None:
    """
    Valida las reglas de comisiones de Alfa Importaciones estrictamente sobre Precio Promo USD:
    - ASESORA en PASILLO -> 1%
    - ASESORA en LEAD -> 8%
    - ENCARGADO_TIENDA en PASILLO -> 5%
    - ENCARGADO_TIENDA en LEAD -> 8%
    - Tienda (asesor_id=None) -> 0%
    - Ventas ANULADA excluidas del cálculo
    - Incluso cuando el cliente paga en Bs a Precio Regular (recargo 30%), la base es Precio Promo USD.
    """
    cab_dir, _ = _login(cliente, "direccion@alfaimportaciones.com", "Alfa2026!")
    hoy = obtener_fecha_hoy()

    sucs = {s["nombre"]: s["id"] for s in cliente.get("/api/sucursales", headers=cab_dir).json()}
    t38_id = sucs["Local T38"]

    # 1. Crear usuarios ASESORA y ENCARGADO_TIENDA
    asesora = _crear_usuario(
        cliente, cab_dir, "María Asesora", "maria@alfaimportaciones.com", "ASESORA", t38_id
    )
    encargado = _crear_usuario(
        cliente,
        cab_dir,
        "Carlos Encargado",
        "carlos@alfaimportaciones.com",
        "ENCARGADO_TIENDA",
        t38_id,
    )

    # Verificar que ENCARGADO_TIENDA aparece en /api/usuarios/operativos con es_encargado=True
    resp_ops = cliente.get("/api/usuarios/operativos", headers=cab_dir)
    assert resp_ops.status_code == 200, resp_ops.text
    enc_op = next((u for u in resp_ops.json() if u["id"] == encargado["id"]), None)
    assert enc_op is not None
    assert enc_op["rol"] == "ENCARGADO_TIENDA"
    assert enc_op["es_encargado"] is True

    # 2. Registrar tasa del día con 30% de recargo (BCV=100, USDT=130)
    resp_tasa = cliente.post(
        "/api/tasas",
        headers=cab_dir,
        json={
            "fecha": hoy.isoformat(),
            "tasa_bcv": 100.0,
            "tasa_usdt": 130.0,
            "recargo_porcentaje": 30.0,
            "origen": "MANUAL",
        },
    )
    assert resp_tasa.status_code in (200, 201), resp_tasa.text

    # 3. Ingresar 6 equipos LISTO en Local T38 con precios promo conocidos
    equipos_compra = [
        ("ALFA-COM-1", "Laptop Dell 1", 200.0),
        ("ALFA-COM-2", "Laptop Dell 2", 300.0),
        ("ALFA-COM-3", "Laptop HP 1", 400.0),
        ("ALFA-COM-4", "Laptop HP 2", 500.0),
        ("ALFA-COM-5", "Laptop Lenovo 1", 200.0),
        ("ALFA-COM-6", "Laptop Lenovo 2", 100.0),
    ]
    resp_compra = cliente.post(
        "/api/logistica/compras",
        headers=cab_dir,
        json={
            "origen": "NACIONAL",
            "fecha": hoy.isoformat(),
            "llega_preparada": True,
            "equipos": [
                {
                    "serial": serial,
                    "modelo": modelo,
                    "ubicacion_id": t38_id,
                    "costo_compra_usd": promo * 0.7,
                    "precio_promo_usd": promo,
                }
                for serial, modelo, promo in equipos_compra
            ],
        },
    )
    assert resp_compra.status_code in (200, 201), resp_compra.text

    equipos_inv = {
        e["serial"]: e
        for e in cliente.get("/api/logistica/inventario/equipos?busqueda=ALFA-COM-", headers=cab_dir).json()
    }
    assert len(equipos_inv) == 6

    # Obtener instrumentos: Efectivo divisas (USD Promo) y Pago móvil Mercantil (Bs Regular)
    insts = cliente.get("/api/finanzas/instrumentos", headers=cab_dir).json()
    inst_usd = next(i for i in insts if i["moneda"] == "USD" and i["tipo_precio"] == "PROMO")
    inst_bs = next(i for i in insts if i["moneda"] == "BS")

    def crear_venta_equipo(
        serial: str,
        promo_usd: float,
        asesor_id: int | None,
        origen_venta: str,
        pagar_en_bs: bool = False,
    ) -> dict:
        eq = equipos_inv[serial]
        if pagar_en_bs:
            # Precio regular = promo * 1.30; en Bs = regular * 100 (BCV)
            monto_bs = promo_usd * 1.30 * 100.0
            pagos = [{"instrumento_id": inst_bs["id"], "monto_moneda_origen": monto_bs, "referencia": f"REF-{serial}"}]
        else:
            pagos = [{"instrumento_id": inst_usd["id"], "monto_moneda_origen": promo_usd}]

        resp = cliente.post(
            "/api/ventas",
            headers=cab_dir,
            json={
                "sucursal_id": t38_id,
                "asesor_id": asesor_id,
                "canal_visita": "WhatsApp" if origen_venta == "LEAD" else "Tienda",
                "origen_venta": origen_venta,
                "entrega": "Tienda",
                "items": [{"equipo_id": eq["id"], "cantidad": 1}],
                "pagos": pagos,
            },
        )
        assert resp.status_code == 201, resp.text
        v = resp.json()
        assert v["origen_venta"] == origen_venta
        return v

    # Escenario 1: ASESORA en PASILLO ($200 Promo, pagado en Bs a $260 Regular) -> 1% de $200 = $2.00
    crear_venta_equipo("ALFA-COM-1", 200.0, asesora["id"], "PASILLO", pagar_en_bs=True)

    # Escenario 2: ASESORA en LEAD ($300 Promo) -> 8% de $300 = $24.00
    crear_venta_equipo("ALFA-COM-2", 300.0, asesora["id"], "LEAD", pagar_en_bs=False)

    # Escenario 3: ENCARGADO_TIENDA en PASILLO ($400 Promo, pagado en Bs a $520 Regular) -> 5% de $400 = $20.00
    crear_venta_equipo("ALFA-COM-3", 400.0, encargado["id"], "PASILLO", pagar_en_bs=True)

    # Escenario 4: ENCARGADO_TIENDA en LEAD ($500 Promo) -> 8% de $500 = $40.00
    crear_venta_equipo("ALFA-COM-4", 500.0, encargado["id"], "LEAD", pagar_en_bs=False)

    # Escenario 5: Venta Tienda (asesor_id=None) en LEAD ($200 Promo) -> 0%
    crear_venta_equipo("ALFA-COM-5", 200.0, None, "LEAD", pagar_en_bs=False)

    # Escenario 6: Venta de ASESORA en LEAD ($100 Promo) luego ANULADA -> no debe sumar comisión
    venta_anular = crear_venta_equipo("ALFA-COM-6", 100.0, asesora["id"], "LEAD", pagar_en_bs=False)
    resp_anular = cliente.post(
        f"/api/ventas/{venta_anular['id']}/anular",
        headers=cab_dir,
        json={"motivo": "Cliente canceló pedido en prueba"},
    )
    assert resp_anular.status_code == 200, resp_anular.text

    # Consultar reporte de comisiones del mes actual
    resp_com = cliente.get(
        f"/api/finanzas/comisiones?mes={hoy.month}&anio={hoy.year}",
        headers=cab_dir,
    )
    assert resp_com.status_code == 200, resp_com.text
    comisiones = {c["usuario_id"]: c for c in resp_com.json()["comisiones"]}

    # Validar ASESORA: Pasillo $200 * 1% = $2.00 | Lead $300 * 8% = $24.00 | Total = $26.00
    com_as = comisiones[asesora["id"]]
    assert com_as["ventas_pasillo_usd"] == pytest.approx(200.0)
    assert com_as["porcentaje_pasillo"] == 1
    assert com_as["comision_pasillo_usd"] == pytest.approx(2.0)
    assert com_as["ventas_leads_usd"] == pytest.approx(300.0)
    assert com_as["porcentaje_leads"] == 8
    assert com_as["comision_leads_usd"] == pytest.approx(24.0)
    assert com_as["total_comision_usd"] == pytest.approx(26.0)

    # Validar ENCARGADO_TIENDA: Pasillo $400 * 5% = $20.00 | Lead $500 * 8% = $40.00 | Total = $60.00
    com_enc = comisiones[encargado["id"]]
    assert com_enc["ventas_pasillo_usd"] == pytest.approx(400.0)
    assert com_enc["porcentaje_pasillo"] == 5
    assert com_enc["comision_pasillo_usd"] == pytest.approx(20.0)
    assert com_enc["ventas_leads_usd"] == pytest.approx(500.0)
    assert com_enc["porcentaje_leads"] == 8
    assert com_enc["comision_leads_usd"] == pytest.approx(40.0)
    assert com_enc["total_comision_usd"] == pytest.approx(60.0)
