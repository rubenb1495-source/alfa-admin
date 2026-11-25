from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.configuracion import configuracion
from app.esquemas import (
    TasaActualizarHoyEntrada,
    TasaConfirmarHoyEntrada,
    TasaCrearEntrada,
    TasaHoySalida,
    TasaSalida,
    TasasPaginadasSalida,
)
from app.modelos import OrigenTasa, TasaDiaria, Usuario
from app.seguridad import ROLES_ADMINISTRATIVOS, obtener_usuario_actual, requerir_roles
from app.servicios.tasas_externas import consultar_tasas_automaticas


enrutador = APIRouter(prefix="/api/tasas", tags=["Tasas Diarias"])


def obtener_fecha_hoy() -> date:
    """Obtiene la fecha actual en la zona horaria de Venezuela (America/Caracas)."""
    return datetime.now(ZoneInfo(configuracion.ZONA_HORARIA)).date()


def calcular_brecha_porcentaje(tasa_bcv: Decimal, tasa_usdt: Decimal) -> float:
    if tasa_bcv <= 0:
        return 0.0
    brecha = ((tasa_usdt - tasa_bcv) / tasa_bcv) * Decimal("100")
    return float(round(brecha, 2))


def serializar_tasa(tasa: TasaDiaria) -> TasaSalida:
    return TasaSalida(
        id=tasa.id,
        fecha=tasa.fecha,
        tasa_bcv=float(tasa.tasa_bcv),
        tasa_usdt=float(tasa.tasa_usdt),
        recargo_porcentaje=float(tasa.recargo_porcentaje),
        recargo_confirmado=bool(getattr(tasa, "recargo_confirmado", True)),
        brecha_porcentaje=calcular_brecha_porcentaje(tasa.tasa_bcv, tasa.tasa_usdt),
        origen=OrigenTasa(tasa.origen),
        fuente_tasa=getattr(tasa, "fuente_tasa", "MANUAL") or "MANUAL",
        nota=tasa.nota or "",
        publicado_por=tasa.publicado_por.nombre if tasa.publicado_por else None,
        actualizado_en=tasa.actualizado_en,
    )


def obtener_ultima_tasa_anterior(bd: Session, fecha_ref: date) -> TasaDiaria | None:
    return (
        bd.query(TasaDiaria)
        .filter(TasaDiaria.fecha < fecha_ref)
        .order_by(TasaDiaria.fecha.desc())
        .first()
    )


def obtener_ultimo_recargo(bd: Session, fecha_ref: date | None = None) -> Decimal | None:
    if fecha_ref is not None:
        anterior = obtener_ultima_tasa_anterior(bd, fecha_ref)
        if anterior is not None:
            return anterior.recargo_porcentaje
    ultima = bd.query(TasaDiaria).order_by(TasaDiaria.fecha.desc()).first()
    return ultima.recargo_porcentaje if ultima else None


def _construir_tasa_hoy_salida(
    tasa: TasaDiaria,
    ultimo_recargo_usado: Decimal | None,
    alerta_extra: str | None = None,
) -> TasaHoySalida:
    confirmado = bool(getattr(tasa, "recargo_confirmado", False))
    recargo_val = float(tasa.recargo_porcentaje) if confirmado else None
    alerta = alerta_extra
    if not confirmado and not alerta:
        alerta = "Apertura del día pendiente — Confirma el porcentaje de recargo"

    actualizado_por: str | None = None
    if tasa.publicado_por is not None:
        actualizado_por = f"{tasa.publicado_por.nombre} ({tasa.publicado_por.rol})"

    return TasaHoySalida(
        fecha=tasa.fecha,
        permite_bolivares=bool(tasa.tasa_bcv > 0 and confirmado),
        alerta=alerta,
        tasa_bcv=float(tasa.tasa_bcv),
        tasa_usdt=float(tasa.tasa_usdt),
        recargo_porcentaje=recargo_val if recargo_val is not None else float(tasa.recargo_porcentaje),
        porcentaje_recargo=recargo_val,
        recargo_confirmado=confirmado,
        fuente_tasa=getattr(tasa, "fuente_tasa", "MANUAL") or "MANUAL",
        ultimo_recargo_usado=float(ultimo_recargo_usado) if ultimo_recargo_usado is not None else None,
        brecha_porcentaje=calcular_brecha_porcentaje(tasa.tasa_bcv, tasa.tasa_usdt),
        origen=OrigenTasa(tasa.origen),
        nota=tasa.nota or "",
        actualizado_por=actualizado_por,
        actualizado_en=tasa.actualizado_en,
    )


