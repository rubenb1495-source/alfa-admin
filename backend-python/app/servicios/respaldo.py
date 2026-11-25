from __future__ import annotations

import base64
import io
import json
import zipfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.orm import Session, joinedload

from app.modelos import CatalogoArticulo, Sucursal, TipoArticulo, Usuario
from app.modelos_admin import FacturaGastoFiscal
from app.modelos_contabilidad import PrestamoFinanciamiento
from app.modelos_finanzas import (
    CuentaPorCobrar,
    EstadoVerificacionPago,
    InstrumentoFinanciero,
    Pago,
    TipoMovimientoPago,
    Venta,
    VentaCasheaFinanzas,
)
from app.modelos_logistica import Equipo, MovimientoInventario, TipoMovimientoInventario


def _ahora_caracas() -> datetime:
    try:
        tz = ZoneInfo("America/Caracas")
    except ZoneInfoNotFoundError:
        tz = timezone(timedelta(hours=-4))
    return datetime.now(tz)


def _serializar_valor(valor: Any) -> Any:
    if valor is None or isinstance(valor, (bool, int, float, str)):
        return valor
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (datetime, date, time)):
        return valor.isoformat()
    if isinstance(valor, Enum):
        return valor.value
    if isinstance(valor, UUID):
        return str(valor)
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(valor)).decode("ascii")
    if isinstance(valor, (list, tuple)):
        return [_serializar_valor(v) for v in valor]
    if isinstance(valor, dict):
        return {str(k): _serializar_valor(v) for k, v in valor.items()}
    return str(valor)


def _exportar_tablas_json(bd: Session, usuario_nombre: str, ahora: datetime) -> tuple[bytes, dict[str, Any]]:
    """Lee todas las tablas del esquema público en modo solo lectura y genera backup_completo.json."""
    bind = bd.get_bind()
    inspector = inspect(bind)
    es_postgres = bind.dialect.name == "postgresql"
    esquema = "public" if es_postgres else None

    nombres_tablas = sorted(inspector.get_table_names(schema=esquema))
    metadata_tmp = MetaData()

    datos_tablas: dict[str, list[dict[str, Any]]] = {}
    conteo_por_tabla: dict[str, int] = {}
    total_registros = 0

    for nombre_tabla in nombres_tablas:
        tabla_ref = Table(nombre_tabla, metadata_tmp, autoload_with=bind, schema=esquema)
        filas = bd.execute(select(tabla_ref)).mappings().all()
        registros = [
            {col: _serializar_valor(val) for col, val in fila.items()}
            for fila in filas
        ]
        datos_tablas[nombre_tabla] = registros
        conteo_por_tabla[nombre_tabla] = len(registros)
        total_registros += len(registros)

    metadatos = {
        "empresa": "ALFA IMPORTACIONES, C.A.",
        "rif": "J-50793794-1",
        "fecha_generacion": ahora.isoformat(),
        "zona_horaria": "America/Caracas",
        "usuario": usuario_nombre,
        "motor_bd": bind.dialect.name,
        "total_tablas": len(nombres_tablas),
        "total_registros": total_registros,
        "conteo_por_tabla": conteo_por_tabla,
    }

    payload = {
        "metadatos": metadatos,
        "tablas": datos_tablas,
    }
    json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return json_bytes, metadatos


def _estilizar_hoja(ws: Any, encabezados: list[str], filas: list[list[Any]]) -> None:
    fill_header = PatternFill(start_color="001D3D", end_color="001D3D", fill_type="solid")
    font_header = Font(color="FFFFFF", bold=True, size=10)
    align_header = Alignment(horizontal="left", vertical="center")

    ws.append(encabezados)
    for col_idx in range(1, len(encabezados) + 1):
        celda = ws.cell(row=1, column=col_idx)
        celda.fill = fill_header
        celda.font = font_header
        celda.alignment = align_header

    for fila in filas:
        ws.append(fila)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    for col_idx in range(1, len(encabezados) + 1):
        col_letra = get_column_letter(col_idx)
        max_len = len(str(encabezados[col_idx - 1]))
        for row_idx in range(2, min(len(filas) + 2, 502)):
            val = ws.cell(row=row_idx, column=col_idx).value
            if val is not None:
                max_len = max(max_len, len(str(val)))
        ws.column_dimensions[col_letra].width = min(max_len + 4, 48)


