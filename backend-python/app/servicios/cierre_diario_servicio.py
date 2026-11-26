from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session, joinedload

from app.configuracion import configuracion
from app.modelos import Sucursal
from app.modelos_finanzas import (
    InstrumentoFinanciero,
    MonedaInstrumento,
    Pago,
    TipoDocumentoPago,
    TipoMovimientoPago,
    Venta,
    VentaCasheaFinanzas,
)
from app.modelos_logistica import EstadoTraslado, Traslado
from app.modelos_taller import Preparacion


INSTRUMENTOS_NO_LIQUIDEZ = {
    "cashea · financiado",
    "equipo como parte de pago",
    "cuenta por cobrar",
}


def _q2(val: Decimal | float | int) -> Decimal:
    return Decimal(str(val or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _r2(val: Decimal | float | int) -> float:
    return float(_q2(val))


def _tz_caracas():
    try:
        return ZoneInfo(configuracion.ZONA_HORARIA)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=-4))


def _fecha_caracas(dt: datetime | None) -> date | None:
    if dt is None:
        return None
    tz = _tz_caracas()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date()


def _hora_caracas(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    tz = _tz_caracas()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%I:%M %p")


def _es_liquidez(nombre_inst: str) -> bool:
    return nombre_inst.strip().lower() not in INSTRUMENTOS_NO_LIQUIDEZ


def _clasificar_egreso(p: Pago) -> str:
    tipo_doc = (p.tipo_documento or "").upper()
    origen = (p.origen_tipo or "").upper()
    texto = f"{p.categoria or ''} {p.nota or ''} {p.referencia or ''}".upper()

    if tipo_doc == TipoDocumentoPago.COMISION.value or origen == "LIQUIDACION_COMISION":
        return "comisiones"
    if origen == "NOMINA" or "NOMINA" in texto or "NÓMINA" in texto:
        return "nomina"
    if origen == "OBLIGACION_LEGAL" or any(k in texto for k in ("SENIAT", "IMPUESTO", "ISLR", "IVA", "ALCALDIA", "ALCALDÍA")):
        return "impuestos"
    if tipo_doc in (TipoDocumentoPago.COMPRA.value, TipoDocumentoPago.GUIA.value) or origen in ("PRESTAMO", "PRESTAMO_PAGO") or "PRESTAMO" in texto or "PRÉSTAMO" in texto:
        return "proveedores_prestamos"
    if any(k in texto for k in ("ENVIO", "ENVÍO", "DELIVERY", "MOTORIZADO", "FLETE", "MRW", "ZOOM", "TEALCA")):
        return "envios_delivery"
    if tipo_doc == TipoDocumentoPago.GASTO.value or origen == "FACTURA_GASTO":
        return "gastos_operativos"
    return "otros_egresos"


def calcular_saldos_cajas_y_movimientos(
    bd: Session,
    fecha_obj: date,
    tasa_bcv: float,
    sucursal_id: int | None = None,
    incluir_saldos_globales: bool = True,
) -> dict[str, Any]:
    """
    Calcula:
    - saldos_cajas (saldo_inicial + entradas - salidas == saldo_final en moneda nativa y USD)
    - liquidez_total_usd
    - egresos_dia (clasificados)
    - movimientos_dia (bitácora cronológica)
    - comparativa_tiendas (por sede + Administración General)
    - resumen_financiero (ingresos, egresos, flujo_neto)
    - operacion_general (traslados, preparaciones, Cashea del día)
    """
    tasa_bcv_dec = Decimal(str(tasa_bcv or 0))

    # Consultar todos los pagos no anulados hasta fecha_obj
    pagos_hasta_fecha = (
        bd.query(Pago)
        .options(
            joinedload(Pago.instrumento),
            joinedload(Pago.venta).joinedload(Venta.sucursal),
            joinedload(Pago.venta).joinedload(Venta.cliente),
        )
        .filter(
            Pago.anulado.is_(False),
            Pago.fecha <= fecha_obj,
        )
        .order_by(Pago.fecha.asc(), Pago.id.asc())
        .all()
    )

    instrumentos = (
        bd.query(InstrumentoFinanciero)
        .filter(InstrumentoFinanciero.activo.is_(True))
        .order_by(InstrumentoFinanciero.id.asc())
        .all()
    )

    # 1. Saldos de TODAS las cajas y bancos (solo para vista GENERAL / ejecutiva)
    saldos_cajas: list[dict[str, Any]] = []
    liquidez_total_usd = Decimal("0")

    if incluir_saldos_globales:
        ini_nativo: dict[int, Decimal] = {i.id: Decimal(i.saldo_inicial or 0) for i in instrumentos}
        ent_nativo: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        sal_nativo: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))

        ini_usd: dict[int, Decimal] = {}
        for i in instrumentos:
            s0 = Decimal(i.saldo_inicial or 0)
            if i.moneda == MonedaInstrumento.BS.value and tasa_bcv_dec > 0:
                ini_usd[i.id] = _q2(s0 / tasa_bcv_dec)
            else:
                ini_usd[i.id] = _q2(s0)
        ent_usd_map: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        sal_usd_map: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))

        for p in pagos_hasta_fecha:
            iid = p.instrumento_id
            if iid not in ini_nativo:
                continue
            monto_orig = Decimal(p.monto_moneda_origen or 0)
            if p.moneda == MonedaInstrumento.BS.value and tasa_bcv_dec > 0:
                monto_usd_eq = _q2(monto_orig / tasa_bcv_dec)
            else:
                monto_usd_eq = _q2(p.usd_nominal if p.usd_nominal else monto_orig)

            if p.fecha < fecha_obj:
                if p.tipo_movimiento == TipoMovimientoPago.INGRESO.value:
                    ini_nativo[iid] += monto_orig
                    ini_usd[iid] += monto_usd_eq
                elif p.tipo_movimiento == TipoMovimientoPago.EGRESO.value:
                    ini_nativo[iid] -= monto_orig
                    ini_usd[iid] -= monto_usd_eq
            elif p.fecha == fecha_obj:
                if p.tipo_movimiento == TipoMovimientoPago.INGRESO.value:
                    ent_nativo[iid] += monto_orig
                    ent_usd_map[iid] += monto_usd_eq
                elif p.tipo_movimiento == TipoMovimientoPago.EGRESO.value:
                    sal_nativo[iid] += monto_orig
                    sal_usd_map[iid] += monto_usd_eq

        for inst in instrumentos:
            iid = inst.id
            s_ini = _q2(ini_nativo[iid])
            ent = _q2(ent_nativo[iid])
            sal = _q2(sal_nativo[iid])
            s_fin = _q2(s_ini + ent - sal)

            s_ini_u = _q2(ini_usd[iid])
            ent_u = _q2(ent_usd_map[iid])
            sal_u = _q2(sal_usd_map[iid])
            s_fin_u = _q2(s_ini_u + ent_u - sal_u)

            es_liq = _es_liquidez(inst.nombre)
            if es_liq:
                liquidez_total_usd += s_fin_u

            saldos_cajas.append(
                {
                    "instrumento_id": iid,
                    "nombre": inst.nombre,
                    "moneda": inst.moneda,
                    "es_liquidez": es_liq,
                    "saldo_inicial": _r2(s_ini),
                    "entradas": _r2(ent),
                    "salidas": _r2(sal),
                    "saldo_final": _r2(s_fin),
                    "saldo_inicial_usd": _r2(s_ini_u),
                    "entradas_usd": _r2(ent_u),
                    "salidas_usd": _r2(sal_u),
                    "saldo_final_usd": _r2(s_fin_u),
                }
            )

    # 2. Movimientos y Egresos del día (filtrados por sucursal si aplica)
    pagos_hoy = [p for p in pagos_hasta_fecha if p.fecha == fecha_obj]
    if sucursal_id is not None:
        pagos_hoy_filtrados = [
            p for p in pagos_hoy if p.venta is not None and p.venta.sucursal_id == sucursal_id
        ]
    else:
        pagos_hoy_filtrados = pagos_hoy

    ingresos_totales_usd = Decimal("0")
    egresos_totales_usd = Decimal("0")
    egresos_cat: dict[str, Decimal] = {
        "gastos_operativos": Decimal("0"),
        "envios_delivery": Decimal("0"),
        "nomina": Decimal("0"),
        "comisiones": Decimal("0"),
        "proveedores_prestamos": Decimal("0"),
        "impuestos": Decimal("0"),
        "otros_egresos": Decimal("0"),
    }
    egresos_items: list[dict[str, Any]] = []
    movimientos_dia: list[dict[str, Any]] = []

    for p in pagos_hoy_filtrados:
        inst_nom = p.instrumento.nombre if p.instrumento else "Instrumento"
        monto_usd = _q2(p.usd_nominal)
        sede_id = p.venta.sucursal_id if p.venta is not None else None
        sede_nom = (
            p.venta.sucursal.nombre
            if (p.venta is not None and p.venta.sucursal is not None)
            else "Administración General"
        )
        hora_txt = _hora_caracas(p.venta.creado_en) if p.venta is not None else "—"
        if p.venta is not None:
            cli_nom = p.venta.cliente.nombre if p.venta.cliente else "Cliente general"
            concepto = f"Venta {p.venta.numero_venta} · {cli_nom}"
        else:
            concepto = p.nota or p.categoria or p.tipo_documento or "Movimiento administrativo"

        if p.tipo_movimiento == TipoMovimientoPago.INGRESO.value:
            ingresos_totales_usd += monto_usd
        elif p.tipo_movimiento == TipoMovimientoPago.EGRESO.value:
            egresos_totales_usd += monto_usd
            cat_key = _clasificar_egreso(p)
            egresos_cat[cat_key] += monto_usd
            egresos_items.append(
                {
                    "id": p.id,
                    "categoria_resumen": cat_key,
                    "tipo_documento": p.tipo_documento,
                    "categoria": p.categoria or p.origen_tipo or p.tipo_documento,
                    "concepto": concepto,
                    "instrumento": inst_nom,
                    "moneda": p.moneda,
                    "monto_moneda_origen": _r2(p.monto_moneda_origen),
                    "monto_usd": _r2(monto_usd),
                    "referencia": p.referencia or "",
                }
            )

        movimientos_dia.append(
            {
                "id": p.id,
                "hora": hora_txt,
                "sede_id": sede_id,
                "sede_nombre": sede_nom,
                "instrumento_id": p.instrumento_id,
                "instrumento_nombre": inst_nom,
                "moneda": p.moneda,
                "tipo_movimiento": p.tipo_movimiento,
                "tipo_documento": p.tipo_documento,
                "categoria": p.categoria or p.origen_tipo or p.tipo_documento,
                "concepto": concepto,
                "referencia": p.referencia or "",
                "monto_moneda_origen": _r2(p.monto_moneda_origen),
                "monto_usd": _r2(monto_usd),
            }
        )

    # 3. Comparativa por tienda + Administración General (en vista GENERAL)
    comparativa_tiendas: list[dict[str, Any]] = []
    if incluir_saldos_globales:
        sucursales_activas = (
            bd.query(Sucursal)
            .filter(Sucursal.estado == "ACTIVA")
            .order_by(Sucursal.id.asc())
            .all()
        )
        comp_map: dict[int | None, dict[str, Any]] = {}
        for s in sucursales_activas:
            comp_map[s.id] = {
                "sucursal_id": s.id,
                "nombre": s.nombre,
                "cantidad_ventas": 0,
                "ventas_promo_usd": Decimal("0"),
                "ingresos_usd": Decimal("0"),
                "egresos_usd": Decimal("0"),
            }
        comp_map[None] = {
            "sucursal_id": None,
            "nombre": "Administración General",
            "cantidad_ventas": 0,
            "ventas_promo_usd": Decimal("0"),
            "ingresos_usd": Decimal("0"),
            "egresos_usd": Decimal("0"),
        }

        ventas_hoy_todas = (
            bd.query(Venta)
            .filter(Venta.fecha == fecha_obj, Venta.estado != "ANULADA")
            .all()
        )
        for v in ventas_hoy_todas:
            if v.sucursal_id not in comp_map:
                comp_map[v.sucursal_id] = {
                    "sucursal_id": v.sucursal_id,
                    "nombre": f"Sede #{v.sucursal_id}",
                    "cantidad_ventas": 0,
                    "ventas_promo_usd": Decimal("0"),
                    "ingresos_usd": Decimal("0"),
                    "egresos_usd": Decimal("0"),
                }
            comp_map[v.sucursal_id]["cantidad_ventas"] += 1
            comp_map[v.sucursal_id]["ventas_promo_usd"] += Decimal(v.total_promo_usd or 0)

        for p in pagos_hoy:
            clave_sede = p.venta.sucursal_id if p.venta is not None else None
            if clave_sede not in comp_map:
                comp_map[clave_sede] = {
                    "sucursal_id": clave_sede,
                    "nombre": f"Sede #{clave_sede}" if clave_sede else "Administración General",
                    "cantidad_ventas": 0,
                    "ventas_promo_usd": Decimal("0"),
                    "ingresos_usd": Decimal("0"),
                    "egresos_usd": Decimal("0"),
                }
            if p.tipo_movimiento == TipoMovimientoPago.INGRESO.value:
                comp_map[clave_sede]["ingresos_usd"] += _q2(p.usd_nominal)
            elif p.tipo_movimiento == TipoMovimientoPago.EGRESO.value:
                comp_map[clave_sede]["egresos_usd"] += _q2(p.usd_nominal)

        for item in comp_map.values():
            ing_u = _q2(item["ingresos_usd"])
            egr_u = _q2(item["egresos_usd"])
            comparativa_tiendas.append(
                {
                    "sucursal_id": item["sucursal_id"],
                    "nombre": item["nombre"],
                    "cantidad_ventas": item["cantidad_ventas"],
                    "ventas_promo_usd": _r2(item["ventas_promo_usd"]),
                    "ingresos_usd": _r2(ing_u),
                    "egresos_usd": _r2(egr_u),
                    "flujo_neto_usd": _r2(ing_u - egr_u),
                }
            )

    # 4. Operación general consolidada (traslados despachados/recibidos, preparaciones, Cashea)
    operacion_general: dict[str, Any] | None = None
    if incluir_saldos_globales:
        traslados_todos = bd.query(Traslado).all()
        despachados_hoy = sum(
            1 for t in traslados_todos if _fecha_caracas(t.fecha_envio) == fecha_obj
        )
        recibidos_hoy = sum(
            1
            for t in traslados_todos
            if t.estado == EstadoTraslado.RECIBIDO.value
            and _fecha_caracas(t.fecha_recepcion) == fecha_obj
        )

        preparaciones_hoy = (
            bd.query(Preparacion)
            .filter(Preparacion.fecha == fecha_obj)
            .count()
        )

        casheas_hoy = (
            bd.query(VentaCasheaFinanzas)
            .filter(VentaCasheaFinanzas.fecha_venta == fecha_obj)
            .all()
        )
        casheas_cobrados_hoy = (
            bd.query(VentaCasheaFinanzas)
            .filter(VentaCasheaFinanzas.fecha_cobro == fecha_obj)
            .all()
        )
        operacion_general = {
            "traslados_despachados_hoy": despachados_hoy,
            "traslados_recibidos_hoy": recibidos_hoy,
            "preparaciones_hoy": preparaciones_hoy,
            "cashea_dia": {
                "cantidad": len(casheas_hoy),
                "total_regular_usd": _r2(sum((Decimal(c.total_precio_regular_usd or 0) for c in casheas_hoy), Decimal("0"))),
                "inicial_usd": _r2(sum((Decimal(c.inicial_cobrada_usd or 0) for c in casheas_hoy), Decimal("0"))),
                "financiado_usd": _r2(sum((Decimal(c.monto_financiado_usd or 0) for c in casheas_hoy), Decimal("0"))),
                "cargos_usd": _r2(sum((Decimal(c.cashea_total_cargos_usd or 0) for c in casheas_hoy), Decimal("0"))),
                "neto_por_cobrar_usd": _r2(sum((Decimal(c.cashea_neto_por_cobrar_usd or 0) for c in casheas_hoy), Decimal("0"))),
                "cobrado_hoy_usd": _r2(sum((Decimal(c.monto_cobrado_usd or 0) for c in casheas_cobrados_hoy), Decimal("0"))),
            },
        }

    return {
        "resumen_financiero": {
            "ingresos_totales_usd": _r2(ingresos_totales_usd),
            "egresos_totales_usd": _r2(egresos_totales_usd),
            "flujo_neto_usd": _r2(ingresos_totales_usd - egresos_totales_usd),
            "liquidez_total_usd": _r2(liquidez_total_usd),
        },
        "egresos_dia": {
            "total_usd": _r2(egresos_totales_usd),
            "gastos_operativos_usd": _r2(egresos_cat["gastos_operativos"]),
            "envios_delivery_usd": _r2(egresos_cat["envios_delivery"]),
            "nomina_usd": _r2(egresos_cat["nomina"]),
            "comisiones_usd": _r2(egresos_cat["comisiones"]),
            "proveedores_prestamos_usd": _r2(egresos_cat["proveedores_prestamos"]),
            "impuestos_usd": _r2(egresos_cat["impuestos"]),
            "otros_egresos_usd": _r2(egresos_cat["otros_egresos"]),
            "items": egresos_items,
        },
        "saldos_cajas": saldos_cajas,
        "comparativa_tiendas": comparativa_tiendas,
        "movimientos_dia": movimientos_dia,
        "operacion_general": operacion_general,
    }


