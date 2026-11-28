from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.configuracion import configuracion
from app.modelos import CatalogoArticulo, RolUsuario, Sucursal, TasaDiaria, TipoArticulo, Usuario
from app.modelos_finanzas import (
    CierreDiario,
    EstadoVenta,
    OrigenVenta,
    Pago,
    TipoDocumentoPago,
    TipoMovimientoPago,
    Venta,
    VentaDetalle,
)
from app.modelos_logistica import (
    Equipo,
    EstadoEquipo,
    EstadoTraslado,
    MovimientoInventario,
    Traslado,
    TrasladoDetalle,
)
from app.modelos_operaciones import DevolucionGarantia
from app.modelos_taller import (
    CasoPostventa,
    EstadoCasoPostventa,
    EstadoOrdenRecepcion,
    OrdenRecepcionTecnica,
)
from app.rutas.tasas import obtener_fecha_hoy
from app.rutas.ventas import redondear_usd
from app.seguridad import es_administrador, es_director_solo_lectura, requerir_roles
from app.servicios.cierre_diario_servicio import (
    calcular_saldos_cajas_y_movimientos,
    generar_mensaje_whatsapp_cierre,
)


enrutador = APIRouter(prefix="/api/cierre-diario", tags=["Cierre Diario de Tienda"])

ROLES_CIERRE_DIARIO = (
    RolUsuario.DIRECCION.value,
    RolUsuario.ADMINISTRACION.value,
    RolUsuario.DIRECTOR.value,
    RolUsuario.ENCARGADO_TIENDA.value,
    RolUsuario.LIDER.value,
)

ROLES_EJECUTIVOS_CIERRE = (
    RolUsuario.DIRECCION.value,
    RolUsuario.ADMINISTRACION.value,
    RolUsuario.DIRECTOR.value,
)


class CierreDiarioGuardarEntrada(BaseModel):
    fecha: date | None = None
    sucursal_id: int | None = None
    encargado_tienda_id: int
    observaciones: str = Field(default="", max_length=2000)


def _fecha_caracas(dt: datetime | None) -> date | None:
    if dt is None:
        return None
    tz = ZoneInfo(configuracion.ZONA_HORARIA)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date()


