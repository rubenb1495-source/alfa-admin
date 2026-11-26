from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.configuracion import configuracion
from app.esquemas import LoginEntrada, LoginSalida, UsuarioSalida
from app.modelos import Usuario
from app.modelos_admin import AuditLog
from app.seguridad import (
    crear_token_acceso,
    generar_hash_clave,
    obtener_permisos_rol,
    obtener_usuario_actual,
    verificar_clave,
)

MAX_INTENTOS_FALLIDOS = 5
enrutador = APIRouter(prefix="/api/auth", tags=["Autenticación"])


def _ahora_caracas() -> datetime:
    return datetime.now(ZoneInfo(configuracion.ZONA_HORARIA))


def _serializar_usuario_con_permisos(usuario: Usuario) -> UsuarioSalida:
    salida = UsuarioSalida.model_validate(usuario)
    salida.permisos = obtener_permisos_rol(usuario.rol)
    return salida


@enrutador.post("/login", response_model=LoginSalida)
def iniciar_sesion(datos: LoginEntrada, bd: Session = Depends(obtener_bd)):
    ident = (datos.usuario or "").strip()
    ident_lower = ident.lower()
    clave = datos.clave or ""

    usuario = (
        bd.query(Usuario)
        .options(joinedload(Usuario.sucursal))
        .filter(
            or_(
                func.lower(Usuario.usuario) == ident_lower,
                func.lower(Usuario.nombre) == ident_lower,
                func.lower(Usuario.correo) == ident_lower,
            )
        )
        .first()
    )

    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o clave incorrectos.",
        )

    if not getattr(usuario, "tiene_acceso", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este colaborador no tiene acceso habilitado al sistema.",
        )

    if not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu cuenta se encuentra desactivada. Contacta a Dirección o Administración.",
        )

    if getattr(usuario, "cuenta_bloqueada", False):
        return JSONResponse(
            status_code=status.HTTP_423_LOCKED,
            content={
                "detail": "Acceso bloqueado tras 5 intentos fallidos. Contacta al Administrador para desbloquearlo.",
                "cuenta_bloqueada": True,
                "intentos_restantes": 0,
            },
        )

    if not usuario.clave_hash or not verificar_clave(clave, usuario.clave_hash):
        usuario.intentos_fallidos = int(getattr(usuario, "intentos_fallidos", 0) or 0) + 1
        if usuario.intentos_fallidos >= MAX_INTENTOS_FALLIDOS:
            ahora = _ahora_caracas()
            usuario.cuenta_bloqueada = True
            usuario.fecha_bloqueo = ahora
            bd.add(
                AuditLog(
                    usuario_id=usuario.id,
                    usuario_nombre=usuario.nombre,
                    modulo="SEGURIDAD",
                    accion="BLOQUEO_ACCESO",
                    entidad_id=str(usuario.id),
                    datos_anteriores_json=json.dumps({"cuenta_bloqueada": False}, ensure_ascii=False),
                    datos_nuevos_json=json.dumps(
                        {
                            "cuenta_bloqueada": True,
                            "usuario": usuario.usuario or usuario.nombre,
                            "intentos_fallidos": usuario.intentos_fallidos,
                            "fecha_bloqueo": ahora.isoformat(),
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            bd.commit()
            return JSONResponse(
                status_code=status.HTTP_423_LOCKED,
                content={
                    "detail": "Acceso bloqueado tras 5 intentos fallidos. Contacta al Administrador para desbloquearlo.",
                    "cuenta_bloqueada": True,
                    "intentos_restantes": 0,
                },
            )

        restantes = MAX_INTENTOS_FALLIDOS - usuario.intentos_fallidos
        bd.commit()
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "detail": f"Clave incorrecta. Te quedan {restantes} intento{'s' if restantes != 1 else ''} antes de bloquear tu acceso.",
                "intentos_restantes": restantes,
                "cuenta_bloqueada": False,
            },
        )

    # Login exitoso: reiniciar contador de intentos fallidos
    if usuario.intentos_fallidos:
        usuario.intentos_fallidos = 0
        bd.commit()

    token = crear_token_acceso(usuario)
    return LoginSalida(
        token=token,
        debe_cambiar_clave=bool(getattr(usuario, "debe_cambiar_clave", False)),
        usuario=_serializar_usuario_con_permisos(usuario),
    )


@enrutador.post("/logout")
def cerrar_sesion(
    _usuario_actual: Usuario = Depends(obtener_usuario_actual),
) -> dict[str, str]:
    """Endpoint de cierre de sesión (permitido incluso cuando debe_cambiar_clave es True)."""
    return {"mensaje": "Sesión cerrada correctamente."}


@enrutador.get("/perfil", response_model=UsuarioSalida)
@enrutador.get("/me", response_model=UsuarioSalida)
def obtener_perfil(usuario_actual: Usuario = Depends(obtener_usuario_actual)) -> UsuarioSalida:
    return _serializar_usuario_con_permisos(usuario_actual)


class CambiarClaveEntrada(BaseModel):
    clave_actual: str = Field(min_length=4, max_length=128)
    nueva_clave: str = Field(min_length=6, max_length=128)
    confirmar_clave: str | None = Field(default=None, max_length=128)


@enrutador.post("/cambiar-clave")
def cambiar_mi_clave(
    datos: CambiarClaveEntrada,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> dict[str, object]:
    if not usuario_actual.clave_hash or not verificar_clave(datos.clave_actual, usuario_actual.clave_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La clave actual es incorrecta.",
        )
    if datos.confirmar_clave is not None and datos.nueva_clave != datos.confirmar_clave:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nueva clave y su confirmación no coinciden.",
        )
    if datos.nueva_clave == datos.clave_actual or verificar_clave(datos.nueva_clave, usuario_actual.clave_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nueva clave debe ser distinta a la clave temporal actual.",
        )

    era_primer_ingreso = bool(getattr(usuario_actual, "debe_cambiar_clave", False))
    usuario_actual.clave_hash = generar_hash_clave(datos.nueva_clave)
    usuario_actual.debe_cambiar_clave = False
    bd.add(
        AuditLog(
            usuario_id=usuario_actual.id,
            usuario_nombre=usuario_actual.nombre,
            rol=usuario_actual.rol,
            modulo="SEGURIDAD",
            accion="CAMBIO_CLAVE_PRIMER_INGRESO" if era_primer_ingreso else "CAMBIO_CLAVE",
            entidad_id=str(usuario_actual.id),
            datos_anteriores_json=json.dumps({"debe_cambiar_clave": era_primer_ingreso}, ensure_ascii=False),
            datos_nuevos_json=json.dumps(
                {
                    "usuario": usuario_actual.usuario or usuario_actual.nombre,
                    "debe_cambiar_clave": False,
                },
                ensure_ascii=False,
            ),
        )
    )
    bd.commit()
    return {
        "mensaje": "Contraseña actualizada correctamente.",
        "debe_cambiar_clave": False,
    }
