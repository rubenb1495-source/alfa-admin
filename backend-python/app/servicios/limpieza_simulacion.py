from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.modelos import CatalogoArticulo, CatalogoPrecio, Sucursal, Usuario
from app.modelos_admin import (
    AuditLog,
    FacturaGastoFiscal,
    Nomina,
    NominaDetalle,
    ObligacionLegal,
)
from app.modelos_contabilidad import (
    AsientoContable,
    AsientoDetalle,
    EquipoComponenteInstalado,
    PrestamoFinanciamiento,
    PrestamoPago,
)
from app.modelos_finanzas import (
    CierreDiario,
    CuentaPorCobrar,
    LiquidacionComision,
    MovimientoTesoreria,
    Pago,
    Venta,
    VentaDetalle,
)
from app.modelos_logistica import (
    Compra,
    CompraComponente,
    Equipo,
    GuiaImportacion,
    HistorialEstadoEquipo,
    MovimientoInventario,
    Tercero,
    Traslado,
    TrasladoDetalle,
)
from app.modelos_operaciones import DevolucionGarantia
from app.modelos_taller import (
    CasoPostventa,
    CasoPresupuesto,
    CasoRepuestoUsado,
    Preparacion,
    PreparacionComponente,
)

PREFIJO_SIM = "[SIM-ALFA]"


