from __future__ import annotations

from sqlalchemy.orm import Session

from app.modelos_contabilidad import PlanCuenta


CUENTAS_BASE_ALFA: list[tuple[str, str, str, str]] = [
    # 1. ACTIVO
    ("1.1.01", "Cajas y Bancos", "ACTIVO", "DEUDORA"),
    ("1.1.02", "Cuentas por Cobrar (Clientes / Cashea)", "ACTIVO", "DEUDORA"),
    ("1.1.03", "Inventario de Equipos Disponibles", "ACTIVO", "DEUDORA"),
    ("1.1.04", "Inventario de Equipos en Preparación / En Tránsito", "ACTIVO", "DEUDORA"),
    ("1.1.05", "Inventario de Componentes, Repuestos y Accesorios", "ACTIVO", "DEUDORA"),
    ("1.2.01", "Activos Fijos y Depreciación Acumulada", "ACTIVO", "DEUDORA"),
    # 2. PASIVO
    ("2.1.01", "Cuentas por Pagar Proveedores y Consignaciones", "PASIVO", "ACREEDORA"),
    ("2.1.02", "Comisiones por Pagar (Asesores / Encargados)", "PASIVO", "ACREEDORA"),
    ("2.1.03", "Impuestos y Retenciones por Pagar (IVA, ISLR, IGTF, Alcaldía)", "PASIVO", "ACREEDORA"),
    ("2.1.04", "Nómina y Pasivos Laborales por Pagar", "PASIVO", "ACREEDORA"),
    ("2.2.01", "Préstamos y Financiamientos por Pagar (Capital)", "PASIVO", "ACREEDORA"),
    # 3. PATRIMONIO
    ("3.1.01", "Capital Social / Aportes de Socios", "PATRIMONIO", "ACREEDORA"),
    ("3.2.01", "Utilidades Acumuladas / Resultado del Ejercicio", "PATRIMONIO", "ACREEDORA"),
    # 4. INGRESOS
    ("4.1.01", "Ingresos por Ventas de Equipos y Productos", "INGRESO", "ACREEDORA"),
    ("4.1.02", "Ingresos por Servicio Técnico", "INGRESO", "ACREEDORA"),
    ("4.2.01", "Otros Ingresos (No Operativos)", "INGRESO", "ACREEDORA"),
    # 5. COSTO DE VENTAS (COGS)
    ("5.1.01", "Costo de Equipos Vendidos", "COSTO", "DEUDORA"),
    ("5.1.02", "Costo de Componentes y Accesorios Vendidos", "COSTO", "DEUDORA"),
    # 6. GASTOS VARIABLES DE VENTA Y OPERACIÓN
    ("6.1.01", "Comisiones de Ventas", "GASTO_VARIABLE", "DEUDORA"),
    ("6.1.02", "Embalaje, Envíos y Despachos por Venta", "GASTO_VARIABLE", "DEUDORA"),
    ("6.1.03", "Garantías y Repuestos sin Costo al Cliente", "GASTO_VARIABLE", "DEUDORA"),
    # 7. GASTOS FIJOS OPERATIVOS Y ADMINISTRATIVOS
    ("7.1.01", "Sueldos — Encargados de Tienda", "GASTO_FIJO", "DEUDORA"),
    ("7.1.02", "Sueldos — Administración / Administradora", "GASTO_FIJO", "DEUDORA"),
    ("7.1.03", "Sueldos / Honorarios — Accionistas / Directores", "GASTO_FIJO", "DEUDORA"),
    ("7.1.04", "Sueldos — Chofer / Motorizado y Logística", "GASTO_FIJO", "DEUDORA"),
    ("7.1.05", "Parafiscales y Beneficios de Ley (IVSS, FAOV, INCES, Cestaticket)", "GASTO_FIJO", "DEUDORA"),
    ("7.2.01", "Alquiler de Locales Comerciales", "GASTO_FIJO", "DEUDORA"),
    ("7.2.02", "Alquiler de Almacén", "GASTO_FIJO", "DEUDORA"),
    ("7.2.03", "Condominio (Locales y Almacén)", "GASTO_FIJO", "DEUDORA"),
    ("7.3.01", "Servicios Fijos (Electricidad, Agua, Internet, Telefonía, Software)", "GASTO_FIJO", "DEUDORA"),
    ("7.3.02", "Mantenimiento, Papelería y Honorarios Profesionales", "GASTO_FIJO", "DEUDORA"),
    # 8. GASTOS FINANCIEROS Y CAMBIARIOS
    ("8.1.01", "Comisiones Bancarias y Puntos de Venta", "GASTO_FINANCIERO", "DEUDORA"),
    ("8.1.02", "Intereses de Préstamos y Financiamientos", "GASTO_FINANCIERO", "DEUDORA"),
    ("8.1.03", "Ganancia / Pérdida por Diferencial Cambiario", "GASTO_FINANCIERO", "DEUDORA"),
    # 9. IMPUESTOS
    ("9.1.01", "Impuestos Nacionales (ISLR, IGTF)", "IMPUESTO", "DEUDORA"),
    ("9.1.02", "Impuestos Municipales (Patente / ISAE, Aseo, Publicidad)", "IMPUESTO", "DEUDORA"),
]


def ejecutar_semilla_contabilidad(bd: Session) -> None:
    """Crea de forma idempotente el Plan de Cuentas oficial de Alfa."""
    existentes = {c.codigo for c in bd.query(PlanCuenta.codigo).all()}
    creadas = 0
    for codigo, nombre, tipo, naturaleza in CUENTAS_BASE_ALFA:
        if codigo not in existentes:
            bd.add(
                PlanCuenta(
                    codigo=codigo,
                    nombre=nombre,
                    tipo=tipo,
                    naturaleza=naturaleza,
                    activa=True,
                )
            )
            creadas += 1
    if creadas > 0:
        bd.commit()
