from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.base_datos import Base


class FacturaGastoFiscal(Base):
    __tablename__ = "facturas_gastos_fiscales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rif_proveedor: Mapped[str] = mapped_column(String(40), default="", nullable=False, index=True)
    razon_social: Mapped[str] = mapped_column(String(180), nullable=False)
    numero_factura: Mapped[str] = mapped_column(String(60), default="", nullable=False, index=True)
    numero_control: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    fecha_emision: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    categoria: Mapped[str] = mapped_column(String(80), default="Varios", nullable=False, index=True)
    es_deducible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    es_recurrente: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    base_imponible_bs: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)
    monto_exento_bs: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)
    alicuota_iva: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("16.00"), nullable=False)
    monto_iva_bs: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)
    igtf_bs: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)
    monto_total_bs: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)
    tasa_bcv_fecha: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("1"), nullable=False)
    monto_total_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    monto_pagado_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)

    estado: Mapped[str] = mapped_column(String(20), default="PENDIENTE", nullable=False, index=True)
    observaciones: Mapped[str] = mapped_column(Text, default="", nullable=False)
    registrado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    registrado_por = relationship("Usuario")
    retenciones = relationship("RetencionFiscal", back_populates="factura_gasto")


class RetencionFiscal(Base):
    __tablename__ = "retenciones_fiscales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    numero_comprobante: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # IVA | ISLR
    factura_gasto_id: Mapped[int | None] = mapped_column(ForeignKey("facturas_gastos_fiscales.id"), nullable=True)
    rif_sujeto: Mapped[str] = mapped_column(String(40), nullable=False)
    razon_social: Mapped[str] = mapped_column(String(180), nullable=False)
    numero_factura_ref: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    numero_control_ref: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    fecha_emision: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    periodo_fiscal: Mapped[str] = mapped_column(String(10), nullable=False)  # AAAAMM
    base_imponible_bs: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)
    porcentaje_retencion: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("75.00"), nullable=False)
    monto_retenido_bs: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)
    monto_retenido_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    concepto: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default="EMITIDA", nullable=False)
    registrado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    factura_gasto = relationship("FacturaGastoFiscal", back_populates="retenciones")
    registrado_por = relationship("Usuario")


class ObligacionLegal(Base):
    __tablename__ = "obligaciones_legales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organismo: Mapped[str] = mapped_column(String(30), nullable=False, index=True)  # SENIAT | ALCALDIA | PARAFISCAL | PERMISOLOGIA
    tipo_obligacion: Mapped[str] = mapped_column(String(120), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    periodo: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    fecha_vencimiento: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    monto_estimado_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    monto_pagado_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default="PENDIENTE", nullable=False, index=True)
    instrumento_pago_id: Mapped[int | None] = mapped_column(ForeignKey("instrumentos_financieros.id"), nullable=True)
    pago_id: Mapped[int | None] = mapped_column(ForeignKey("pagos.id"), nullable=True)
    referencia_pago: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    fecha_pago: Mapped[date | None] = mapped_column(Date, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    instrumento_pago = relationship("InstrumentoFinanciero")
    pago = relationship("Pago")


class Nomina(Base):
    __tablename__ = "nominas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    tipo_periodo: Mapped[str] = mapped_column(String(20), default="QUINCENAL", nullable=False)
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[date] = mapped_column(Date, nullable=False)
    tasa_bcv_aplicada: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("1"), nullable=False)
    total_asignaciones_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    total_deducciones_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    total_neto_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default="BORRADOR", nullable=False, index=True)
    instrumento_pago_id: Mapped[int | None] = mapped_column(ForeignKey("instrumentos_financieros.id"), nullable=True)
    pago_id: Mapped[int | None] = mapped_column(ForeignKey("pagos.id"), nullable=True)
    referencia_pago: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    observaciones: Mapped[str] = mapped_column(Text, default="", nullable=False)
    creado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    detalles = relationship("NominaDetalle", back_populates="nomina", cascade="all, delete-orphan")
    instrumento_pago = relationship("InstrumentoFinanciero")
    pago = relationship("Pago")
    creado_por = relationship("Usuario")


class NominaDetalle(Base):
    __tablename__ = "nomina_detalle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nomina_id: Mapped[int] = mapped_column(ForeignKey("nominas.id"), index=True, nullable=False)
    personal_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True, nullable=False)
    nombre_trabajador: Mapped[str] = mapped_column(String(150), nullable=False)
    cargo: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    salario_periodo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    cestaticket_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    bonos_extras_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    ivss_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    rpe_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    faov_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    otras_deducciones_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    neto_pagar_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    neto_pagar_bs: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)
    observacion: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    nomina = relationship("Nomina", back_populates="detalles")
    personal = relationship("Usuario")


class ContratoPoliza(Base):
    __tablename__ = "contratos_polizas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tipo: Mapped[str] = mapped_column(String(50), nullable=False)  # ARRENDAMIENTO | SEGURO | SERVICIO | OTRO
    proveedor_contraparte: Mapped[str] = mapped_column(String(160), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False)
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_vencimiento: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    canon_mensual_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default="VIGENTE", nullable=False)
    sucursal_id: Mapped[int | None] = mapped_column(ForeignKey("sucursales.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    sucursal = relationship("Sucursal")


class ActivoFijo(Base):
    __tablename__ = "activos_fijos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    codigo_activo: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False)
    categoria: Mapped[str] = mapped_column(String(80), default="Mobiliario", nullable=False)
    sucursal_id: Mapped[int | None] = mapped_column(ForeignKey("sucursales.id"), nullable=True)
    responsable: Mapped[str] = mapped_column(String(150), default="", nullable=False)
    fecha_compra: Mapped[date] = mapped_column(Date, nullable=False)
    costo_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    vida_util_meses: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    estado: Mapped[str] = mapped_column(String(25), default="ACTIVO", nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    sucursal = relationship("Sucursal")


class ConciliacionBancaria(Base):
    __tablename__ = "conciliaciones_bancarias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    instrumento_id: Mapped[int] = mapped_column(ForeignKey("instrumentos_financieros.id"), index=True, nullable=False)
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[date] = mapped_column(Date, nullable=False)
    saldo_libros: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)
    saldo_banco: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)
    diferencia: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)
    movimientos_conciliados: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    partidas_transito: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    observaciones: Mapped[str] = mapped_column(Text, default="", nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default="CERRADA", nullable=False)
    cerrado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    instrumento = relationship("InstrumentoFinanciero")
    cerrado_por = relationship("Usuario")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True, index=True)
    usuario_nombre: Mapped[str] = mapped_column(String(150), default="", nullable=False)
    rol: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    fecha_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)
    modulo: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    accion: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    entidad_id: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    datos_anteriores_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    datos_nuevos_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