def calcular_snapshot_cierre_diario(
    bd: Session,
    fecha_obj: date,
    sucursal_id: int | None = None,
    alcance: str = "TIENDA",
    es_vista_ejecutiva: bool = False,
) -> dict[str, Any]:
    """Calcula en vivo el movimiento operativo y comercial de tienda del día (SIN liquidaciones ni pagos de comisiones)."""
    sucursal_obj = (
        bd.query(Sucursal).filter(Sucursal.id == sucursal_id).first()
        if sucursal_id is not None
        else None
    )

    # 1. Datos de Jornada: Tasas del día + Encargados de Tienda disponibles
    tasa = bd.query(TasaDiaria).filter(TasaDiaria.fecha == fecha_obj).first()
    if tasa is None:
        tasa = bd.query(TasaDiaria).order_by(TasaDiaria.fecha.desc()).first()

    tasa_bcv = float(tasa.tasa_bcv) if tasa else 0.0
    tasa_usdt = float(tasa.tasa_usdt) if tasa else 0.0
    pct_recargo = float(tasa.recargo_porcentaje) if tasa else 0.0

    encargados = (
        bd.query(Usuario)
        .filter(
            Usuario.activo.is_(True),
            Usuario.rol.in_(
                [
                    RolUsuario.ENCARGADO_TIENDA.value,
                    RolUsuario.LIDER.value,
                    RolUsuario.DIRECCION.value,
                    RolUsuario.ADMINISTRACION.value,
                ]
            ),
        )
        .order_by(Usuario.nombre.asc())
        .all()
    )
    encargado_sug = next(
        (
            u
            for u in encargados
            if u.rol in (RolUsuario.ENCARGADO_TIENDA.value, RolUsuario.LIDER.value)
            and (sucursal_id is None or u.sucursal_id == sucursal_id)
        ),
        encargados[0] if encargados else None,
    )

    cierre_prev = (
        bd.query(CierreDiario)
        .filter(
            CierreDiario.fecha == fecha_obj,
            CierreDiario.sucursal_id == sucursal_id,
        )
        .first()
    )

    # 2. Ventas del Día (excluyendo ANULADA)
    q_ventas = (
        bd.query(Venta)
        .options(
            joinedload(Venta.asesor),
            joinedload(Venta.cliente),
            joinedload(Venta.detalles).joinedload(VentaDetalle.equipo),
            joinedload(Venta.detalles).joinedload(VentaDetalle.articulo),
            joinedload(Venta.pagos).joinedload(Pago.instrumento),
        )
        .filter(
            Venta.fecha == fecha_obj,
            Venta.estado != EstadoVenta.ANULADA.value,
        )
    )
    if sucursal_id is not None:
        q_ventas = q_ventas.filter(Venta.sucursal_id == sucursal_id)
    ventas = q_ventas.order_by(Venta.id.asc()).all()

    total_promo_usd = Decimal("0")
    total_regular_usd = Decimal("0")
    pasillo_cant = 0
    pasillo_usd = Decimal("0")
    lead_cant = 0
    lead_usd = Decimal("0")
    cashea_cant = 0
    cashea_inicial_usd = Decimal("0")
    cashea_financiado_usd = Decimal("0")

    # 7. Resumen aparte de ventas por asesor (SIN comisiones)
    asesores_map: dict[int, dict[str, Any]] = {}
    ventas_tienda_sin_asesor = {"cantidad": 0, "usd": Decimal("0")}

    # 5a. Salidas de inventario por ventas de hoy
    salidas_items: list[dict[str, Any]] = []

    for v in ventas:
        total_promo_usd += v.total_promo_usd
        total_regular_usd += v.total_regular_usd

        origen_vta = (getattr(v, "origen_venta", OrigenVenta.PASILLO.value) or OrigenVenta.PASILLO.value).upper()
        if origen_vta == OrigenVenta.LEAD.value:
            lead_cant += 1
            lead_usd += v.total_promo_usd
        else:
            pasillo_cant += 1
            pasillo_usd += v.total_promo_usd

        # Cashea breakdown
        pagos_act = [p for p in v.pagos if not p.anulado]
        pagos_cashea = [
            p for p in pagos_act if p.instrumento and "cashea" in p.instrumento.nombre.lower()
        ]
        if pagos_cashea:
            cashea_cant += 1
            fin = sum((p.usd_nominal for p in pagos_cashea), Decimal("0"))
            ini = sum(
                (p.usd_nominal for p in pagos_act if p not in pagos_cashea),
                Decimal("0"),
            )
            cashea_financiado_usd += fin
            cashea_inicial_usd += ini

        # Resumen por asesor (solo ventas, cero comisiones)
        if v.asesor_id is not None and v.asesor is not None:
            if v.asesor_id not in asesores_map:
                asesores_map[v.asesor_id] = {
                    "personal_id": v.asesor_id,
                    "nombre": v.asesor.nombre,
                    "rol": v.asesor.rol,
                    "modalidad": getattr(v.asesor, "modalidad", "PRESENCIAL") or "PRESENCIAL",
                    "cantidad_pasillo": 0,
                    "cantidad_lead": 0,
                    "total_ventas": 0,
                    "total_usd": Decimal("0"),
                }
            a_rec = asesores_map[v.asesor_id]
            a_rec["total_ventas"] += 1
            if origen_vta == OrigenVenta.LEAD.value:
                a_rec["cantidad_lead"] += 1
            else:
                a_rec["cantidad_pasillo"] += 1
            a_rec["total_usd"] += v.total_promo_usd
        else:
            ventas_tienda_sin_asesor["cantidad"] += 1
            ventas_tienda_sin_asesor["usd"] += v.total_promo_usd

        # Salidas de inventario (equipos y componentes vendidos hoy)
        for det in v.detalles:
            es_serv = det.articulo is not None and det.articulo.tipo == TipoArticulo.SERVICIO.value
            if es_serv:
                continue
            salidas_items.append(
                {
                    "motivo": "VENTA",
                    "documento": v.numero_venta,
                    "descripcion": det.descripcion or (det.equipo.modelo if det.equipo else "Artículo"),
                    "serial": det.equipo.serial if det.equipo else None,
                    "cantidad": det.cantidad,
                }
            )

    # 3. Todo lo Recibido por Instrumento de Pago (STRICTLY INGRESO, EXCLUYENDO COMISIONES / LIQUIDACIONES)
    q_pagos = (
        bd.query(Pago)
        .options(joinedload(Pago.instrumento), joinedload(Pago.venta))
        .filter(
            Pago.fecha == fecha_obj,
            Pago.anulado.is_(False),
            Pago.tipo_movimiento == TipoMovimientoPago.INGRESO.value,
            Pago.tipo_documento != TipoDocumentoPago.COMISION.value,
            Pago.origen_tipo != "LIQUIDACION_COMISION",
        )
    )
    pagos_dia = q_pagos.all()
    if sucursal_id is not None:
        pagos_dia = [p for p in pagos_dia if p.venta is not None and p.venta.sucursal_id == sucursal_id]

    recibido_map: dict[int, dict[str, Any]] = {}
    total_recibido_usd = Decimal("0")
    for p in pagos_dia:
        inst = p.instrumento
        if inst is None:
            continue
        if inst.id not in recibido_map:
            recibido_map[inst.id] = {
                "instrumento_id": inst.id,
                "instrumento": inst.nombre,
                "moneda": p.moneda,
                "cantidad_pagos": 0,
                "total_moneda_origen": Decimal("0"),
                "total_usd": Decimal("0"),
            }
        rec = recibido_map[inst.id]
        rec["cantidad_pagos"] += 1
        rec["total_moneda_origen"] += p.monto_moneda_origen
        rec["total_usd"] += p.usd_nominal
        total_recibido_usd += p.usd_nominal

    recibido_lista = [
        {
            "instrumento_id": r["instrumento_id"],
            "instrumento": r["instrumento"],
            "moneda": r["moneda"],
            "cantidad_pagos": r["cantidad_pagos"],
            "total_moneda_origen": redondear_usd(r["total_moneda_origen"]),
            "total_usd": redondear_usd(r["total_usd"]),
        }
        for r in sorted(recibido_map.values(), key=lambda x: (-float(x["total_usd"]), x["instrumento"]))
    ]

    # 4. Recepciones de Equipos / Componentes desde Almacén en la fecha
    recepciones_items: list[dict[str, Any]] = []
    q_traslados = (
        bd.query(Traslado)
        .options(
            joinedload(Traslado.origen),
            joinedload(Traslado.destino),
            joinedload(Traslado.detalles).joinedload(TrasladoDetalle.equipo),
            joinedload(Traslado.detalles).joinedload(TrasladoDetalle.articulo),
        )
        .filter(Traslado.estado == EstadoTraslado.RECIBIDO.value)
    )
    if sucursal_id is not None:
        q_traslados = q_traslados.filter(Traslado.destino_id == sucursal_id)

    for tr in q_traslados.all():
        if _fecha_caracas(tr.fecha_recepcion) != fecha_obj:
            continue
        origen_nom = tr.origen.nombre if tr.origen else "Almacén"
        for d in tr.detalles:
            if d.equipo is not None:
                recepciones_items.append(
                    {
                        "origen": origen_nom,
                        "documento": tr.numero_traslado,
                        "tipo": "EQUIPO",
                        "descripcion": d.equipo.modelo or "Equipo",
                        "serial": d.equipo.serial,
                        "cantidad": 1,
                    }
                )
            elif d.articulo is not None:
                recepciones_items.append(
                    {
                        "origen": origen_nom,
                        "documento": tr.numero_traslado,
                        "tipo": "COMPONENTE",
                        "descripcion": f"{d.articulo.sku} · {d.articulo.descripcion}",
                        "serial": None,
                        "cantidad": d.cantidad,
                    }
                )

    # También incluir equipos recibidos directamente en la fecha (que no vinieron por traslado hoy)
    seriales_en_traslado = {item["serial"] for item in recepciones_items if item["serial"]}
    q_eq_rec = bd.query(Equipo).filter(Equipo.fecha_recepcion == fecha_obj)
    if sucursal_id is not None:
        q_eq_rec = q_eq_rec.filter(Equipo.ubicacion_id == sucursal_id)
    for eq in q_eq_rec.all():
        if eq.serial not in seriales_en_traslado:
            recepciones_items.append(
                {
                    "origen": "Ingreso directo / Compra",
                    "documento": f"CMP-{eq.compra_id}" if eq.compra_id else "INGRESO",
                    "tipo": "EQUIPO",
                    "descripcion": eq.modelo or "Equipo",
                    "serial": eq.serial,
                    "cantidad": 1,
                }
            )

    total_recepciones_unidades = sum(int(i["cantidad"]) for i in recepciones_items)

    # 5b. Stock disponible al cierre del día
    q_eq_disp = bd.query(Equipo).filter(Equipo.estado == EstadoEquipo.LISTO.value)
    if sucursal_id is not None:
        q_eq_disp = q_eq_disp.filter(Equipo.ubicacion_id == sucursal_id)
    equipos_disp = q_eq_disp.all()

    modelos_disp: dict[tuple[str, str], int] = {}
    for eq in equipos_disp:
        clave = (eq.modelo or "Sin modelo", eq.categoria or "Laptop")
        modelos_disp[clave] = modelos_disp.get(clave, 0) + 1

    equipos_por_modelo = [
        {"modelo": mod, "categoria": cat, "cantidad": cnt}
        for (mod, cat), cnt in sorted(modelos_disp.items(), key=lambda x: (-x[1], x[0][0]))
    ]

    # Stock disponible de componentes/accesorios (desde MovimientoInventario)
    q_movs = bd.query(MovimientoInventario).filter(MovimientoInventario.articulo_id.isnot(None))
    if sucursal_id is not None:
        q_movs = q_movs.filter(MovimientoInventario.sucursal_id == sucursal_id)
    stock_art: dict[int, int] = {}
    for m in q_movs.all():
        if m.articulo_id is None:
            continue
        stock_art[m.articulo_id] = stock_art.get(m.articulo_id, 0) + int(m.cantidad)

    art_ids_pos = [aid for aid, qty in stock_art.items() if qty > 0]
    articulos_map = (
        {
            a.id: a
            for a in bd.query(CatalogoArticulo)
            .filter(
                CatalogoArticulo.id.in_(art_ids_pos),
                CatalogoArticulo.tipo != TipoArticulo.SERVICIO.value,
            )
            .all()
        }
        if art_ids_pos
        else {}
    )
    componentes_stock = [
        {
            "sku": articulos_map[aid].sku,
            "descripcion": articulos_map[aid].descripcion,
            "cantidad": stock_art[aid],
        }
        for aid in art_ids_pos
        if aid in articulos_map
    ]
    componentes_stock.sort(key=lambda x: (-x["cantidad"], x["descripcion"]))

    total_equipos_disp = len(equipos_disp)
    total_comp_disp = sum(c["cantidad"] for c in componentes_stock)

    # 6. Garantías y Casos (Recibidas hoy, Resueltas hoy y Pendientes)
    q_casos = bd.query(CasoPostventa).options(joinedload(CasoPostventa.cliente))
    if sucursal_id is not None:
        q_casos = q_casos.filter(CasoPostventa.sucursal_id == sucursal_id)
    todos_casos = q_casos.order_by(CasoPostventa.id.desc()).all()

    estados_cerrados = {EstadoCasoPostventa.ENTREGADO.value, EstadoCasoPostventa.RECHAZADO.value}
    recibidas_hoy: list[dict[str, Any]] = []
    resueltas_hoy: list[dict[str, Any]] = []
    pendientes_casos: list[dict[str, Any]] = []

    for c in todos_casos:
        cli_nom = c.cliente.nombre if c.cliente else "Cliente general"
        f_ing = _fecha_caracas(c.fecha_ingreso)
        f_cie = _fecha_caracas(c.fecha_cierre)
        if f_ing == fecha_obj:
            recibidas_hoy.append(
                {
                    "numero_caso": c.numero_caso,
                    "tipo": c.tipo,
                    "cliente": cli_nom,
                    "equipo": c.descripcion_equipo,
                    "serial": c.serial_o_codigo,
                    "motivo": c.falla_reportada,
                }
            )
        if f_cie == fecha_obj or (
            c.estado in (EstadoCasoPostventa.TERMINADO.value, EstadoCasoPostventa.ENTREGADO.value)
            and f_ing == fecha_obj
        ):
            resueltas_hoy.append(
                {
                    "numero": c.numero_caso,
                    "tipo": c.tipo,
                    "cliente": cli_nom,
                    "equipo": c.descripcion_equipo,
                    "resolucion": c.trabajo_realizado or c.estado,
                }
            )
        if c.estado not in estados_cerrados:
            pendientes_casos.append(
                {
                    "numero_caso": c.numero_caso,
                    "tipo": c.tipo,
                    "cliente": cli_nom,
                    "equipo": c.descripcion_equipo,
                    "serial": c.serial_o_codigo,
                    "estado": c.estado,
                    "fecha_ingreso": f_ing.isoformat() if f_ing else "",
                }
            )

    # También incluir Órdenes de Recepción Técnica (GAR-XXXX / ST-XXXX)
    q_ord = bd.query(OrdenRecepcionTecnica)
    if sucursal_id is not None:
        q_ord = q_ord.filter(OrdenRecepcionTecnica.sucursal_id == sucursal_id)
    estados_ord_cerrados = {
        EstadoOrdenRecepcion.RESUELTO_ENTREGADO.value,
        EstadoOrdenRecepcion.NO_REPARADO_ENTREGADO.value,
    }
    for o in q_ord.order_by(OrdenRecepcionTecnica.id.desc()).all():
        f_rec_o = _fecha_caracas(o.fecha_recepcion)
        f_res_o = _fecha_caracas(o.fecha_resolucion)
        eq_desc = f"{o.marca} {o.modelo}".strip() or o.modelo
        if f_rec_o == fecha_obj:
            recibidas_hoy.append(
                {
                    "numero_caso": o.codigo,
                    "tipo": o.tipo_orden,
                    "cliente": o.cliente_nombre or "Cliente general",
                    "equipo": eq_desc,
                    "serial": o.serial,
                    "motivo": o.falla_declarada_cliente,
                }
            )
        if f_res_o == fecha_obj or (o.estado in estados_ord_cerrados and f_rec_o == fecha_obj):
            resueltas_hoy.append(
                {
                    "numero": o.codigo,
                    "tipo": o.tipo_orden,
                    "cliente": o.cliente_nombre or "Cliente general",
                    "equipo": eq_desc,
                    "resolucion": o.solucion_aplicada or o.estado,
                }
            )
        if o.estado not in estados_ord_cerrados:
            pendientes_casos.append(
                {
                    "numero_caso": o.codigo,
                    "tipo": o.tipo_orden,
                    "cliente": o.cliente_nombre or "Cliente general",
                    "equipo": eq_desc,
                    "serial": o.serial,
                    "estado": o.estado,
                    "fecha_ingreso": f_rec_o.isoformat() if f_rec_o else "",
                }
            )

    # También incluir Devoluciones / Cambios resueltos hoy
    q_devs = (
        bd.query(DevolucionGarantia)
        .options(
            joinedload(DevolucionGarantia.venta).joinedload(Venta.cliente),
            joinedload(DevolucionGarantia.equipo_destino),
            joinedload(DevolucionGarantia.equipo_origen),
        )
        .filter(DevolucionGarantia.fecha == fecha_obj)
    )
    for dev in q_devs.all():
        if sucursal_id is not None and dev.venta is not None and dev.venta.sucursal_id != sucursal_id:
            continue
        cli_dev = dev.venta.cliente.nombre if dev.venta and dev.venta.cliente else "Cliente general"
        resueltas_hoy.append(
            {
                "numero": dev.numero_operacion,
                "tipo": dev.tipo_resolucion,
                "cliente": cli_dev,
                "equipo": (
                    dev.equipo_origen.modelo
                    if dev.equipo_origen
                    else (dev.equipo_destino.modelo if dev.equipo_destino else "Equipo")
                ),
                "resolucion": dev.motivo or dev.tipo_resolucion,
            }
        )
        if dev.equipo_destino is not None:
            salidas_items.append(
                {
                    "motivo": "CAMBIO / GARANTÍA",
                    "documento": dev.numero_operacion,
                    "descripcion": dev.equipo_destino.modelo or "Equipo reemplazo",
                    "serial": dev.equipo_destino.serial,
                    "cantidad": 1,
                }
            )

    ventas_por_asesor = [
        {
            "personal_id": a["personal_id"],
            "nombre": a["nombre"],
            "rol": a["rol"],
            "modalidad": a["modalidad"],
            "cantidad_pasillo": a["cantidad_pasillo"],
            "cantidad_lead": a["cantidad_lead"],
            "total_ventas": a["total_ventas"],
            "total_usd": redondear_usd(a["total_usd"]),
        }
        for a in sorted(asesores_map.values(), key=lambda x: (-float(x["total_usd"]), x["nombre"]))
    ]

    alcance_norm = (alcance or "TIENDA").upper()
    snapshot: dict[str, Any] = {
        "alcance": alcance_norm,
        "jornada": {
            "fecha": fecha_obj.isoformat(),
            "sucursal_id": sucursal_id,
            "sucursal_nombre": (
                sucursal_obj.nombre
                if sucursal_obj
                else ("Administración General (Consolidado)" if alcance_norm == "GENERAL" else "Todas las sucursales")
            ),
            "encargado_sugerido_id": (
                cierre_prev.encargado_tienda_id
                if cierre_prev
                else (encargado_sug.id if encargado_sug else None)
            ),
            "encargado_sugerido_nombre": (
                cierre_prev.encargado_tienda_nombre
                if cierre_prev
                else (encargado_sug.nombre if encargado_sug else "")
            ),
            "encargados_disponibles": [
                {"id": u.id, "nombre": u.nombre, "rol": u.rol} for u in encargados
            ],
            "tasa_bcv": tasa_bcv,
            "tasa_usdt": tasa_usdt,
            "porcentaje_recargo": pct_recargo,
            "ya_cerrado": cierre_prev is not None,
            "cierre_existente_id": cierre_prev.id if cierre_prev else None,
            "observaciones_guardadas": cierre_prev.observaciones if cierre_prev else "",
        },
        "ventas_dia": {
            "cantidad_total": len(ventas),
            "total_promo_usd": redondear_usd(total_promo_usd),
            "total_regular_usd": redondear_usd(total_regular_usd),
            "pasillo_cantidad": pasillo_cant,
            "pasillo_usd": redondear_usd(pasillo_usd),
            "lead_cantidad": lead_cant,
            "lead_usd": redondear_usd(lead_usd),
            "cashea_cantidad": cashea_cant,
            "cashea_inicial_usd": redondear_usd(cashea_inicial_usd),
            "cashea_financiado_usd": redondear_usd(cashea_financiado_usd),
        },
        "recibido_por_instrumento": {
            "total_usd": redondear_usd(total_recibido_usd),
            "items": recibido_lista,
        },
        "recepciones_almacen": {
            "total_unidades": total_recepciones_unidades,
            "items": recepciones_items,
        },
        "inventario": {
            "salidas_hoy": {
                "total_unidades": sum(int(i["cantidad"]) for i in salidas_items),
                "items": salidas_items,
            },
            "disponible_cierre": {
                "total_equipos": total_equipos_disp,
                "total_componentes": total_comp_disp,
                "total_unidades": total_equipos_disp + total_comp_disp,
                "equipos_por_modelo": equipos_por_modelo,
                "componentes_stock": componentes_stock,
            },
        },
        "garantias_casos": {
            "recibidas_hoy": recibidas_hoy,
            "resueltas_hoy": resueltas_hoy,
            "pendientes": {
                "total": len(pendientes_casos),
                "items": pendientes_casos[:30],
            },
        },
        "ventas_por_asesor": ventas_por_asesor,
        "ventas_tienda_sin_asesor": {
            "cantidad": ventas_tienda_sin_asesor["cantidad"],
            "total_usd": redondear_usd(ventas_tienda_sin_asesor["usd"]),
        },
    }

    if es_vista_ejecutiva:
        fin_data = calcular_saldos_cajas_y_movimientos(
            bd=bd,
            fecha_obj=fecha_obj,
            tasa_bcv=tasa_bcv,
            sucursal_id=None if alcance_norm == "GENERAL" else sucursal_id,
            incluir_saldos_globales=(alcance_norm == "GENERAL"),
        )
        snapshot["resumen_financiero"] = fin_data["resumen_financiero"]
        snapshot["movimientos_dia"] = fin_data["movimientos_dia"]
        snapshot["traspasos_cambios_dia"] = fin_data["traspasos_cambios_dia"]
        if alcance_norm == "GENERAL":
            snapshot["egresos_dia"] = fin_data["egresos_dia"]
            snapshot["saldos_cajas"] = fin_data["saldos_cajas"]
            snapshot["comparativa_tiendas"] = fin_data["comparativa_tiendas"]
            snapshot["operacion_general"] = fin_data["operacion_general"]
        else:
            snapshot["egresos_dia"] = fin_data["egresos_dia"]
            snapshot["saldos_cajas"] = fin_data["saldos_cajas"] if sucursal_id is not None else None
            snapshot["comparativa_tiendas"] = None
            snapshot["operacion_general"] = None
    else:
        # Estricto para ENCARGADO: cero costos internos, cero comisiones, cero finanzas globales
        snapshot["resumen_financiero"] = None
        snapshot["egresos_dia"] = None
        snapshot["saldos_cajas"] = None
        snapshot["comparativa_tiendas"] = None
        snapshot["movimientos_dia"] = None
        snapshot["operacion_general"] = None

    snapshot["mensaje_whatsapp"] = generar_mensaje_whatsapp_cierre(
        snapshot,
        observaciones=snapshot["jornada"]["observaciones_guardadas"],
    )
    return snapshot


