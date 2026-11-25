from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.configuracion import configuracion
from app.modelos import RolUsuario, Usuario


esquema_bearer = HTTPBearer(auto_error=False)

ROLES_SIN_COSTOS: frozenset[str] = frozenset({
    RolUsuario.ASESORA.value,
    RolUsuario.TECNICO.value,
    RolUsuario.ENCARGADO_TIENDA.value,
    RolUsuario.LIDER.value,
    RolUsuario.OTRO.value,
})

ROLES_ADMINISTRATIVOS: tuple[str, ...] = (
    RolUsuario.DIRECCION.value,
    RolUsuario.ADMINISTRACION.value,
)

ROLES_LECTURA_EJECUTIVA: tuple[str, ...] = (
    RolUsuario.DIRECCION.value,
    RolUsuario.ADMINISTRACION.value,
    RolUsuario.DIRECTOR.value,
)


def es_administrador(rol: str) -> bool:
    """Devuelve True solo para roles con acceso administrativo total (DIRECCION / ADMINISTRACION)."""
    return rol in ROLES_ADMINISTRATIVOS


def es_director_solo_lectura(rol: str) -> bool:
    """Devuelve True si el rol es DIRECTOR (acceso ejecutivo de solo lectura)."""
    return rol == RolUsuario.DIRECTOR.value


def obtener_permisos_rol(rol: str) -> list[str]:
    """Devuelve la lista explícita de permisos por rol para el frontend (/auth/me y /auth/perfil)."""
    if rol in ROLES_ADMINISTRATIVOS:
        return [
            "admin:all",
            "direccion:read",
            "costos:read",
            "finanzas:read",
            "finanzas:write",
            "tesoreria:read",
            "tesoreria:write",
            "comisiones:read",
            "comisiones:write",
            "usuarios:write",
            "ventas:anular",
            "apertura:write",
            "pos:write",
            "cotizaciones:write",
            "clientes:write",
            "inventario:read",
            "traslados:receive",
            "garantias:write",
            "cierre:write",
            "cierre:reopen",
        ]
    if rol == RolUsuario.DIRECTOR.value:
        return [
            "direccion:read",
            "costos:read",
            "finanzas:read",
            "tesoreria:read",
            "comisiones:read",
            "inventario:read",
        ]
    if rol in (RolUsuario.ENCARGADO_TIENDA.value, RolUsuario.LIDER.value):
        return [
            "apertura:write",
            "pos:write",
            "cotizaciones:write",
            "clientes:write",
            "inventario:read_no_cost",
            "traslados:receive",
            "garantias:write",
            "cierre:write",
        ]
    if rol == RolUsuario.LOGISTICA.value:
        return [
            "apertura:write",
            "costos:read",
            "inventario:read",
            "traslados:receive",
            "pos:write",
            "cotizaciones:write",
            "clientes:write",
        ]
    if rol == RolUsuario.TECNICO.value:
        return [
            "apertura:write",
            "inventario:read_no_cost",
            "garantias:write",
            "pos:write",
        ]
    return [
        "apertura:write",
        "pos:write",
        "cotizaciones:write",
        "clientes:write",
        "inventario:read_no_cost",
        "garantias:write",
    ]


def generar_hash_clave(clave_plana: str) -> str:
    """Genera hash seguro con scrypt y sal aleatoria."""
    sal = secrets.token_hex(16)
    derivada = hashlib.scrypt(
        clave_plana.encode("utf-8"),
        salt=sal.encode("utf-8"),
        n=16384,
        r=8,
        p=1,
        dklen=64,
    ).hex()
    return f"scrypt${sal}${derivada}"


def verificar_clave(clave_plana: str, clave_hash: str) -> bool:
    """Verifica la contraseña en tiempo constante."""
    try:
        prefijo, sal, hash_guardado = clave_hash.split("$", 2)
        if prefijo != "scrypt":
            return False
    except ValueError:
        return False

    derivada = hashlib.scrypt(
        clave_plana.encode("utf-8"),
        salt=sal.encode("utf-8"),
        n=16384,
        r=8,
        p=1,
        dklen=64,
    ).hex()
    return hmac.compare_digest(derivada, hash_guardado)


def crear_token_acceso(usuario: Usuario) -> str:
    """Firma un JWT con expiración y rol del usuario."""
    ahora = datetime.now(timezone.utc)
    expiracion = ahora + timedelta(hours=configuracion.EXPIRACION_JWT_HORAS)
    carga = {
        "sub": str(usuario.id),
        "correo": usuario.correo,
        "rol": usuario.rol,
        "iat": int(ahora.timestamp()),
        "exp": int(expiracion.timestamp()),
    }
    return jwt.encode(carga, configuracion.secreto_jwt_efectivo, algorithm=configuracion.ALGORITMO_JWT)


def puede_ver_costos(rol: str) -> bool:
    """Determina si el rol puede recibir campos de costos desde el backend."""
    return rol not in ROLES_SIN_COSTOS


def obtener_usuario_actual(
    credenciales: HTTPAuthorizationCredentials | None = Depends(esquema_bearer),
    bd: Session = Depends(obtener_bd),
) -> Usuario:
    """Valida el JWT Bearer y devuelve el usuario activo."""
    if credenciales is None or not credenciales.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida. Inicia sesión para continuar.",
        )

    try:
        carga = jwt.decode(
            credenciales.credentials,
            configuracion.secreto_jwt_efectivo,
            algorithms=[configuracion.ALGORITMO_JWT],
        )
        usuario_id = int(carga["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de sesión inválido o expirado.",
        )

    usuario = (
        bd.query(Usuario)
        .options(joinedload(Usuario.sucursal))
        .filter(Usuario.id == usuario_id)
        .first()
    )
    if usuario is None or not usuario.activo or not getattr(usuario, "tiene_acceso", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo, sin acceso o inexistente.",
        )
    return usuario


def requerir_roles(*roles_permitidos: str) -> Callable[[Usuario], Usuario]:
    """Dependencia RBAC que restringe el endpoint a los roles indicados."""
    conjunto_roles = set(roles_permitidos)

    def validador(usuario_actual: Usuario = Depends(obtener_usuario_actual)) -> Usuario:
        if usuario_actual.rol not in conjunto_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos suficientes para realizar esta operación.",
            )
        return usuario_actual

    return validador


# Alias explícito reutilizable para endpoints exclusivos de Administrador
requerir_admin = requerir_roles(*ROLES_ADMINISTRATIVOS)
requerir_direccion_lectura = requerir_roles(*ROLES_LECTURA_EJECUTIVA)
require_roles = requerir_roles
require_admin = requerir_admin


def requerir_escritura_operativa(
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
) -> Usuario:
    """Impide que el rol DIRECTOR (solo lectura) realice mutaciones operativas."""
    if usuario_actual.rol == RolUsuario.DIRECTOR.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El rol Director es de solo lectura y no puede crear ni modificar registros.",
        )
    return usuario_actual
