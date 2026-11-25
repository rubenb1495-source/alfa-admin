from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.configuracion import configuracion
from app.modelos import CatalogoArticulo, CatalogoPrecio, RolUsuario, Sucursal, TipoArticulo, Usuario
from app.modelos_logistica import (
    Equipo,
    EstadoEquipo,
    HistorialEstadoEquipo,
    LoteTransito,
    LoteTransitoItem,
    MovimientoInventario,
    TipoMovimientoInventario,
)
from app.rutas.logistica import generar_correlativo
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import obtener_usuario_actual, requerir_roles
from app.servicios.contabilidad import crear_asiento_contable

enrutador = APIRouter(prefix="/api/logistica/transito", tags=["Inventario en Tránsito y Recepción Flexible"])

ROLES_CREAR_TRANSITO = (
    RolUsuario.DIRECCION.value,
    RolUsuario.ADMINISTRACION.value,
    RolUsuario.LOGISTICA.value,
)
ROLES_RECIBIR_TRANSITO = (
    RolUsuario.DIRECCION.value,
    RolUsuario.ADMINISTRACION.value,
    RolUsuario.LOGISTICA.value,
    RolUsuario.ENCARGADO_TIENDA.value,
    RolUsuario.LIDER.value,
)

MAPA_ESTADO_RECEPCION = {
    "PENDIENTE_REVISION": EstadoEquipo.PENDIENTE_REVISION.value,
    "EN_PREPARACION": EstadoEquipo.EN_PREPARACION.value,
    "POR_INCIDENCIA": EstadoEquipo.DEFECTUOSO.value,
    "DEFECTUOSO": EstadoEquipo.DEFECTUOSO.value,
    "LISTO": EstadoEquipo.LISTO.value,
    "DISPONIBLE": EstadoEquipo.LISTO.value,
}


def _q2(val: Decimal | float | int | str) -> Decimal:
    return Decimal(str(val or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _r2(val: Decimal | float | int | str) -> float:
    return float(_q2(val))


def _ahora_caracas() -> datetime:
    return datetime.now(ZoneInfo(configuracion.ZONA_HORARIA))


class LoteItemCrearEntrada(BaseModel):
    tipo_item: str = Field(default="EQUIPO", pattern="^(EQUIPO|COMPONENTE|ACCESORIO)$")
    articulo_id: int | None = None
    sku: str = Field(default="", max_length=80)
    descripcion_esperada: str = Field(min_length=2, max_length=255)
    especificaciones_esperadas: str = Field(default="", max_length=255)
    cantidad_esperada: int = Field(ge=1)
    costo_unitario_estimado_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    precio_promo_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))

    @field_validator("articulo_id", mode="before")
    @classmethod
    def vacio_a_none(cls, v: Any) -> Any:
        return None if (v == "" or v is None) else v


class LoteTransitoCrearEntrada(BaseModel):
    proveedor_nombre: str = Field(min_length=2, max_length=160)
    almacen_destino_id: int | None = None
    fecha_compra: date | None = None
    fecha_estimada_llegada: date | None = None
    trackings: str = Field(default="", max_length=1000)
    costo_flete_estimado_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    costo_aduana_otros_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    observaciones: str = Field(default="", max_length=1000)
    items: list[LoteItemCrearEntrada] = Field(min_length=1)

    @field_validator("almacen_destino_id", "fecha_compra", "fecha_estimada_llegada", mode="before")
    @classmethod
    def vacios_a_none(cls, v: Any) -> Any:
        return None if (v == "" or v is None) else v


class EquipoRecibidoEntrada(BaseModel):
    serial: str = Field(min_length=2, max_length=100)
    modelo: str | None = Field(default=None, max_length=160)
    especificaciones: str | None = Field(default=None, max_length=255)
    estado_inicial: str = Field(default="PENDIENTE_REVISION")
    precio_promo_usd: Decimal | None = Field(default=None, ge=Decimal("0"))


