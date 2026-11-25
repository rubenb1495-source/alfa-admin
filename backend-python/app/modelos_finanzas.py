from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.base_datos import Base


class MonedaInstrumento(str, Enum):
    USD = "USD"
    USDT = "USDT"
    BS = "BS"


class TipoPrecioInstrumento(str, Enum):
    PROMO = "PROMO"
    REGULAR = "REGULAR"


class EstadoVenta(str, Enum):
    CUADRADA = "CUADRADA"
    CON_SALDO = "CON_SALDO"
    ANULADA = "ANULADA"
    DEVUELTA = "DEVUELTA"


class OrigenVenta(str, Enum):
    PASILLO = "PASILLO"
    LEAD = "LEAD"


class EstadoComision(str, Enum):
    PENDIENTE = "PENDIENTE"
    PAGADA = "PAGADA"
    ANULADA = "ANULADA"


class EstadoLiquidacionComision(str, Enum):
    PAGADA = "PAGADA"
    ANULADA = "ANULADA"


class TipoMovimientoPago(str, Enum):
    INGRESO = "INGRESO"
    EGRESO = "EGRESO"
    TRASLADO = "TRASLADO"


class TipoDocumentoPago(str, Enum):
    VENTA = "VENTA"
    ABONO = "ABONO"
    CASHEA = "CASHEA"
    GASTO = "GASTO"
    COMPRA = "COMPRA"
    GUIA = "GUIA"
    PARTE_DE_PAGO = "PARTE_DE_PAGO"
    DEVOLUCION = "DEVOLUCION"
    COMISION = "COMISION"
    TESORERIA = "TESORERIA"


class EstadoVerificacionPago(str, Enum):
    CONFIRMADO = "CONFIRMADO"
    PENDIENTE = "PENDIENTE"


class EstadoReingresoNC(str, Enum):
    POR_PREPARAR = "POR_PREPARAR"
    GARANTIA = "GARANTIA"
    LISTO = "LISTO"


class TipoCuentaPorCobrar(str, Enum):
    CLIENTE = "CLIENTE"
    CASHEA = "CASHEA"


class EstadoCuentaPorCobrar(str, Enum):
    PENDIENTE = "PENDIENTE"
    PAGADA = "PAGADA"
    ANULADA = "ANULADA"


class InstrumentoFinanciero(Base):
    __tablename__ = "instrumentos_financieros"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    moneda: Mapped[str] = mapped_column(String(10), nullable=False)
    tipo_precio: Mapped[str] = mapped_column(String(15), nullable=False)
    requiere_verificacion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    liquida_en_bs: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    saldo_inicial: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Venta(Base):
    __tablename__ = "ventas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    numero_venta: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"), index=True, nullable=False)
    fecha: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("terceros.id"), nullable=True)
    asesor_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    tecnico_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    canal_visita: Mapped[str] = mapped_column(String(60), default="Tienda", nullable=False)
    origen_venta: Mapped[str] = mapped_column(String(20), default=OrigenVenta.PASILLO.value, nullable=False, index=True)
    tipo_entrega: Mapped[str] = mapped_column(String(60), default="Tienda", nullable=False)
    datos_entrega_json: Mapped[str] = mapped_column(Text, default="", nullable=False)
    origen_equipo: Mapped[str] = mapped_column(String(60), default="Propio", nullable=False)
    tasa_bcv_snapshot: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    tasa_usdt_snapshot: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    recargo_porcentaje_snapshot: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"), nullable=False)
    recargo_especial_porcentaje: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    total_promo_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    total_regular_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    es_cashea: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    cashea_inicial_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_financiado_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_comision_venta_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_comision_financiado_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_iva_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_islr_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_total_cargos_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_neto_por_cobrar_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    tasa_bcv_aplicada: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    tasa_usdt_aplicada: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    vuelto_caja_chica_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    es_factura: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    numero_control: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default=EstadoVenta.CUADRADA.value, nullable=False, index=True)
    estado_comision: Mapped[str] = mapped_column(String(20), default=EstadoComision.PENDIENTE.value, nullable=False, index=True)
    liquidacion_id: Mapped[int | None] = mapped_column(ForeignKey("liquidaciones_comisiones.id"), nullable=True, index=True)
    motivo_anulacion: Mapped[str] = mapped_column(Text, default="", nullable=False)
    nota: Mapped[str] = mapped_column(Text, default="", nullable=False)
    creado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    sucursal = relationship("Sucursal")
    cliente = relationship("Tercero")
    asesor = relationship("Usuario", foreign_keys=[asesor_id])
    tecnico = relationship("Usuario", foreign_keys=[tecnico_id])
    creado_por = relationship("Usuario", foreign_keys=[creado_por_id])
    detalles = relationship("VentaDetalle", back_populates="venta", cascade="all, delete-orphan")
    pagos = relationship("Pago", back_populates="venta")
    cuentas_por_cobrar = relationship("CuentaPorCobrar", back_populates="venta")