@enrutador.get("")
def obtener_cierre_diario_en_vivo(
    fecha: date | None = Query(default=None),
    sucursal_id: int | None = Query(default=None),
    alcance: str | None = Query(default=None, pattern="^(TIENDA|GENERAL)$"),
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_CIERRE_DIARIO)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    fecha_obj = fecha or obtener_fecha_hoy()
    es_ejecutivo = usuario_actual.rol in ROLES_EJECUTIVOS_CIERRE

    if not es_ejecutivo:
        # ENCARGADO / LIDER: bloqueado estrictamente a su propia sucursal y alcance TIENDA
        if alcance == "GENERAL":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El cierre completo de Administración General es exclusivo para Dirección, Administración o Director.",
            )
        if usuario_actual.sucursal_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tu usuario no tiene una tienda asignada para consultar el cierre diario.",
            )
        if sucursal_id is not None and sucursal_id != usuario_actual.sucursal_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo tienes acceso al cierre diario de tu propia tienda asignada.",
            )
        alcance_efectivo = "TIENDA"
        sucursal_efectiva = usuario_actual.sucursal_id
    else:
        if alcance == "GENERAL":
            alcance_efectivo = "GENERAL"
            sucursal_efectiva = None
        elif alcance == "TIENDA":
            alcance_efectivo = "TIENDA"
            sucursal_efectiva = sucursal_id
        else:
            if sucursal_id is not None:
                alcance_efectivo = "TIENDA"
                sucursal_efectiva = sucursal_id
            else:
                alcance_efectivo = "GENERAL"
                sucursal_efectiva = None

    return calcular_snapshot_cierre_diario(
        bd=bd,
        fecha_obj=fecha_obj,
        sucursal_id=sucursal_efectiva,
        alcance=alcance_efectivo,
        es_vista_ejecutiva=es_ejecutivo,
    )


