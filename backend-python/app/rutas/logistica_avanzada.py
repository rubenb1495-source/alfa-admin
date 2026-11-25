from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.esquemas import normalizar_sku
from app.esquemas_logistica import normalizar_serial
from app.modelos import CatalogoArticulo, EstadoSucursal, RolUsuario, Sucursal, TipoArticulo, Usuario
from app.modelos_logistica import (
    Compra,
    CompraComponente,
    Equipo,
    EstadoCompra,
    EstadoEquipo,
    EstadoTraslado,
    HistorialEstadoEquipo,
    MovimientoInventario,
    OrigenCompra,
    TipoMovimientoInventario,
    Traslado,
    TrasladoDetalle,
)
from app.modelos_contabilidad import EquipoComponenteInstalado
from app.rutas.logistica import (
    calcular_stock_componente,
    generar_correlativo,
    redondear_usd,
    serializar_equipo,
)
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import obtener_usuario_actual, puede_ver_costos, requerir_admin, requerir_roles
from app.servicios.contabilidad import crear_asiento_contable


enrutador = APIRouter(tags=["Logística Avanzada y Preparaciones"])

ROLES_PREPARACIONES: tuple[str, ...] = (
    RolUsuario.DIRECCION.value,
    RolUsuario.ADMINISTRACION.value,
    RolUsuario.LOGISTICA.value,
    RolUsuario.ENCARGADO_TIENDA.value,
    RolUsuario.LIDER.value,
    RolUsuario.TECNICO.value,
)

ROLES_TRASLADOS_MASIVOS: tuple[str, ...] = (
    RolUsuario.DIRECCION.value,
    RolUsuario.ADMINISTRACION.value,
    RolUsuario.LOGISTICA.value,
    RolUsuario.ENCARGADO_TIENDA.value,
    RolUsuario.LIDER.value,
)

TIPOS_PLANTILLA_VALIDOS: set[str] = {
    "COMPRA_NACIONAL",
    "COMPRA_INTERNACIONAL",
    "CONSIGNACION",
    "TRASLADO",
    "PREPARACION_ESTADOS",
}

MAPA_ESTADOS_EQUIPO: dict[str, str] = {
    "DISPONIBLE": EstadoEquipo.LISTO.value,
    "LISTO": EstadoEquipo.LISTO.value,
    "PENDIENTE_REVISION": EstadoEquipo.PENDIENTE_REVISION.value,
    "POR_PREPARAR": EstadoEquipo.POR_PREPARAR.value,
    "EN_PREPARACION": EstadoEquipo.EN_PREPARACION.value,
    "DEFECTUOSO": EstadoEquipo.DEFECTUOSO.value,
    "RESERVADO": EstadoEquipo.RESERVADO.value,
    "EN_GARANTIA": EstadoEquipo.EN_GARANTIA.value,
    "HOSPITAL": EstadoEquipo.HOSPITAL.value,
    "CEMENTERIO": EstadoEquipo.CEMENTERIO.value,
}

ESTADOS_ETIQUETA_UI: dict[str, str] = {
    EstadoEquipo.LISTO.value: "Disponible",
    EstadoEquipo.PENDIENTE_REVISION.value: "Pendiente Revisión",
    EstadoEquipo.POR_PREPARAR.value: "Por Preparar",
    EstadoEquipo.EN_PREPARACION.value: "En Preparación",
    EstadoEquipo.DEFECTUOSO.value: "Defectuoso",
    EstadoEquipo.RESERVADO.value: "Reservado",
    EstadoEquipo.EN_GARANTIA.value: "En Garantía",
    EstadoEquipo.EN_TRANSITO.value: "En Tránsito",
    EstadoEquipo.HOSPITAL.value: "Hospital",
    EstadoEquipo.CEMENTERIO.value: "Cementerio",
    EstadoEquipo.VENDIDO.value: "Vendido",
}


def normalizar_estado_equipo(valor: str | None, defecto: str | None = None) -> str:
    if not valor or not valor.strip():
        if defecto is not None:
            return defecto
        raise ValueError("El estado del equipo es obligatorio.")
    clave = valor.strip().upper().replace(" ", "_")
    if clave not in MAPA_ESTADOS_EQUIPO:
        validos = ", ".join(sorted(MAPA_ESTADOS_EQUIPO.keys()))
        raise ValueError(f"Estado '{valor}' inválido. Valores permitidos: {validos}.")
    return MAPA_ESTADOS_EQUIPO[clave]


def parsear_decimal_seguro(valor: Any, defecto: Decimal = Decimal("0")) -> Decimal:
    if valor is None:
        return defecto
    texto = str(valor).strip().replace("$", "").replace(",", ".")
    if not texto:
        return defecto
    try:
        return Decimal(texto)
    except InvalidOperation as exc:
        raise ValueError(f"Valor numérico inválido: '{valor}'.") from exc


def parsear_entero_seguro(valor: Any, defecto: int = 1) -> int:
    if valor is None or str(valor).strip() == "":
        return defecto
    try:
        numero = int(Decimal(str(valor).strip()))
        return numero
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"Cantidad entera inválida: '{valor}'.") from exc


def _normalizar_encabezado(valor: Any) -> str:
    if valor is None:
        return ""
    texto = str(valor).strip().lower()
    reemplazos = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
        " ": "_",
        "-": "_",
    }
    for orig, dest in reemplazos.items():
        texto = texto.replace(orig, dest)
    return texto


def _leer_filas_archivo(contenido: bytes, nombre_archivo: str) -> list[tuple[int, dict[str, str]]]:
    nombre = (nombre_archivo or "").lower()
    if nombre.endswith(".xlsx") or nombre.endswith(".xlsm"):
        wb = load_workbook(io.BytesIO(contenido), data_only=True)
        hoja = wb["Datos"] if "Datos" in wb.sheetnames else wb.active
        filas_crudas = list(hoja.iter_rows(values_only=True))
        if not filas_crudas:
            return []
        encabezados = [_normalizar_encabezado(c) for c in filas_crudas[0]]
        resultado: list[tuple[int, dict[str, str]]] = []
        for idx, fila in enumerate(filas_crudas[1:], start=2):
            if all(v is None or str(v).strip() == "" for v in fila):
                continue
            dic = {
                encabezados[i]: ("" if fila[i] is None else str(fila[i]).strip())
                for i in range(min(len(encabezados), len(fila)))
                if encabezados[i]
            }
            resultado.append((idx, dic))
        return resultado

    if nombre.endswith(".csv") or nombre.endswith(".txt"):
        texto: str | None = None
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                texto = contenido.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if texto is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se pudo decodificar el archivo CSV.",
            )
        muestra = texto[:2048]
        delimitador = ";" if muestra.count(";") > muestra.count(",") else ","
        lector = csv.reader(io.StringIO(texto), delimiter=delimitador)
        filas_crudas_csv = list(lector)
        if not filas_crudas_csv:
            return []
        encabezados = [_normalizar_encabezado(c) for c in filas_crudas_csv[0]]
        resultado_csv: list[tuple[int, dict[str, str]]] = []
        for idx, fila in enumerate(filas_crudas_csv[1:], start=2):
            if all(not c.strip() for c in fila):
                continue
            dic = {
                encabezados[i]: fila[i].strip()
                for i in range(min(len(encabezados), len(fila)))
                if encabezados[i]
            }
            resultado_csv.append((idx, dic))
        return resultado_csv

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Formato no soportado. Sube un archivo .xlsx o .csv.",
    )