class VentaDetalle(Base):
    __tablename__ = "ventas_detalle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), index=True, nullable=False)
    equipo_id: Mapped[int | None] = mapped_column(ForeignKey("equipos.id"), nullable=True)
    articulo_id: Mapped[int | None] = mapped_column(ForeignKey("catalogo_articulos.id"), nullable=True)
    descripcion: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    descripcion_servicio: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    precio_promo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    precio_regular_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    precio_pactado_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    costo_total_snapshot_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)

    venta = relationship("Venta", back_populates="detalles")
    equipo = relationship("Equipo")
    articulo = relationship("CatalogoArticulo")


class ExtractoBancario(Base):
    __tablename__ = "extractos_bancarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    instrumento_id: Mapped[int] = mapped_column(ForeignKey("instrumentos_financieros.id"), index=True, nullable=False)
    fecha: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    referencia: Mapped[str] = mapped_column(String(120), default="", nullable=False, index=True)
    descripcion: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    monto_con_signo: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    conciliado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    instrumento = relationship("InstrumentoFinanciero")


class Pago(Base):
    __tablename__ = "pagos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    venta_id: Mapped[int | None] = mapped_column(ForeignKey("ventas.id"), index=True, nullable=True)
    instrumento_id: Mapped[int] = mapped_column(ForeignKey("instrumentos_financieros.id"), index=True, nullable=False)
    fecha: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    tipo_movimiento: Mapped[str] = mapped_column(String(20), default=TipoMovimientoPago.INGRESO.value, nullable=False)
    tipo_documento: Mapped[str] = mapped_column(String(20), default=TipoDocumentoPago.VENTA.value, nullable=False)
    monto_moneda_origen: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    moneda: Mapped[str] = mapped_column(String(10), nullable=False)
    tasa_bcv_dia: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    tasa_usdt_dia: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    usd_nominal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    usd_real: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cubre_promo_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    referencia: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    estado_verificacion: Mapped[str] = mapped_column(String(20), default=EstadoVerificacionPago.CONFIRMADO.value, nullable=False, index=True)
    verificado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    conciliado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extracto_id: Mapped[int | None] = mapped_column(ForeignKey("extractos_bancarios.id"), nullable=True)
    anulado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    categoria: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    origen_tipo: Mapped[str] = mapped_column(String(40), default="", nullable=False, index=True)
    origen_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    nota: Mapped[str] = mapped_column(Text, default="", nullable=False)

    venta = relationship("Venta", back_populates="pagos")
    instrumento = relationship("InstrumentoFinanciero")
    verificado_por = relationship("Usuario")
    extracto = relationship("ExtractoBancario")


class NotaCredito(Base):
    __tablename__ = "notas_credito"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    numero_nc: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    venta_original_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), index=True, nullable=False)
    equipo_id: Mapped[int | None] = mapped_column(ForeignKey("equipos.id"), nullable=True)
    articulo_id: Mapped[int | None] = mapped_column(ForeignKey("catalogo_articulos.id"), nullable=True)
    cantidad: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    monto_reconocido_promo_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    motivo: Mapped[str] = mapped_column(String(255), nullable=False)
    estado_reingreso: Mapped[str] = mapped_column(String(20), default=EstadoReingresoNC.POR_PREPARAR.value, nullable=False)
    autorizado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)

    venta_original = relationship("Venta")
    equipo = relationship("Equipo")
    articulo = relationship("CatalogoArticulo")
    autorizado_por = relationship("Usuario")


