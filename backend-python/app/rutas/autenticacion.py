from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.esquemas import LoginEntrada, LoginSalida, UsuarioSalida
from app.modelos import Usuario
from app.seguridad import (
    crear_token_acceso,
    generar_hash_clave,
    obtener_permisos_rol,
    obtener_usuario_actual,
    verificar_clave,
)


enrutador = APIRouter(prefix="/api/auth", tags=["Autenticación"])


def _serializar_usuario_con_permisos(usuario: Usuario) -> UsuarioSalida:
    salida = UsuarioSalida.model_validate(usuario)
    salida.permisos = obtener_permisos_rol(usuario.rol)
    return salida


@enrutador.post("/login", response_model=LoginSalida)
def iniciar_sesion(datos: LoginEntrada, bd: Session = Depends(obtener_bd)) -> LoginSalida:
    correo_normalizado = datos.correo.strip().lower()
    usuario = (
        bd.query(Usuario)
        .options(joinedload(Usuario.sucursal))
        .filter(Usuario.correo == correo_normalizado)
        .first()
    )

    if usuario is None or not usuario.clave_hash or not verificar_clave(datos.clave, usuario.clave_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o clave incorrectos.",
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

    token = crear_token_acceso(usuario)
    return LoginSalida(
        token=token,
        usuario=_serializar_usuario_con_permisos(usuario),
    )


@enrutador.get("/perfil", response_model=UsuarioSalida)
@enrutador.get("/me", response_model=UsuarioSalida)
def obtener_perfil(usuario_actual: Usuario = Depends(obtener_usuario_actual)) -> UsuarioSalida:
    return _serializar_usuario_con_permisos(usuario_actual)


class CambiarClaveEntrada(BaseModel):
    clave_actual: str = Field(min_length=4, max_length=128)
    nueva_clave: str = Field(min_length=6, max_length=128)


@enrutador.post("/cambiar-clave")
def cambiar_mi_clave(
    datos: CambiarClaveEntrada,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> dict[str, str]:
    if not usuario_actual.clave_hash or not verificar_clave(datos.clave_actual, usuario_actual.clave_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña actual es incorrecta.",
        )
    usuario_actual.clave_hash = generar_hash_clave(datos.nueva_clave)
    usuario_actual.debe_cambiar_clave = False
    bd.commit()
    return {"mensaje": "Contraseña actualizada correctamente."}