def _verificar_permiso_tipo(tipo: str, usuario: Usuario) -> None:
    if tipo in {"COMPRA_NACIONAL", "COMPRA_INTERNACIONAL", "CONSIGNACION"}:
        if usuario.rol not in {RolUsuario.DIRECCION.value, RolUsuario.ADMINISTRACION.value}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo el Administrador puede registrar compras o consignaciones.",
            )
    elif tipo == "TRASLADO":
        if usuario.rol not in ROLES_TRASLADOS_MASIVOS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para gestionar traslados.",
            )
    elif tipo == "PREPARACION_ESTADOS":
        if usuario.rol not in ROLES_PREPARACIONES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para cambiar estados de preparación.",
            )


# ---------------- Esquemas Pydantic ----------------


class ItemIngresoEntrada(BaseModel):
    sku: str = Field(min_length=2, max_length=60)
    serial: str | None = Field(default=None, max_length=120)
    cantidad: int = Field(default=1, ge=1)
    costo_unitario_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    precio_venta_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    estado_inicial: str | None = Field(default="PENDIENTE_REVISION")
    nota: str = Field(default="", max_length=300)

    @field_validator("serial", "estado_inicial", mode="before")
    @classmethod
    def _vacio_a_none(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("nota", mode="before")
    @classmethod
    def _none_a_vacio_nota(cls, v: Any) -> str:
        return "" if v is None else str(v)

    @field_validator("costo_unitario_usd", mode="before")
    @classmethod
    def _coercer_costo(cls, v: Any) -> Any:
        if v is None or (isinstance(v, str) and not v.strip()):
            return Decimal("0")
        if isinstance(v, str):
            return v.strip().replace(",", ".")
        return v

    @field_validator("precio_venta_usd", mode="before")
    @classmethod
    def _coercer_precio_opcional(cls, v: Any) -> Any:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            return v.strip().replace(",", ".")
        return v


class IngresoInventarioCrearEntrada(BaseModel):
    tipo_ingreso: str = Field(pattern="^(COMPRA_NACIONAL|COMPRA_INTERNACIONAL|CONSIGNACION)$")
    proveedor_nombre: str = Field(min_length=2, max_length=160)
    almacen_destino_id: int = Field(gt=0)
    referencia_factura: str = Field(default="", max_length=120)
    observaciones: str = Field(default="", max_length=500)
    costo_flete_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    costo_aduana_otros_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    tracking_guia: str = Field(default="", max_length=120)
    items: list[ItemIngresoEntrada] = Field(min_length=1)

    @field_validator("referencia_factura", "observaciones", "tracking_guia", mode="before")
    @classmethod
    def _none_a_vacio_str(cls, v: Any) -> str:
        return "" if v is None else str(v)

    @field_validator("costo_flete_usd", "costo_aduana_otros_usd", mode="before")
    @classmethod
    def _coercer_gastos(cls, v: Any) -> Any:
        if v is None or (isinstance(v, str) and not v.strip()):
            return Decimal("0")
        if isinstance(v, str):
            return v.strip().replace(",", ".")
        return v


class ComponentePreparacionEntrada(BaseModel):
    articulo_id: int
    cantidad: int = Field(ge=1)


class CambioEstadoMasivoEntrada(BaseModel):
    equipo_ids: list[int] = Field(default_factory=list)
    seriales: list[str] = Field(default_factory=list)
    nuevo_estado: str = Field(min_length=2, max_length=40)
    observacion: str = Field(default="", max_length=400)
    componentes_usados: list[ComponentePreparacionEntrada] = Field(default_factory=list)


# ---------------- Motor de Ingresos (CN / CI / CON) ----------------


def _ejecutar_ingreso_inventario(
    bd: Session,
    usuario: Usuario,
    tipo_ingreso: str,
    proveedor_nombre: str,
    almacen_destino: Sucursal,
    referencia_factura: str,
    observaciones: str,
    costo_flete_usd: Decimal,
    costo_aduana_otros_usd: Decimal,
    tracking_guia: str,
    items_normalizados: list[dict[str, Any]],
) -> dict[str, Any]:
    prefijo_mapa = {
        "COMPRA_NACIONAL": "CN",
        "COMPRA_INTERNACIONAL": "CI",
        "CONSIGNACION": "CON",
    }
    prefijo = prefijo_mapa[tipo_ingreso]
    numero_compra = generar_correlativo(bd, Compra, Compra.numero_compra, prefijo)

    total_unidades = sum(int(item["cantidad"]) for item in items_normalizados)
    if total_unidades <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El ingreso debe contener al menos una unidad.",
        )

    gastos_importacion = (
        (costo_flete_usd + costo_aduana_otros_usd)
        if tipo_ingreso == "COMPRA_INTERNACIONAL"
        else Decimal("0")
    )
    prorrateo_unitario = (
        (gastos_importacion / Decimal(total_unidades)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if gastos_importacion > 0
        else Decimal("0")
    )

    subtotal_items = sum(
        Decimal(str(item["costo_unitario_usd"])) * int(item["cantidad"])
        for item in items_normalizados
    )
    total_compra = subtotal_items + gastos_importacion

    nota_compuesta = observaciones.strip()
    if referencia_factura.strip():
        nota_compuesta = (
            f"Ref/Factura: {referencia_factura.strip()}"
            + (f" | {nota_compuesta}" if nota_compuesta else "")
        )

    compra = Compra(
        numero_compra=numero_compra,
        origen=tipo_ingreso,
        fecha=obtener_fecha_hoy(),
        factura_orden=referencia_factura.strip(),
        estado=EstadoCompra.RECIBIDA.value,
        proveedor_nombre=proveedor_nombre.strip(),
        tracking_guia=tracking_guia.strip(),
        monto_mercancia_usd=subtotal_items,
        envio_usd=costo_flete_usd if tipo_ingreso == "COMPRA_INTERNACIONAL" else Decimal("0"),
        otros_gastos_usd=costo_aduana_otros_usd if tipo_ingreso == "COMPRA_INTERNACIONAL" else Decimal("0"),
        creado_por_id=usuario.id,
        nota=nota_compuesta,
    )
    bd.add(compra)
    bd.flush()

    equipos_creados = 0
    productos_creados = 0
    es_consignacion = tipo_ingreso == "CONSIGNACION"
    ahora = datetime.now(timezone.utc)

    for item in items_normalizados:
        articulo: CatalogoArticulo = item["articulo"]
        serial: str | None = item.get("serial")
        cantidad: int = int(item["cantidad"])
        costo_unit: Decimal = Decimal(str(item["costo_unitario_usd"]))
        precio_catalogo = (
            articulo.precios[0].precio_promo_usd
            if getattr(articulo, "precios", None)
            else Decimal("0")
        )
        precio_venta: Decimal = (
            Decimal(str(item["precio_venta_usd"]))
            if item.get("precio_venta_usd") is not None
            else precio_catalogo
        )
        estado_inicial: str = item.get("estado_inicial") or EstadoEquipo.PENDIENTE_REVISION.value
        nota_item: str = item.get("nota") or ""

        if serial:
            equipo = Equipo(
                serial=serial,
                articulo_id=articulo.id,
                compra_id=compra.id,
                modelo=articulo.descripcion,
                configuracion="",
                categoria=articulo.categoria or "",
                ubicacion_id=almacen_destino.id,
                estado=estado_inicial,
                costo_compra_usd=costo_unit,
                costo_flete_usd=prorrateo_unitario,
                costo_taller_usd=Decimal("0"),
                precio_promo_usd=precio_venta,
                es_consignacion=es_consignacion,
                consignante_nombre=proveedor_nombre.strip() if es_consignacion else "",
                costo_acordado_usd=costo_unit if es_consignacion else None,
                recibido_por_id=usuario.id,
                fecha_recepcion=ahora,
                nota=nota_item,
            )
            bd.add(equipo)
            bd.flush()
            bd.add(
                HistorialEstadoEquipo(
                    equipo_id=equipo.id,
                    estado_anterior="",
                    estado_nuevo=estado_inicial,
                    usuario_id=usuario.id,
                    nota_tecnica=f"Ingreso {numero_compra} ({tipo_ingreso})",
                )
            )
            bd.add(
                MovimientoInventario(
                    tipo=TipoMovimientoInventario.COMPRA.value,
                    articulo_id=articulo.id,
                    equipo_id=equipo.id,
                    sucursal_id=almacen_destino.id,
                    cantidad=1,
                    costo_unitario_usd=costo_unit + prorrateo_unitario,
                    documento_ref=numero_compra,
                    motivo=f"Ingreso {tipo_ingreso} - {proveedor_nombre.strip()}",
                    usuario_id=usuario.id,
                )
            )
            equipos_creados += 1
        else:
            bd.add(
                CompraComponente(
                    compra_id=compra.id,
                    articulo_id=articulo.id,
                    cantidad=cantidad,
                    cantidad_recibida=cantidad,
                    costo_unitario_usd=costo_unit,
                    costo_flete_unitario_usd=prorrateo_unitario,
                )
            )
            bd.add(
                MovimientoInventario(
                    tipo=TipoMovimientoInventario.COMPRA.value,
                    articulo_id=articulo.id,
                    equipo_id=None,
                    sucursal_id=almacen_destino.id,
                    cantidad=cantidad,
                    costo_unitario_usd=costo_unit + prorrateo_unitario,
                    documento_ref=numero_compra,
                    motivo=f"Ingreso {tipo_ingreso} - {proveedor_nombre.strip()}",
                    usuario_id=usuario.id,
                )
            )
            productos_creados += cantidad

    bd.commit()
    return {
        "id": compra.id,
        "codigo": numero_compra,
        "tipo_ingreso": tipo_ingreso,
        "proveedor_nombre": compra.proveedor_nombre,
        "almacen_destino": almacen_destino.nombre,
        "tracking_guia": compra.tracking_guia,
        "gastos_importacion_usd": redondear_usd(gastos_importacion),
        "prorrateo_unitario_usd": redondear_usd(prorrateo_unitario),
        "total_compra_usd": redondear_usd(total_compra),
        "equipos_creados": equipos_creados,
        "productos_creados": productos_creados,
        "total_unidades": total_unidades,
    }


@enrutador.post("/api/logistica/ingresos", status_code=status.HTTP_201_CREATED)
def crear_ingreso_inventario(
    datos: IngresoInventarioCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    almacen = bd.query(Sucursal).filter(Sucursal.id == datos.almacen_destino_id).first()
    if almacen is None or almacen.estado != EstadoSucursal.ACTIVA.value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Almacén destino no encontrado o inactivo.",
        )

    skus_unicos = {normalizar_sku(it.sku) for it in datos.items}
    articulos = bd.query(CatalogoArticulo).filter(CatalogoArticulo.sku.in_(skus_unicos)).all()
    mapa_art = {a.sku: a for a in articulos}

    seriales_lote: set[str] = set()
    items_norm: list[dict[str, Any]] = []

    for idx, it in enumerate(datos.items, start=1):
        sku_norm = normalizar_sku(it.sku)
        articulo = mapa_art.get(sku_norm)
        if articulo is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Ítem #{idx}: el SKU '{sku_norm}' no existe en el catálogo.",
            )
        serial_norm: str | None = None
        if it.serial and it.serial.strip():
            serial_norm = normalizar_serial(it.serial)
            if serial_norm in seriales_lote:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Ítem #{idx}: serial '{serial_norm}' duplicado en el ingreso.",
                )
            seriales_lote.add(serial_norm)
        elif articulo.tipo == TipoArticulo.EQUIPO.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Ítem #{idx}: el SKU '{sku_norm}' es un EQUIPO y requiere serial obligatorio.",
            )

        try:
            estado_norm = normalizar_estado_equipo(
                it.estado_inicial, defecto=EstadoEquipo.PENDIENTE_REVISION.value
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        items_norm.append(
            {
                "articulo": articulo,
                "serial": serial_norm,
                "cantidad": 1 if serial_norm else it.cantidad,
                "costo_unitario_usd": it.costo_unitario_usd,
                "precio_venta_usd": it.precio_venta_usd,
                "estado_inicial": estado_norm,
                "nota": it.nota,
            }
        )

    if seriales_lote:
        existentes = {
            row[0]
            for row in bd.query(Equipo.serial).filter(Equipo.serial.in_(seriales_lote)).all()
        }
        if existentes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Los siguientes seriales ya existen en inventario: {', '.join(sorted(existentes))}.",
            )

    return _ejecutar_ingreso_inventario(
        bd=bd,
        usuario=usuario_actual,
        tipo_ingreso=datos.tipo_ingreso,
        proveedor_nombre=datos.proveedor_nombre,
        almacen_destino=almacen,
        referencia_factura=datos.referencia_factura,
        observaciones=datos.observaciones,
        costo_flete_usd=datos.costo_flete_usd,
        costo_aduana_otros_usd=datos.costo_aduana_otros_usd,
        tracking_guia=datos.tracking_guia,
        items_normalizados=items_norm,
    )


