from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.configuracion import configuracion
from app.modelos import RolUsuario, Sucursal, Usuario
from app.modelos_finanzas import EstadoVenta, Venta, VentaDetalle
from app.modelos_logistica import Equipo, Tercero, TipoTercero
from app.modelos_taller import EstadoOrdenRecepcion, OrdenRecepcionTecnica, TipoOrdenRecepcion
from app.rutas.logistica import generar_correlativo
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import obtener_usuario_actual, requerir_roles
from app.servicios.pdf_recepcion_tecnica import generar_pdf_recepcion_tecnica

enrutador = APIRouter(prefix="/api/recepcion-tecnica", tags=["Recepción de Garantías y Servicios Técnicos"])

ROLES_CREAR_RECEPCION = (
    RolUsuario.DIRECCION.value,
    RolUsuario.ADMINISTRACION.value,
    RolUsuario.ENCARGADO_TIENDA.value,
    RolUsuario.LIDER.value,
)
ROLES_VER_RECEPCION = (
    RolUsuario.DIRECCION.value,
    RolUsuario.ADMINISTRACION.value,
    RolUsuario.DIRECTOR.value,
    RolUsuario.ENCARGADO_TIENDA.value,
    RolUsuario.LIDER.value,
    RolUsuario.TECNICO.value,
)
ESTADOS_TECNICO_PERMITIDOS = {
    EstadoOrdenRecepcion.EN_REVISION.value,
    EstadoOrdenRecepcion.PRESUPUESTADO.value,
    EstadoOrdenRecepcion.EN_REPARACION.value,
    EstadoOrdenRecepcion.LISTO_PARA_ENTREGA.value,
}
ESTADOS_CERRADOS = {
    EstadoOrdenRecepcion.RESUELTO_ENTREGADO.value,
    EstadoOrdenRecepcion.NO_REPARADO_ENTREGADO.value,
}


def _ahora_caracas() -> datetime:
    return datetime.now(ZoneInfo(configuracion.ZONA_HORARIA))


