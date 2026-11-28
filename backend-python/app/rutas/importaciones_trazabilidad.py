from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.configuracion import configuracion
from app.esquemas_logistica import normalizar_serial
from app.modelos import CatalogoArticulo, CatalogoPrecio, RolUsuario, Sucursal, Usuario
from app.modelos_contabilidad import EquipoComponenteInstalado
from app.modelos_finanzas import EstadoVenta, Venta, VentaDetalle
from app.modelos_logistica import (
    Compra,
    CompraInternacionalLote,
    Equipo,
    EstadoEquipo,
    HistorialEstadoEquipo,
    MovimientoInventario,
    TipoMovimientoInventario,
    Traslado,
    TrasladoDetalle,
)
from app.modelos_operaciones import DevolucionGarantia
from app.modelos_taller import (
    CasoPostventa,
    OrdenRecepcionTecnica,
    Preparacion,
    PreparacionComponente,
    ResultadoPreparacion,
    TipoPreparacion,
)
from app.rutas.logistica import calcular_stock_componente, generar_correlativo
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import obtener_usuario_actual, puede_ver_costos, requerir_roles
from app.servicios.contabilidad import crear_asiento_contable


enrutador = APIRouter(prefix="/api", tags=["Importaciones, Preparación y Trazabilidad"])

ROLES_IMPORTACION = (
    RolUsuario.DIRECCION.value,
    RolUsuario.ADMINISTRACION.value,
    RolUsuario.LOGISTICA.value,
)

ROLES_PREPARACION = (
    RolUsuario.DIRECCION.value,
    RolUsuario.ADMINISTRACION.value,
    RolUsuario.LOGISTICA.value,
    RolUsuario.TECNICO.value,
)

MAPA_PROCESO_A_ESTADO: dict[str, str] = {
    "REVISION": EstadoEquipo.PENDIENTE_REVISION.value,
    "PENDIENTE_REVISION": EstadoEquipo.PENDIENTE_REVISION.value,
    "PREPARACION": EstadoEquipo.EN_PREPARACION.value,
    "EN_PREPARACION": EstadoEquipo.EN_PREPARACION.value,
    "POR_PREPARAR": EstadoEquipo.POR_PREPARAR.value,
    "HOSPITAL": EstadoEquipo.HOSPITAL.value,
    "CEMENTERIO": EstadoEquipo.CEMENTERIO.value,
}

ETIQUETA_PROCESO: dict[str, str] = {
    EstadoEquipo.PENDIENTE_REVISION.value: "Revisión",
    EstadoEquipo.POR_PREPARAR.value: "Preparación",
    EstadoEquipo.EN_PREPARACION.value: "Preparación",
    EstadoEquipo.HOSPITAL.value: "Hospital",
    EstadoEquipo.CEMENTERIO.value: "Cementerio",
    EstadoEquipo.LISTO.value: "Disponible",
    EstadoEquipo.VENDIDO.value: "Vendido",
}