@enrutador.get("/api/logistica/ingresos")
def listar_ingresos_inventario(
    tipo_ingreso: str | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    consulta = (
        bd.query(Compra)
        .options(
            joinedload(Compra.creado_por),
            joinedload(Compra.equipos),
            joinedload(Compra.componentes),
        )
        .order_by(Compra.creado_en.desc())
    )
    if tipo_ingreso:
        consulta = consulta.filter(Compra.origen == tipo_ingreso.upper())
    compras = consulta.limit(100).all()
    resultado: list[dict[str, Any]] = []
    for c in compras:
        unidades_comp = sum(comp.cantidad for comp in c.componentes)
        gastos_imp = (c.envio_usd or Decimal("0")) + (c.otros_gastos_usd or Decimal("0"))
        total_cmp = (c.monto_mercancia_usd or Decimal("0")) + gastos_imp
        resultado.append(
            {
                "id": c.id,
                "codigo": c.numero_compra,
                "tipo_ingreso": c.origen,
                "estado": c.estado,
                "proveedor_nombre": c.proveedor_nombre or "",
                "tracking_guia": c.tracking_guia or "",
                "costo_flete_usd": redondear_usd(gastos_imp),
                "total_compra_usd": redondear_usd(total_cmp),
                "equipos_cantidad": len(c.equipos),
                "productos_cantidad": unidades_comp,
                "registrado_por": c.creado_por.nombre if c.creado_por else "",
                "nota": c.nota or "",
                "creado_en": c.creado_en.isoformat() if c.creado_en else None,
            }
        )
    return resultado


# ---------------- Preparaciones: Cambio de Estado Masivo + Historial ----------------


@enrutador.patch("/api/preparaciones/estado-masivo")
def cambiar_estado_masivo(
    datos: CambioEstadoMasivoEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_PREPARACIONES)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    if not datos.equipo_ids and not datos.seriales:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes seleccionar al menos un equipo (por ID o serial).",
        )
    try:
        estado_destino = normalizar_estado_equipo(datos.nuevo_estado)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    seriales_norm = [normalizar_serial(s) for s in datos.seriales if s.strip()]
    consulta = bd.query(Equipo).options(
        joinedload(Equipo.articulo),
        joinedload(Equipo.ubicacion),
    )
    if datos.equipo_ids and seriales_norm:
        equipos = consulta.filter(
            (Equipo.id.in_(datos.equipo_ids)) | (Equipo.serial.in_(seriales_norm))
        ).all()
    elif datos.equipo_ids:
        equipos = consulta.filter(Equipo.id.in_(datos.equipo_ids)).all()
    else:
        equipos = consulta.filter(Equipo.serial.in_(seriales_norm)).all()

    if not equipos:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontraron equipos con los criterios indicados.",
        )

    estados_bloqueados = {EstadoEquipo.VENDIDO.value, EstadoEquipo.EN_TRANSITO.value}
    for eq in equipos:
        if eq.estado in estados_bloqueados:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El equipo '{eq.serial}' está '{eq.estado}' y no puede cambiar de estado.",
            )

    # Si hay componentes usados, verificar stock suficiente por sucursal
    if datos.componentes_usados:
        if len(equipos) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El consumo de componentes aplica sobre un equipo a la vez.",
            )
        eq_unico = equipos[0]
        for comp in datos.componentes_usados:
            articulo = bd.query(CatalogoArticulo).filter(CatalogoArticulo.id == comp.articulo_id).first()
            if articulo is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Componente ID {comp.articulo_id} no encontrado.",
                )
            stock_disp = calcular_stock_componente(bd, comp.articulo_id, eq_unico.ubicacion_id)
            if stock_disp < comp.cantidad:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Stock insuficiente para '{articulo.descripcion}' en la sucursal del equipo (disponible: {stock_disp}).",
                )
            costo_ref = (
                (articulo.precios[0].costo_referencia_usd or Decimal("0"))
                if getattr(articulo, "precios", None)
                else Decimal("0")
            )
            costo_linea = (costo_ref * comp.cantidad).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            eq_unico.costo_taller_usd = (eq_unico.costo_taller_usd or Decimal("0")) + costo_linea
            bd.add(
                EquipoComponenteInstalado(
                    equipo_id=eq_unico.id,
                    articulo_id=articulo.id,
                    sku=articulo.sku,
                    descripcion=articulo.descripcion,
                    cantidad=comp.cantidad,
                    costo_unitario_usd=costo_ref,
                    costo_total_usd=costo_linea,
                    instalado_por_id=usuario_actual.id,
                )
            )
            bd.add(
                MovimientoInventario(
                    tipo=TipoMovimientoInventario.TALLER.value,
                    articulo_id=articulo.id,
                    equipo_id=None,
                    sucursal_id=eq_unico.ubicacion_id,
                    cantidad=-comp.cantidad,
                    costo_unitario_usd=costo_ref,
                    documento_ref=f"PREP-{eq_unico.serial}",
                    motivo=f"Consumo en preparación de {eq_unico.serial}",
                    usuario_id=usuario_actual.id,
                )
            )
            if costo_linea > 0:
                cuenta_destino_eq = "1.1.03" if estado_destino == EstadoEquipo.LISTO.value else "1.1.04"
                crear_asiento_contable(
                    bd=bd,
                    usuario=usuario_actual,
                    fecha_op=obtener_fecha_hoy(),
                    descripcion=f"Costeo preparación {eq_unico.serial}: {articulo.sku} x{comp.cantidad}",
                    origen_tipo="PREPARACION",
                    origen_id=eq_unico.id,
                    lineas=[
                        {"cuenta_codigo": cuenta_destino_eq, "debe_usd": costo_linea, "haber_usd": Decimal("0")},
                        {"cuenta_codigo": "1.1.05", "debe_usd": Decimal("0"), "haber_usd": costo_linea},
                    ],
                )

    incluir_costos = puede_ver_costos(usuario_actual.rol)
    actualizados: list[dict[str, Any]] = []
    for eq in equipos:
        estado_anterior = eq.estado
        eq.estado = estado_destino
        if datos.observacion.strip():
            eq.nota = (
                f"{eq.nota} | {datos.observacion.strip()}" if eq.nota else datos.observacion.strip()
            )
        bd.add(
            HistorialEstadoEquipo(
                equipo_id=eq.id,
                estado_anterior=estado_anterior,
                estado_nuevo=estado_destino,
                usuario_id=usuario_actual.id,
                nota_tecnica=datos.observacion.strip(),
            )
        )
        actualizados.append(serializar_equipo(eq, incluir_costos))

    bd.commit()
    return {
        "actualizados": len(actualizados),
        "estado_aplicado": estado_destino,
        "estado_etiqueta": ESTADOS_ETIQUETA_UI.get(estado_destino, estado_destino),
        "equipos": actualizados,
    }