class OrdenRecepcionCrearEntrada(BaseModel):
    tipo_orden: TipoOrdenRecepcion
    sucursal_id: int | None = None
    tecnico_asignado_id: int | None = None
    enviar_a_tecnico: bool = True

    # Cliente (seleccionado o creación rápida)
    cliente_id: int | None = None
    cliente_nombre: str = Field(default="", max_length=160)
    cliente_documento: str = Field(default="", max_length=50)
    cliente_telefono: str = Field(default="", max_length=40)

    # Nota de Venta (SOLO GARANTÍA)
    venta_id: int | None = None
    numero_nota_venta: str | None = Field(default=None, max_length=40)

    # Detalles del Equipo
    equipo_id: int | None = None
    marca: str = Field(default="", max_length=100)
    modelo: str = Field(min_length=2, max_length=160)
    serial: str = Field(default="", max_length=120)
    especificaciones: str = Field(default="", max_length=255)
    clave_acceso: str = Field(default="", max_length=100)

    # Diagnóstico de Recepción
    falla_declarada_cliente: str = Field(min_length=3, max_length=2000)
    accesorios_entregados: list[str] = Field(default_factory=list)
    accesorios_otros: str = Field(default="", max_length=255)
    detalles_esteticos: str = Field(default="", max_length=2000)
    detalles_sistema_recepcion: str = Field(default="", max_length=2000)
    equipo_llega_apagado: bool = False
    condiciones_aceptadas: bool = True

    # Costo de Revisión (SOLO SERVICIO TÉCNICO; ignorado en GARANTÍA)
    costo_revision_usd: Decimal | None = Field(default=None, ge=Decimal("0"))

    @field_validator("venta_id", "equipo_id", "cliente_id", "tecnico_asignado_id", "sucursal_id", mode="before")
    @classmethod
    def vacio_a_none_int(cls, v: Any) -> Any:
        if v == "" or v is None:
            return None
        return v

    @field_validator("numero_nota_venta", mode="before")
    @classmethod
    def vacio_a_none_str(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v


class OrdenRecepcionActualizarEntrada(BaseModel):
    estado: EstadoOrdenRecepcion | None = None
    tecnico_asignado_id: int | None = None
    diagnostico_tecnico: str | None = Field(default=None, max_length=3000)
    solucion_aplicada: str | None = Field(default=None, max_length=3000)
    reparacion_aprobada: bool | None = None
    repuestos_usados: list[dict[str, Any]] | None = None


def _serializar_orden(orden: OrdenRecepcionTecnica, es_tecnico: bool = False) -> dict[str, Any]:
    try:
        accesorios = json.loads(orden.accesorios_entregados_json or "[]")
    except Exception:
        accesorios = []
    try:
        repuestos = json.loads(orden.repuestos_usados_json or "[]")
    except Exception:
        repuestos = []
    if es_tecnico:
        repuestos = [
            {k: v for k, v in r.items() if "costo" not in k.lower()}
            if isinstance(r, dict)
            else r
            for r in repuestos
        ]

    es_st = orden.tipo_orden == TipoOrdenRecepcion.SERVICIO_TECNICO.value
    costo_rev_efectivo = 0.0 if (not es_st or orden.reparacion_aprobada) else float(orden.costo_revision_usd or 0)

    return {
        "id": orden.id,
        "codigo": orden.codigo,
        "tipo_orden": orden.tipo_orden,
        "estado": orden.estado,
        "sucursal_id": orden.sucursal_id,
        "sucursal_nombre": orden.sucursal.nombre if orden.sucursal else "",
        "recibido_por_id": orden.recibido_por_id,
        "recibido_por_nombre": orden.recibido_por.nombre if orden.recibido_por else "",
        "tecnico_asignado_id": orden.tecnico_asignado_id,
        "tecnico_asignado_nombre": orden.tecnico_asignado.nombre if orden.tecnico_asignado else "",
        "tecnico_asignado_telefono": orden.tecnico_asignado.telefono if orden.tecnico_asignado else "",
        "cliente_id": orden.cliente_id,
        "cliente_nombre": orden.cliente_nombre,
        "cliente_documento": orden.cliente_documento,
        "cliente_telefono": orden.cliente_telefono,
        "venta_id": orden.venta_id,
        "numero_nota_venta": orden.numero_nota_venta,
        "fecha_venta": orden.fecha_venta.isoformat() if orden.fecha_venta else None,
        "dias_transcurridos_garantia": orden.dias_transcurridos_garantia,
        "garantia_vigente": (
            orden.dias_transcurridos_garantia <= 180
            if orden.dias_transcurridos_garantia is not None
            else None
        ),
        "equipo_id": orden.equipo_id,
        "marca": orden.marca,
        "modelo": orden.modelo,
        "serial": orden.serial,
        "especificaciones": orden.especificaciones,
        "clave_acceso": orden.clave_acceso,
        "falla_declarada_cliente": orden.falla_declarada_cliente,
        "accesorios_entregados": accesorios,
        "accesorios_otros": orden.accesorios_otros,
        "detalles_esteticos": orden.detalles_esteticos,
        "detalles_sistema_recepcion": orden.detalles_sistema_recepcion,
        "equipo_llega_apagado": bool(orden.equipo_llega_apagado),
        "condiciones_aceptadas": bool(orden.condiciones_aceptadas),
        "costo_revision_usd": float(orden.costo_revision_usd or 0),
        "costo_revision_efectivo_usd": costo_rev_efectivo,
        "reparacion_aprobada": bool(orden.reparacion_aprobada),
        "repuestos_usados": repuestos,
        "fecha_recepcion": orden.fecha_recepcion.isoformat() if orden.fecha_recepcion else None,
        "fecha_envio_tecnico": orden.fecha_envio_tecnico.isoformat() if orden.fecha_envio_tecnico else None,
        "fecha_resolucion": orden.fecha_resolucion.isoformat() if orden.fecha_resolucion else None,
        "diagnostico_tecnico": orden.diagnostico_tecnico,
        "solucion_aplicada": orden.solucion_aplicada,
    }


@enrutador.get("/tecnicos")
def listar_tecnicos_disponibles(
    _usuario: Usuario = Depends(requerir_roles(*ROLES_VER_RECEPCION)),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    tecnicos = (
        bd.query(Usuario)
        .filter(Usuario.activo.is_(True), Usuario.rol == RolUsuario.TECNICO.value)
        .order_by(Usuario.nombre.asc())
        .all()
    )
    return [
        {
            "id": t.id,
            "nombre": t.nombre,
            "telefono": t.telefono or "",
            "sucursal_id": t.sucursal_id,
        }
        for t in tecnicos
    ]


@enrutador.get("/buscar-ventas")
def buscar_notas_venta_garantia(
    q: str = Query(default="", max_length=100),
    _usuario: Usuario = Depends(requerir_roles(*ROLES_CREAR_RECEPCION)),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    """Busca notas de venta por # de nota, serial del equipo o cédula/nombre del cliente."""
    termino = q.strip()
    hoy = obtener_fecha_hoy()

    consulta = (
        bd.query(Venta)
        .options(
            joinedload(Venta.cliente),
            joinedload(Venta.sucursal),
            joinedload(Venta.detalles).joinedload(VentaDetalle.equipo),
            joinedload(Venta.detalles).joinedload(VentaDetalle.articulo),
        )
        .filter(Venta.estado != EstadoVenta.ANULADA.value)
    )
    if termino:
        patron = f"%{termino}%"
        consulta = (
            consulta.outerjoin(Tercero, Venta.cliente_id == Tercero.id)
            .outerjoin(VentaDetalle, Venta.id == VentaDetalle.venta_id)
            .outerjoin(Equipo, VentaDetalle.equipo_id == Equipo.id)
            .filter(
                or_(
                    Venta.numero_venta.ilike(patron),
                    Tercero.nombre.ilike(patron),
                    Tercero.documento.ilike(patron),
                    Tercero.rif_cedula.ilike(patron),
                    Equipo.serial.ilike(patron),
                    Equipo.modelo.ilike(patron),
                )
            )
            .distinct()
        )

    ventas = consulta.order_by(Venta.id.desc()).limit(20).all()
    salida: list[dict[str, Any]] = []
    for v in ventas:
        dias = max(0, (hoy - v.fecha).days) if v.fecha else 0
        equipos_v: list[dict[str, Any]] = []
        for det in v.detalles:
            if det.equipo is not None:
                equipos_v.append(
                    {
                        "equipo_id": det.equipo.id,
                        "modelo": det.equipo.modelo or det.descripcion,
                        "serial": det.equipo.serial,
                        "especificaciones": det.equipo.configuracion or "",
                        "categoria": det.equipo.categoria or "",
                    }
                )
            elif det.descripcion:
                equipos_v.append(
                    {
                        "equipo_id": None,
                        "modelo": det.descripcion,
                        "serial": "",
                        "especificaciones": "",
                        "categoria": "",
                    }
                )
        salida.append(
            {
                "venta_id": v.id,
                "numero_nota_venta": v.numero_venta,
                "fecha_venta": v.fecha.isoformat() if v.fecha else None,
                "dias_transcurridos_garantia": dias,
                "garantia_vigente": dias <= 180,
                "sucursal_id": v.sucursal_id,
                "sucursal_nombre": v.sucursal.nombre if v.sucursal else "",
                "cliente_id": v.cliente_id,
                "cliente_nombre": v.cliente.nombre if v.cliente else "",
                "cliente_documento": (v.cliente.documento or v.cliente.rif_cedula) if v.cliente else "",
                "cliente_telefono": v.cliente.telefono if v.cliente else "",
                "equipos": equipos_v,
            }
        )
    return salida


@enrutador.get("")
def listar_ordenes_recepcion(
    tipo_orden: str | None = Query(default=None),
    estado: str | None = Query(default=None),
    tecnico_asignado_id: int | None = Query(default=None),
    sucursal_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_VER_RECEPCION)),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    es_tecnico = usuario_actual.rol == RolUsuario.TECNICO.value
    consulta = bd.query(OrdenRecepcionTecnica).options(
        joinedload(OrdenRecepcionTecnica.sucursal),
        joinedload(OrdenRecepcionTecnica.recibido_por),
        joinedload(OrdenRecepcionTecnica.tecnico_asignado),
    )

    if es_tecnico:
        consulta = consulta.filter(
            or_(
                OrdenRecepcionTecnica.tecnico_asignado_id == usuario_actual.id,
                OrdenRecepcionTecnica.tecnico_asignado_id.is_(None),
            )
        )
    elif tecnico_asignado_id is not None:
        consulta = consulta.filter(OrdenRecepcionTecnica.tecnico_asignado_id == tecnico_asignado_id)

    if tipo_orden:
        consulta = consulta.filter(OrdenRecepcionTecnica.tipo_orden == tipo_orden.upper())
    if estado:
        consulta = consulta.filter(OrdenRecepcionTecnica.estado == estado.upper())
    if sucursal_id is not None:
        consulta = consulta.filter(OrdenRecepcionTecnica.sucursal_id == sucursal_id)
    if q and q.strip():
        patron = f"%{q.strip()}%"
        consulta = consulta.filter(
            or_(
                OrdenRecepcionTecnica.codigo.ilike(patron),
                OrdenRecepcionTecnica.cliente_nombre.ilike(patron),
                OrdenRecepcionTecnica.cliente_documento.ilike(patron),
                OrdenRecepcionTecnica.serial.ilike(patron),
                OrdenRecepcionTecnica.modelo.ilike(patron),
                OrdenRecepcionTecnica.numero_nota_venta.ilike(patron),
            )
        )

    ordenes = consulta.order_by(OrdenRecepcionTecnica.id.desc()).limit(200).all()
    return [_serializar_orden(o, es_tecnico=es_tecnico) for o in ordenes]


@enrutador.post("", status_code=status.HTTP_201_CREATED)
def crear_orden_recepcion(
    datos: OrdenRecepcionCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_CREAR_RECEPCION)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    sucursal_id = datos.sucursal_id or usuario_actual.sucursal_id
    if sucursal_id is None:
        suc = bd.query(Sucursal).order_by(Sucursal.id.asc()).first()
        if suc is None:
            raise HTTPException(status_code=400, detail="No hay sucursales registradas.")
        sucursal_id = suc.id
    else:
        if bd.query(Sucursal).filter(Sucursal.id == sucursal_id).first() is None:
            raise HTTPException(status_code=404, detail="La sucursal indicada no existe.")

    es_garantia = datos.tipo_orden == TipoOrdenRecepcion.GARANTIA
    hoy = obtener_fecha_hoy()
    ahora = _ahora_caracas()

    # Resolver o crear cliente
    cliente_id = datos.cliente_id
    cliente_nombre = datos.cliente_nombre.strip()
    cliente_documento = datos.cliente_documento.strip()
    cliente_telefono = datos.cliente_telefono.strip()

    if cliente_id is not None:
        cli = bd.query(Tercero).filter(Tercero.id == cliente_id).first()
        if cli is None:
            raise HTTPException(status_code=404, detail="El cliente seleccionado no existe.")
        cliente_nombre = cliente_nombre or cli.nombre
        cliente_documento = cliente_documento or cli.documento or cli.rif_cedula
        cliente_telefono = cliente_telefono or cli.telefono
    elif cliente_nombre:
        nuevo_cli = Tercero(
            nombre=cliente_nombre,
            tipo=TipoTercero.CLIENTE.value,
            documento=cliente_documento,
            rif_cedula=cliente_documento,
            telefono=cliente_telefono,
            activo=True,
        )
        bd.add(nuevo_cli)
        bd.flush()
        cliente_id = nuevo_cli.id

    # Datos de Nota de Venta (SOLO GARANTÍA; estrictamente NULL en SERVICIO_TECNICO)
    venta_id: int | None = None
    numero_nota_venta: str | None = None
    fecha_venta = None
    dias_garantia: int | None = None
    equipo_id = datos.equipo_id

    if es_garantia:
        venta_obj: Venta | None = None
        if datos.venta_id is not None:
            venta_obj = (
                bd.query(Venta)
                .options(joinedload(Venta.cliente))
                .filter(Venta.id == datos.venta_id)
                .first()
            )
            if venta_obj is None:
                raise HTTPException(status_code=404, detail="La Nota de Venta indicada no existe.")
        elif datos.numero_nota_venta:
            venta_obj = (
                bd.query(Venta)
                .options(joinedload(Venta.cliente))
                .filter(Venta.numero_venta.ilike(datos.numero_nota_venta.strip()))
                .first()
            )
            numero_nota_venta = datos.numero_nota_venta.strip()

        if venta_obj is not None:
            venta_id = venta_obj.id
            numero_nota_venta = venta_obj.numero_venta
            fecha_venta = venta_obj.fecha
            dias_garantia = max(0, (hoy - venta_obj.fecha).days) if venta_obj.fecha else 0
            if not cliente_nombre and venta_obj.cliente is not None:
                cliente_id = venta_obj.cliente_id
                cliente_nombre = venta_obj.cliente.nombre
                cliente_documento = venta_obj.cliente.documento or venta_obj.cliente.rif_cedula
                cliente_telefono = venta_obj.cliente.telefono

        if not cliente_nombre:
            raise HTTPException(
                status_code=400,
                detail="Debes seleccionar una Nota de Venta o indicar el nombre del cliente.",
            )
        costo_revision = Decimal("0.00")
    else:
        if not cliente_nombre:
            raise HTTPException(
                status_code=400,
                detail="Debes seleccionar o indicar el nombre del cliente para el Servicio Técnico.",
            )
        costo_revision = datos.costo_revision_usd if datos.costo_revision_usd is not None else Decimal("10.00")

    # Validar técnico si fue asignado
    tecnico_id = datos.tecnico_asignado_id
    if tecnico_id is not None:
        tec = bd.query(Usuario).filter(Usuario.id == tecnico_id).first()
        if tec is None:
            raise HTTPException(status_code=404, detail="El técnico seleccionado no existe.")

    estado_inicial = (
        EstadoOrdenRecepcion.ENVIADO_A_TECNICO.value
        if (tecnico_id is not None and datos.enviar_a_tecnico)
        else EstadoOrdenRecepcion.RECIBIDO_EN_TIENDA.value
    )
    prefijo = "GAR" if es_garantia else "ST"
    codigo = generar_correlativo(bd, OrdenRecepcionTecnica, OrdenRecepcionTecnica.codigo, prefijo)

    orden = OrdenRecepcionTecnica(
        codigo=codigo,
        tipo_orden=datos.tipo_orden.value,
        sucursal_id=sucursal_id,
        recibido_por_id=usuario_actual.id,
        tecnico_asignado_id=tecnico_id,
        cliente_id=cliente_id,
        cliente_nombre=cliente_nombre,
        cliente_documento=cliente_documento,
        cliente_telefono=cliente_telefono,
        venta_id=venta_id,
        numero_nota_venta=numero_nota_venta,
        fecha_venta=fecha_venta,
        dias_transcurridos_garantia=dias_garantia,
        equipo_id=equipo_id,
        marca=datos.marca.strip(),
        modelo=datos.modelo.strip(),
        serial=datos.serial.strip().upper(),
        especificaciones=datos.especificaciones.strip(),
        clave_acceso=datos.clave_acceso.strip(),
        falla_declarada_cliente=datos.falla_declarada_cliente.strip(),
        accesorios_entregados_json=json.dumps(datos.accesorios_entregados, ensure_ascii=False),
        accesorios_otros=datos.accesorios_otros.strip(),
        detalles_esteticos=datos.detalles_esteticos.strip(),
        detalles_sistema_recepcion=datos.detalles_sistema_recepcion.strip(),
        equipo_llega_apagado=bool(datos.equipo_llega_apagado),
        condiciones_aceptadas=bool(datos.condiciones_aceptadas),
        costo_revision_usd=costo_revision,
        reparacion_aprobada=False,
        estado=estado_inicial,
        fecha_recepcion=ahora,
        fecha_envio_tecnico=ahora if estado_inicial == EstadoOrdenRecepcion.ENVIADO_A_TECNICO.value else None,
    )
    bd.add(orden)
    bd.commit()

    orden_completa = (
        bd.query(OrdenRecepcionTecnica)
        .options(
            joinedload(OrdenRecepcionTecnica.sucursal),
            joinedload(OrdenRecepcionTecnica.recibido_por),
            joinedload(OrdenRecepcionTecnica.tecnico_asignado),
        )
        .filter(OrdenRecepcionTecnica.id == orden.id)
        .first()
    )
    return _serializar_orden(orden_completa)


@enrutador.patch("/{orden_id}")
def actualizar_orden_recepcion(
    orden_id: int,
    datos: OrdenRecepcionActualizarEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_VER_RECEPCION)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    if usuario_actual.rol == RolUsuario.DIRECTOR.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El rol DIRECTOR es de solo lectura.",
        )

    orden = (
        bd.query(OrdenRecepcionTecnica)
        .options(
            joinedload(OrdenRecepcionTecnica.sucursal),
            joinedload(OrdenRecepcionTecnica.recibido_por),
            joinedload(OrdenRecepcionTecnica.tecnico_asignado),
        )
        .filter(OrdenRecepcionTecnica.id == orden_id)
        .first()
    )
    if orden is None:
        raise HTTPException(status_code=404, detail="Orden de recepción no encontrada.")

    es_tecnico = usuario_actual.rol == RolUsuario.TECNICO.value
    ahora = _ahora_caracas()

    if es_tecnico:
        if orden.tecnico_asignado_id is not None and orden.tecnico_asignado_id != usuario_actual.id:
            raise HTTPException(
                status_code=403,
                detail="Esta orden está asignada a otro técnico.",
            )
        if datos.estado is not None and datos.estado.value not in ESTADOS_TECNICO_PERMITIDOS:
            raise HTTPException(
                status_code=403,
                detail="El técnico solo puede actualizar estados técnicos (EN_REVISION, PRESUPUESTADO, EN_REPARACION, LISTO_PARA_ENTREGA).",
            )
        if orden.tecnico_asignado_id is None:
            orden.tecnico_asignado_id = usuario_actual.id
    else:
        if datos.tecnico_asignado_id is not None:
            tec = bd.query(Usuario).filter(Usuario.id == datos.tecnico_asignado_id).first()
            if tec is None:
                raise HTTPException(status_code=404, detail="Técnico no encontrado.")
            orden.tecnico_asignado_id = tec.id
            if orden.fecha_envio_tecnico is None:
                orden.fecha_envio_tecnico = ahora
        if datos.reparacion_aprobada is not None:
            orden.reparacion_aprobada = bool(datos.reparacion_aprobada)
            if orden.reparacion_aprobada and orden.tipo_orden == TipoOrdenRecepcion.SERVICIO_TECNICO.value:
                orden.costo_revision_usd = Decimal("0.00")

    if datos.diagnostico_tecnico is not None:
        orden.diagnostico_tecnico = datos.diagnostico_tecnico.strip()
    if datos.solucion_aplicada is not None:
        orden.solucion_aplicada = datos.solucion_aplicada.strip()
    if datos.repuestos_usados is not None:
        orden.repuestos_usados_json = json.dumps(datos.repuestos_usados, ensure_ascii=False)
    if datos.estado is not None:
        orden.estado = datos.estado.value
        if datos.estado == EstadoOrdenRecepcion.ENVIADO_A_TECNICO and orden.fecha_envio_tecnico is None:
            orden.fecha_envio_tecnico = ahora
        if datos.estado.value in ESTADOS_CERRADOS:
            orden.fecha_resolucion = ahora

    bd.commit()
    bd.refresh(orden)
    orden_actualizada = (
        bd.query(OrdenRecepcionTecnica)
        .options(
            joinedload(OrdenRecepcionTecnica.sucursal),
            joinedload(OrdenRecepcionTecnica.recibido_por),
            joinedload(OrdenRecepcionTecnica.tecnico_asignado),
        )
        .filter(OrdenRecepcionTecnica.id == orden.id)
        .first()
    )
    return _serializar_orden(orden_actualizada, es_tecnico=es_tecnico)


@enrutador.get("/{orden_id}/pdf")
def descargar_comprobante_recepcion_pdf(
    orden_id: int,
    _usuario: Usuario = Depends(requerir_roles(*ROLES_VER_RECEPCION)),
    bd: Session = Depends(obtener_bd),
) -> Response:
    orden = (
        bd.query(OrdenRecepcionTecnica)
        .options(
            joinedload(OrdenRecepcionTecnica.sucursal),
            joinedload(OrdenRecepcionTecnica.recibido_por),
            joinedload(OrdenRecepcionTecnica.tecnico_asignado),
        )
        .filter(OrdenRecepcionTecnica.id == orden_id)
        .first()
    )
    if orden is None:
        raise HTTPException(status_code=404, detail="Orden de recepción no encontrada.")

    pdf_bytes = generar_pdf_recepcion_tecnica(orden)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="recepcion_{orden.codigo}.pdf"'},
    )
