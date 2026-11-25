from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.esquemas import normalizar_sku
from app.modelos import CatalogoArticulo, EstadoSucursal, Sucursal, TipoArticulo, Usuario
from app.modelos_finanzas import ConfiguracionAlertas, CuentaPorPagar
from app.modelos_logistica import (
    Compra,
    Equipo,
    EstadoCompra,
    EstadoEquipo,
    EstadoTraslado,
    MovimientoInventario,
    Traslado,
    TrasladoDetalle,
)
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import requerir_admin, requerir_direccion_lectura


enrutador = APIRouter(prefix="/api/alertas", tags=["Alertas Inteligentes"])


def _r2(valor: Decimal) -> float:
    return float(valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _obtener_o_crear_config(bd: Session) -> ConfiguracionAlertas:
    cfg = bd.query(ConfiguracionAlertas).order_by(ConfiguracionAlertas.id.asc()).first()
    if cfg is None:
        cfg = ConfiguracionAlertas(
            stock_minimo_global=2,
            dias_alerta_cxp=5,
            actualizado_por="Sistema",
        )
        bd.add(cfg)
        bd.commit()
        bd.refresh(cfg)
    return cfg


class ConfiguracionAlertasActualizarEntrada(BaseModel):
    stock_minimo_global: int | None = Field(default=None, ge=0, le=500)
    dias_alerta_cxp: int | None = Field(default=None, ge=1, le=90)
    sku: str | None = Field(default=None, max_length=80)
    stock_minimo_sku: int | None = Field(default=None, ge=0, le=500)


class CuentaPorPagarCrearEntrada(BaseModel):
    proveedor_nombre: str = Field(min_length=2, max_length=160)
    concepto: str = Field(min_length=2, max_length=255)
    referencia: str = Field(default="", max_length=120)
    fecha_vencimiento: date
    monto_usd: Decimal = Field(gt=Decimal("0"))
    origen_tipo: str = Field(default="FACTURA", max_length=40)


@enrutador.get("/resumen")
def obtener_resumen_alertas(
    sucursal_id: int | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Resumen de Alertas Inteligentes (Stock Bajo/Agotado + CxP Vencidas/Próximas). Solo ADMIN y DIRECTOR."""
    cfg = _obtener_o_crear_config(bd)
    hoy = obtener_fecha_hoy()

    sucursales_q = bd.query(Sucursal).filter(Sucursal.estado == EstadoSucursal.ACTIVA.value)
    if sucursal_id is not None:
        sucursales_q = sucursales_q.filter(Sucursal.id == sucursal_id)
    sucursales = sucursales_q.order_by(Sucursal.id.asc()).all()

    articulos = (
        bd.query(CatalogoArticulo)
        .filter(
            CatalogoArticulo.activo.is_(True),
            CatalogoArticulo.tipo != TipoArticulo.SERVICIO.value,
        )
        .order_by(CatalogoArticulo.sku.asc())
        .all()
    )

    # Stock disponible de EQUIPOS (solo estado LISTO, excluyendo defectuosos/vendidos/en tránsito)
    equipos_listos = (
        bd.query(Equipo.articulo_id, Equipo.ubicacion_id, func.count(Equipo.id))
        .filter(
            Equipo.estado == EstadoEquipo.LISTO.value,
            Equipo.articulo_id.isnot(None),
        )
        .group_by(Equipo.articulo_id, Equipo.ubicacion_id)
        .all()
    )
    stock_eq_map: dict[tuple[int, int], int] = {
        (int(art_id), int(suc_id)): int(cnt)
        for art_id, suc_id, cnt in equipos_listos
        if art_id is not None and suc_id is not None
    }

    # Stock disponible de productos por cantidad (COMPONENTES / ACCESORIOS)
    movs_prod = (
        bd.query(
            MovimientoInventario.articulo_id,
            MovimientoInventario.sucursal_id,
            func.coalesce(func.sum(MovimientoInventario.cantidad), 0),
        )
        .filter(
            MovimientoInventario.equipo_id.is_(None),
            MovimientoInventario.articulo_id.isnot(None),
        )
        .group_by(MovimientoInventario.articulo_id, MovimientoInventario.sucursal_id)
        .all()
    )
    stock_prod_map: dict[tuple[int, int], int] = {
        (int(art_id), int(suc_id)): max(0, int(cant or 0))
        for art_id, suc_id, cant in movs_prod
        if art_id is not None and suc_id is not None
    }

    # Unidades EN_TRANSITO hacia cada sucursal (de traslados EN_TRANSITO) + equipos EN_TRANSITO globales
    transito_destino_map: dict[tuple[int, int], int] = {}
    traslados_activos = (
        bd.query(Traslado)
        .options(joinedload(Traslado.detalles).joinedload(TrasladoDetalle.equipo))
        .filter(Traslado.estado == EstadoTraslado.EN_TRANSITO.value)
        .all()
    )
    for tr in traslados_activos:
        for det in tr.detalles:
            art_id_t = det.equipo.articulo_id if det.equipo is not None else det.articulo_id
            if art_id_t is not None:
                clave_t = (int(art_id_t), int(tr.destino_id))
                transito_destino_map[clave_t] = transito_destino_map.get(clave_t, 0) + int(det.cantidad or 1)

    # También contar equipos EN_TRANSITO sin traslado activo (por ej. compras internacionales en camino)
    equipos_en_transito_directo = (
        bd.query(Equipo.articulo_id, Equipo.ubicacion_id, func.count(Equipo.id))
        .filter(
            Equipo.estado == EstadoEquipo.EN_TRANSITO.value,
            Equipo.articulo_id.isnot(None),
        )
        .group_by(Equipo.articulo_id, Equipo.ubicacion_id)
        .all()
    )
    transito_global_por_art: dict[int, int] = {}
    for art_id, _suc_id, cnt in equipos_en_transito_directo:
        if art_id is not None:
            transito_global_por_art[int(art_id)] = transito_global_por_art.get(int(art_id), 0) + int(cnt)

    alertas_inventario: list[dict[str, Any]] = []
    for art in articulos:
        minimo = int(art.stock_minimo if art.stock_minimo is not None else cfg.stock_minimo_global)
        if minimo <= 0:
            continue
        es_equipo = art.tipo == TipoArticulo.EQUIPO.value
        for suc in sucursales:
            clave = (art.id, suc.id)
            disponible = stock_eq_map.get(clave, 0) if es_equipo else stock_prod_map.get(clave, 0)
            if disponible > minimo:
                continue

            en_transito_suc = transito_destino_map.get(clave, 0)
            if en_transito_suc == 0 and es_equipo:
                en_transito_suc = transito_global_por_art.get(art.id, 0)

            severidad = "AGOTADO" if disponible == 0 else "BAJO"
            alertas_inventario.append(
                {
                    "articulo_id": art.id,
                    "sku": art.sku,
                    "nombre": art.descripcion,
                    "categoria": art.categoria,
                    "tipo": art.tipo,
                    "sucursal_id": suc.id,
                    "almacen": suc.nombre,
                    "stock_disponible": disponible,
                    "stock_minimo": minimo,
                    "cantidad_en_transito": en_transito_suc,
                    "severidad": severidad,
                }
            )

    alertas_inventario.sort(
        key=lambda x: (0 if x["severidad"] == "AGOTADO" else 1, x["stock_disponible"], x["sku"])
    )

    # 2. Alertas de Cuentas por Pagar (CxP)
    alertas_cxp: list[dict[str, Any]] = []

    cxp_filas = (
        bd.query(CuentaPorPagar)
        .filter(
            CuentaPorPagar.estado == "PENDIENTE",
            CuentaPorPagar.monto_pendiente_usd > 0,
        )
        .all()
    )
    for cxp in cxp_filas:
        delta = (cxp.fecha_vencimiento - hoy).days
        if delta < 0:
            urgencia = "VENCIDA"
            dias_diff = abs(delta)
        elif delta == 0:
            urgencia = "VENCE_HOY"
            dias_diff = 0
        elif delta <= cfg.dias_alerta_cxp:
            urgencia = "PROXIMA"
            dias_diff = delta
        else:
            continue

        alertas_cxp.append(
            {
                "id": cxp.id,
                "fuente": "CXP",
                "proveedor": cxp.proveedor_nombre,
                "concepto_o_referencia": (
                    f"{cxp.concepto} ({cxp.referencia})" if cxp.referencia else cxp.concepto
                ),
                "fecha_vencimiento": cxp.fecha_vencimiento.isoformat(),
                "monto_pendiente_usd": _r2(Decimal(cxp.monto_pendiente_usd)),
                "dias_diferencia": dias_diff,
                "urgencia": urgencia,
            }
        )

    compras_pend = (
        bd.query(Compra)
        .filter(
            Compra.estado.in_([EstadoCompra.PENDIENTE.value, EstadoCompra.RECIBIDA_PARCIAL.value]),
            Compra.fecha_vencimiento.isnot(None),
        )
        .all()
    )
    for cmp in compras_pend:
        assert cmp.fecha_vencimiento is not None
        delta = (cmp.fecha_vencimiento - hoy).days
        if delta < 0:
            urgencia = "VENCIDA"
            dias_diff = abs(delta)
        elif delta == 0:
            urgencia = "VENCE_HOY"
            dias_diff = 0
        elif delta <= cfg.dias_alerta_cxp:
            urgencia = "PROXIMA"
            dias_diff = delta
        else:
            continue

        monto_cmp = (
            Decimal(cmp.monto_mercancia_usd or 0)
            + Decimal(cmp.envio_usd or 0)
            + Decimal(cmp.otros_gastos_usd or 0)
        )
        alertas_cxp.append(
            {
                "id": cmp.id,
                "fuente": "COMPRA",
                "proveedor": cmp.proveedor_nombre or "Proveedor",
                "concepto_o_referencia": f"Compra {cmp.numero_compra}"
                + (f" · {cmp.factura_orden}" if cmp.factura_orden else ""),
                "fecha_vencimiento": cmp.fecha_vencimiento.isoformat(),
                "monto_pendiente_usd": _r2(monto_cmp),
                "dias_diferencia": dias_diff,
                "urgencia": urgencia,
            }
        )

    orden_urgencia = {"VENCIDA": 0, "VENCE_HOY": 1, "PROXIMA": 2}
    alertas_cxp.sort(
        key=lambda x: (
            orden_urgencia.get(x["urgencia"], 9),
            -x["dias_diferencia"] if x["urgencia"] == "VENCIDA" else x["dias_diferencia"],
        )
    )

    criticas_inv = sum(1 for a in alertas_inventario if a["severidad"] == "AGOTADO")
    preventivas_inv = sum(1 for a in alertas_inventario if a["severidad"] == "BAJO")
    criticas_cxp = sum(1 for c in alertas_cxp if c["urgencia"] in ("VENCIDA", "VENCE_HOY"))
    preventivas_cxp = sum(1 for c in alertas_cxp if c["urgencia"] == "PROXIMA")
    monto_total_cxp = sum((Decimal(str(c["monto_pendiente_usd"])) for c in alertas_cxp), Decimal("0"))

    return {
        "fecha_evaluacion": hoy.isoformat(),
        "configuracion": {
            "stock_minimo_global": cfg.stock_minimo_global,
            "dias_alerta_cxp": cfg.dias_alerta_cxp,
            "actualizado_por": cfg.actualizado_por,
        },
        "contadores": {
            "total_criticas": criticas_inv + criticas_cxp,
            "total_preventivas": preventivas_inv + preventivas_cxp,
            "total_alertas": len(alertas_inventario) + len(alertas_cxp),
            "agotados": criticas_inv,
            "stock_bajo": preventivas_inv,
            "cxp_criticas": criticas_cxp,
            "cxp_proximas": preventivas_cxp,
            "monto_total_cxp_alerta_usd": _r2(monto_total_cxp),
        },
        "inventario": alertas_inventario,
        "cuentas_por_pagar": alertas_cxp,
    }


@enrutador.patch("/configuracion")
def actualizar_configuracion_alertas(
    datos: ConfiguracionAlertasActualizarEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Actualiza umbrales globales de alertas y/o stock_minimo de un SKU específico. Solo ADMIN."""
    cfg = _obtener_o_crear_config(bd)

    if datos.stock_minimo_global is not None:
        viejo_global = cfg.stock_minimo_global
        cfg.stock_minimo_global = datos.stock_minimo_global
        # Actualizar artículos que mantenían el mínimo global anterior
        bd.query(CatalogoArticulo).filter(
            CatalogoArticulo.stock_minimo == viejo_global
        ).update({"stock_minimo": datos.stock_minimo_global})

    if datos.dias_alerta_cxp is not None:
        cfg.dias_alerta_cxp = datos.dias_alerta_cxp

    sku_actualizado: dict[str, Any] | None = None
    if datos.sku is not None:
        if datos.stock_minimo_sku is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes indicar stock_minimo_sku al especificar un SKU.",
            )
        sku_norm = normalizar_sku(datos.sku)
        art = bd.query(CatalogoArticulo).filter(CatalogoArticulo.sku == sku_norm).first()
        if art is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SKU '{sku_norm}' no encontrado en el catálogo.",
            )
        art.stock_minimo = datos.stock_minimo_sku
        sku_actualizado = {
            "sku": art.sku,
            "nombre": art.descripcion,
            "stock_minimo": art.stock_minimo,
        }

    cfg.actualizado_por = usuario_actual.nombre
    bd.commit()
    bd.refresh(cfg)

    return {
        "stock_minimo_global": cfg.stock_minimo_global,
        "dias_alerta_cxp": cfg.dias_alerta_cxp,
        "actualizado_por": cfg.actualizado_por,
        "sku_actualizado": sku_actualizado,
    }


@enrutador.post("/cxp", status_code=status.HTTP_201_CREATED)
def registrar_cuenta_por_pagar(
    datos: CuentaPorPagarCrearEntrada,
    _usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Registra una factura o cuenta por pagar con fecha de vencimiento. Solo ADMIN."""
    cxp = CuentaPorPagar(
        proveedor_nombre=datos.proveedor_nombre.strip(),
        concepto=datos.concepto.strip(),
        referencia=datos.referencia.strip(),
        fecha_vencimiento=datos.fecha_vencimiento,
        monto_original_usd=datos.monto_usd,
        monto_pendiente_usd=datos.monto_usd,
        estado="PENDIENTE",
        origen_tipo=datos.origen_tipo.strip().upper(),
    )
    bd.add(cxp)
    bd.commit()
    bd.refresh(cxp)
    return {
        "id": cxp.id,
        "proveedor_nombre": cxp.proveedor_nombre,
        "concepto": cxp.concepto,
        "referencia": cxp.referencia,
        "fecha_vencimiento": cxp.fecha_vencimiento.isoformat(),
        "monto_pendiente_usd": _r2(Decimal(cxp.monto_pendiente_usd)),
        "estado": cxp.estado,
    }