def _q2(val: Decimal | float | int) -> Decimal:
    return Decimal(str(val or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _r2(val: Decimal | float | int) -> float:
    return float(_q2(val))


def _ahora_caracas() -> datetime:
    try:
        tz = ZoneInfo(configuracion.ZONA_HORARIA)
    except ZoneInfoNotFoundError:
        tz = timezone(timedelta(hours=-4))
    return datetime.now(tz)


def _costo_ref_articulo(bd: Session, articulo_id: int) -> Decimal:
    p = (
        bd.query(CatalogoPrecio)
        .filter(CatalogoPrecio.articulo_id == articulo_id)
        .order_by(CatalogoPrecio.fecha_vigencia.desc(), CatalogoPrecio.id.desc())
        .first()
    )
    if p and p.costo_referencia_usd is not None:
        return _q2(p.costo_referencia_usd)
    return Decimal("0.00")


# =============================================================================
# 1. COMPRAS INTERNACIONALES (LOTE EN TRÁNSITO SIN SERIALES)
# =============================================================================


class CompraInternacionalLoteCrearEntrada(BaseModel):
    proveedor_nombre: str = Field(min_length=2, max_length=160)
    referencia: str = Field(default="", max_length=120)
    descripcion_previa: str = Field(min_length=2, max_length=1000)
    cantidad_equipos_esperados: int = Field(ge=1, le=5000)
    monto_compra_usd: Decimal = Field(gt=Decimal("0"))
    taxes_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    envio_miami_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    fecha_compra: date | None = None
    observaciones: str = Field(default="", max_length=1000)


def _serializar_lote(lote: CompraInternacionalLote, incluir_costos: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": lote.id,
        "codigo": lote.codigo,
        "proveedor_nombre": lote.proveedor_nombre,
        "referencia": lote.referencia,
        "descripcion_previa": lote.descripcion_previa,
        "cantidad_equipos_esperados": lote.cantidad_equipos_esperados,
        "cantidad_equipos_recibidos": lote.cantidad_equipos_recibidos,
        "cantidad_pendiente": max(0, lote.cantidad_equipos_esperados - lote.cantidad_equipos_recibidos),
        "estado": lote.estado,
        "fecha_compra": lote.fecha_compra.isoformat(),
        "fecha_recepcion": lote.fecha_recepcion.isoformat() if lote.fecha_recepcion else None,
        "observaciones": lote.observaciones,
        "equipos": [
            {
                "id": e.id,
                "serial": e.serial,
                "modelo": e.modelo,
                "configuracion": e.configuracion,
                "grado_estetico": e.grado_estetico,
                "proceso_inicial": e.proceso_inicial,
                "estado": e.estado,
                "ubicacion_id": e.ubicacion_id,
                **({"primer_costo_usd": _r2(e.primer_costo_usd), "costo_final_usd": _r2(e.costo_final_usd)} if incluir_costos else {}),
            }
            for e in (lote.equipos or [])
        ],
    }
    if incluir_costos:
        data.update(
            {
                "monto_compra_usd": _r2(lote.monto_compra_usd),
                "taxes_usd": _r2(lote.taxes_usd),
                "envio_miami_usd": _r2(lote.envio_miami_usd),
                "subtotal_miami_usd": _r2(lote.subtotal_miami_usd),
                "gastos_envio_venezuela_usd": _r2(lote.gastos_envio_venezuela_usd),
                "costo_total_aterrizado_usd": _r2(lote.costo_total_aterrizado_usd),
            }
        )
    return data


@enrutador.get("/importaciones/lotes")
def listar_lotes_internacionales(
    estado: str | None = Query(default=None),
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_IMPORTACION, RolUsuario.DIRECTOR.value)),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    q = bd.query(CompraInternacionalLote).options(joinedload(CompraInternacionalLote.equipos))
    if estado and estado.strip():
        q = q.filter(CompraInternacionalLote.estado == estado.strip().upper())
    lotes = q.order_by(CompraInternacionalLote.id.desc()).all()
    ver_costos = puede_ver_costos(usuario_actual.rol)
    return [_serializar_lote(l, incluir_costos=ver_costos) for l in lotes]


@enrutador.post("/importaciones/lotes", status_code=status.HTTP_201_CREATED)
def crear_lote_internacional(
    datos: CompraInternacionalLoteCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_IMPORTACION)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Registra una Compra Internacional a nivel de lote (sin seriales) en estado EN_TRANSITO."""
    fecha_op = datos.fecha_compra or obtener_fecha_hoy()
    monto = _q2(datos.monto_compra_usd)
    taxes = _q2(datos.taxes_usd)
    envio_miami = _q2(datos.envio_miami_usd)
    subtotal_miami = _q2(monto + taxes + envio_miami)

    codigo = generar_correlativo(bd, CompraInternacionalLote, CompraInternacionalLote.codigo, "INT")
    lote = CompraInternacionalLote(
        codigo=codigo,
        proveedor_nombre=datos.proveedor_nombre.strip(),
        referencia=datos.referencia.strip(),
        descripcion_previa=datos.descripcion_previa.strip(),
        cantidad_equipos_esperados=datos.cantidad_equipos_esperados,
        cantidad_equipos_recibidos=0,
        monto_compra_usd=monto,
        taxes_usd=taxes,
        envio_miami_usd=envio_miami,
        subtotal_miami_usd=subtotal_miami,
        gastos_envio_venezuela_usd=Decimal("0"),
        costo_total_aterrizado_usd=subtotal_miami,
        estado="EN_TRANSITO",
        fecha_compra=fecha_op,
        observaciones=datos.observaciones.strip(),
        creado_por_id=usuario_actual.id,
    )
    bd.add(lote)
    bd.flush()

    crear_asiento_contable(
        bd=bd,
        usuario=usuario_actual,
        fecha_op=fecha_op,
        descripcion=f"Compra Internacional en Tránsito {codigo} · {lote.proveedor_nombre}",
        origen_tipo="COMPRA_INTERNACIONAL_LOTE",
        origen_id=lote.id,
        lineas=[
            {"cuenta_codigo": "1.1.04", "debe_usd": subtotal_miami, "haber_usd": 0, "nota": f"Lote {codigo} Subtotal Miami"},
            {"cuenta_codigo": "2.1.01", "debe_usd": 0, "haber_usd": subtotal_miami, "nota": f"CxP Proveedor {lote.proveedor_nombre}"},
        ],
    )
    bd.commit()
    bd.refresh(lote)
    return _serializar_lote(lote, incluir_costos=True)


# =============================================================================
# 2. RECEPCIÓN EN VENEZUELA (DESGLOSE POR SERIAL + PRIMER COSTO ATERRIZADO)
# =============================================================================


class EquipoRecepcionInternacionalEntrada(BaseModel):
    serial: str = Field(min_length=2, max_length=100)
    articulo_id: int | None = None
    sku: str = Field(default="", max_length=80)
    modelo: str = Field(min_length=2, max_length=160)
    configuracion: str = Field(default="", max_length=255)
    grado_estetico: str = Field(default="", max_length=40)
    categoria: str = Field(default="Laptop", max_length=100)
    ubicacion_id: int
    proceso_inicial: str = Field(description="REVISION | PREPARACION | HOSPITAL | CEMENTERIO")
    precio_promo_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    primer_costo_manual_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    observaciones: str = Field(default="", max_length=500)


class RecepcionLoteInternacionalEntrada(BaseModel):
    gastos_envio_venezuela_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    fecha_recepcion: date | None = None
    observaciones: str = Field(default="", max_length=1000)
    equipos: list[EquipoRecepcionInternacionalEntrada] = Field(min_length=1)


@enrutador.post("/importaciones/lotes/{lote_id}/recibir")
def recibir_lote_internacional(
    lote_id: int,
    datos: RecepcionLoteInternacionalEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_IMPORTACION)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Recibe un lote internacional en Venezuela, desglosa por serial y calcula Primer Costo Aterrizado."""
    lote = (
        bd.query(CompraInternacionalLote)
        .options(joinedload(CompraInternacionalLote.equipos))
        .filter(CompraInternacionalLote.id == lote_id)
        .first()
    )
    if lote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lote internacional no encontrado.")
    if lote.estado == "RECIBIDO":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este lote internacional ya fue recibido completamente.")

    pendientes = lote.cantidad_equipos_esperados - lote.cantidad_equipos_recibidos
    if len(datos.equipos) > pendientes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Intentas recibir {len(datos.equipos)} equipos pero solo quedan {pendientes} pendientes en este lote.",
        )

    # Validar seriales únicos y ubicaciones válidas
    seriales_vistos: set[str] = set()
    ubicaciones_ids = {e.ubicacion_id for e in datos.equipos}
    sucs_map = {s.id: s for s in bd.query(Sucursal).filter(Sucursal.id.in_(ubicaciones_ids)).all()}
    if len(sucs_map) != len(ubicaciones_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Una o más ubicaciones de recepción no existen.")

    for eq_in in datos.equipos:
        ser = normalizar_serial(eq_in.serial)
        if ser in seriales_vistos:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Serial duplicado en el envío: {ser}")
        seriales_vistos.add(ser)
        if bd.query(Equipo.id).filter(func.upper(Equipo.serial) == ser).first() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"El serial '{ser}' ya existe en el inventario.")
        if eq_in.proceso_inicial.strip().upper() not in MAPA_PROCESO_A_ESTADO:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Proceso inicial inválido '{eq_in.proceso_inicial}'. Usa: REVISION, PREPARACION, HOSPITAL o CEMENTERIO.",
            )

    # Calcular costo total aterrizado de esta recepción
    envio_vzla_nuevo = _q2(datos.gastos_envio_venezuela_usd)
    envio_vzla_total = _q2(Decimal(lote.gastos_envio_venezuela_usd or 0) + envio_vzla_nuevo)
    costo_total_lote = _q2(Decimal(lote.subtotal_miami_usd) + envio_vzla_total)

    # Porción de costo correspondiente a los equipos recibidos ahora
    proporcion = Decimal(len(datos.equipos)) / Decimal(lote.cantidad_equipos_esperados)
    costo_porcion_miami = _q2(Decimal(lote.subtotal_miami_usd) * proporcion)
    costo_a_distribuir = _q2(costo_porcion_miami + envio_vzla_nuevo)

    usa_manual = any(e.primer_costo_manual_usd is not None for e in datos.equipos)
    costos_unitarios: list[Decimal] = []
    if usa_manual:
        if any(e.primer_costo_manual_usd is None for e in datos.equipos):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Si ajustas costos manuales, debes indicar primer_costo_manual_usd en todos los equipos de esta recepción.",
            )
        costos_unitarios = [_q2(e.primer_costo_manual_usd or 0) for e in datos.equipos]
        suma_manual = _q2(sum(costos_unitarios, Decimal("0")))
        if abs(suma_manual - costo_a_distribuir) > Decimal("0.05"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"La suma de costos manuales (${suma_manual}) no cuadra con el costo aterrizado a distribuir (${costo_a_distribuir}).",
            )
    else:
        base_unit = _q2(costo_a_distribuir / Decimal(len(datos.equipos)))
        acum = Decimal("0")
        for idx in range(len(datos.equipos)):
            if idx == len(datos.equipos) - 1:
                costos_unitarios.append(_q2(costo_a_distribuir - acum))
            else:
                costos_unitarios.append(base_unit)
                acum += base_unit

    fecha_rec = datos.fecha_recepcion or obtener_fecha_hoy()
    ahora = _ahora_caracas()
    creados: list[dict[str, Any]] = []

    for eq_in, primer_costo in zip(datos.equipos, costos_unitarios):
        ser = normalizar_serial(eq_in.serial)
        proc_raw = eq_in.proceso_inicial.strip().upper()
        estado_eq = MAPA_PROCESO_A_ESTADO[proc_raw]

        art_id = eq_in.articulo_id
        if art_id is None and eq_in.sku.strip():
            art_obj = bd.query(CatalogoArticulo).filter(func.upper(CatalogoArticulo.sku) == eq_in.sku.strip().upper()).first()
            if art_obj is not None:
                art_id = art_obj.id

        eq = Equipo(
            serial=ser,
            articulo_id=art_id,
            lote_internacional_id=lote.id,
            modelo=eq_in.modelo.strip(),
            configuracion=eq_in.configuracion.strip(),
            grado_estetico=eq_in.grado_estetico.strip(),
            proceso_inicial=proc_raw,
            categoria=eq_in.categoria.strip() or "Laptop",
            ubicacion_id=eq_in.ubicacion_id,
            estado=estado_eq,
            costo_compra_usd=primer_costo,
            costo_flete_usd=Decimal("0"),
            costo_taller_usd=Decimal("0"),
            primer_costo_usd=primer_costo,
            costo_componentes_usd=Decimal("0"),
            comision_preparacion_usd=Decimal("0"),
            costo_final_usd=primer_costo,
            precio_promo_usd=_q2(eq_in.precio_promo_usd),
            recibido_por_id=usuario_actual.id,
            fecha_recepcion=fecha_rec,
            nota=eq_in.observaciones.strip(),
        )
        bd.add(eq)
        bd.flush()

        bd.add(
            HistorialEstadoEquipo(
                equipo_id=eq.id,
                usuario_id=usuario_actual.id,
                estado_anterior=EstadoEquipo.EN_TRANSITO.value,
                estado_nuevo=estado_eq,
                nota_tecnica=(
                    f"Recepción lote {lote.codigo} · Proceso inicial: {ETIQUETA_PROCESO.get(estado_eq, proc_raw)} · "
                    f"Primer Costo: ${primer_costo}"
                    + (f" · {eq_in.observaciones.strip()}" if eq_in.observaciones.strip() else "")
                ),
            )
        )
        bd.add(
            MovimientoInventario(
                tipo=TipoMovimientoInventario.COMPRA.value,
                articulo_id=art_id,
                equipo_id=eq.id,
                sucursal_id=eq.ubicacion_id,
                cantidad=1,
                costo_unitario_usd=primer_costo,
                documento_ref=lote.codigo,
                motivo=f"Recepción internacional {lote.codigo} ({proc_raw})",
                usuario_id=usuario_actual.id,
            )
        )
        creados.append(
            {
                "id": eq.id,
                "serial": eq.serial,
                "modelo": eq.modelo,
                "estado": eq.estado,
                "proceso_inicial": eq.proceso_inicial,
                "ubicacion_id": eq.ubicacion_id,
                "primer_costo_usd": _r2(primer_costo),
                "costo_final_usd": _r2(primer_costo),
            }
        )

    lote.cantidad_equipos_recibidos += len(datos.equipos)
    lote.gastos_envio_venezuela_usd = envio_vzla_total
    lote.costo_total_aterrizado_usd = costo_total_lote
    lote.recibido_por_id = usuario_actual.id
    lote.fecha_recepcion = ahora
    lote.estado = "RECIBIDO" if lote.cantidad_equipos_recibidos >= lote.cantidad_equipos_esperados else "RECIBIDO_PARCIAL"
    if datos.observaciones.strip():
        lote.observaciones = f"{lote.observaciones}\n[Recepción] {datos.observaciones.strip()}".strip()

    # Asiento contable: 1.1.03 Equipos (DEBE = costo_a_distribuir) vs 1.1.04 Tránsito (HABER = costo_porcion_miami) + 2.1.01 Flete Vzla (HABER = envio_vzla_nuevo)
    lineas_asiento: list[dict[str, Any]] = [
        {"cuenta_codigo": "1.1.03", "debe_usd": costo_a_distribuir, "haber_usd": 0, "nota": f"Ingreso {len(creados)} equipos lote {lote.codigo}"},
        {"cuenta_codigo": "1.1.04", "debe_usd": 0, "haber_usd": costo_porcion_miami, "nota": f"Descargo tránsito lote {lote.codigo}"},
    ]
    if envio_vzla_nuevo > Decimal("0"):
        lineas_asiento.append(
            {"cuenta_codigo": "2.1.01", "debe_usd": 0, "haber_usd": envio_vzla_nuevo, "nota": f"Flete/Aduana Venezuela lote {lote.codigo}"}
        )
    crear_asiento_contable(
        bd=bd,
        usuario=usuario_actual,
        fecha_op=fecha_rec,
        descripcion=f"Recepción Internacional {lote.codigo} ({len(creados)} equipos)",
        origen_tipo="RECEPCION_INTERNACIONAL",
        origen_id=lote.id,
        lineas=lineas_asiento,
    )

    bd.commit()
    bd.refresh(lote)
    return {
        "lote": _serializar_lote(lote, incluir_costos=True),
        "equipos_recibidos": creados,
        "costo_aterrizado_recepcion_usd": _r2(costo_a_distribuir),
    }