@enrutador.get("/api/preparaciones/equipos/{equipo_id}/historial")
def listar_historial_equipo(
    equipo_id: int,
    _usuario: Usuario = Depends(requerir_roles(*ROLES_PREPARACIONES)),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    equipo = bd.query(Equipo).filter(Equipo.id == equipo_id).first()
    if equipo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipo no encontrado.")
    filas = (
        bd.query(HistorialEstadoEquipo)
        .options(joinedload(HistorialEstadoEquipo.usuario))
        .filter(HistorialEstadoEquipo.equipo_id == equipo_id)
        .order_by(HistorialEstadoEquipo.fecha.desc(), HistorialEstadoEquipo.id.desc())
        .all()
    )
    return [
        {
            "id": f.id,
            "equipo_id": f.equipo_id,
            "estado_anterior": f.estado_anterior,
            "estado_nuevo": f.estado_nuevo,
            "estado_nuevo_etiqueta": ESTADOS_ETIQUETA_UI.get(f.estado_nuevo, f.estado_nuevo),
            "usuario_nombre": f.usuario.nombre if f.usuario else "",
            "observacion": f.nota_tecnica,
            "creado_en": f.fecha.isoformat() if f.fecha else None,
        }
        for f in filas
    ]


# ---------------- Planillas Descargables (.xlsx) ----------------


@enrutador.get("/api/logistica/plantilla/{tipo}")
def descargar_plantilla_excel(
    tipo: str,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> StreamingResponse:
    tipo_norm = tipo.strip().upper()
    if tipo_norm not in TIPOS_PLANTILLA_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de plantilla inválido. Usa: {', '.join(sorted(TIPOS_PLANTILLA_VALIDOS))}.",
        )
    _verificar_permiso_tipo(tipo_norm, usuario_actual)

    sucursales = (
        bd.query(Sucursal)
        .filter(Sucursal.estado == EstadoSucursal.ACTIVA.value)
        .order_by(Sucursal.id.asc())
        .all()
    )
    articulos = (
        bd.query(CatalogoArticulo)
        .filter(CatalogoArticulo.activo.is_(True))
        .order_by(CatalogoArticulo.sku.asc())
        .limit(60)
        .all()
    )

    sku_equipo_ejemplo = next(
        (a.sku for a in articulos if a.tipo == TipoArticulo.EQUIPO.value),
        "LP-DELL-5420-I5",
    )
    sku_comp_ejemplo = next(
        (a.sku for a in articulos if a.tipo != TipoArticulo.EQUIPO.value),
        "CO-CARG-DEL-TIPO-C",
    )
    almacen_ejemplo = sucursales[0].nombre if sucursales else "Almacén Guaparo Norte"

    wb = Workbook()
    ws_datos = wb.active
    ws_datos.title = "Datos"

    relleno_header = PatternFill(start_color="003566", end_color="003566", fill_type="solid")
    fuente_header = Font(color="FFFFFF", bold=True, size=11)
    alineacion_header = Alignment(horizontal="center", vertical="center")

    definiciones: dict[str, tuple[list[str], list[list[Any]], list[str]]] = {
        "COMPRA_NACIONAL": (
            ["sku", "serial", "cantidad", "costo_unitario_usd", "precio_venta_usd", "estado_inicial", "nota"],
            [
                [sku_equipo_ejemplo, "SN-EJEMPLO-001", 1, 210.00, 290.00, "PENDIENTE_REVISION", "Laptop nacional ejemplo"],
                [sku_comp_ejemplo, "", 10, 12.50, 25.00, "DISPONIBLE", "Cargadores ejemplo"],
            ],
            [
                "sku (obligatorio): Código SKU exacto registrado en el Catálogo.",
                "serial (obligatorio para equipos, vacío para componentes/accesorios): Serial único.",
                "cantidad: 1 para equipos con serial; número entero >= 1 para componentes/accesorios.",
                "costo_unitario_usd (obligatorio): Costo de compra unitario en USD.",
                "precio_venta_usd (opcional): Si se deja vacío usa el Precio Promo del catálogo.",
                "estado_inicial (opcional): PENDIENTE_REVISION, EN_PREPARACION o DISPONIBLE.",
            ],
        ),
        "COMPRA_INTERNACIONAL": (
            ["sku", "serial", "cantidad", "costo_unitario_usd", "precio_venta_usd", "estado_inicial", "nota"],
            [
                [sku_equipo_ejemplo, "SN-IMP-001", 1, 180.00, 290.00, "PENDIENTE_REVISION", "Importación USA"],
            ],
            [
                "El costo de flete y aduana/otros ingresados en el formulario se prorratean automáticamente entre todas las unidades.",
                "sku (obligatorio): Código SKU exacto registrado en el Catálogo.",
                "serial (obligatorio para equipos, vacío para componentes/accesorios).",
                "costo_unitario_usd (obligatorio): Costo FOB / proveedor unitario en USD antes de flete.",
            ],
        ),
        "CONSIGNACION": (
            ["sku", "serial", "cantidad", "costo_acordado_usd", "precio_venta_usd", "estado_inicial", "nota"],
            [
                [sku_equipo_ejemplo, "SN-CONS-001", 1, 200.00, 285.00, "PENDIENTE_REVISION", "Consignación proveedor"],
            ],
            [
                "Todos los equipos ingresados se marcan automáticamente como Consignación.",
                "costo_acordado_usd (obligatorio): Monto acordado a liquidar al consignante al venderse.",
                "serial (obligatorio para equipos).",
            ],
        ),
        "TRASLADO": (
            ["sku", "serial", "cantidad", "nota"],
            [
                [sku_equipo_ejemplo, "SN-EXISTENTE-001", 1, "Traslado de laptop"],
                [sku_comp_ejemplo, "", 5, "Traslado de cargadores"],
            ],
            [
                "Puedes mezclar equipos con serial y componentes/accesorios por cantidad en el mismo archivo.",
                "Para equipos: indica el serial exacto existente en el almacén de origen (cantidad = 1).",
                "Para componentes/accesorios: deja serial vacío e indica sku + cantidad a trasladar.",
            ],
        ),
        "PREPARACION_ESTADOS": (
            ["serial", "nuevo_estado", "observacion"],
            [
                ["SN-EXISTENTE-001", "DISPONIBLE", "Limpieza, Windows y pruebas OK"],
            ],
            [
                "serial (obligatorio): Serial exacto del equipo en inventario.",
                "nuevo_estado (obligatorio): PENDIENTE_REVISION, EN_PREPARACION, DISPONIBLE, DEFECTUOSO, RESERVADO, EN_GARANTIA.",
                "observacion (opcional): Nota que quedará registrada en el historial del equipo.",
            ],
        ),
    }

    encabezados, filas_ejemplo, notas = definiciones[tipo_norm]
    ws_datos.append(encabezados)
    for col_idx in range(1, len(encabezados) + 1):
        celda = ws_datos.cell(row=1, column=col_idx)
        celda.fill = relleno_header
        celda.font = fuente_header
        celda.alignment = alineacion_header
        ws_datos.column_dimensions[celda.column_letter].width = 22

    for fila in filas_ejemplo:
        ws_datos.append(fila)

    ws_inst = wb.create_sheet("Instrucciones")
    ws_inst.append([f"Plantilla Oficial ALFA Digital Store — {tipo_norm}"])
    ws_inst["A1"].font = Font(bold=True, size=13, color="003566")
    ws_inst.append([f"Almacén de referencia: {almacen_ejemplo}"])
    ws_inst.append([])
    ws_inst.append(["REGLAS DE CARGA:"])
    ws_inst["A4"].font = Font(bold=True)
    for linea in notas:
        ws_inst.append([f"• {linea}"])

    ws_inst.append([])
    ws_inst.append(["ALMACENES / SUCURSALES ACTIVAS:", "ID"])
    for suc in sucursales:
        ws_inst.append([suc.nombre, suc.id])

    ws_inst.append([])
    ws_inst.append(["ESTADOS VÁLIDOS DE EQUIPO:"])
    for est in ["PENDIENTE_REVISION", "EN_PREPARACION", "DISPONIBLE", "DEFECTUOSO", "RESERVADO", "EN_GARANTIA"]:
        ws_inst.append([est])

    ws_inst.append([])
    ws_inst.append(["CATÁLOGO DE SKUs ACTIVOS (Muestra):", "Descripción", "Tipo"])
    for art in articulos:
        ws_inst.append([art.sku, art.descripcion, art.tipo])

    ws_inst.column_dimensions["A"].width = 45
    ws_inst.column_dimensions["B"].width = 40
    ws_inst.column_dimensions["C"].width = 18

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    nombre_descarga = f"plantilla_{tipo_norm.lower()}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre_descarga}"'},
    )


