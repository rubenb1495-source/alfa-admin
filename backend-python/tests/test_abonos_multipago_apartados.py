from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import RolUsuario, Sucursal, TasaDiaria, Usuario
from app.modelos_finanzas import (
    CuentaPorCobrar,
    EstadoCuentaPorCobrar,
    EstadoVenta,
    InstrumentoFinanciero,
    MonedaInstrumento,
    TipoCuentaPorCobrar,
    Venta,
)
from app.seguridad import generar_hash_clave
from app.semilla import ejecutar_semilla
from app.semilla_contabilidad import ejecutar_semilla_contabilidad
from app.semilla_finanzas import ejecutar_semilla_finanzas


def test_abonos_multipago_apartados_por_encargado_tienda() -> None:
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

    sucs = bd.query(Sucursal).order_by(Sucursal.id.asc()).all()
    suc_a = sucs[0]
    suc_b = sucs[1] if len(sucs) > 1 else sucs[0]

    encargado = Usuario(
        nombre="Encargado Sucursal A",
        usuario="encargado_a",
        correo="encargado_a@tekioelectronics.com",
        clave_hash=generar_hash_clave("Encargado2026!"),
        rol=RolUsuario.ENCARGADO_TIENDA.value,
        sucursal_id=suc_a.id,
        activo=True,
        debe_cambiar_clave=False,
    )
    bd.add(encargado)
    bd.flush()

    hoy = date.today()
    bd.add(TasaDiaria(fecha=hoy, tasa_bcv=Decimal("50.00"), tasa_usdt=Decimal("60.00"), recargo_porcentaje=Decimal("30.00")))

    v_a = Venta(
        numero_venta="N-0001",
        fecha=hoy,
        sucursal_id=suc_a.id,
        cliente_id=None,
        asesor_id=encargado.id,
        creado_por_id=encargado.id,
        total_regular_usd=Decimal("300.00"),
        estado=EstadoVenta.CON_SALDO.value,
    )
    v_b = Venta(
        numero_venta="N-0002",
        fecha=hoy,
        sucursal_id=suc_b.id,
        cliente_id=None,
        asesor_id=encargado.id,
        creado_por_id=encargado.id,
        total_regular_usd=Decimal("200.00"),
        estado=EstadoVenta.CON_SALDO.value,
    )
    bd.add_all([v_a, v_b])
    bd.flush()

    cxc_a = CuentaPorCobrar(
        venta_id=v_a.id,
        cliente_id=None,
        tipo=TipoCuentaPorCobrar.CLIENTE.value,
        monto_original_usd=Decimal("200.00"),
        saldo_pendiente_usd=Decimal("200.00"),
        estado=EstadoCuentaPorCobrar.PENDIENTE.value,
    )
    cxc_b = CuentaPorCobrar(
        venta_id=v_b.id,
        cliente_id=None,
        tipo=TipoCuentaPorCobrar.CLIENTE.value,
        monto_original_usd=Decimal("150.00"),
        saldo_pendiente_usd=Decimal("150.00"),
        estado=EstadoCuentaPorCobrar.PENDIENTE.value,
    )
    bd.add_all([cxc_a, cxc_b])

    inst_usd = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.moneda == MonedaInstrumento.USD.value).first()
    inst_bs = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.moneda == MonedaInstrumento.BS.value).first()
    assert inst_usd is not None and inst_bs is not None

    bd.commit()
    suc_a_id, suc_b_id = suc_a.id, suc_b.id
    cxc_a_id, cxc_b_id = cxc_a.id, cxc_b.id
    inst_usd_id, inst_bs_id = inst_usd.id, inst_bs.id
    bd.close()

    def override_bd():
        s = Sesion()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[obtener_bd] = override_bd
    try:
        client = TestClient(app)

        r_login = client.post(
            "/api/auth/login",
            json={"usuario": "encargado_a", "clave": "Encargado2026!"},
        )
        assert r_login.status_code == 200, r_login.text
        tok = r_login.json().get("access_token") or r_login.json().get("token")
        headers = {"Authorization": f"Bearer {tok}"}

        # 1. Encargado solo ve las CxC de su propia sucursal
        r_list = client.get("/api/finanzas/cuentas-por-cobrar?tipo=CLIENTE&estado=PENDIENTE", headers=headers)
        assert r_list.status_code == 200, r_list.text
        ids_visibles = [x["id"] for x in r_list.json()]
        assert cxc_a_id in ids_visibles
        if suc_a_id != suc_b_id:
            assert cxc_b_id not in ids_visibles
            # Intentar abonar CxC de otra sucursal -> 403
            r_forb = client.post(
                f"/api/finanzas/cuentas-por-cobrar/{cxc_b_id}/abono",
                headers=headers,
                json={"pagos": [{"instrumento_id": inst_usd_id, "monto_moneda_origen": 50.0, "referencia": "X"}]},
            )
            assert r_forb.status_code == 403

        # 2. Abono multipago parcial: $100 USD + Bs 2500 (=$50 USD a BCV 50) = $150 abonado -> resta $50
        r_ab1 = client.post(
            f"/api/finanzas/cuentas-por-cobrar/{cxc_a_id}/abono",
            headers=headers,
            json={
                "fecha": hoy.isoformat(),
                "pagos": [
                    {"instrumento_id": inst_usd_id, "monto_moneda_origen": 100.0, "referencia": "EFE-01"},
                    {"instrumento_id": inst_bs_id, "monto_moneda_origen": 2500.0, "referencia": "PM-8899"},
                ],
            },
        )
        assert r_ab1.status_code == 200, r_ab1.text
        d1 = r_ab1.json()
        assert d1["total_abonado_usd"] == 150.0
        assert d1["saldo_pendiente_usd"] == 50.0
        assert d1["liquidada"] is False
        assert len(d1["pagos_registrados"]) == 2

        # 3. Cancelación final del saldo restante ($50)
        r_ab2 = client.post(
            f"/api/finanzas/cuentas-por-cobrar/{cxc_a_id}/abono",
            headers=headers,
            json={
                "fecha": hoy.isoformat(),
                "pagos": [
                    {"instrumento_id": inst_usd_id, "monto_moneda_origen": 50.0, "referencia": "CIERRE-01"},
                ],
            },
        )
        assert r_ab2.status_code == 200, r_ab2.text
        d2 = r_ab2.json()
        assert d2["saldo_pendiente_usd"] == 0.0
        assert d2["estado"] == "PAGADA"
        assert d2["liquidada"] is True
    finally:
        app.dependency_overrides.clear()