def _num(valor: Any) -> float:
    return float(Decimal(str(valor or 0)).quantize(Decimal("0.01")))


def _generar_excel_resumen(bd: Session) -> bytes:
    """Genera resumen_legible_alfa.xlsx en memoria con las 7 pestañas ejecutivas."""
    wb = Workbook()
    # Reutilizamos la hoja inicial para la primera pestaña
    ws_cajas = wb.active
    ws_cajas.title = "Saldos Cajas y Bancos"

    # 1. Saldos de Cajas / Bancos
    instrumentos = bd.query(InstrumentoFinanciero).order_by(InstrumentoFinanciero.id.asc()).all()
    pagos_confirmados = (
        bd.query(Pago)
        .filter(
            Pago.anulado.is_(False),
            Pago.estado_verificacion == EstadoVerificacionPago.CONFIRMADO.value,
        )
        .all()
    )
    ingresos_por_inst: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    egresos_por_inst: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for p in pagos_confirmados:
        monto = Decimal(p.monto_moneda_origen or 0)
        if p.tipo_movimiento == TipoMovimientoPago.INGRESO.value:
            ingresos_por_inst[p.instrumento_id] += monto
        elif p.tipo_movimiento == TipoMovimientoPago.EGRESO.value:
            egresos_por_inst[p.instrumento_id] += monto

    filas_cajas: list[list[Any]] = []
    for inst in instrumentos:
        saldo_ini = Decimal(inst.saldo_inicial or 0)
        ing = ingresos_por_inst[inst.id]
        egr = egresos_por_inst[inst.id]
        saldo_actual = saldo_ini + ing - egr
        filas_cajas.append([
            inst.id,
            inst.nombre,
            inst.moneda,
            inst.tipo_precio,
            _num(saldo_ini),
            _num(ing),
            _num(egr),
            _num(saldo_actual),
            "SI" if inst.activo else "NO",
        ])
    _estilizar_hoja(
        ws_cajas,
        [
            "ID",
            "Instrumento / Cuenta",
            "Moneda",
            "Tipo Precio",
            "Saldo Inicial",
            "Ingresos Confirmados",
            "Egresos Confirmados",
            "Saldo Actual",
            "Activo",
        ],
        filas_cajas,
    )

    # 2. Inventario Equipos
    ws_equipos = wb.create_sheet(title="Inventario Equipos")
    equipos = (
        bd.query(Equipo)
        .options(joinedload(Equipo.ubicacion))
        .order_by(Equipo.id.desc())
        .all()
    )
    filas_equipos: list[list[Any]] = []
    for eq in equipos:
        costo_total = (
            Decimal(eq.costo_compra_usd or 0)
            + Decimal(eq.costo_flete_usd or 0)
            + Decimal(eq.costo_taller_usd or 0)
        )
        filas_equipos.append([
            eq.id,
            eq.serial,
            eq.modelo,
            eq.configuracion,
            eq.categoria,
            eq.ubicacion.nombre if eq.ubicacion else "",
            eq.estado,
            _num(eq.costo_compra_usd),
            _num(eq.costo_flete_usd),
            _num(eq.costo_taller_usd),
            _num(costo_total),
            _num(eq.precio_promo_usd),
            "SI" if eq.es_consignacion else "NO",
            eq.fecha_recepcion.isoformat() if eq.fecha_recepcion else "",
        ])
    _estilizar_hoja(
        ws_equipos,
        [
            "ID",
            "Serial",
            "Modelo",
            "Configuración",
            "Categoría",
            "Ubicación",
            "Estado",
            "Costo Compra USD",
            "Costo Flete USD",
            "Costo Taller USD",
            "Costo Total USD",
            "Precio Promo USD",
            "Consignación",
            "Fecha Recepción",
        ],
        filas_equipos,
    )

    # 3. Inventario Componentes / Accesorios
    ws_comp = wb.create_sheet(title="Inventario Componentes")
    sucursales_map = {s.id: s.nombre for s in bd.query(Sucursal).all()}
    articulos = (
        bd.query(CatalogoArticulo)
        .options(joinedload(CatalogoArticulo.precios))
        .filter(CatalogoArticulo.tipo != TipoArticulo.EQUIPO.value)
        .order_by(CatalogoArticulo.sku.asc())
        .all()
    )
    articulos_map = {a.id: a for a in articulos}
    movs = (
        bd.query(MovimientoInventario)
        .filter(MovimientoInventario.articulo_id.is_not(None))
        .all()
    )
    tipos_entrada = {
        TipoMovimientoInventario.COMPRA.value,
        TipoMovimientoInventario.TRASLADO_ENTRADA.value,
        TipoMovimientoInventario.AJUSTE_POSITIVO.value,
    }
    tipos_salida = {
        TipoMovimientoInventario.TRASLADO_SALIDA.value,
        TipoMovimientoInventario.AJUSTE_NEGATIVO.value,
        TipoMovimientoInventario.BAJA.value,
        TipoMovimientoInventario.TALLER.value,
        TipoMovimientoInventario.VENTA.value,
    }
    stock_por_par: dict[tuple[int, int], int] = defaultdict(int)
    for m in movs:
        if m.articulo_id is None or m.articulo_id not in articulos_map:
            continue
        clave = (m.articulo_id, m.sucursal_id)
        if m.tipo in tipos_entrada:
            stock_por_par[clave] += int(m.cantidad or 0)
        elif m.tipo in tipos_salida:
            stock_por_par[clave] -= int(m.cantidad or 0)

    filas_comp: list[list[Any]] = []
    articulos_con_mov: set[int] = set()
    for (art_id, suc_id), cant in sorted(stock_por_par.items()):
        art = articulos_map[art_id]
        articulos_con_mov.add(art_id)
        precio_vig = art.precios[0] if art.precios else None
        filas_comp.append([
            art.sku,
            art.descripcion,
            art.tipo,
            art.categoria,
            sucursales_map.get(suc_id, f"Sucursal #{suc_id}"),
            cant,
            art.stock_minimo,
            _num(precio_vig.costo_referencia_usd) if precio_vig else 0.0,
            _num(precio_vig.precio_promo_usd) if precio_vig else 0.0,
            "SI" if art.activo else "NO",
        ])
    for art in articulos:
        if art.id not in articulos_con_mov:
            precio_vig = art.precios[0] if art.precios else None
            filas_comp.append([
                art.sku,
                art.descripcion,
                art.tipo,
                art.categoria,
                "Sin movimientos",
                0,
                art.stock_minimo,
                _num(precio_vig.costo_referencia_usd) if precio_vig else 0.0,
                _num(precio_vig.precio_promo_usd) if precio_vig else 0.0,
                "SI" if art.activo else "NO",
            ])
    _estilizar_hoja(
        ws_comp,
        [
            "SKU",
            "Descripción",
            "Tipo",
            "Categoría",
            "Sucursal / Almacén",
            "Stock Actual",
            "Stock Mínimo",
            "Costo Ref. USD",
            "Precio Promo USD",
            "Activo",
        ],
        filas_comp,
    )

    # 4. Ventas
    ws_ventas = wb.create_sheet(title="Ventas")
    ventas = (
        bd.query(Venta)
        .options(
            joinedload(Venta.sucursal),
            joinedload(Venta.cliente),
            joinedload(Venta.asesor),
        )
        .order_by(Venta.fecha.desc(), Venta.id.desc())
        .all()
    )
    filas_ventas: list[list[Any]] = []
    for v in ventas:
        filas_ventas.append([
            v.id,
            v.numero_venta,
            v.fecha.isoformat() if v.fecha else "",
            v.sucursal.nombre if v.sucursal else "",
            v.cliente.nombre if v.cliente else "Cliente general",
            v.asesor.nombre if v.asesor else "",
            v.canal_visita,
            v.origen_venta,
            _num(v.total_promo_usd),
            _num(v.total_regular_usd),
            "SI" if v.es_cashea else "NO",
            v.estado,
            v.estado_comision,
            v.nota,
        ])
    _estilizar_hoja(
        ws_ventas,
        [
            "ID",
            "N° Venta",
            "Fecha",
            "Sucursal",
            "Cliente",
            "Asesor",
            "Canal",
            "Origen",
            "Total Promo USD",
            "Total Regular USD",
            "Cashea",
            "Estado",
            "Estado Comisión",
            "Nota",
        ],
        filas_ventas,
    )

    # 5. CxC / Cashea
    ws_cxc = wb.create_sheet(title="CxC y Cashea")
    casheas = (
        bd.query(VentaCasheaFinanzas)
        .options(
            joinedload(VentaCasheaFinanzas.sucursal),
            joinedload(VentaCasheaFinanzas.cliente),
        )
        .order_by(VentaCasheaFinanzas.fecha_venta.desc(), VentaCasheaFinanzas.id.desc())
        .all()
    )
    cxc_list = (
        bd.query(CuentaPorCobrar)
        .options(
            joinedload(CuentaPorCobrar.venta),
            joinedload(CuentaPorCobrar.cliente),
        )
        .order_by(CuentaPorCobrar.id.desc())
        .all()
    )
    cxc_ids_cashea = {c.cxc_id for c in casheas if c.cxc_id is not None}
    filas_cxc: list[list[Any]] = []
    for c in casheas:
        pendiente = max(Decimal("0"), Decimal(c.cashea_neto_por_cobrar_usd or 0) - Decimal(c.monto_cobrado_usd or 0))
        filas_cxc.append([
            "CASHEA",
            c.numero_nota,
            c.fecha_venta.isoformat() if c.fecha_venta else "",
            c.sucursal.nombre if c.sucursal else "",
            c.cliente.nombre if c.cliente else "Cliente general",
            _num(c.monto_financiado_usd),
            _num(c.cashea_total_cargos_usd),
            _num(c.cashea_neto_por_cobrar_usd),
            _num(c.monto_cobrado_usd),
            _num(pendiente),
            c.estado,
        ])
    for cxc in cxc_list:
        if cxc.id in cxc_ids_cashea:
            continue
        cobrado = max(Decimal("0"), Decimal(cxc.monto_original_usd or 0) - Decimal(cxc.saldo_pendiente_usd or 0))
        filas_cxc.append([
            cxc.tipo,
            cxc.venta.numero_venta if cxc.venta else f"CXC-{cxc.id}",
            cxc.venta.fecha.isoformat() if (cxc.venta and cxc.venta.fecha) else "",
            sucursales_map.get(cxc.venta.sucursal_id, "") if cxc.venta else "",
            cxc.cliente.nombre if cxc.cliente else "Cliente general",
            _num(cxc.monto_original_usd),
            0.0,
            _num(cxc.monto_original_usd),
            _num(cobrado),
            _num(cxc.saldo_pendiente_usd),
            cxc.estado,
        ])
    _estilizar_hoja(
        ws_cxc,
        [
            "Tipo",
            "Nota / Ref.",
            "Fecha",
            "Sucursal",
            "Cliente",
            "Monto Financiado / Orig. USD",
            "Cargos Cashea USD",
            "Neto por Cobrar USD",
            "Cobrado USD",
            "Saldo Pendiente USD",
            "Estado",
        ],
        filas_cxc,
    )

    # 6. CxP / Préstamos
    ws_cxp = wb.create_sheet(title="CxP y Préstamos")
    prestamos = bd.query(PrestamoFinanciamiento).order_by(PrestamoFinanciamiento.id.desc()).all()
    gastos = bd.query(FacturaGastoFiscal).order_by(FacturaGastoFiscal.fecha_emision.desc(), FacturaGastoFiscal.id.desc()).all()
    filas_cxp: list[list[Any]] = []
    for pr in prestamos:
        pagado_cap = max(Decimal("0"), Decimal(pr.capital_original_usd or 0) - Decimal(pr.saldo_capital_usd or 0))
        filas_cxp.append([
            "PRESTAMO",
            pr.codigo,
            pr.acreedor,
            pr.concepto,
            pr.fecha_desembolso.isoformat() if pr.fecha_desembolso else "",
            pr.fecha_vencimiento.isoformat() if pr.fecha_vencimiento else "",
            _num(pr.capital_original_usd),
            _num(pagado_cap),
            _num(pr.saldo_capital_usd),
            pr.estado,
        ])
    for g in gastos:
        pend = max(Decimal("0"), Decimal(g.monto_total_usd or 0) - Decimal(g.monto_pagado_usd or 0))
        filas_cxp.append([
            "GASTO_CXP",
            g.numero_factura or f"GASTO-{g.id}",
            g.razon_social,
            g.categoria,
            g.fecha_emision.isoformat() if g.fecha_emision else "",
            g.fecha_vencimiento.isoformat() if g.fecha_vencimiento else "",
            _num(g.monto_total_usd),
            _num(g.monto_pagado_usd),
            _num(pend),
            g.estado,
        ])
    _estilizar_hoja(
        ws_cxp,
        [
            "Tipo",
            "Código / Factura",
            "Acreedor / Proveedor",
            "Concepto / Categoría",
            "Fecha Emisión",
            "Vencimiento",
            "Monto Original USD",
            "Pagado USD",
            "Saldo Pendiente USD",
            "Estado",
        ],
        filas_cxp,
    )

    # 7. Personal (sin clave_hash)
    ws_personal = wb.create_sheet(title="Personal")
    usuarios = (
        bd.query(Usuario)
        .options(joinedload(Usuario.sucursal))
        .order_by(Usuario.id.asc())
        .all()
    )
    filas_personal: list[list[Any]] = []
    for u in usuarios:
        filas_personal.append([
            u.id,
            u.nombre,
            u.usuario or "",
            u.correo or "",
            u.rol,
            u.cargo,
            u.modalidad,
            u.sucursal.nombre if u.sucursal else "",
            u.cedula,
            u.telefono,
            "SI" if u.tiene_acceso else "NO",
            "SI" if u.cuenta_bloqueada else "NO",
            _num(u.salario_base_usd),
            _num(u.bono_alimentacion_usd),
            _num(u.bonos_fijos_usd),
            "SI" if u.activo else "NO",
        ])
    _estilizar_hoja(
        ws_personal,
        [
            "ID",
            "Nombre",
            "Usuario",
            "Correo",
            "Rol",
            "Cargo",
            "Modalidad",
            "Sucursal",
            "Cédula",
            "Teléfono",
            "Tiene Acceso",
            "Cuenta Bloqueada",
            "Salario Base USD",
            "Bono Alimentación USD",
            "Bonos Fijos USD",
            "Activo",
        ],
        filas_personal,
    )

    buffer_xlsx = io.BytesIO()
    wb.save(buffer_xlsx)
    return buffer_xlsx.getvalue()


def generar_respaldo_completo_zip(bd: Session, usuario_actual: Usuario) -> tuple[bytes, str, dict[str, Any]]:
    """
    Genera en memoria el archivo ZIP de respaldo completo de Alfa:
    - backup_completo.json (todas las tablas del esquema público)
    - resumen_legible_alfa.xlsx (7 pestañas ejecutivas)
    """
    ahora = _ahora_caracas()
    nombre_archivo = f"respaldo_alfa_{ahora.strftime('%Y-%m-%d_%H%M')}.zip"

    json_bytes, metadatos = _exportar_tablas_json(bd, usuario_actual.nombre, ahora)
    xlsx_bytes = _generar_excel_resumen(bd)

    buffer_zip = io.BytesIO()
    with zipfile.ZipFile(buffer_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("backup_completo.json", json_bytes)
        zf.writestr("resumen_legible_alfa.xlsx", xlsx_bytes)

    zip_bytes = buffer_zip.getvalue()
    metadatos["archivo"] = nombre_archivo
    metadatos["tamano_bytes"] = len(zip_bytes)
    return zip_bytes, nombre_archivo, metadatos