# ---------------- Validación y Confirmación Masiva (.xlsx / .csv) ----------------


def _validar_lote_importacion(
    bd: Session,
    tipo: str,
    filas_crudas: list[tuple[int, dict[str, str]]],
    almacen_origen_id: int | None,
    almacen_destino_id: int | None,
) -> dict[str, Any]:
    filas_validas: list[dict[str, Any]] = []
    filas_con_error: list[dict[str, Any]] = []

    articulos_db = bd.query(CatalogoArticulo).filter(CatalogoArticulo.activo.is_(True)).all()
    mapa_sku = {a.sku.upper(): a for a in articulos_db}

    if tipo in {"COMPRA_NACIONAL", "COMPRA_INTERNACIONAL", "CONSIGNACION"}:
        seriales_en_archivo: set[str] = set()
        seriales_a_consultar: set[str] = set()
        pre_filas: list[tuple[int, dict[str, str], str | None]] = []

        for num_fila, raw in filas_crudas:
            ser = normalizar_serial(raw.get("serial", "")) if raw.get("serial", "").strip() else None
            if ser:
                seriales_a_consultar.add(ser)
            pre_filas.append((num_fila, raw, ser))

        existentes_db = (
            {
                row[0]
                for row in bd.query(Equipo.serial).filter(Equipo.serial.in_(seriales_a_consultar)).all()
            }
            if seriales_a_consultar
            else set()
        )

        for num_fila, raw, ser in pre_filas:
            errores: list[str] = []
            sku_raw = raw.get("sku", "").strip()
            sku_norm = normalizar_sku(sku_raw) if sku_raw else ""
            articulo = mapa_sku.get(sku_norm)
            if not sku_norm or articulo is None:
                errores.append(f"SKU '{sku_raw}' no existe en el catálogo.")

            if articulo and articulo.tipo == TipoArticulo.EQUIPO.value and not ser:
                errores.append(f"El SKU '{sku_norm}' es un EQUIPO y requiere serial.")

            if ser:
                if ser in seriales_en_archivo:
                    errores.append(f"Serial '{ser}' duplicado dentro del archivo.")
                elif ser in existentes_db:
                    errores.append(f"Serial '{ser}' ya existe en el inventario.")
                else:
                    seriales_en_archivo.add(ser)

            try:
                cantidad = 1 if ser else parsear_entero_seguro(raw.get("cantidad"), 1)
                if cantidad <= 0:
                    errores.append("La cantidad debe ser mayor a 0.")
            except ValueError as exc:
                cantidad = 0
                errores.append(str(exc))

            clave_costo = (
                "costo_acordado_usd"
                if tipo == "CONSIGNACION" and "costo_acordado_usd" in raw
                else "costo_unitario_usd"
            )
            costo_raw = raw.get(clave_costo) or raw.get("costo_unitario_usd") or raw.get("costo_acordado_usd")
            try:
                costo_unit = parsear_decimal_seguro(costo_raw, Decimal("-1"))
                if costo_unit < 0:
                    errores.append("El costo unitario USD es obligatorio y debe ser >= 0.")
            except ValueError as exc:
                costo_unit = Decimal("0")
                errores.append(str(exc))

            precio_venta_raw = raw.get("precio_venta_usd", "")
            precio_venta: Decimal | None = None
            if precio_venta_raw.strip():
                try:
                    precio_venta = parsear_decimal_seguro(precio_venta_raw)
                    if precio_venta < 0:
                        errores.append("El precio de venta no puede ser negativo.")
                except ValueError as exc:
                    errores.append(str(exc))

            try:
                estado_norm = normalizar_estado_equipo(
                    raw.get("estado_inicial"), defecto=EstadoEquipo.PENDIENTE_REVISION.value
                )
            except ValueError as exc:
                estado_norm = EstadoEquipo.PENDIENTE_REVISION.value
                errores.append(str(exc))

            resumen_fila = {
                "fila": num_fila,
                "sku": sku_norm,
                "nombre_articulo": articulo.descripcion if articulo else "",
                "serial": ser or "",
                "cantidad": cantidad,
                "costo_unitario_usd": float(costo_unit),
                "precio_venta_usd": float(precio_venta) if precio_venta is not None else None,
                "estado_inicial": estado_norm,
                "nota": raw.get("nota", ""),
            }
            if errores:
                resumen_fila["errores"] = errores
                filas_con_error.append(resumen_fila)
            else:
                filas_validas.append(resumen_fila)

    elif tipo == "TRASLADO":
        if not almacen_origen_id or not almacen_destino_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes indicar almacen_origen_id y almacen_destino_id para validar un traslado.",
            )
        if almacen_origen_id == almacen_destino_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El almacén de origen y destino deben ser distintos.",
            )
        seriales_vistos: set[str] = set()
        consumo_acumulado: dict[int, int] = {}
        estados_bloqueados = {
            EstadoEquipo.EN_TRANSITO.value,
            EstadoEquipo.VENDIDO.value,
            EstadoEquipo.CEMENTERIO.value,
        }

        for num_fila, raw in filas_crudas:
            errores = []
            ser = normalizar_serial(raw.get("serial", "")) if raw.get("serial", "").strip() else None
            sku_raw = raw.get("sku", "").strip()
            sku_norm = normalizar_sku(sku_raw) if sku_raw else ""

            if ser:
                if ser in seriales_vistos:
                    errores.append(f"Serial '{ser}' repetido en el archivo.")
                else:
                    seriales_vistos.add(ser)
                eq = bd.query(Equipo).filter(Equipo.serial == ser).first()
                if eq is None:
                    errores.append(f"Serial '{ser}' no existe en inventario.")
                else:
                    if eq.ubicacion_id != almacen_origen_id:
                        errores.append(f"El equipo '{ser}' no está en el almacén de origen.")
                    if eq.estado in estados_bloqueados:
                        errores.append(f"El equipo '{ser}' está '{eq.estado}' y no puede trasladarse.")
                resumen_fila = {
                    "fila": num_fila,
                    "tipo_item": "EQUIPO",
                    "equipo_id": eq.id if eq else None,
                    "sku": eq.articulo.sku if (eq and eq.articulo) else sku_norm,
                    "nombre_articulo": eq.modelo if eq else "",
                    "serial": ser,
                    "cantidad": 1,
                    "nota": raw.get("nota", ""),
                }
            else:
                articulo = mapa_sku.get(sku_norm)
                if not sku_norm or articulo is None:
                    errores.append(f"SKU '{sku_raw}' no existe en el catálogo.")
                try:
                    cantidad = parsear_entero_seguro(raw.get("cantidad"), 0)
                    if cantidad <= 0:
                        errores.append("La cantidad a trasladar debe ser mayor a 0.")
                except ValueError as exc:
                    cantidad = 0
                    errores.append(str(exc))

                if articulo is not None and cantidad > 0:
                    stock_origen = calcular_stock_componente(bd, articulo.id, almacen_origen_id)
                    acum = consumo_acumulado.get(articulo.id, 0) + cantidad
                    if acum > stock_origen:
                        errores.append(
                            f"Stock insuficiente para '{articulo.sku}' en origen (disponible: {stock_origen}, solicitado acumulado: {acum})."
                        )
                    else:
                        consumo_acumulado[articulo.id] = acum

                resumen_fila = {
                    "fila": num_fila,
                    "tipo_item": "PRODUCTO",
                    "articulo_id": articulo.id if articulo else None,
                    "sku": sku_norm,
                    "nombre_articulo": articulo.descripcion if articulo else "",
                    "serial": "",
                    "cantidad": cantidad,
                    "nota": raw.get("nota", ""),
                }

            if errores:
                resumen_fila["errores"] = errores
                filas_con_error.append(resumen_fila)
            else:
                filas_validas.append(resumen_fila)

    elif tipo == "PREPARACION_ESTADOS":
        seriales_vistos_prep: set[str] = set()
        estados_bloqueados_prep = {EstadoEquipo.VENDIDO.value, EstadoEquipo.EN_TRANSITO.value}

        for num_fila, raw in filas_crudas:
            errores = []
            ser = normalizar_serial(raw.get("serial", "")) if raw.get("serial", "").strip() else ""
            if not ser:
                errores.append("El serial es obligatorio.")
            elif ser in seriales_vistos_prep:
                errores.append(f"Serial '{ser}' duplicado en el archivo.")
            else:
                seriales_vistos_prep.add(ser)

            eq = bd.query(Equipo).filter(Equipo.serial == ser).first() if ser else None
            if ser and eq is None:
                errores.append(f"Serial '{ser}' no encontrado en inventario.")
            elif eq and eq.estado in estados_bloqueados_prep:
                errores.append(f"El equipo '{ser}' está '{eq.estado}' y no puede modificarse.")

            try:
                nuevo_estado = normalizar_estado_equipo(raw.get("nuevo_estado"))
            except ValueError as exc:
                nuevo_estado = ""
                errores.append(str(exc))

            resumen_fila = {
                "fila": num_fila,
                "equipo_id": eq.id if eq else None,
                "serial": ser,
                "modelo": eq.modelo if eq else "",
                "estado_actual": eq.estado if eq else "",
                "nuevo_estado": nuevo_estado,
                "observacion": raw.get("observacion", ""),
            }
            if errores:
                resumen_fila["errores"] = errores
                filas_con_error.append(resumen_fila)
            else:
                filas_validas.append(resumen_fila)

    return {
        "tipo": tipo,
        "total_filas": len(filas_crudas),
        "validas_count": len(filas_validas),
        "errores_count": len(filas_con_error),
        "filas_validas": filas_validas,
        "filas_con_error": filas_con_error,
    }


