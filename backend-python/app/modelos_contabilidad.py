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


class PlanCuenta(Base):
    __tablename__ = "plan_cuentas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    # ACTIVO | PASIVO | PATRIMONIO | INGRESO | COSTO | GASTO_FIJO | GASTO_VARIABLE | GASTO_FINANCIERO | IMPUESTO
    naturaleza: Mapped[str] = mapped_column(String(15), nullable=False)  # DEUDORA | ACREEDORA
    cuenta_padre_id: Mapped[int | None] = mapped_column(ForeignKey("plan_cuentas.id"), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    cuenta_padre = relationship("PlanCuenta", remote_side=[id])


class AsientoContable(Base):
    __tablename__ = "asientos_contables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fecha: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False)
    origen_tipo: Mapped[str] = mapped_column(String(40), index=True, default="MANUAL", nullable=False)
    origen_id: Mapped[str] = mapped_column(String(60), index=True, default="", nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default="CONTABILIZADO", nullable=False)
    creado_por: Mapped[str] = mapped_column(String(150), default="Sistema", nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    detalles = relationship("AsientoDetalle", back_populates="asiento", cascade="all, delete-orphan")


class AsientoDetalle(Base):
    __tablename__ = "asientos_detalle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    asiento_id: Mapped[int] = mapped_column(ForeignKey("asientos_contables.id"), index=True, nullable=False)
    cuenta_contable_id: Mapped[int] = mapped_column(ForeignKey("plan_cuentas.id"), index=True, nullable=False)
    debe_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    haber_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    moneda_origen: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    monto_origen: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"), nullable=False)
    tasa_bcv: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("1"), nullable=False)
    nota: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    asiento = relationship("AsientoContable", back_populates="detalles")
    cuenta = relationship("PlanCuenta")


class EquipoComponenteInstalado(Base):
    __tablename__ = "equipo_componentes_instalados"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    equipo_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"), index=True, nullable=False)
    articulo_id: Mapped[int] = mapped_column(ForeignKey("catalogo_articulos.id"), nullable=False)
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    costo_unitario_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    costo_total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    instalado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    equipo = relationship("Equipo")
    articulo = relationship("CatalogoArticulo")
    instalado_por = relationship("Usuario")


class PrestamoFinanciamiento(Base):
    __tablename__ = "prestamos_financiamientos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    acreedor: Mapped[str] = mapped_column(String(160), nullable=False)
    concepto: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    fecha_desembolso: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date, nullable=True)
    capital_original_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    saldo_capital_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tasa_interes_mensual_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"), nullable=False)
    total_intereses_pagados_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    instrumento_ingreso_id: Mapped[int | None] = mapped_column(ForeignKey("instrumentos_financieros.id"), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="ACTIVO", nullable=False, index=True)  # ACTIVO | PAGADO | ANULADO
    creado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    pagos = relationship("PrestamoPago", back_populates="prestamo", cascade="all, delete-orphan")
    instrumento_ingreso = relationship("InstrumentoFinanciero")


class PrestamoPago(Base):
    __tablename__ = "prestamos_pagos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    prestamo_id: Mapped[int] = mapped_column(ForeignKey("prestamos_financiamientos.id"), index=True, nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    monto_capital_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    monto_interes_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    monto_total_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    instrumento_pago_id: Mapped[int] = mapped_column(ForeignKey("instrumentos_financieros.id"), nullable=False)
    pago_id: Mapped[int | None] = mapped_column(ForeignKey("pagos.id"), nullable=True)
    referencia: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    prestamo = relationship("PrestamoFinanciamiento", back_populates="pagos")
    instrumento_pago = relationship("InstrumentoFinanciero")
    pago = relationship("Pago")