class ItemRecepcionFlexibleEntrada(BaseModel):
    item_id: int
    descripcion_real: str | None = Field(default=None, max_length=255)
    especificaciones_reales: str | None = Field(default=None, max_length=255)
    cantidad_recibida: int = Field(ge=0)
    cantidad_danada_faltante: int = Field(default=0, ge=0)
    costo_unitario_real_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    precio_promo_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    observacion_recepcion: str = Field(default="", max_length=500)
    equipos_recibidos: list[EquipoRecibidoEntrada] = Field(default_factory=list)


class LoteRecepcionFlexibleEntrada(BaseModel):
    almacen_destino_id: int | None = None
    costo_flete_real_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    costo_aduana_real_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    observaciones: str = Field(default="", max_length=1000)
    items: list[ItemRecepcionFlexibleEntrada] = Field(min_length=1)


def _serializar_lote(lote: LoteTransito) -> dict[str, Any]:
    return {
        "id": lote.id,
        "codigo": lote.codigo,
        "proveedor_nombre": lote.proveedor_nombre,
        "almacen_destino_id": lote.almacen_destino_id,
        "almacen_destino": lote.almacen_destino.nombre if lote.almacen_destino else "",
        "fecha_compra": lote.fecha_compra.isoformat(),
        "fecha_estimada_llegada": lote.fecha_estimada_llegada.isoformat() if lote.fecha_estimada_llegada else None,
        "trackings": lote.trackings,
        "costo_mercancia_estimado_usd": _r2(lote.costo_mercancia_estimado_usd),
        "costo_flete_estimado_usd": _r2(lote.costo_flete_estimado_usd),
        "costo_aduana_otros_usd": _r2(lote.costo_aduana_otros_usd),
        "total_en_transito_usd": _r2(lote.total_en_transito_usd),
        "estado": lote.estado,
        "observaciones": lote.observaciones,
        "creado_por": lote.creado_por.nombre if lote.creado_por else "",
        "recibido_por": lote.recibido_por.nombre if lote.recibido_por else "",
        "fecha_recepcion": lote.fecha_recepcion.isoformat() if lote.fecha_recepcion else None,
        "total_unidades_esperadas": sum(i.cantidad_esperada for i in lote.items),
        "total_unidades_recibidas": sum(i.cantidad_recibida for i in lote.items),
        "items": [
            {
                "id": it.id,
                "tipo_item": it.tipo_item,
                "articulo_id": it.articulo_id,
                "sku": it.sku,
                "descripcion_esperada": it.descripcion_esperada,
                "especificaciones_esperadas": it.especificaciones_esperadas,
                "cantidad_esperada": it.cantidad_esperada,
                "costo_unitario_estimado_usd": _r2(it.costo_unitario_estimado_usd),
                "precio_promo_usd": _r2(it.precio_promo_usd),
                "cantidad_recibida": it.cantidad_recibida,
                "cantidad_danada_faltante": it.cantidad_danada_faltante,
                "descripcion_real": it.descripcion_real,
                "observacion_recepcion": it.observacion_recepcion,
            }
            for it in lote.items
        ],
    }