class CuentaPorCobrar(Base):
    __tablename__ = "cuentas_por_cobrar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), index=True, nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("terceros.id"), nullable=True)
    monto_original_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    saldo_pendiente_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default=EstadoCuentaPorCobrar.PENDIENTE.value, nullable=False, index=True)

    venta = relationship("Venta", back_populates="cuentas_por_cobrar")
    cliente = relationship("Tercero")


class VentaCasheaFinanzas(Base):
    __tablename__ = "ventas_cashea_finanzas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"), unique=True, index=True, nullable=False)
    cxc_id: Mapped[int | None] = mapped_column(ForeignKey("cuentas_por_cobrar.id"), nullable=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"), index=True, nullable=False)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("terceros.id"), nullable=True)
    fecha_venta: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    numero_nota: Mapped[str] = mapped_column(String(40), index=True, nullable=False)

    tasa_bcv_aplicada: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    tasa_usdt_aplicada: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)

    total_precio_regular_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    total_precio_regular_usdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    total_precio_regular_bs: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)
    inicial_cobrada_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    monto_financiado_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)

    cashea_comision_venta_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_comision_financiado_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_iva_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_islr_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_total_cargos_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_neto_por_cobrar_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_neto_usdt: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    cashea_neto_bs: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)

    monto_cobrado_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default="PENDIENTE", nullable=False, index=True)  # PENDIENTE | PARCIAL | COBRADO
    fecha_cobro: Mapped[date | None] = mapped_column(Date, nullable=True)
    instrumento_cobro_id: Mapped[int | None] = mapped_column(ForeignKey("instrumentos_financieros.id"), nullable=True)
    pago_cobro_id: Mapped[int | None] = mapped_column(ForeignKey("pagos.id"), nullable=True)
    referencia_cobro: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    venta = relationship("Venta")
    sucursal = relationship("Sucursal")
    cliente = relationship("Tercero")
    instrumento_cobro = relationship("InstrumentoFinanciero")