def generar_mensaje_whatsapp_cierre(
    snapshot: dict[str, Any],
    observaciones: str = "",
) -> str:
    """Genera el mensaje de cierre listo para WhatsApp, diferenciado por TIENDA vs GENERAL."""
    alcance = snapshot.get("alcance", "TIENDA")
    j = snapshot["jornada"]
    v = snapshot["ventas_dia"]
    rec = snapshot["recibido_por_instrumento"]
    rec_alm = snapshot["recepciones_almacen"]
    inv = snapshot["inventario"]
    gar = snapshot["garantias_casos"]
    asesores = snapshot.get("ventas_por_asesor", [])

    def _usd(n: float | int) -> str:
        return f"${float(n or 0):,.2f}"

    def _bs(n: float | int) -> str:
        return f"Bs {float(n or 0):,.2f}"

    if alcance == "GENERAL":
        rf = snapshot.get("resumen_financiero") or {}
        eg = snapshot.get("egresos_dia") or {}
        comp = snapshot.get("comparativa_tiendas") or []
        cajas = snapshot.get("saldos_cajas") or []
        op = snapshot.get("operacion_general") or {}
        cashea = op.get("cashea_dia") or {}

        lineas = [
            "🏦 *CIERRE DIARIO — ADMINISTRACIÓN GENERAL (CONSOLIDADO)*",
            f"📅 Fecha: *{j['fecha']}*",
            f"💱 Tasas: BCV {_bs(j['tasa_bcv'])} | USDT {_bs(j['tasa_usdt'])} | Recargo {j['porcentaje_recargo']}%",
            "",
            "📊 *RESUMEN POR TIENDA Y ADMINISTRACIÓN:*",
        ]
        for c in comp:
            if c["cantidad_ventas"] == 0 and c["ingresos_usd"] == 0 and c["egresos_usd"] == 0:
                continue
            lineas.append(
                f"• *{c['nombre']}*: {c['cantidad_ventas']} ventas ({_usd(c['ventas_promo_usd'])}) | "
                f"Ing: {_usd(c['ingresos_usd'])} | Egr: {_usd(c['egresos_usd'])}"
            )

        lineas.extend(
            [
                "",
                "💰 *TOTALES GENERALES DEL DÍA:*",
                f"• Ingresos Totales: *{_usd(rf.get('ingresos_totales_usd', 0))}*",
                f"• Egresos Totales: *{_usd(rf.get('egresos_totales_usd', 0))}*",
                f"• Flujo Neto del Día: *{_usd(rf.get('flujo_neto_usd', 0))}*",
                f"• Liquidez Total Disponible: *{_usd(rf.get('liquidez_total_usd', 0))}*",
            ]
        )

        if float(eg.get("total_usd", 0)) > 0:
            lineas.append("")
            lineas.append("📤 *DESGLOSE DE EGRESOS:*")
            etiquetas_eg = [
                ("gastos_operativos_usd", "Gastos Operativos"),
                ("envios_delivery_usd", "Envíos / Delivery"),
                ("nomina_usd", "Nómina"),
                ("comisiones_usd", "Comisiones"),
                ("proveedores_prestamos_usd", "Proveedores / Préstamos"),
                ("impuestos_usd", "Impuestos"),
                ("otros_egresos_usd", "Otros Egresos"),
            ]
            for clave, titulo in etiquetas_eg:
                val = float(eg.get(clave, 0))
                if val > 0:
                    lineas.append(f"• {titulo}: {_usd(val)}")

        if rec["items"]:
            lineas.append("")
            lineas.append("💳 *INGRESOS POR INSTRUMENTO:*")
            for it in rec["items"]:
                monto_nat = _bs(it["total_moneda_origen"]) if it["moneda"] == "BS" else f"{_usd(it['total_moneda_origen'])} {it['moneda']}"
                lineas.append(f"• {it['instrumento']}: {monto_nat} ({_usd(it['total_usd'])})")

        if cashea.get("cantidad", 0) > 0:
            lineas.append("")
            lineas.append(
                f"🟣 *CASHEA DEL DÍA:* {cashea['cantidad']} ventas · Inicial {_usd(cashea.get('inicial_usd', 0))} · "
                f"Financiado {_usd(cashea.get('financiado_usd', 0))} · Neto CxC {_usd(cashea.get('neto_por_cobrar_usd', 0))}"
            )

        lineas.extend(
            [
                "",
                "📦 *OPERACIÓN DEL DÍA:*",
                f"• Traslados: {op.get('traslados_despachados_hoy', 0)} despachados | {op.get('traslados_recibidos_hoy', 0)} recibidos",
                f"• Preparaciones taller: {op.get('preparaciones_hoy', 0)}",
                f"• Garantías / ST: {len(gar['recibidas_hoy'])} recibidas | {len(gar['resueltas_hoy'])} resueltas | {gar['pendientes']['total']} pendientes",
                f"• Stock disponible total: {inv['disponible_cierre']['total_equipos']} equipos y {inv['disponible_cierre']['total_componentes']} comp./acc.",
            ]
        )

        cajas_liq = [c for c in cajas if c["es_liquidez"] and (c["saldo_final"] != 0 or c["entradas"] != 0 or c["salidas"] != 0)]
        if cajas_liq:
            lineas.append("")
            lineas.append("🏦 *SALDOS DE CAJAS Y BANCOS:*")
            for c in cajas_liq:
                saldo_nat = _bs(c["saldo_final"]) if c["moneda"] == "BS" else f"{_usd(c['saldo_final'])} {c['moneda']}"
                lineas.append(f"• {c['nombre']}: *{saldo_nat}* ({_usd(c['saldo_final_usd'])})")

        if observaciones.strip():
            lineas.extend(["", f"📝 *Observaciones:* {observaciones.strip()}"])

        return "\n".join(lineas)

    # Mensaje estrictamente de TIENDA (sin costos internos, sin comisiones, sin finanzas globales)
    sede_titulo = (j.get("sucursal_nombre") or "TIENDA").upper()
    lineas = [
        f"🏪 *CIERRE DIARIO — {sede_titulo}*",
        f"📅 Fecha: *{j['fecha']}*",
        f"👤 Encargado: *{j.get('encargado_sugerido_nombre') or 'No asignado'}*",
        f"💱 Tasas: BCV {_bs(j['tasa_bcv'])} | USDT {_bs(j['tasa_usdt'])} | Recargo {j['porcentaje_recargo']}%",
        "",
        "🛒 *VENTAS DEL DÍA:*",
        f"• Total ventas: *{v['cantidad_total']}* ({_usd(v['total_promo_usd'])} Promo)",
        f"• Pasillo: {v['pasillo_cantidad']} ({_usd(v['pasillo_usd'])}) | Lead: {v['lead_cantidad']} ({_usd(v['lead_usd'])})",
    ]
    if v["cashea_cantidad"] > 0:
        lineas.append(
            f"• Cashea: {v['cashea_cantidad']} · Inicial {_usd(v['cashea_inicial_usd'])} · Financiado {_usd(v['cashea_financiado_usd'])}"
        )

    lineas.append("")
    lineas.append(f"💳 *RECIBIDO EN TIENDA ({_usd(rec['total_usd'])}):*")
    if rec["items"]:
        for it in rec["items"]:
            monto_nat = _bs(it["total_moneda_origen"]) if it["moneda"] == "BS" else f"{_usd(it['total_moneda_origen'])} {it['moneda']}"
            lineas.append(f"• {it['instrumento']}: {monto_nat} ({_usd(it['total_usd'])})")
    else:
        lineas.append("• Sin cobros registrados hoy")

    lineas.extend(
        [
            "",
            "📦 *INVENTARIO DE TIENDA:*",
            f"• Recepciones hoy: {rec_alm['total_unidades']} unid.",
            f"• Salidas hoy: {inv['salidas_hoy']['total_unidades']} unid.",
            f"• Stock disponible al cierre: *{inv['disponible_cierre']['total_equipos']} equipos* y *{inv['disponible_cierre']['total_componentes']} comp./acc.*",
            "",
            "🛠️ *GARANTÍAS Y SERVICIOS TÉCNICOS:*",
            f"• Recibidos hoy: {len(gar['recibidas_hoy'])} | Resueltos hoy: {len(gar['resueltas_hoy'])} | Pendientes: {gar['pendientes']['total']}",
        ]
    )

    if asesores:
        lineas.append("")
        lineas.append("👥 *RESUMEN DE VENTAS POR ASESOR:*")
        for a in asesores:
            lineas.append(
                f"• {a['nombre']}: {a['total_ventas']} ventas ({a['cantidad_pasillo']}P / {a['cantidad_lead']}L) · {_usd(a['total_usd'])}"
            )

    if observaciones.strip():
        lineas.extend(["", f"📝 *Observaciones:* {observaciones.strip()}"])

    return "\n".join(lineas)
