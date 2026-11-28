from __future__ import annotations

import io
import json
import zipfile
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.base_datos import obtener_bd
from app.modelos import TasaDiaria, Usuario
from app.modelos_admin import (
    ActivoFijo,
    AuditLog,
    ConciliacionBancaria,
    ContratoPoliza,
    FacturaGastoFiscal,
    Nomina,
    NominaDetalle,
    ObligacionLegal,
    RetencionFiscal,
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
    CierreMensual,
    CuentaPorCobrar,
    CuentaPorPagar,
    ExtractoBancario,
    InstrumentoFinanciero,
    LiquidacionComision,
    MonedaInstrumento,
    MovimientoTesoreria,
    NotaCredito,
    Pago,
    Venta,
    VentaCasheaFinanzas,
    VentaDetalle,
)
from app.modelos_logistica import (
    AjusteInventario,
    Compra,
    CompraComponente,
    CompraInternacionalLote,
    Equipo,
    GuiaImportacion,
    HistorialEstadoEquipo,
    LoteTransito,
    LoteTransitoItem,
    MovimientoInventario,
    Traslado,
    TrasladoDetalle,
    guias_compras,
)
from app.modelos_operaciones import (
    Cotizacion,
    CotizacionDetalle,
    DevolucionGarantia,
)
from app.modelos_taller import (
    CasoPostventa,
    OrdenRecepcionTecnica,
    Preparacion,
    PreparacionComponente,
    RepuestoSolicitado,
)
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import requerir_admin, verificar_clave
from app.servicios.contabilidad import crear_asiento_contable

enrutador = APIRouter(prefix="/api/apertura", tags=["Apertura 01/12/2026"])

FRASE_CONFIRMACION_RESET = "REINICIAR ALFA DESDE CERO"