class CierreMensual(Base):
    __tablename__ = "cierres_mensuales"
    __table_args__ = (UniqueConstraint("anio", "mes", name="uq_cierre_anio_mes"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    cerrado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    fecha_cierre: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resumen_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    bloqueado: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    cerrado_por = relationship("Usuario")


class LiquidacionComision(Base):
    __tablename__ = "liquidaciones_comisiones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    codigo: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    personal_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True, nullable=False)
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[date] = mapped_column(Date, nullable=False)
    cantidad_ventas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cantidad_pasillo: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cantidad_lead: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    monto_pasillo_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    monto_lead_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    monto_total_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    metodo_pago: Mapped[str] = mapped_column(String(40), nullable=False)
    instrumento_pago_id: Mapped[int | None] = mapped_column(
        ForeignKey("instrumentos_financieros.id"), nullable=True, index=True
    )
    movimiento_financiero_id: Mapped[int | None] = mapped_column(
        ForeignKey("pagos.id"), nullable=True, index=True
    )
    tasa_bcv_aplicada: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    monto_bs: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    referencia: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    observaciones: Mapped[str] = mapped_column(Text, default="", nullable=False)
    estado: Mapped[str] = mapped_column(
        String(20), default=EstadoLiquidacionComision.PAGADA.value, nullable=False, index=True
    )
    motivo_anulacion: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pagado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    personal = relationship("Usuario", foreign_keys=[personal_id])
    pagado_por = relationship("Usuario", foreign_keys=[pagado_por_id])
    instrumento_pago = relationship("InstrumentoFinanciero", foreign_keys=[instrumento_pago_id])
    movimiento_financiero = relationship("Pago", foreign_keys=[movimiento_financiero_id])
    ventas = relationship("Venta", foreign_keys="Venta.liquidacion_id")


class CierreDiario(Base):
    __tablename__ = "cierres_diarios"
    __table_args__ = (UniqueConstraint("fecha", "sucursal_id", name="uq_cierre_diario_fecha_sucursal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fecha: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    sucursal_id: Mapped[int | None] = mapped_column(ForeignKey("sucursales.id"), index=True, nullable=True)
    encargado_tienda_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    encargado_tienda_nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    tasa_bcv: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    tasa_usdt: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    porcentaje_recargo: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"), nullable=False)
    resumen_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    observaciones: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cerrado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    sucursal = relationship("Sucursal")
    encargado_tienda = relationship("Usuario", foreign_keys=[encargado_tienda_id])
    cerrado_por = relationship("Usuario", foreign_keys=[cerrado_por_id])


class TipoMovimientoTesoreria(str, Enum):
    TRASLADO = "TRASLADO"
    CAMBIO_DIVISA = "CAMBIO_DIVISA"
    INGRESO_ADMIN = "INGRESO_ADMIN"
    EGRESO_ADMIN = "EGRESO_ADMIN"


class EstadoMovimientoTesoreria(str, Enum):
    CONFIRMADO = "CONFIRMADO"
    ANULADO = "ANULADO"


class ResultadoCambiario(str, Enum):
    GANANCIA = "GANANCIA"
    PERDIDA = "PERDIDA"
    NEUTRO = "NEUTRO"


class MovimientoTesoreria(Base):
    __tablename__ = "movimientos_tesoreria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    tipo: Mapped[str] = mapped_column(String(25), index=True, nullable=False)
    fecha: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    estado: Mapped[str] = mapped_column(
        String(20), default=EstadoMovimientoTesoreria.CONFIRMADO.value, nullable=False, index=True
    )

    cuenta_origen_id: Mapped[int | None] = mapped_column(
        ForeignKey("instrumentos_financieros.id"), nullable=True, index=True
    )
    moneda_origen: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    monto_salida: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)

    cuenta_destino_id: Mapped[int | None] = mapped_column(
        ForeignKey("instrumentos_financieros.id"), nullable=True, index=True
    )
    moneda_destino: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    monto_entrada: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)

    comision_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    tasa_referencia_tipo: Mapped[str] = mapped_column(String(10), default="BCV", nullable=False)
    tasa_bcv_dia: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    tasa_usdt_dia: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    tasa_referencia_aplicada: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"), nullable=False)
    tasa_operacion: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)

    equivalente_salida_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    equivalente_entrada_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    diferencial_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    diferencial_porcentaje: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"), nullable=False)
    resultado_tipo: Mapped[str] = mapped_column(
        String(15), default=ResultadoCambiario.NEUTRO.value, nullable=False
    )

    concepto: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    referencia: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    observaciones: Mapped[str] = mapped_column(Text, default="", nullable=False)

    pago_salida_id: Mapped[int | None] = mapped_column(ForeignKey("pagos.id"), nullable=True)
    pago_entrada_id: Mapped[int | None] = mapped_column(ForeignKey("pagos.id"), nullable=True)
    registrado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    anulado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    motivo_anulacion: Mapped[str] = mapped_column(Text, default="", nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    cuenta_origen = relationship("InstrumentoFinanciero", foreign_keys=[cuenta_origen_id])
    cuenta_destino = relationship("InstrumentoFinanciero", foreign_keys=[cuenta_destino_id])
    pago_salida = relationship("Pago", foreign_keys=[pago_salida_id])
    pago_entrada = relationship("Pago", foreign_keys=[pago_entrada_id])
    registrado_por = relationship("Usuario", foreign_keys=[registrado_por_id])
    anulado_por = relationship("Usuario", foreign_keys=[anulado_por_id])


class ConfiguracionAlertas(Base):
    __tablename__ = "configuracion_alertas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    stock_minimo_global: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    dias_alerta_cxp: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    actualizado_por: Mapped[str] = mapped_column(String(150), default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CuentaPorPagar(Base):
    __tablename__ = "cuentas_por_pagar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    proveedor_nombre: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    concepto: Mapped[str] = mapped_column(String(255), nullable=False)
    referencia: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    fecha_vencimiento: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    monto_original_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    monto_pendiente_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default="PENDIENTE", nullable=False, index=True)
    origen_tipo: Mapped[str] = mapped_column(String(40), default="FACTURA", nullable=False)
    origen_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