@enrutador.post("/api/logistica/importar/{tipo}/preview")
async def preview_carga_masiva(
    tipo: str,
    archivo: UploadFile = File(...),
    almacen_origen_id: str | None = Form(default=None),
    almacen_destino_id: str | None = Form(default=None),
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    origen_id_int = int(almacen_origen_id) if (almacen_origen_id and almacen_origen_id.strip().isdigit()) else None
    destino_id_int = int(almacen_destino_id) if (almacen_destino_id and almacen_destino_id.strip().isdigit()) else None
    tipo_norm = tipo.strip().upper()
    if tipo_norm not in TIPOS_PLANTILLA_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de importación inválido: '{tipo}'.",
        )
    _verificar_permiso_tipo(tipo_norm, usuario_actual)

    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El archivo está vacío.")

    filas_crudas = _leer_filas_archivo(contenido, archivo.filename or "carga.xlsx")
    if not filas_crudas:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo no contiene filas de datos.",
        )

    resultado = _validar_lote_importacion(
        bd=bd,
        tipo=tipo_norm,
        filas_crudas=filas_crudas,
        almacen_origen_id=origen_id_int,
        almacen_destino_id=destino_id_int,
    )
    resultado["nombre_archivo"] = archivo.filename or "carga.xlsx"
    return resultado