@enrutador.get("")
def listar_lotes_transito(
    estado: str | None = Query(default=None),
    _usuario: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    consulta = bd.query(LoteTransito).options(
        joinedload(LoteTransito.almacen_destino),
        joinedload(LoteTransito.creado_por),
        joinedload(LoteTransito.recibido_por),
        joinedload(LoteTransito.items),
    )
    if estado and estado.strip():
        consulta = consulta.filter(LoteTransito.estado == estado.strip().upper())
    lotes = consulta.order_by(LoteTransito.id.desc()).limit(100).all()
    return [_serializar_lote(l) for l in lotes]


@enrutador.post("", status_code=status.HTTP_201_CREATED)
def crear_lote_en_transito(
    datos: LoteTransitoCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_CREAR_TRANSITO)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Registra una compra internacional / lote en tránsito SIN exigir seriales todavía, contabilizando en 1.1.04."""
    almacen_id = datos.almacen_destino_id
    if almacen_id is None:
        alm = (
            bd.query(Sucursal)
            .filter(Sucursal.nombre.ilike("%almac%"))
            .order_by(Sucursal.id.asc())
            .first()
        ) or bd.query(Sucursal).order_by(Sucursal.id.asc()).first()
        if alm is None:
            raise HTTPException(status_code=400, detail="No hay almacenes configurados.")
        almacen_id = alm.id
    elif bd.query(Sucursal).filter(Sucursal.id == almacen_id).first() is None:
        raise HTTPException(status_code=404, detail="El almacén de destino no existe.")

    fecha_op = datos.fecha_compra or obtener_fecha_hoy()
    costo_merc = sum(
        (_q2(it.costo_unitario_estimado_usd) * it.cantidad_esperada for it in datos.items),
        Decimal("0.00"),
    )
    flete = _q2(datos.costo_flete_estimado_usd)
    aduana = _q2(datos.costo_aduana_otros_usd)
    total_transito = _q2(costo_merc + flete + aduana)

    codigo = generar_correlativo(bd, LoteTransito, LoteTransito.codigo, "TRN")
    lote = LoteTransito(
        codigo=codigo,
        proveedor_nombre=datos.proveedor_nombre.strip(),
        almacen_destino_id=almacen_id,
        fecha_compra=fecha_op,
        fecha_estimada_llegada=datos.fecha_estimada_llegada,
        trackings=datos.trackings.strip(),
        costo_mercancia_estimado_usd=costo_merc,
        costo_flete_estimado_usd=flete,
        costo_aduana_otros_usd=aduana,
        total_en_transito_usd=total_transito,
        estado="EN_TRANSITO",
        observaciones=datos.observaciones.strip(),
        creado_por_id=usuario_actual.id,
    )
    bd.add(lote)
    bd.flush()

    for it in datos.items:
        bd.add(
            LoteTransitoItem(
                lote_id=lote.id,
                tipo_item=it.tipo_item.upper(),
                articulo_id=it.articulo_id,
                sku=it.sku.strip().upper(),
                descripcion_esperada=it.descripcion_esperada.strip(),
                especificaciones_esperadas=it.especificaciones_esperadas.strip(),
                cantidad_esperada=it.cantidad_esperada,
                costo_unitario_estimado_usd=_q2(it.costo_unitario_estimado_usd),
                precio_promo_usd=_q2(it.precio_promo_usd),
            )
        )

    if total_transito > 0:
        crear_asiento_contable(
            bd=bd,
            usuario=usuario_actual,
            fecha_op=fecha_op,
            descripcion=f"Inventario en Tránsito {codigo} · {lote.proveedor_nombre}",
            origen_tipo="LOTE_TRANSITO",
            origen_id=lote.id,
            lineas=[
                {"cuenta_codigo": "1.1.04", "debe_usd": total_transito, "haber_usd": 0, "nota": f"Mercancía + flete en tránsito {codigo}"},
                {"cuenta_codigo": "2.1.01", "debe_usd": 0, "haber_usd": total_transito, "nota": f"CxP proveedor {lote.proveedor_nombre}"},
            ],
        )

    bd.commit()
    lote_full = (
        bd.query(LoteTransito)
        .options(
            joinedload(LoteTransito.almacen_destino),
            joinedload(LoteTransito.creado_por),
            joinedload(LoteTransito.recibido_por),
            joinedload(LoteTransito.items),
        )
        .filter(LoteTransito.id == lote.id)
        .first()
    )
    return _serializar_lote(lote_full)


def _resolver_o_crear_articulo(
    bd: Session,
    item_lote: LoteTransitoItem,
    descripcion_real: str,
    costo_ref: Decimal,
    precio_promo: Decimal,
    fecha_op: date,
) -> CatalogoArticulo:
    if item_lote.articulo_id:
        art = bd.query(CatalogoArticulo).filter(CatalogoArticulo.id == item_lote.articulo_id).first()
        if art is not None:
            return art
    if item_lote.sku:
        art = bd.query(CatalogoArticulo).filter(CatalogoArticulo.sku == item_lote.sku).first()
        if art is not None:
            return art

    sku_nuevo = item_lote.sku or f"TRN-{item_lote.lote_id}-{item_lote.id}"
    existente = bd.query(CatalogoArticulo).filter(CatalogoArticulo.sku == sku_nuevo).first()
    if existente is not None:
        return existente

    tipo_art = (
        TipoArticulo.EQUIPO.value
        if item_lote.tipo_item == "EQUIPO"
        else (TipoArticulo.ACCESORIO.value if item_lote.tipo_item == "ACCESORIO" else TipoArticulo.COMPONENTE.value)
    )
    nuevo_art = CatalogoArticulo(
        sku=sku_nuevo,
        descripcion=descripcion_real or item_lote.descripcion_esperada,
        tipo=tipo_art,
        categoria="Equipos" if tipo_art == TipoArticulo.EQUIPO.value else "Componentes",
        stock_minimo=2,
        activo=True,
    )
    bd.add(nuevo_art)
    bd.flush()
    bd.add(
        CatalogoPrecio(
            articulo_id=nuevo_art.id,
            costo_referencia_usd=costo_ref,
            precio_promo_usd=precio_promo if precio_promo > 0 else _q2(costo_ref * Decimal("1.5")),
            fecha_vigencia=fecha_op,
        )
    )
    bd.flush()
    return nuevo_art


@enrutador.post("/{lote_id}/recibir")
def recibir_lote_en_almacen(
    lote_id: int,
    datos: LoteRecepcionFlexibleEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_RECIBIR_TRANSITO)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """
    Recepción flexible en almacén (ALM-01):
      - Permite ajustar modelo/specs, cantidad real recibida y marcar dañados/faltantes.
      - Para equipos, ingresa los seriales reales uno por uno con su estado inicial.
      - Recalcula el prorrateo real de flete + aduana sobre las unidades realmente recibidas.
      - Genera el asiento contable moviendo el costo de 1.1.04 En Tránsito -> 1.1.03 Equipos / 1.1.05 Componentes.
    """
    lote = (
        bd.query(LoteTransito)
        .options(
            joinedload(LoteTransito.almacen_destino),
            joinedload(LoteTransito.items),
        )
        .filter(LoteTransito.id == lote_id)
        .first()
    )
    if lote is None:
        raise HTTPException(status_code=404, detail="Lote en tránsito no encontrado.")
    if lote.estado == "RECIBIDO":
        raise HTTPException(status_code=400, detail="Este lote ya fue recibido en su totalidad.")

    almacen_id = datos.almacen_destino_id or lote.almacen_destino_id
    almacen = bd.query(Sucursal).filter(Sucursal.id == almacen_id).first()
    if almacen is None:
        raise HTTPException(status_code=404, detail="Almacén de recepción no encontrado.")

    flete_real = _q2(datos.costo_flete_real_usd) if datos.costo_flete_real_usd is not None else _q2(lote.costo_flete_estimado_usd)
    aduana_real = _q2(datos.costo_aduana_real_usd) if datos.costo_aduana_real_usd is not None else _q2(lote.costo_aduana_otros_usd)
    total_gastos_log = _q2(flete_real + aduana_real)

    mapa_items = {it.id: it for it in lote.items}
    total_unidades_rec = sum(it_in.cantidad_recibida for it_in in datos.items)
    if total_unidades_rec <= 0:
        raise HTTPException(status_code=400, detail="Debes recibir al menos 1 unidad para confirmar la recepción.")

    flete_por_unidad = _q2(total_gastos_log / Decimal(total_unidades_rec)) if total_unidades_rec > 0 else Decimal("0.00")
    hoy = obtener_fecha_hoy()
    ahora = _ahora_caracas()

    equipos_creados = 0
    componentes_recibidos = 0
    valor_equipos_1103 = Decimal("0.00")
    valor_comp_1105 = Decimal("0.00")
    seriales_vistos: set[str] = set()

    for it_in in datos.items:
        item_bd = mapa_items.get(it_in.item_id)
        if item_bd is None:
            raise HTTPException(status_code=404, detail=f"Ítem de lote ID {it_in.item_id} no pertenece al lote {lote.codigo}.")

        desc_real = (it_in.descripcion_real or item_bd.descripcion_esperada).strip()
        specs_real = (it_in.especificaciones_reales or item_bd.especificaciones_esperadas).strip()
        costo_unit = _q2(it_in.costo_unitario_real_usd) if it_in.costo_unitario_real_usd is not None else _q2(item_bd.costo_unitario_estimado_usd)
        precio_p = _q2(it_in.precio_promo_usd) if it_in.precio_promo_usd is not None else _q2(item_bd.precio_promo_usd)

        item_bd.cantidad_recibida = it_in.cantidad_recibida
        item_bd.cantidad_danada_faltante = it_in.cantidad_danada_faltante
        item_bd.descripcion_real = desc_real
        item_bd.observacion_recepcion = it_in.observacion_recepcion.strip()

        if it_in.cantidad_recibida == 0:
            continue

        art = _resolver_o_crear_articulo(bd, item_bd, desc_real, costo_unit, precio_p, hoy)
        item_bd.articulo_id = art.id

        if item_bd.tipo_item == "EQUIPO":
            if len(it_in.equipos_recibidos) != it_in.cantidad_recibida:
                raise HTTPException(
                    status_code=400,
                    detail=f"Para '{desc_real}' indicaste {it_in.cantidad_recibida} recibidos, pero enviaste {len(it_in.equipos_recibidos)} serial(es).",
                )
            for eq_in in it_in.equipos_recibidos:
                ser = eq_in.serial.strip().upper()
                if ser in seriales_vistos:
                    raise HTTPException(status_code=409, detail=f"Serial duplicado en esta recepción: '{ser}'.")
                if bd.query(Equipo.id).filter(Equipo.serial == ser).first() is not None:
                    raise HTTPException(status_code=409, detail=f"El serial '{ser}' ya existe en el inventario.")
                seriales_vistos.add(ser)

                est_key = (eq_in.estado_inicial or "PENDIENTE_REVISION").strip().upper()
                estado_bd = MAPA_ESTADO_RECEPCION.get(est_key, EstadoEquipo.PENDIENTE_REVISION.value)
                eq_obj = Equipo(
                    serial=ser,
                    articulo_id=art.id,
                    modelo=(eq_in.modelo or desc_real)[:160],
                    configuracion=(eq_in.especificaciones or specs_real)[:255],
                    categoria=art.categoria or "Laptop",
                    ubicacion_id=almacen_id,
                    estado=estado_bd,
                    costo_compra_usd=costo_unit,
                    costo_flete_usd=flete_por_unidad,
                    costo_taller_usd=Decimal("0.00"),
                    precio_promo_usd=_q2(eq_in.precio_promo_usd) if eq_in.precio_promo_usd is not None else precio_p,
                    recibido_por_id=usuario_actual.id,
                    fecha_recepcion=hoy,
                    nota=f"Recibido de lote {lote.codigo} ({lote.proveedor_nombre}). {it_in.observacion_recepcion.strip()}".strip(),
                )
                bd.add(eq_obj)
                bd.flush()
                bd.add(
                    HistorialEstadoEquipo(
                        equipo_id=eq_obj.id,
                        estado_anterior="EN_TRANSITO",
                        estado_nuevo=estado_bd,
                        nota_tecnica=f"Recepción en {almacen.nombre} desde lote {lote.codigo}",
                        usuario_id=usuario_actual.id,
                    )
                )
                bd.add(
                    MovimientoInventario(
                        tipo=TipoMovimientoInventario.COMPRA.value,
                        articulo_id=art.id,
                        equipo_id=eq_obj.id,
                        sucursal_id=almacen_id,
                        cantidad=1,
                        costo_unitario_usd=_q2(costo_unit + flete_por_unidad),
                        documento_ref=lote.codigo,
                        motivo=f"Recepción flexible de lote {lote.codigo} en {almacen.nombre}",
                        usuario_id=usuario_actual.id,
                    )
                )
                equipos_creados += 1
                valor_equipos_1103 += _q2(costo_unit + flete_por_unidad)
        else:
            costo_tot_u = _q2(costo_unit + flete_por_unidad)
            bd.add(
                MovimientoInventario(
                    tipo=TipoMovimientoInventario.COMPRA.value,
                    articulo_id=art.id,
                    equipo_id=None,
                    sucursal_id=almacen_id,
                    cantidad=it_in.cantidad_recibida,
                    costo_unitario_usd=costo_tot_u,
                    documento_ref=lote.codigo,
                    motivo=f"Recepción de {item_bd.tipo_item.lower()} ({it_in.cantidad_recibida}/{item_bd.cantidad_esperada}) lote {lote.codigo}",
                    usuario_id=usuario_actual.id,
                )
            )
            componentes_recibidos += it_in.cantidad_recibida
            valor_comp_1105 += _q2(costo_tot_u * it_in.cantidad_recibida)

    lote.almacen_destino_id = almacen_id
    lote.costo_flete_estimado_usd = flete_real
    lote.costo_aduana_otros_usd = aduana_real
    lote.estado = "RECIBIDO"
    lote.recibido_por_id = usuario_actual.id
    lote.fecha_recepcion = ahora
    if datos.observaciones.strip():
        lote.observaciones = f"{lote.observaciones} | Recepción: {datos.observaciones.strip()}".strip(" |")

    # Asiento contable: reclasificar de 1.1.04 En Tránsito -> 1.1.03 Equipos y/o 1.1.05 Componentes
    total_reclasificado = _q2(valor_equipos_1103 + valor_comp_1105)
    if total_reclasificado > 0:
        lineas_rec: list[dict[str, Any]] = []
        if valor_equipos_1103 > 0:
            lineas_rec.append(
                {"cuenta_codigo": "1.1.03", "debe_usd": valor_equipos_1103, "haber_usd": 0, "nota": f"Ingreso equipos lote {lote.codigo}"}
            )
        if valor_comp_1105 > 0:
            lineas_rec.append(
                {"cuenta_codigo": "1.1.05", "debe_usd": valor_comp_1105, "haber_usd": 0, "nota": f"Ingreso componentes lote {lote.codigo}"}
            )
        lineas_rec.append(
            {"cuenta_codigo": "1.1.04", "debe_usd": 0, "haber_usd": total_reclasificado, "nota": f"Salida de inventario en tránsito {lote.codigo}"}
        )
        crear_asiento_contable(
            bd=bd,
            usuario=usuario_actual,
            fecha_op=hoy,
            descripcion=f"Recepción en Almacén ({almacen.nombre}) · Lote {lote.codigo}",
            origen_tipo="RECEPCION_TRANSITO",
            origen_id=lote.id,
            lineas=lineas_rec,
        )

    bd.commit()
    return {
        "lote_id": lote.id,
        "codigo": lote.codigo,
        "estado": lote.estado,
        "almacen_destino": almacen.nombre,
        "equipos_creados": equipos_creados,
        "componentes_recibidos": componentes_recibidos,
        "flete_prorrateado_por_unidad_usd": _r2(flete_por_unidad),
        "total_reclasificado_usd": _r2(total_reclasificado),
    }