# =============================================================================
# 3. PREPARACIÓN Y GESTIÓN DE PROCESOS (COMPONENTES + COMISIÓN -> COSTO FINAL)
# =============================================================================


class CambiarProcesoEquipoEntrada(BaseModel):
    nuevo_proceso: str = Field(description="REVISION | PREPARACION | HOSPITAL | CEMENTERIO")
    nota_tecnica: str = Field(default="", max_length=500)


@enrutador.patch("/importaciones/equipos/{equipo_id}/proceso")
def cambiar_proceso_equipo(
    equipo_id: int,
    datos: CambiarProcesoEquipoEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_PREPARACION)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Cambia un equipo entre Revisión, Preparación, Hospital o Cementerio dejando trazabilidad."""
    eq = bd.query(Equipo).filter(Equipo.id == equipo_id).first()
    if eq is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipo no encontrado.")
    if eq.estado == EstadoEquipo.VENDIDO.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No se puede cambiar el proceso de un equipo vendido.")

    proc_u = datos.nuevo_proceso.strip().upper()
    if proc_u not in MAPA_PROCESO_A_ESTADO:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Proceso inválido.")

    estado_ant = eq.estado
    estado_nuevo = MAPA_PROCESO_A_ESTADO[proc_u]
    eq.estado = estado_nuevo
    bd.add(
        HistorialEstadoEquipo(
            equipo_id=eq.id,
            usuario_id=usuario_actual.id,
            estado_anterior=estado_ant,
            estado_nuevo=estado_nuevo,
            nota_tecnica=datos.nota_tecnica.strip() or f"Cambio de proceso a {ETIQUETA_PROCESO.get(estado_nuevo, proc_u)}",
        )
    )
    bd.commit()
    return {
        "id": eq.id,
        "serial": eq.serial,
        "estado_anterior": estado_ant,
        "estado_nuevo": eq.estado,
    }


class ComponentePreparacionEntrada(BaseModel):
    articulo_id: int
    cantidad: int = Field(default=1, ge=1)


class FichaPreparacionEntrada(BaseModel):
    tecnico_id: int | None = None
    componentes: list[ComponentePreparacionEntrada] = Field(default_factory=list)
    comision_preparacion_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    marcar_disponible: bool = False
    precio_promo_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    nota_tecnica: str = Field(default="", max_length=1000)


@enrutador.post("/importaciones/equipos/{equipo_id}/preparacion")
def registrar_ficha_preparacion_equipo(
    equipo_id: int,
    datos: FichaPreparacionEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_PREPARACION)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Agrega componentes del inventario + comisión de preparación, recalcula Costo Final y opcionalmente marca Disponible."""
    eq = bd.query(Equipo).filter(Equipo.id == equipo_id).first()
    if eq is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipo no encontrado.")
    if eq.estado == EstadoEquipo.VENDIDO.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El equipo ya fue vendido.")

    hoy = obtener_fecha_hoy()
    tecnico_id = datos.tecnico_id or usuario_actual.id
    suma_comp_nueva = Decimal("0")
    componentes_agregados: list[dict[str, Any]] = []

    prep = Preparacion(
        equipo_id=eq.id,
        tecnico_id=tecnico_id,
        fecha=hoy,
        tipo=TipoPreparacion.ESPECIAL.value if datos.componentes else TipoPreparacion.ESTANDAR.value,
        pago_tecnico_usd=_q2(datos.comision_preparacion_usd),
        resultado=ResultadoPreparacion.LISTO.value if datos.marcar_disponible else EstadoEquipo.EN_PREPARACION.value,
        nota=datos.nota_tecnica.strip(),
    )
    bd.add(prep)
    bd.flush()

    for comp in datos.componentes:
        art = bd.query(CatalogoArticulo).filter(CatalogoArticulo.id == comp.articulo_id).first()
        if art is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Componente #{comp.articulo_id} no encontrado.")
        stock_disp = calcular_stock_componente(bd, art.id, eq.ubicacion_id)
        if stock_disp < comp.cantidad:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stock insuficiente de '{art.descripcion}' en esta ubicación (disponible: {stock_disp}, requerido: {comp.cantidad}).",
            )
        costo_unit = _costo_ref_articulo(bd, art.id)
        costo_tot = _q2(costo_unit * Decimal(comp.cantidad))
        suma_comp_nueva += costo_tot

        # Descontar del inventario
        bd.add(
            MovimientoInventario(
                tipo=TipoMovimientoInventario.TALLER.value,
                articulo_id=art.id,
                equipo_id=eq.id,
                sucursal_id=eq.ubicacion_id,
                cantidad=-comp.cantidad,
                costo_unitario_usd=costo_unit,
                documento_ref=f"PREP-{prep.id}",
                motivo=f"Componente instalado en {eq.serial}",
                usuario_id=usuario_actual.id,
            )
        )
        bd.add(
            PreparacionComponente(
                preparacion_id=prep.id,
                articulo_id=art.id,
                cantidad=comp.cantidad,
                costo_unitario_snapshot_usd=costo_unit,
            )
        )
        bd.add(
            EquipoComponenteInstalado(
                equipo_id=eq.id,
                articulo_id=art.id,
                sku=art.sku,
                descripcion=art.descripcion,
                cantidad=comp.cantidad,
                costo_unitario_usd=costo_unit,
                costo_total_usd=costo_tot,
                instalado_por_id=tecnico_id,
            )
        )
        componentes_agregados.append(
            {
                "articulo_id": art.id,
                "sku": art.sku,
                "descripcion": art.descripcion,
                "cantidad": comp.cantidad,
                "costo_unitario_usd": _r2(costo_unit),
                "costo_total_usd": _r2(costo_tot),
            }
        )

    # Recalcular Costo Final = Primer Costo + Suma Componentes + Comisión de Preparación
    primer_costo = _q2(eq.primer_costo_usd if eq.primer_costo_usd and eq.primer_costo_usd > 0 else (Decimal(eq.costo_compra_usd or 0) + Decimal(eq.costo_flete_usd or 0)))
    eq.primer_costo_usd = primer_costo
    eq.costo_componentes_usd = _q2(Decimal(eq.costo_componentes_usd or 0) + suma_comp_nueva)
    eq.comision_preparacion_usd = _q2(Decimal(eq.comision_preparacion_usd or 0) + _q2(datos.comision_preparacion_usd))
    eq.costo_taller_usd = _q2(eq.costo_componentes_usd + eq.comision_preparacion_usd)
    eq.costo_final_usd = _q2(primer_costo + eq.costo_taller_usd)

    # Mantener coherencia exacta con COGS en ventas: costo_compra_usd + costo_flete_usd + costo_taller_usd == costo_final_usd
    if eq.lote_internacional_id is not None:
        eq.costo_compra_usd = primer_costo
        eq.costo_flete_usd = Decimal("0")

    if datos.precio_promo_usd is not None and datos.precio_promo_usd > Decimal("0"):
        eq.precio_promo_usd = _q2(datos.precio_promo_usd)

    estado_ant = eq.estado
    if datos.marcar_disponible:
        eq.estado = EstadoEquipo.LISTO.value
    elif eq.estado != EstadoEquipo.EN_PREPARACION.value:
        eq.estado = EstadoEquipo.EN_PREPARACION.value

    bd.add(
        HistorialEstadoEquipo(
            equipo_id=eq.id,
            usuario_id=usuario_actual.id,
            estado_anterior=estado_ant,
            estado_nuevo=eq.estado,
            nota_tecnica=(
                f"Preparación #{prep.id} · +{len(componentes_agregados)} comp. (${suma_comp_nueva}) · "
                f"Comisión ${_q2(datos.comision_preparacion_usd)} · Costo Final: ${eq.costo_final_usd}"
                + (f" · {datos.nota_tecnica.strip()}" if datos.nota_tecnica.strip() else "")
            ),
        )
    )

    if suma_comp_nueva > Decimal("0"):
        crear_asiento_contable(
            bd=bd,
            usuario=usuario_actual,
            fecha_op=hoy,
            descripcion=f"Componentes instalados en preparación de {eq.serial}",
            origen_tipo="PREPARACION_EQUIPO",
            origen_id=prep.id,
            lineas=[
                {"cuenta_codigo": "1.1.03", "debe_usd": suma_comp_nueva, "haber_usd": 0, "nota": f"Capitalización componentes en {eq.serial}"},
                {"cuenta_codigo": "1.1.05", "debe_usd": 0, "haber_usd": suma_comp_nueva, "nota": f"Salida inventario componentes para {eq.serial}"},
            ],
        )

    bd.commit()
    return {
        "equipo_id": eq.id,
        "serial": eq.serial,
        "estado": eq.estado,
        "disponible_para_venta": eq.estado == EstadoEquipo.LISTO.value,
        "primer_costo_usd": _r2(eq.primer_costo_usd),
        "costo_componentes_usd": _r2(eq.costo_componentes_usd),
        "comision_preparacion_usd": _r2(eq.comision_preparacion_usd),
        "costo_final_usd": _r2(eq.costo_final_usd),
        "componentes_agregados": componentes_agregados,
    }