@enrutador.post("/api/logistica/importar/{tipo}/confirmar", status_code=status.HTTP_201_CREATED)
async def confirmar_carga_masiva(
    tipo: str,
    archivo: UploadFile = File(...),
    almacen_origen_id: str | None = Form(default=None),
    almacen_destino_id: str | None = Form(default=None),
    proveedor_nombre: str = Form(default=""),
    referencia_factura: str = Form(default=""),
    costo_flete_usd: str = Form(default="0"),
    costo_aduana_otros_usd: str = Form(default="0"),
    tracking_guia: str = Form(default=""),
    observaciones: str = Form(default=""),
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    origen_id_int = int(almacen_origen_id) if (almacen_origen_id and almacen_origen_id.strip().isdigit()) else None
    destino_id_int = int(almacen_destino_id) if (almacen_destino_id and almacen_destino_id.strip().isdigit()) else None
    try:
        flete_dec = parsear_decimal_seguro(costo_flete_usd, Decimal("0"))
        aduana_dec = parsear_decimal_seguro(costo_aduana_otros_usd, Decimal("0"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    almacen_origen_id_val = origen_id_int
    almacen_destino_id_val = destino_id_int
    tipo_norm = tipo.strip().upper()
    if tipo_norm not in TIPOS_PLANTILLA_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de importación inválido: '{tipo}'.",
        )
    _verificar_permiso_tipo(tipo_norm, usuario_actual)

    contenido = await archivo.read()
    filas_crudas = _leer_filas_archivo(contenido, archivo.filename or "carga.xlsx")
    if not filas_crudas:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo no contiene filas de datos.",
        )

    validacion = _validar_lote_importacion(
        bd=bd,
        tipo=tipo_norm,
        filas_crudas=filas_crudas,
        almacen_origen_id=almacen_origen_id_val,
        almacen_destino_id=almacen_destino_id_val,
    )
    if validacion["errores_count"] > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "mensaje": f"El archivo contiene {validacion['errores_count']} fila(s) con errores. Corrige y vuelve a intentar.",
                "filas_con_error": validacion["filas_con_error"],
            },
        )
    if validacion["validas_count"] == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay filas válidas para importar.",
        )

    if tipo_norm in {"COMPRA_NACIONAL", "COMPRA_INTERNACIONAL", "CONSIGNACION"}:
        if not almacen_destino_id_val:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes seleccionar el almacén de destino.",
            )
        if not proveedor_nombre.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes indicar el nombre del proveedor o consignante.",
            )
        almacen = bd.query(Sucursal).filter(Sucursal.id == almacen_destino_id_val).first()
        if almacen is None or almacen.estado != EstadoSucursal.ACTIVA.value:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Almacén destino no encontrado o inactivo.",
            )
        articulos_db = bd.query(CatalogoArticulo).all()
        mapa_sku = {a.sku.upper(): a for a in articulos_db}
        items_norm = [
            {
                "articulo": mapa_sku[f["sku"]],
                "serial": f["serial"] or None,
                "cantidad": f["cantidad"],
                "costo_unitario_usd": Decimal(str(f["costo_unitario_usd"])),
                "precio_venta_usd": (
                    Decimal(str(f["precio_venta_usd"])) if f["precio_venta_usd"] is not None else None
                ),
                "estado_inicial": f["estado_inicial"],
                "nota": f["nota"],
            }
            for f in validacion["filas_validas"]
        ]
        res = _ejecutar_ingreso_inventario(
            bd=bd,
            usuario=usuario_actual,
            tipo_ingreso=tipo_norm,
            proveedor_nombre=proveedor_nombre,
            almacen_destino=almacen,
            referencia_factura=referencia_factura,
            observaciones=observaciones,
            costo_flete_usd=flete_dec,
            costo_aduana_otros_usd=aduana_dec,
            tracking_guia=tracking_guia,
            items_normalizados=items_norm,
        )
        res["filas_procesadas"] = validacion["validas_count"]
        return res

    if tipo_norm == "TRASLADO":
        origen = bd.query(Sucursal).filter(Sucursal.id == almacen_origen_id_val).first()
        destino = bd.query(Sucursal).filter(Sucursal.id == almacen_destino_id_val).first()
        if origen is None or destino is None or destino.estado != EstadoSucursal.ACTIVA.value:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Almacén de origen o destino inválido.",
            )
        numero_traslado = generar_correlativo(bd, Traslado, Traslado.numero_traslado, "TR")
        traslado = Traslado(
            numero_traslado=numero_traslado,
            origen_id=origen.id,
            destino_id=destino.id,
            estado=EstadoTraslado.EN_TRANSITO.value,
            enviado_por_id=usuario_actual.id,
            nota=observaciones.strip() or f"Carga masiva ({archivo.filename})",
        )
        bd.add(traslado)
        bd.flush()

        equipos_count = 0
        productos_count = 0
        for f in validacion["filas_validas"]:
            if f["tipo_item"] == "EQUIPO":
                eq = bd.query(Equipo).filter(Equipo.id == f["equipo_id"]).first()
                assert eq is not None
                eq.estado_previo_traslado = eq.estado
                eq.estado = EstadoEquipo.EN_TRANSITO.value
                bd.add(TrasladoDetalle(traslado_id=traslado.id, equipo_id=eq.id, cantidad=1))
                bd.add(
                    MovimientoInventario(
                        tipo=TipoMovimientoInventario.TRASLADO_SALIDA.value,
                        articulo_id=eq.articulo_id,
                        equipo_id=eq.id,
                        sucursal_id=origen.id,
                        cantidad=-1,
                        costo_unitario_usd=eq.costo_compra_usd + eq.costo_flete_usd + eq.costo_taller_usd,
                        documento_ref=numero_traslado,
                        motivo=f"Salida masiva hacia {destino.nombre}",
                        usuario_id=usuario_actual.id,
                    )
                )
                equipos_count += 1
            else:
                bd.add(
                    TrasladoDetalle(
                        traslado_id=traslado.id,
                        articulo_id=f["articulo_id"],
                        cantidad=f["cantidad"],
                    )
                )
                bd.add(
                    MovimientoInventario(
                        tipo=TipoMovimientoInventario.TRASLADO_SALIDA.value,
                        articulo_id=f["articulo_id"],
                        equipo_id=None,
                        sucursal_id=origen.id,
                        cantidad=-f["cantidad"],
                        costo_unitario_usd=Decimal("0"),
                        documento_ref=numero_traslado,
                        motivo=f"Salida masiva de productos hacia {destino.nombre}",
                        usuario_id=usuario_actual.id,
                    )
                )
                productos_count += int(f["cantidad"])

        bd.commit()
        return {
            "id": traslado.id,
            "codigo": numero_traslado,
            "estado": traslado.estado,
            "equipos_en_transito": equipos_count,
            "productos_en_transito": productos_count,
            "filas_procesadas": validacion["validas_count"],
        }

    # PREPARACION_ESTADOS
    actualizados = 0
    for f in validacion["filas_validas"]:
        eq = bd.query(Equipo).filter(Equipo.id == f["equipo_id"]).first()
        assert eq is not None
        estado_ant = eq.estado
        eq.estado = f["nuevo_estado"]
        obs = f["observacion"] or observaciones.strip()
        if obs:
            eq.nota = f"{eq.nota} | {obs}" if eq.nota else obs
        bd.add(
            HistorialEstadoEquipo(
                equipo_id=eq.id,
                estado_anterior=estado_ant,
                estado_nuevo=f["nuevo_estado"],
                usuario_id=usuario_actual.id,
                nota_tecnica=obs or "Actualización masiva por plantilla",
            )
        )
        actualizados += 1

    bd.commit()
    return {
        "actualizados": actualizados,
        "filas_procesadas": actualizados,
    }