@enrutador.post("/cerrar", status_code=status.HTTP_201_CREATED)
def guardar_cierre_diario(
    datos: CierreDiarioGuardarEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_CIERRE_DIARIO)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    if es_director_solo_lectura(usuario_actual.rol):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El rol Director es de solo lectura y no puede registrar ni modificar cierres.",
        )

    es_admin = es_administrador(usuario_actual.rol)
    sucursal_objetivo = datos.sucursal_id
    if not es_admin:
        if usuario_actual.sucursal_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tu usuario no tiene una tienda asignada.",
            )
        if sucursal_objetivo is not None and sucursal_objetivo != usuario_actual.sucursal_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes guardar el cierre diario de tu propia tienda.",
            )
        sucursal_objetivo = usuario_actual.sucursal_id

    hoy = obtener_fecha_hoy()
    fecha_obj = datos.fecha or hoy
    if fecha_obj < hoy and not es_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo Dirección o Administración pueden registrar o modificar cierres de fechas anteriores.",
        )

    encargado = bd.query(Usuario).filter(Usuario.id == datos.encargado_tienda_id).first()
    if encargado is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El Encargado de Tienda seleccionado no existe.",
        )

    existente = (
        bd.query(CierreDiario)
        .filter(
            CierreDiario.fecha == fecha_obj,
            CierreDiario.sucursal_id == sucursal_objetivo,
        )
        .first()
    )
    if existente is not None and not es_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El cierre diario de esta fecha ya fue registrado. Solo Dirección o Administración pueden reabrirlo o modificarlo.",
        )

    alcance_guardar = "GENERAL" if (es_admin and sucursal_objetivo is None) else "TIENDA"
    snapshot = calcular_snapshot_cierre_diario(
        bd=bd,
        fecha_obj=fecha_obj,
        sucursal_id=sucursal_objetivo,
        alcance=alcance_guardar,
        es_vista_ejecutiva=es_admin,
    )
    snapshot["jornada"]["encargado_sugerido_id"] = encargado.id
    snapshot["jornada"]["encargado_sugerido_nombre"] = encargado.nombre
    snapshot["jornada"]["ya_cerrado"] = True
    snapshot["jornada"]["observaciones_guardadas"] = datos.observaciones.strip()
    snapshot["mensaje_whatsapp"] = generar_mensaje_whatsapp_cierre(
        snapshot,
        observaciones=datos.observaciones.strip(),
    )

    tasa_bcv_dec = Decimal(str(snapshot["jornada"]["tasa_bcv"]))
    tasa_usdt_dec = Decimal(str(snapshot["jornada"]["tasa_usdt"]))
    recargo_dec = Decimal(str(snapshot["jornada"]["porcentaje_recargo"]))
    resumen_str = json.dumps(snapshot, ensure_ascii=False)

    if existente is not None:
        existente.encargado_tienda_id = encargado.id
        existente.encargado_tienda_nombre = encargado.nombre
        existente.tasa_bcv = tasa_bcv_dec
        existente.tasa_usdt = tasa_usdt_dec
        existente.porcentaje_recargo = recargo_dec
        existente.resumen_json = resumen_str
        existente.observaciones = datos.observaciones.strip()
        existente.cerrado_por_id = usuario_actual.id
        cierre = existente
    else:
        cierre = CierreDiario(
            fecha=fecha_obj,
            sucursal_id=sucursal_objetivo,
            encargado_tienda_id=encargado.id,
            encargado_tienda_nombre=encargado.nombre,
            tasa_bcv=tasa_bcv_dec,
            tasa_usdt=tasa_usdt_dec,
            porcentaje_recargo=recargo_dec,
            resumen_json=resumen_str,
            observaciones=datos.observaciones.strip(),
            cerrado_por_id=usuario_actual.id,
        )
        bd.add(cierre)

    bd.commit()
    bd.refresh(cierre)
    return {
        "id": cierre.id,
        "fecha": cierre.fecha.isoformat(),
        "sucursal_id": cierre.sucursal_id,
        "encargado_tienda_id": cierre.encargado_tienda_id,
        "encargado_tienda_nombre": cierre.encargado_tienda_nombre,
        "tasa_bcv": float(cierre.tasa_bcv),
        "tasa_usdt": float(cierre.tasa_usdt),
        "porcentaje_recargo": float(cierre.porcentaje_recargo),
        "observaciones": cierre.observaciones,
        "cerrado_por": usuario_actual.nombre,
        "created_at": cierre.created_at.isoformat() if cierre.created_at else None,
        "resumen": snapshot,
    }