def limpiar_datos_simulacion(bd: Session, prefijo: str = PREFIJO_SIM) -> dict[str, Any]:
    """
    Elimina exclusivamente los registros etiquetados con `[SIM-ALFA]` en orden seguro
    de llaves foráneas, sin tocar ningún dato real de producción.
    """
    patron = f"%{prefijo}%"
    patron_cod = "%SIM-%"
    eliminados: dict[str, int] = {}

    def _contar_y_borrar(nombre: str, query) -> int:
        n = query.delete(synchronize_session=False)
        eliminados[nombre] = eliminados.get(nombre, 0) + int(n)
        return int(n)

    # 1. Identificar IDs base de la simulación
    ventas_sim_ids = [
        r[0]
        for r in bd.query(Venta.id)
        .filter(
            or_(
                Venta.nota.ilike(patron),
                Venta.numero_venta.ilike(patron_cod),
            )
        )
        .all()
    ]
    equipos_sim_ids = [
        r[0]
        for r in bd.query(Equipo.id)
        .filter(
            or_(
                Equipo.serial.ilike("SIM-%"),
                Equipo.serial.ilike(patron),
                Equipo.nota.ilike(patron),
                Equipo.consignante_nombre.ilike(patron),
            )
        )
        .all()
    ]
    articulos_sim_ids = [
        r[0]
        for r in bd.query(CatalogoArticulo.id)
        .filter(
            or_(
                CatalogoArticulo.sku.ilike("SIM-%"),
                CatalogoArticulo.descripcion.ilike(patron),
            )
        )
        .all()
    ]
    terceros_sim_ids = [
        r[0]
        for r in bd.query(Tercero.id)
        .filter(
            or_(
                Tercero.nombre.ilike(patron),
                Tercero.documento.ilike("SIM-%"),
            )
        )
        .all()
    ]
    usuarios_sim_ids = [
        r[0]
        for r in bd.query(Usuario.id)
        .filter(
            or_(
                Usuario.nombre.ilike(patron),
                Usuario.correo.ilike("%sim-alfa%"),
            )
        )
        .all()
    ]
    sucursales_sim_ids = [
        r[0]
        for r in bd.query(Sucursal.id)
        .filter(
            or_(
                Sucursal.nombre.ilike(patron),
                Sucursal.direccion.ilike(patron),
            )
        )
        .all()
    ]
    compras_sim_ids = [
        r[0]
        for r in bd.query(Compra.id)
        .filter(
            or_(
                Compra.nota.ilike(patron),
                Compra.numero_compra.ilike(patron_cod),
                Compra.proveedor_nombre.ilike(patron),
            )
        )
        .all()
    ]
    traslados_sim_ids = [
        r[0]
        for r in bd.query(Traslado.id)
        .filter(Traslado.nota.ilike(patron))
        .all()
    ]
    prestamos_sim_ids = [
        r[0]
        for r in bd.query(PrestamoFinanciamiento.id)
        .filter(
            or_(
                PrestamoFinanciamiento.codigo.ilike(patron_cod),
                PrestamoFinanciamiento.concepto.ilike(patron),
                PrestamoFinanciamiento.acreedor.ilike(patron),
            )
        )
        .all()
    ]
    gastos_sim_ids = [
        r[0]
        for r in bd.query(FacturaGastoFiscal.id)
        .filter(
            or_(
                FacturaGastoFiscal.observaciones.ilike(patron),
                FacturaGastoFiscal.razon_social.ilike(patron),
                FacturaGastoFiscal.numero_factura.ilike(patron_cod),
            )
        )
        .all()
    ]
    obligaciones_sim_ids = [
        r[0]
        for r in bd.query(ObligacionLegal.id)
        .filter(
            or_(
                ObligacionLegal.descripcion.ilike(patron),
                ObligacionLegal.referencia_pago.ilike(patron),
                ObligacionLegal.tipo_obligacion.ilike(patron),
            )
        )
        .all()
    ]
    nominas_sim_ids = [
        r[0]
        for r in bd.query(Nomina.id)
        .filter(
            or_(
                Nomina.observaciones.ilike(patron),
                Nomina.referencia_pago.ilike(patron),
            )
        )
        .all()
    ]
    liq_sim_ids = [
        r[0]
        for r in bd.query(LiquidacionComision.id)
        .filter(
            or_(
                LiquidacionComision.observaciones.ilike(patron),
                LiquidacionComision.referencia.ilike(patron),
                LiquidacionComision.personal_id.in_(usuarios_sim_ids) if usuarios_sim_ids else False,
            )
        )
        .all()
    ]
    casos_sim_ids = [
        r[0]
        for r in bd.query(CasoPostventa.id)
        .filter(
            or_(
                CasoPostventa.falla_reportada.ilike(patron),
                CasoPostventa.descripcion_equipo.ilike(patron),
                CasoPostventa.equipo_id.in_(equipos_sim_ids) if equipos_sim_ids else False,
            )
        )
        .all()
    ]

    # 2. Asientos contables generados por la simulación
    asientos_filtros = [AsientoContable.descripcion.ilike(patron)]
    if ventas_sim_ids:
        asientos_filtros.append(
            (AsientoContable.origen_tipo == "VENTA")
            & (AsientoContable.origen_id.in_([str(i) for i in ventas_sim_ids]))
        )
    if equipos_sim_ids:
        asientos_filtros.append(
            (AsientoContable.origen_tipo == "PREPARACION")
            & (AsientoContable.origen_id.in_([str(i) for i in equipos_sim_ids]))
        )
    if prestamos_sim_ids:
        asientos_filtros.append(
            (AsientoContable.origen_tipo.in_(["PRESTAMO", "PAGO_PRESTAMO"]))
            & (AsientoContable.origen_id.in_([str(i) for i in prestamos_sim_ids]))
        )
    if gastos_sim_ids:
        asientos_filtros.append(
            (AsientoContable.origen_tipo == "FACTURA_GASTO")
            & (AsientoContable.origen_id.in_([str(i) for i in gastos_sim_ids]))
        )
    if obligaciones_sim_ids:
        asientos_filtros.append(
            (AsientoContable.origen_tipo == "OBLIGACION_LEGAL")
            & (AsientoContable.origen_id.in_([str(i) for i in obligaciones_sim_ids]))
        )
    if nominas_sim_ids:
        asientos_filtros.append(
            (AsientoContable.origen_tipo == "NOMINA")
            & (AsientoContable.origen_id.in_([str(i) for i in nominas_sim_ids]))
        )
    if liq_sim_ids:
        asientos_filtros.append(
            (AsientoContable.origen_tipo == "LIQUIDACION_COMISION")
            & (AsientoContable.origen_id.in_([str(i) for i in liq_sim_ids]))
        )

    asientos_sim_ids = [
        r[0] for r in bd.query(AsientoContable.id).filter(or_(*asientos_filtros)).all()
    ]
    if asientos_sim_ids:
        _contar_y_borrar(
            "asientos_detalle",
            bd.query(AsientoDetalle).filter(AsientoDetalle.asiento_id.in_(asientos_sim_ids)),
        )
        _contar_y_borrar(
            "asientos_contables",
            bd.query(AsientoContable).filter(AsientoContable.id.in_(asientos_sim_ids)),
        )

    # 3. Cierres diarios de simulación
    _contar_y_borrar(
        "cierres_diarios",
        bd.query(CierreDiario).filter(CierreDiario.observaciones.ilike(patron)),
    )

    # 4. Casos de garantía / postventa y devoluciones
    if casos_sim_ids:
        _contar_y_borrar(
            "casos_presupuesto",
            bd.query(CasoPresupuesto).filter(CasoPresupuesto.caso_id.in_(casos_sim_ids)),
        )
        _contar_y_borrar(
            "casos_repuestos_usados",
            bd.query(CasoRepuestoUsado).filter(CasoRepuestoUsado.caso_id.in_(casos_sim_ids)),
        )
        _contar_y_borrar(
            "casos_postventa",
            bd.query(CasoPostventa).filter(CasoPostventa.id.in_(casos_sim_ids)),
        )
    if ventas_sim_ids:
        _contar_y_borrar(
            "devoluciones_garantias",
            bd.query(DevolucionGarantia).filter(DevolucionGarantia.venta_id.in_(ventas_sim_ids)),
        )

    # 5. Nóminas, Obligaciones, Gastos, Préstamos
    if nominas_sim_ids:
        _contar_y_borrar(
            "nomina_detalles",
            bd.query(NominaDetalle).filter(NominaDetalle.nomina_id.in_(nominas_sim_ids)),
        )
        _contar_y_borrar(
            "nominas",
            bd.query(Nomina).filter(Nomina.id.in_(nominas_sim_ids)),
        )
    if obligaciones_sim_ids:
        _contar_y_borrar(
            "obligaciones_legales",
            bd.query(ObligacionLegal).filter(ObligacionLegal.id.in_(obligaciones_sim_ids)),
        )
    if gastos_sim_ids:
        _contar_y_borrar(
            "facturas_gasto_fiscal",
            bd.query(FacturaGastoFiscal).filter(FacturaGastoFiscal.id.in_(gastos_sim_ids)),
        )
    if prestamos_sim_ids:
        _contar_y_borrar(
            "prestamos_pagos",
            bd.query(PrestamoPago).filter(PrestamoPago.prestamo_id.in_(prestamos_sim_ids)),
        )
        _contar_y_borrar(
            "prestamos_financiamiento",
            bd.query(PrestamoFinanciamiento).filter(PrestamoFinanciamiento.id.in_(prestamos_sim_ids)),
        )

    # 6. Tesorería y Pagos (CxC, Liquidaciones, Ventas, Patrimoniales)
    _contar_y_borrar(
        "movimientos_tesoreria",
        bd.query(MovimientoTesoreria).filter(
            or_(
                MovimientoTesoreria.observaciones.ilike(patron),
                MovimientoTesoreria.referencia.ilike(patron),
            )
        ),
    )

    if ventas_sim_ids:
        bd.query(Venta).filter(Venta.id.in_(ventas_sim_ids)).update(
            {Venta.liquidacion_id: None}, synchronize_session=False
        )
        _contar_y_borrar(
            "cuentas_por_cobrar",
            bd.query(CuentaPorCobrar).filter(CuentaPorCobrar.venta_id.in_(ventas_sim_ids)),
        )

    if liq_sim_ids:
        bd.query(LiquidacionComision).filter(LiquidacionComision.id.in_(liq_sim_ids)).update(
            {LiquidacionComision.movimiento_financiero_id: None}, synchronize_session=False
        )

    pagos_filtros = [
        Pago.nota.ilike(patron),
        Pago.referencia.ilike(patron),
    ]
    if ventas_sim_ids:
        pagos_filtros.append(Pago.venta_id.in_(ventas_sim_ids))
    if liq_sim_ids:
        pagos_filtros.append(
            (Pago.origen_tipo == "LIQUIDACION_COMISION") & (Pago.origen_id.in_(liq_sim_ids))
        )
    if gastos_sim_ids:
        pagos_filtros.append(
            (Pago.origen_tipo == "FACTURA_GASTO") & (Pago.origen_id.in_(gastos_sim_ids))
        )
    if obligaciones_sim_ids:
        pagos_filtros.append(
            (Pago.origen_tipo == "OBLIGACION_LEGAL") & (Pago.origen_id.in_(obligaciones_sim_ids))
        )
    if nominas_sim_ids:
        pagos_filtros.append(
            (Pago.origen_tipo == "NOMINA") & (Pago.origen_id.in_(nominas_sim_ids))
        )
    if prestamos_sim_ids:
        pagos_filtros.append(
            (Pago.origen_tipo.in_(["PRESTAMO", "PAGO_PRESTAMO"])) & (Pago.origen_id.in_(prestamos_sim_ids))
        )
    _contar_y_borrar("pagos", bd.query(Pago).filter(or_(*pagos_filtros)))

    if liq_sim_ids:
        _contar_y_borrar(
            "liquidaciones_comisiones",
            bd.query(LiquidacionComision).filter(LiquidacionComision.id.in_(liq_sim_ids)),
        )

    if ventas_sim_ids:
        _contar_y_borrar(
            "ventas_detalle",
            bd.query(VentaDetalle).filter(VentaDetalle.venta_id.in_(ventas_sim_ids)),
        )
        _contar_y_borrar(
            "ventas",
            bd.query(Venta).filter(Venta.id.in_(ventas_sim_ids)),
        )

    # 7. Logística: Traslados, Preparaciones, Movimientos, Equipos, Ingresos, Compras, Guías
    if traslados_sim_ids:
        traslados_nums = [
            r[0] for r in bd.query(Traslado.numero_traslado).filter(Traslado.id.in_(traslados_sim_ids)).all()
        ]
        if traslados_nums:
            _contar_y_borrar(
                "movimientos_inventario_traslados",
                bd.query(MovimientoInventario).filter(MovimientoInventario.documento_ref.in_(traslados_nums)),
            )
        _contar_y_borrar(
            "traslados_detalle",
            bd.query(TrasladoDetalle).filter(TrasladoDetalle.traslado_id.in_(traslados_sim_ids)),
        )
        _contar_y_borrar(
            "traslados",
            bd.query(Traslado).filter(Traslado.id.in_(traslados_sim_ids)),
        )

    if equipos_sim_ids:
        preps_ids = [
            r[0] for r in bd.query(Preparacion.id).filter(Preparacion.equipo_id.in_(equipos_sim_ids)).all()
        ]
        if preps_ids:
            _contar_y_borrar(
                "preparaciones_componentes",
                bd.query(PreparacionComponente).filter(PreparacionComponente.preparacion_id.in_(preps_ids)),
            )
            _contar_y_borrar(
                "preparaciones",
                bd.query(Preparacion).filter(Preparacion.id.in_(preps_ids)),
            )
        _contar_y_borrar(
            "equipos_componentes_instalados",
            bd.query(EquipoComponenteInstalado).filter(EquipoComponenteInstalado.equipo_id.in_(equipos_sim_ids)),
        )
        _contar_y_borrar(
            "historial_estados_equipo",
            bd.query(HistorialEstadoEquipo).filter(HistorialEstadoEquipo.equipo_id.in_(equipos_sim_ids)),
        )

    movs_filtros = [
        MovimientoInventario.motivo.ilike(patron),
        MovimientoInventario.documento_ref.ilike(patron),
    ]
    if equipos_sim_ids:
        movs_filtros.append(MovimientoInventario.equipo_id.in_(equipos_sim_ids))
    if articulos_sim_ids:
        movs_filtros.append(MovimientoInventario.articulo_id.in_(articulos_sim_ids))
    _contar_y_borrar(
        "movimientos_inventario",
        bd.query(MovimientoInventario).filter(or_(*movs_filtros)),
    )

    if equipos_sim_ids:
        _contar_y_borrar(
            "equipos",
            bd.query(Equipo).filter(Equipo.id.in_(equipos_sim_ids)),
        )

    if compras_sim_ids:
        _contar_y_borrar("compras_componentes", bd.query(CompraComponente).filter(CompraComponente.compra_id.in_(compras_sim_ids)))
        _contar_y_borrar("compras", bd.query(Compra).filter(Compra.id.in_(compras_sim_ids)))

    # 8. Catálogo, Terceros, Usuarios, Sucursales de simulación y AuditLogs
    if articulos_sim_ids:
        _contar_y_borrar(
            "catalogo_precios",
            bd.query(CatalogoPrecio).filter(CatalogoPrecio.articulo_id.in_(articulos_sim_ids)),
        )
        _contar_y_borrar(
            "catalogo_articulos",
            bd.query(CatalogoArticulo).filter(CatalogoArticulo.id.in_(articulos_sim_ids)),
        )

    if terceros_sim_ids:
        _contar_y_borrar("terceros", bd.query(Tercero).filter(Tercero.id.in_(terceros_sim_ids)))

    if usuarios_sim_ids:
        _contar_y_borrar("usuarios", bd.query(Usuario).filter(Usuario.id.in_(usuarios_sim_ids)))

    if sucursales_sim_ids:
        _contar_y_borrar("sucursales", bd.query(Sucursal).filter(Sucursal.id.in_(sucursales_sim_ids)))

    _contar_y_borrar(
        "audit_logs",
        bd.query(AuditLog).filter(
            or_(
                AuditLog.datos_nuevos_json.ilike(patron),
                AuditLog.datos_anteriores_json.ilike(patron),
            )
        ),
    )

    bd.commit()
    return {
        "prefijo": prefijo,
        "total_registros_eliminados": sum(eliminados.values()),
        "detalle": {k: v for k, v in eliminados.items() if v > 0},
    }