def _q2(val: Decimal | float | int) -> Decimal:
    return Decimal(str(val or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _crear_excel_plantilla(titulo: str, columnas: list[str], ejemplo: list[Any]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = titulo[:31]
    ws.append(columnas)
    fill = PatternFill(start_color="003566", end_color="003566", fill_type="solid")
    font = Font(color="FFFFFF", bold=True)
    for cell in ws[1]:
        cell.fill = fill
        cell.font = font
    ws.append(ejemplo)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@enrutador.get("/estado")
def estado_apertura(
    _usuario: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Devuelve contadores operativos actuales para verificar si la BD está en cero para apertura."""
    insts = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.activo.is_(True)).order_by(InstrumentoFinanciero.id.asc()).all()
    tasa = bd.query(TasaDiaria).order_by(TasaDiaria.fecha.desc()).first()
    tasa_bcv = Decimal(tasa.tasa_bcv) if tasa and tasa.tasa_bcv else Decimal("1")

    saldos_lista = []
    total_usd = Decimal("0")
    for i in insts:
        s = Decimal(i.saldo_inicial or 0)
        s_usd = _q2(s / tasa_bcv) if (i.moneda == MonedaInstrumento.BS.value and tasa_bcv > 0) else _q2(s)
        total_usd += s_usd
        saldos_lista.append(
            {
                "id": i.id,
                "nombre": i.nombre,
                "moneda": i.moneda,
                "saldo_inicial": float(_q2(s)),
                "saldo_inicial_usd": float(s_usd),
            }
        )

    conteos = {
        "ventas": bd.query(Venta).count(),
        "pagos": bd.query(Pago).count(),
        "equipos": bd.query(Equipo).count(),
        "compras": bd.query(Compra).count(),
        "traslados": bd.query(Traslado).count(),
        "asientos_contables": bd.query(AsientoContable).count(),
        "cierres_diarios": bd.query(CierreDiario).count(),
        "cashea_registros": bd.query(VentaCasheaFinanzas).count(),
        "ordenes_recepcion": bd.query(OrdenRecepcionTecnica).count(),
    }
    return {
        "en_cero": all(v == 0 for v in conteos.values()),
        "conteos": conteos,
        "frase_confirmacion_requerida": FRASE_CONFIRMACION_RESET,
        "total_saldos_iniciales_usd": float(_q2(total_usd)),
        "instrumentos": saldos_lista,
    }


@enrutador.get("/plantillas-zip")
def descargar_plantillas_apertura_zip(
    _usuario: Usuario = Depends(requerir_admin),
) -> StreamingResponse:
    """Genera un .zip en memoria con las 6 planillas oficiales de carga inicial para Alfa."""
    plantillas = {
        "01_saldos_cajas_bancos_alfa.xlsx": _crear_excel_plantilla(
            "Saldos Cajas y Bancos",
            ["instrumento", "moneda", "saldo_inicial", "nota"],
            ["Efectivo divisas", "USD", 500.00, "Saldo inicial apertura 01/12/2026"],
        ),
        "02_inventario_equipos_alfa.xlsx": _crear_excel_plantilla(
            "Inventario Equipos",
            ["serial", "modelo", "configuracion", "categoria", "sucursal", "estado", "costo_compra_usd", "precio_promo_usd"],
            ["ALFA-INI-001", "Dell Latitude 5420", "i5 11va / 16GB / 256GB SSD", "Laptop", "Local T38", "LISTO", 210.00, 320.00],
        ),
        "03_inventario_componentes_alfa.xlsx": _crear_excel_plantilla(
            "Inventario Componentes",
            ["sku", "descripcion", "tipo", "categoria", "sucursal", "cantidad", "costo_unitario_usd", "precio_promo_usd"],
            ["RAM-8GB-DDR4", "Memoria RAM 8GB DDR4", "COMPONENTE", "Memorias", "Almacén Guaparo Norte", 10, 15.00, 30.00],
        ),
        "04_cuentas_por_cobrar_alfa.xlsx": _crear_excel_plantilla(
            "Cuentas por Cobrar",
            ["cliente", "tipo", "referencia", "monto_pendiente_usd", "nota"],
            ["Cliente Apertura", "CLIENTE", "CXC-INI-01", 120.00, "Saldo pendiente anterior al corte"],
        ),
        "05_cuentas_por_pagar_prestamos_alfa.xlsx": _crear_excel_plantilla(
            "CxP y Préstamos",
            ["tipo", "acreedor_o_proveedor", "documento", "fecha_vencimiento", "saldo_pendiente_usd", "concepto"],
            ["PRESTAMO", "Socio Capital", "PREST-INI-01", "2027-03-01", 2000.00, "Préstamo capital de trabajo"],
        ),
        "06_personal_nomina_alfa.xlsx": _crear_excel_plantilla(
            "Personal y Nómina",
            ["nombre", "usuario", "rol", "sucursal", "cedula", "telefono", "salario_base_usd", "bonos_fijos_usd"],
            ["María Gómez", "María Gómez", "ASESORA", "Local T38", "V-25123456", "0414-0000000", 200.00, 50.00],
        ),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for nombre, contenido in plantillas.items():
            zf.writestr(nombre, contenido)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="plantillas_apertura_alfa_01_12.zip"'},
    )


class ResetCeroEntrada(BaseModel):
    password: str = Field(min_length=1)
    frase_confirmacion: str = Field(min_length=1)


@enrutador.post("/reset-cero")
def ejecutar_reset_en_cero(
    datos: ResetCeroEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Limpia toda la data transaccional para arranque en cero, preservando catálogo, cuentas, sucursales y usuarios."""
    if not usuario_actual.clave_hash or not verificar_clave(datos.password, usuario_actual.clave_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Contraseña de administrador incorrecta.")
    if datos.frase_confirmacion.strip().upper() != FRASE_CONFIRMACION_RESET:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Frase de confirmación inválida. Escribe exactamente: {FRASE_CONFIRMACION_RESET}",
        )

    from app.rutas.recuperacion_clave import SolicitudRecuperacionClave

    eliminados: dict[str, int] = {}
    # Borrado en orden seguro respetando llaves foráneas
    modelos_orden = [
        ("solicitudes_recuperacion_clave", SolicitudRecuperacionClave),
        ("venta_cashea_finanzas", VentaCasheaFinanzas),
        ("cuentas_por_cobrar", CuentaPorCobrar),
        ("cuentas_por_pagar", CuentaPorPagar),
        ("notas_credito", NotaCredito),
        ("devoluciones_garantia", DevolucionGarantia),
        ("ventas_detalle", VentaDetalle),
        ("pagos", Pago),
        ("liquidaciones_comisiones", LiquidacionComision),
        ("ventas", Venta),
        ("cotizaciones_detalle", CotizacionDetalle),
        ("cotizaciones", Cotizacion),
        ("traslados_detalle", TrasladoDetalle),
        ("traslados", Traslado),
        ("ajustes_inventario", AjusteInventario),
        ("preparaciones_componentes", PreparacionComponente),
        ("preparaciones", Preparacion),
        ("repuestos_solicitados", RepuestoSolicitado),
        ("ordenes_recepcion_tecnica", OrdenRecepcionTecnica),
        ("casos_postventa", CasoPostventa),
        ("equipo_componentes_instalados", EquipoComponenteInstalado),
        ("historial_estados_equipo", HistorialEstadoEquipo),
        ("movimientos_inventario", MovimientoInventario),
        ("equipos", Equipo),
        ("compras_internacionales_lotes", CompraInternacionalLote),
        ("lotes_transito_items", LoteTransitoItem),
        ("lotes_transito", LoteTransito),
        ("compras_componentes", CompraComponente),
        ("compras", Compra),
        ("guias_importacion", GuiaImportacion),
        ("prestamos_pagos", PrestamoPago),
        ("prestamos_financiamientos", PrestamoFinanciamiento),
        ("nomina_detalles", NominaDetalle),
        ("nominas", Nomina),
        ("retenciones_fiscales", RetencionFiscal),
        ("facturas_gastos_fiscales", FacturaGastoFiscal),
        ("obligaciones_legales", ObligacionLegal),
        ("conciliaciones_bancarias", ConciliacionBancaria),
        ("extractos_bancarios", ExtractoBancario),
        ("movimientos_tesoreria", MovimientoTesoreria),
        ("activos_fijos", ActivoFijo),
        ("contratos_polizas", ContratoPoliza),
        ("cierres_diarios", CierreDiario),
        ("cierres_mensuales", CierreMensual),
        ("asientos_detalle", AsientoDetalle),
        ("asientos_contables", AsientoContable),
    ]

    bd.execute(guias_compras.delete())
    for etiqueta, modelo in modelos_orden:
        eliminados[etiqueta] = bd.query(modelo).delete(synchronize_session=False)

    # Reiniciar saldo_inicial de instrumentos a 0
    for inst in bd.query(InstrumentoFinanciero).all():
        inst.saldo_inicial = Decimal("0")

    bd.add(
        AuditLog(
            usuario_id=usuario_actual.id,
            usuario_nombre=usuario_actual.nombre,
            rol=usuario_actual.rol,
            modulo="APERTURA",
            accion="RESET_APERTURA_CERO",
            entidad_id="SISTEMA",
            datos_anteriores_json="{}",
            datos_nuevos_json=json.dumps({"total_eliminados": sum(eliminados.values())}, ensure_ascii=False),
        )
    )
    bd.commit()

    return {
        "mensaje": "Sistema reiniciado en cero correctamente. Listo para carga inicial de apertura.",
        "total_registros_eliminados": sum(eliminados.values()),
        "detalle": eliminados,
    }


class SaldoInicialItem(BaseModel):
    instrumento_id: int
    saldo_inicial: Decimal = Field(ge=Decimal("0"))


class CargaSaldosInicialesEntrada(BaseModel):
    fecha_apertura: date | None = None
    saldos: list[SaldoInicialItem] = Field(min_length=1)


@enrutador.post("/cargar-saldos-iniciales")
def cargar_saldos_iniciales_apertura(
    datos: CargaSaldosInicialesEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Actualiza saldos iniciales de cajas/bancos y genera el asiento de apertura cuadrado (1.1.01 vs 3.1.01)."""
    fecha_op = datos.fecha_apertura or obtener_fecha_hoy()
    tasa = bd.query(TasaDiaria).filter(TasaDiaria.fecha == fecha_op).first() or bd.query(TasaDiaria).order_by(TasaDiaria.fecha.desc()).first()
    tasa_bcv = Decimal(tasa.tasa_bcv) if tasa and tasa.tasa_bcv else Decimal("1")

    total_usd = Decimal("0")
    actualizados = 0
    for item in datos.saldos:
        inst = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.id == item.instrumento_id).first()
        if inst is None:
            continue
        inst.saldo_inicial = _q2(item.saldo_inicial)
        actualizados += 1
        s_usd = _q2(inst.saldo_inicial / tasa_bcv) if (inst.moneda == MonedaInstrumento.BS.value and tasa_bcv > 0) else inst.saldo_inicial
        total_usd += s_usd

    asiento_id = None
    if total_usd > Decimal("0"):
        asiento = crear_asiento_contable(
            bd=bd,
            usuario=usuario_actual,
            fecha_op=fecha_op,
            descripcion=f"Asiento de Apertura · Saldos Iniciales de Cajas y Bancos ({actualizados} cuentas)",
            origen_tipo="APERTURA_SALDOS",
            origen_id=fecha_op.isoformat(),
            lineas=[
                {"cuenta_codigo": "1.1.01", "debe_usd": total_usd, "haber_usd": 0, "nota": "Disponibilidad inicial en cajas y bancos"},
                {"cuenta_codigo": "3.1.01", "debe_usd": 0, "haber_usd": total_usd, "nota": "Capital inicial de apertura"},
            ],
        )
        asiento_id = asiento.id

    bd.commit()
    return {
        "mensaje": f"Saldos iniciales guardados para {actualizados} cuentas.",
        "cuentas_actualizadas": actualizados,
        "total_usd": float(_q2(total_usd)),
        "asiento_id": asiento_id,
    }