# =============================================================================
# 4. TRAZABILIDAD TOTAL POR SERIAL (HOJA DE VIDA DEL EQUIPO)
# =============================================================================


@enrutador.get("/inventario/trazabilidad/{serial}")
def obtener_trazabilidad_por_serial(
    serial: str,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Devuelve la Hoja de Vida cronológica completa y el desglose financiero de un equipo por serial."""
    ser_norm = normalizar_serial(serial)
    eq = (
        bd.query(Equipo)
        .options(
            joinedload(Equipo.ubicacion),
            joinedload(Equipo.recibido_por),
            joinedload(Equipo.compra),
        )
        .filter(func.upper(Equipo.serial) == ser_norm)
        .first()
    )
    if eq is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró ningún equipo con el serial '{ser_norm}'.",
        )

    ver_costos = puede_ver_costos(usuario_actual.rol)

    primer_costo = _q2(
        eq.primer_costo_usd
        if eq.primer_costo_usd and eq.primer_costo_usd > 0
        else (Decimal(eq.costo_compra_usd or 0) + Decimal(eq.costo_flete_usd or 0))
    )
    costo_comp = _q2(eq.costo_componentes_usd or 0)
    comision_prep = _q2(eq.comision_preparacion_usd or 0)
    costo_final = _q2(
        eq.costo_final_usd
        if eq.costo_final_usd and eq.costo_final_usd > 0
        else (primer_costo + Decimal(eq.costo_taller_usd or 0))
    )

    linea_tiempo: list[dict[str, Any]] = []

    # 1. Compra Internacional (o Nacional)
    lote_info: dict[str, Any] | None = None
    if eq.lote_internacional_id is not None:
        lote = (
            bd.query(CompraInternacionalLote)
            .filter(CompraInternacionalLote.id == eq.lote_internacional_id)
            .first()
        )
        if lote is not None:
            lote_info = {
                "tipo": "INTERNACIONAL",
                "codigo": lote.codigo,
                "fecha_compra": lote.fecha_compra.isoformat(),
                "proveedor": lote.proveedor_nombre,
                "referencia": lote.referencia,
                "descripcion_previa": lote.descripcion_previa,
                "cantidad_equipos_lote": lote.cantidad_equipos_esperados,
                **(
                    {
                        "monto_compra_usd": _r2(lote.monto_compra_usd),
                        "taxes_usd": _r2(lote.taxes_usd),
                        "envio_miami_usd": _r2(lote.envio_miami_usd),
                        "subtotal_miami_usd": _r2(lote.subtotal_miami_usd),
                        "gastos_envio_venezuela_usd": _r2(lote.gastos_envio_venezuela_usd),
                        "costo_total_aterrizado_usd": _r2(lote.costo_total_aterrizado_usd),
                    }
                    if ver_costos
                    else {}
                ),
            }
            linea_tiempo.append(
                {
                    "fecha": lote.fecha_compra.isoformat(),
                    "tipo": "COMPRA_INTERNACIONAL",
                    "titulo": f"Compra Internacional {lote.codigo}",
                    "detalle": f"Proveedor: {lote.proveedor_nombre} · {lote.descripcion_previa}",
                }
            )
    elif eq.compra is not None:
        lote_info = {
            "tipo": eq.compra.origen,
            "codigo": eq.compra.numero_compra,
            "fecha_compra": eq.compra.fecha.isoformat(),
            "proveedor": eq.compra.proveedor_nombre or "Compra directa",
            "referencia": eq.compra.factura_orden or eq.compra.tracking_guia,
            "descripcion_previa": eq.compra.nota or "",
        }
        linea_tiempo.append(
            {
                "fecha": eq.compra.fecha.isoformat(),
                "tipo": "COMPRA",
                "titulo": f"Compra {eq.compra.numero_compra}",
                "detalle": f"Origen: {eq.compra.origen} · Proveedor: {eq.compra.proveedor_nombre or 'N/A'}",
            }
        )

    # 2. Recepción
    fecha_rec_iso = (
        eq.fecha_recepcion.isoformat()
        if eq.fecha_recepcion
        else (eq.creado_en.date().isoformat() if eq.creado_en else "")
    )
    recepcion_info: dict[str, Any] = {
        "fecha": fecha_rec_iso,
        "ubicacion_actual": eq.ubicacion.nombre if eq.ubicacion else "",
        "modelo": eq.modelo,
        "configuracion": eq.configuracion,
        "grado_estetico": eq.grado_estetico,
        "proceso_inicial": eq.proceso_inicial or ETIQUETA_PROCESO.get(eq.estado, eq.estado),
        "observaciones_iniciales": eq.nota,
        "recibido_por": eq.recibido_por.nombre if eq.recibido_por else "",
        **({"primer_costo_usd": _r2(primer_costo)} if ver_costos else {}),
    }
    linea_tiempo.append(
        {
            "fecha": fecha_rec_iso,
            "tipo": "RECEPCION",
            "titulo": f"Recepción en {recepcion_info['ubicacion_actual']}",
            "detalle": f"Proceso inicial: {recepcion_info['proceso_inicial']}"
            + (f" · Primer Costo: ${_r2(primer_costo):.2f}" if ver_costos else ""),
        }
    )

    # 3. Historial de Procesos
    hist_rows = (
        bd.query(HistorialEstadoEquipo)
        .options(joinedload(HistorialEstadoEquipo.usuario))
        .filter(HistorialEstadoEquipo.equipo_id == eq.id)
        .order_by(HistorialEstadoEquipo.fecha.asc(), HistorialEstadoEquipo.id.asc())
        .all()
    )
    historial_procesos: list[dict[str, Any]] = []
    for h in hist_rows:
        f_iso = h.fecha.isoformat() if h.fecha else ""
        historial_procesos.append(
            {
                "id": h.id,
                "fecha": f_iso,
                "estado_anterior": h.estado_anterior,
                "estado_nuevo": h.estado_nuevo,
                "usuario": h.usuario.nombre if h.usuario else "",
                "nota_tecnica": h.nota_tecnica,
            }
        )
        linea_tiempo.append(
            {
                "fecha": f_iso,
                "tipo": "PROCESO",
                "titulo": f"Proceso: {h.estado_anterior} → {h.estado_nuevo}",
                "detalle": f"{h.usuario.nombre if h.usuario else 'Sistema'}: {h.nota_tecnica}",
            }
        )

    # 4. Preparación y Desglose de Costo Final
    comps_rows = (
        bd.query(EquipoComponenteInstalado)
        .options(joinedload(EquipoComponenteInstalado.instalado_por))
        .filter(EquipoComponenteInstalado.equipo_id == eq.id)
        .order_by(EquipoComponenteInstalado.fecha.asc(), EquipoComponenteInstalado.id.asc())
        .all()
    )
    componentes_lista: list[dict[str, Any]] = []
    for c in comps_rows:
        f_iso = c.fecha.isoformat() if c.fecha else ""
        item_c: dict[str, Any] = {
            "id": c.id,
            "sku": c.sku,
            "descripcion": c.descripcion,
            "cantidad": c.cantidad,
            "fecha": f_iso,
            "instalado_por": c.instalado_por.nombre if c.instalado_por else "",
        }
        if ver_costos:
            item_c["costo_unitario_usd"] = _r2(c.costo_unitario_usd)
            item_c["costo_total_usd"] = _r2(c.costo_total_usd)
        componentes_lista.append(item_c)
        linea_tiempo.append(
            {
                "fecha": f_iso,
                "tipo": "COMPONENTE",
                "titulo": f"Componente agregado: {c.sku} ({c.cantidad}x)",
                "detalle": f"{c.descripcion}" + (f" · ${_r2(c.costo_total_usd):.2f}" if ver_costos else ""),
            }
        )

    preps_rows = (
        bd.query(Preparacion)
        .options(joinedload(Preparacion.tecnico))
        .filter(Preparacion.equipo_id == eq.id)
        .order_by(Preparacion.fecha.asc(), Preparacion.id.asc())
        .all()
    )
    preparaciones_lista = [
        {
            "id": pr.id,
            "fecha": pr.fecha.isoformat(),
            "tecnico": pr.tecnico.nombre if pr.tecnico else "",
            "tipo": pr.tipo,
            "resultado": pr.resultado,
            "nota": pr.nota,
            **({"comision_usd": _r2(pr.pago_tecnico_usd)} if ver_costos else {}),
        }
        for pr in preps_rows
    ]

    preparacion_costos: dict[str, Any] = {
        "componentes": componentes_lista,
        "preparaciones": preparaciones_lista,
    }
    if ver_costos:
        preparacion_costos.update(
            {
                "primer_costo_usd": _r2(primer_costo),
                "costo_componentes_usd": _r2(costo_comp),
                "comision_preparacion_usd": _r2(comision_prep),
                "costo_final_usd": _r2(costo_final),
            }
        )

    # 5. Traslados
    tras_dets = (
        bd.query(TrasladoDetalle)
        .options(
            joinedload(TrasladoDetalle.traslado).joinedload(Traslado.origen),
            joinedload(TrasladoDetalle.traslado).joinedload(Traslado.destino),
            joinedload(TrasladoDetalle.traslado).joinedload(Traslado.enviado_por),
            joinedload(TrasladoDetalle.traslado).joinedload(Traslado.recibido_por),
        )
        .filter(TrasladoDetalle.equipo_id == eq.id)
        .all()
    )
    traslados_lista: list[dict[str, Any]] = []
    for td in tras_dets:
        tr = td.traslado
        if tr is None:
            continue
        f_env = tr.fecha_envio.isoformat() if tr.fecha_envio else ""
        traslados_lista.append(
            {
                "id": tr.id,
                "numero_traslado": tr.numero_traslado,
                "fecha_envio": f_env,
                "fecha_recepcion": tr.fecha_recepcion.isoformat() if tr.fecha_recepcion else None,
                "origen": tr.origen.nombre if tr.origen else "",
                "destino": tr.destino.nombre if tr.destino else "",
                "estado": tr.estado,
                "enviado_por": tr.enviado_por.nombre if tr.enviado_por else "",
                "recibido_por": tr.recibido_por.nombre if tr.recibido_por else "",
                "nota": tr.nota,
            }
        )
        linea_tiempo.append(
            {
                "fecha": f_env,
                "tipo": "TRASLADO",
                "titulo": f"Traslado {tr.numero_traslado} ({tr.estado})",
                "detalle": f"{tr.origen.nombre if tr.origen else ''} → {tr.destino.nombre if tr.destino else ''}",
            }
        )

    # 6. Venta
    venta_det = (
        bd.query(VentaDetalle)
        .options(
            joinedload(VentaDetalle.venta).joinedload(Venta.sucursal),
            joinedload(VentaDetalle.venta).joinedload(Venta.asesor),
            joinedload(VentaDetalle.venta).joinedload(Venta.cliente),
        )
        .join(Venta, VentaDetalle.venta_id == Venta.id)
        .filter(VentaDetalle.equipo_id == eq.id, Venta.estado != EstadoVenta.ANULADA.value)
        .order_by(Venta.id.desc())
        .first()
    )
    venta_info: dict[str, Any] | None = None
    if venta_det is not None and venta_det.venta is not None:
        v = venta_det.venta
        precio_vta = _q2(
            venta_det.precio_pactado_usd
            if venta_det.precio_pactado_usd is not None
            else venta_det.precio_promo_usd
        )
        venta_info = {
            "venta_id": v.id,
            "numero_venta": v.numero_venta,
            "fecha": v.fecha.isoformat(),
            "sucursal": v.sucursal.nombre if v.sucursal else "",
            "asesor": v.asesor.nombre if v.asesor else "Tienda",
            "cliente": v.cliente.nombre if v.cliente else "Cliente general",
            "estado": v.estado,
            "sin_cargador": bool(getattr(v, "sin_cargador", False)),
            "precio_venta_usd": _r2(precio_vta),
            **(
                {
                    "costo_final_usd": _r2(costo_final),
                    "ganancia_real_usd": _r2(precio_vta - costo_final),
                }
                if ver_costos
                else {}
            ),
        }
        linea_tiempo.append(
            {
                "fecha": v.fecha.isoformat(),
                "tipo": "VENTA",
                "titulo": f"Venta {v.numero_venta} ({venta_info['sucursal']})",
                "detalle": f"Cliente: {venta_info['cliente']} · Asesor: {venta_info['asesor']} · Precio: ${_r2(precio_vta):.2f}",
            }
        )

    # 7. Incidentes Futuros (Post-venta: CasoPostventa + OrdenRecepcionTecnica + DevolucionGarantia)
    incidentes: list[dict[str, Any]] = []

    casos = (
        bd.query(CasoPostventa)
        .options(joinedload(CasoPostventa.tecnico), joinedload(CasoPostventa.cliente))
        .filter((CasoPostventa.equipo_id == eq.id) | (func.upper(CasoPostventa.serial_o_codigo) == ser_norm))
        .order_by(CasoPostventa.fecha_ingreso.asc())
        .all()
    )
    for cs in casos:
        f_iso = cs.fecha_ingreso.isoformat() if cs.fecha_ingreso else ""
        incidentes.append(
            {
                "origen": "CASO_POSTVENTA",
                "codigo": cs.numero_caso,
                "tipo": cs.tipo,
                "fecha": f_iso,
                "falla_reportada": cs.falla_reportada,
                "tecnico": cs.tecnico.nombre if cs.tecnico else "",
                "resolucion": cs.trabajo_realizado or cs.diagnostico or cs.estado,
                "estado": cs.estado,
            }
        )
        linea_tiempo.append(
            {
                "fecha": f_iso,
                "tipo": "INCIDENTE_POSTVENTA",
                "titulo": f"{cs.tipo} {cs.numero_caso} ({cs.estado})",
                "detalle": f"Falla: {cs.falla_reportada}",
            }
        )

    ordenes = (
        bd.query(OrdenRecepcionTecnica)
        .options(joinedload(OrdenRecepcionTecnica.tecnico_asignado))
        .filter(func.upper(OrdenRecepcionTecnica.serial) == ser_norm)
        .order_by(OrdenRecepcionTecnica.fecha_recepcion.asc())
        .all()
    )
    for ord_t in ordenes:
        f_iso = ord_t.fecha_recepcion.isoformat() if ord_t.fecha_recepcion else ""
        incidentes.append(
            {
                "origen": "RECEPCION_TECNICA",
                "codigo": ord_t.codigo,
                "tipo": ord_t.tipo_orden,
                "fecha": f_iso,
                "falla_reportada": ord_t.falla_declarada_cliente,
                "tecnico": ord_t.tecnico_asignado.nombre if ord_t.tecnico_asignado else "",
                "resolucion": ord_t.solucion_aplicada or ord_t.diagnostico_tecnico or ord_t.estado,
                "estado": ord_t.estado,
            }
        )
        linea_tiempo.append(
            {
                "fecha": f_iso,
                "tipo": "INCIDENTE_POSTVENTA",
                "titulo": f"{ord_t.tipo_orden} {ord_t.codigo} ({ord_t.estado})",
                "detalle": f"Falla: {ord_t.falla_declarada_cliente}",
            }
        )

    devs = (
        bd.query(DevolucionGarantia)
        .filter((DevolucionGarantia.equipo_origen_id == eq.id) | (DevolucionGarantia.equipo_destino_id == eq.id))
        .order_by(DevolucionGarantia.fecha.asc())
        .all()
    )
    for dv in devs:
        f_iso = dv.fecha.isoformat()
        incidentes.append(
            {
                "origen": "DEVOLUCION_GARANTIA",
                "codigo": dv.numero_operacion,
                "tipo": dv.tipo_resolucion,
                "fecha": f_iso,
                "falla_reportada": dv.motivo,
                "tecnico": "",
                "resolucion": dv.tipo_resolucion,
                "estado": "PROCESADA",
            }
        )
        linea_tiempo.append(
            {
                "fecha": f_iso,
                "tipo": "INCIDENTE_POSTVENTA",
                "titulo": f"Devolución/Cambio {dv.numero_operacion}",
                "detalle": f"{dv.tipo_resolucion}: {dv.motivo}",
            }
        )

    linea_tiempo.sort(key=lambda x: x.get("fecha") or "")

    return {
        "equipo": {
            "id": eq.id,
            "serial": eq.serial,
            "modelo": eq.modelo,
            "configuracion": eq.configuracion,
            "grado_estetico": eq.grado_estetico,
            "categoria": eq.categoria,
            "ubicacion_actual": eq.ubicacion.nombre if eq.ubicacion else "",
            "estado_actual": eq.estado,
            "estado_etiqueta": ETIQUETA_PROCESO.get(eq.estado, eq.estado),
            "precio_promo_usd": _r2(eq.precio_promo_usd),
            **(
                {
                    "primer_costo_usd": _r2(primer_costo),
                    "costo_componentes_usd": _r2(costo_comp),
                    "comision_preparacion_usd": _r2(comision_prep),
                    "costo_final_usd": _r2(costo_final),
                }
                if ver_costos
                else {}
            ),
        },
        "compra_internacional": lote_info,
        "recepcion": recepcion_info,
        "historial_procesos": historial_procesos,
        "preparacion_y_costos": preparacion_costos,
        "traslados": traslados_lista,
        "venta": venta_info,
        "incidentes_postventa": incidentes,
        "linea_tiempo": linea_tiempo,
    }