@enrutador.get("/hoy", response_model=TasaHoySalida)
def obtener_tasa_hoy(
    _usuario: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> TasaHoySalida:
    hoy = obtener_fecha_hoy()
    ultimo_recargo = obtener_ultimo_recargo(bd, hoy)
    tasa = (
        bd.query(TasaDiaria)
        .options(joinedload(TasaDiaria.publicado_por))
        .filter(TasaDiaria.fecha == hoy)
        .first()
    )

    if tasa is None:
        externas = consultar_tasas_automaticas(timeout_segundos=5.0)
        if externas is not None:
            tasa = TasaDiaria(
                fecha=hoy,
                tasa_bcv=externas["tasa_bcv"],
                tasa_usdt=externas["tasa_usdt"],
                recargo_porcentaje=ultimo_recargo if ultimo_recargo is not None else Decimal("0"),
                recargo_confirmado=False,
                origen=OrigenTasa.AUTOMATICO.value,
                fuente_tasa="API_VIVO",
                nota="Tasas cargadas automáticamente al iniciar jornada.",
            )
            bd.add(tasa)
            bd.commit()
            bd.refresh(tasa)
            return _construir_tasa_hoy_salida(tasa, ultimo_recargo)

        # Fallback si la API externa falla: usar la última tasa registrada en BD
        respaldo = obtener_ultima_tasa_anterior(bd, hoy)
        if respaldo is not None:
            tasa = TasaDiaria(
                fecha=hoy,
                tasa_bcv=respaldo.tasa_bcv,
                tasa_usdt=respaldo.tasa_usdt,
                recargo_porcentaje=respaldo.recargo_porcentaje,
                recargo_confirmado=False,
                origen=OrigenTasa.MANUAL.value,
                fuente_tasa="RESPALDO_MANUAL",
                nota="Respaldo automático con última tasa registrada (API externa no disponible).",
            )
            bd.add(tasa)
            bd.commit()
            bd.refresh(tasa)
            return _construir_tasa_hoy_salida(
                tasa,
                ultimo_recargo,
                alerta_extra="API externa no disponible — Usando última tasa de respaldo. Verifica y confirma el recargo.",
            )

        return TasaHoySalida(
            fecha=hoy,
            permite_bolivares=False,
            alerta="No se pudieron obtener las tasas automáticas. Ingresa las tasas y confirma el porcentaje de recargo.",
            tasa_bcv=None,
            tasa_usdt=None,
            recargo_porcentaje=float(ultimo_recargo) if ultimo_recargo is not None else None,
            porcentaje_recargo=None,
            recargo_confirmado=False,
            fuente_tasa="RESPALDO_MANUAL",
            ultimo_recargo_usado=float(ultimo_recargo) if ultimo_recargo is not None else None,
        )

    return _construir_tasa_hoy_salida(tasa, ultimo_recargo)


@enrutador.post("/hoy/confirmar", response_model=TasaHoySalida)
def confirmar_tasa_hoy(
    datos: TasaConfirmarHoyEntrada,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> TasaHoySalida:
    hoy = obtener_fecha_hoy()
    ultimo_recargo = obtener_ultimo_recargo(bd, hoy)
    tasa = (
        bd.query(TasaDiaria)
        .options(joinedload(TasaDiaria.publicado_por))
        .filter(TasaDiaria.fecha == hoy)
        .first()
    )

    if tasa is None:
        if datos.tasa_bcv is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes indicar una tasa BCV válida mayor a 0 para abrir la jornada.",
            )
        tasa_usdt_val = datos.tasa_usdt if datos.tasa_usdt is not None else datos.tasa_bcv
        tasa = TasaDiaria(
            fecha=hoy,
            tasa_bcv=datos.tasa_bcv,
            tasa_usdt=tasa_usdt_val,
            recargo_porcentaje=datos.porcentaje_recargo,
            recargo_confirmado=True,
            origen=OrigenTasa.MANUAL.value,
            fuente_tasa="MANUAL",
            publicado_por_id=usuario_actual.id,
            nota=(datos.nota or "").strip(),
        )
        bd.add(tasa)
    else:
        ajuste_manual = False
        if datos.tasa_bcv is not None and datos.tasa_bcv != tasa.tasa_bcv:
            tasa.tasa_bcv = datos.tasa_bcv
            ajuste_manual = True
        if datos.tasa_usdt is not None and datos.tasa_usdt != tasa.tasa_usdt:
            tasa.tasa_usdt = datos.tasa_usdt
            ajuste_manual = True
        if ajuste_manual:
            tasa.origen = OrigenTasa.MANUAL.value
            tasa.fuente_tasa = "MANUAL"
        tasa.recargo_porcentaje = datos.porcentaje_recargo
        tasa.recargo_confirmado = True
        tasa.publicado_por_id = usuario_actual.id
        if datos.nota is not None:
            tasa.nota = datos.nota.strip()

    bd.commit()
    tasa_actualizada = (
        bd.query(TasaDiaria)
        .options(joinedload(TasaDiaria.publicado_por))
        .filter(TasaDiaria.fecha == hoy)
        .first()
    )
    return _construir_tasa_hoy_salida(tasa_actualizada, ultimo_recargo)


@enrutador.post("/sincronizar", response_model=TasaHoySalida)
def sincronizar_tasas_hoy(
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> TasaHoySalida:
    """Refresca BCV y USDT desde la API externa sin borrar ni desconfirmar el recargo del día."""
    hoy = obtener_fecha_hoy()
    ultimo_recargo = obtener_ultimo_recargo(bd, hoy)
    tasa = (
        bd.query(TasaDiaria)
        .options(joinedload(TasaDiaria.publicado_por))
        .filter(TasaDiaria.fecha == hoy)
        .first()
    )

    externas = consultar_tasas_automaticas(timeout_segundos=5.0)
    if externas is not None:
        if tasa is None:
            tasa = TasaDiaria(
                fecha=hoy,
                tasa_bcv=externas["tasa_bcv"],
                tasa_usdt=externas["tasa_usdt"],
                recargo_porcentaje=ultimo_recargo if ultimo_recargo is not None else Decimal("0"),
                recargo_confirmado=False,
                origen=OrigenTasa.AUTOMATICO.value,
                fuente_tasa="API_VIVO",
                publicado_por_id=usuario_actual.id,
                nota="Sincronizado desde API externa.",
            )
            bd.add(tasa)
        else:
            tasa.tasa_bcv = externas["tasa_bcv"]
            tasa.tasa_usdt = externas["tasa_usdt"]
            tasa.fuente_tasa = "API_VIVO"
            # Preserva intactos recargo_porcentaje y recargo_confirmado
        bd.commit()
        tasa_refrescada = (
            bd.query(TasaDiaria)
            .options(joinedload(TasaDiaria.publicado_por))
            .filter(TasaDiaria.fecha == hoy)
            .first()
        )
        return _construir_tasa_hoy_salida(tasa_refrescada, ultimo_recargo)

    # Si falla la API externa, nunca romper la app
    if tasa is not None:
        tasa.fuente_tasa = "RESPALDO_MANUAL"
        bd.commit()
        bd.refresh(tasa)
        return _construir_tasa_hoy_salida(
            tasa,
            ultimo_recargo,
            alerta_extra="No se pudo conectar con la API externa — Se mantienen las tasas de respaldo.",
        )

    respaldo = obtener_ultima_tasa_anterior(bd, hoy)
    if respaldo is not None:
        tasa = TasaDiaria(
            fecha=hoy,
            tasa_bcv=respaldo.tasa_bcv,
            tasa_usdt=respaldo.tasa_usdt,
            recargo_porcentaje=respaldo.recargo_porcentaje,
            recargo_confirmado=False,
            origen=OrigenTasa.MANUAL.value,
            fuente_tasa="RESPALDO_MANUAL",
            nota="Respaldo con última tasa registrada (API externa no disponible).",
        )
        bd.add(tasa)
        bd.commit()
        bd.refresh(tasa)
        return _construir_tasa_hoy_salida(
            tasa,
            ultimo_recargo,
            alerta_extra="API externa no disponible — Usando última tasa de respaldo.",
        )

    return TasaHoySalida(
        fecha=hoy,
        permite_bolivares=False,
        alerta="No se pudo conectar con la API externa y no hay tasas previas en respaldo.",
        tasa_bcv=None,
        tasa_usdt=None,
        recargo_porcentaje=None,
        porcentaje_recargo=None,
        recargo_confirmado=False,
        fuente_tasa="RESPALDO_MANUAL",
        ultimo_recargo_usado=float(ultimo_recargo) if ultimo_recargo is not None else None,
    )


@enrutador.get("", response_model=TasasPaginadasSalida)
def listar_tasas(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=20, ge=1, le=100),
    _usuario: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> TasasPaginadasSalida:
    consulta = bd.query(TasaDiaria).options(joinedload(TasaDiaria.publicado_por))
    if desde is not None:
        consulta = consulta.filter(TasaDiaria.fecha >= desde)
    if hasta is not None:
        consulta = consulta.filter(TasaDiaria.fecha <= hasta)

    total = consulta.count()
    filas = (
        consulta.order_by(TasaDiaria.fecha.desc())
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
        .all()
    )

    return TasasPaginadasSalida(
        elementos=[serializar_tasa(f) for f in filas],
        total=total,
        pagina=pagina,
        por_pagina=por_pagina,
    )


@enrutador.post("", response_model=TasaSalida, status_code=status.HTTP_201_CREATED)
def crear_tasa(
    datos: TasaCrearEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> TasaSalida:
    hoy = obtener_fecha_hoy()
    if datos.fecha < hoy:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No está permitido registrar ni modificar tasas de fechas pasadas.",
        )

    existente = bd.query(TasaDiaria).filter(TasaDiaria.fecha == datos.fecha).first()
    if existente is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una tasa registrada para esa fecha.",
        )

    recargo = datos.recargo_porcentaje
    if recargo is None:
        recargo = obtener_ultimo_recargo(bd)
        if recargo is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes indicar el porcentaje de recargo al registrar la primera tasa.",
            )

    nueva = TasaDiaria(
        fecha=datos.fecha,
        tasa_bcv=datos.tasa_bcv,
        tasa_usdt=datos.tasa_usdt,
        recargo_porcentaje=recargo,
        recargo_confirmado=True,
        origen=OrigenTasa.MANUAL.value,
        fuente_tasa="MANUAL",
        publicado_por_id=usuario_actual.id,
        nota=datos.nota.strip(),
    )
    bd.add(nueva)
    bd.commit()
    bd.refresh(nueva)

    tasa_completa = (
        bd.query(TasaDiaria)
        .options(joinedload(TasaDiaria.publicado_por))
        .filter(TasaDiaria.id == nueva.id)
        .first()
    )
    return serializar_tasa(tasa_completa)