@enrutador.get("/historial")
def listar_historial_cierres_diarios(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    sucursal_id: int | None = Query(default=None),
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_CIERRE_DIARIO)),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    es_ejecutivo = usuario_actual.rol in ROLES_EJECUTIVOS_CIERRE
    if not es_ejecutivo:
        if usuario_actual.sucursal_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tu usuario no tiene una tienda asignada.",
            )
        if sucursal_id is not None and sucursal_id != usuario_actual.sucursal_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes consultar el historial de cierres de tu propia tienda.",
            )
        sucursal_id = usuario_actual.sucursal_id

    consulta = bd.query(CierreDiario).options(
        joinedload(CierreDiario.sucursal),
        joinedload(CierreDiario.cerrado_por),
    )
    if fecha_inicio is not None:
        consulta = consulta.filter(CierreDiario.fecha >= fecha_inicio)
    if fecha_fin is not None:
        consulta = consulta.filter(CierreDiario.fecha <= fecha_fin)
    if sucursal_id is not None:
        consulta = consulta.filter(CierreDiario.sucursal_id == sucursal_id)

    filas = consulta.order_by(CierreDiario.fecha.desc(), CierreDiario.id.desc()).limit(100).all()
    resultado: list[dict[str, Any]] = []
    for c in filas:
        try:
            resumen = json.loads(c.resumen_json or "{}")
        except ValueError:
            resumen = {}
        resultado.append(
            {
                "id": c.id,
                "fecha": c.fecha.isoformat(),
                "sucursal_id": c.sucursal_id,
                "sucursal_nombre": c.sucursal.nombre if c.sucursal else "Administración General (Consolidado)",
                "encargado_tienda_id": c.encargado_tienda_id,
                "encargado_tienda_nombre": c.encargado_tienda_nombre,
                "tasa_bcv": float(c.tasa_bcv),
                "tasa_usdt": float(c.tasa_usdt),
                "porcentaje_recargo": float(c.porcentaje_recargo),
                "observaciones": c.observaciones,
                "cerrado_por": c.cerrado_por.nombre if c.cerrado_por else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "resumen": resumen,
            }
        )
    return resultado