@enrutador.put("/hoy", response_model=TasaSalida)
def actualizar_tasa_hoy(
    datos: TasaActualizarHoyEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> TasaSalida:
    hoy = obtener_fecha_hoy()
    tasa = (
        bd.query(TasaDiaria)
        .options(joinedload(TasaDiaria.publicado_por))
        .filter(TasaDiaria.fecha == hoy)
        .first()
    )

    if tasa is None:
        if datos.tasa_bcv is None or datos.tasa_usdt is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No existe tasa registrada para hoy. Debes indicar tasa_bcv y tasa_usdt.",
            )
        recargo = datos.recargo_porcentaje
        if recargo is None:
            recargo = obtener_ultimo_recargo(bd)
            if recargo is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Debes indicar el porcentaje de recargo para crear la primera tasa del día.",
                )
        tasa = TasaDiaria(
            fecha=hoy,
            tasa_bcv=datos.tasa_bcv,
            tasa_usdt=datos.tasa_usdt,
            recargo_porcentaje=recargo,
            recargo_confirmado=True,
            origen=OrigenTasa.MANUAL.value,
            fuente_tasa="MANUAL",
            publicado_por_id=usuario_actual.id,
            nota=(datos.nota or "").strip(),
        )
        bd.add(tasa)
    else:
        if datos.tasa_bcv is not None:
            tasa.tasa_bcv = datos.tasa_bcv
        if datos.tasa_usdt is not None:
            tasa.tasa_usdt = datos.tasa_usdt
        if datos.recargo_porcentaje is not None:
            tasa.recargo_porcentaje = datos.recargo_porcentaje
        if datos.nota is not None:
            tasa.nota = datos.nota.strip()
        tasa.recargo_confirmado = True
        tasa.origen = OrigenTasa.MANUAL.value
        tasa.fuente_tasa = "MANUAL"
        tasa.publicado_por_id = usuario_actual.id

    bd.commit()
    tasa_actualizada = (
        bd.query(TasaDiaria)
        .options(joinedload(TasaDiaria.publicado_por))
        .filter(TasaDiaria.fecha == hoy)
        .first()
    )
    return serializar_tasa(tasa_actualizada)
