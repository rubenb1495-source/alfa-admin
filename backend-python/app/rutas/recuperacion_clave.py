from __future__ import annotations

import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func, or_
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.base_datos import Base, obtener_bd
from app.modelos import Usuario
from app.seguridad import generar_hash_clave, requerir_admin, verificar_clave


class SolicitudRecuperacionClave(Base):
    __tablename__ = "solicitudes_recuperacion_clave"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True, nullable=False)
    usuario_nombre: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    correo: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    codigo_hash: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    via_smtp: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    atendida: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


enrutador = APIRouter(prefix="/api/auth", tags=["Recuperación de Clave"])


class SolicitarRecuperacionEntrada(BaseModel):
    usuario: str = Field(min_length=2, max_length=160)


class ConfirmarRecuperacionEntrada(BaseModel):
    usuario: str = Field(min_length=2, max_length=160)
    codigo: str = Field(min_length=4, max_length=20)
    nueva_clave: str = Field(min_length=6, max_length=128)


def _buscar_usuario(bd: Session, identificador: str) -> Usuario | None:
    limpio = identificador.strip()
    if not limpio:
        return None
    filtros = [
        func.lower(Usuario.nombre) == limpio.lower(),
        func.lower(Usuario.correo) == limpio.lower(),
    ]
    if hasattr(Usuario, "usuario"):
        filtros.append(func.lower(Usuario.usuario) == limpio.lower())
    if hasattr(Usuario, "username"):
        filtros.append(func.lower(Usuario.username) == limpio.lower())
    return bd.query(Usuario).filter(or_(*filtros)).first()


def _enviar_codigo_smtp(destinatario: str, nombre: str, codigo: str) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    if not (host and user and password):
        return False
    port = int(os.getenv("SMTP_PORT", "587"))
    remitente = os.getenv("SMTP_FROM", user).strip()
    msg = EmailMessage()
    msg["Subject"] = "Código de recuperación de clave (válido 15 minutos)"
    msg["From"] = remitente
    msg["To"] = destinatario
    msg.set_content(
        f"Hola {nombre},\n\n"
        f"Tu código temporal de recuperación de acceso es: {codigo}\n"
        f"Este código expira en 15 minutos.\n\n"
        f"Si no solicitaste este cambio, ignora este mensaje."
    )
    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except Exception:
        return False


def _desbloquear_usuario_obj(usuario: Usuario) -> None:
    if hasattr(usuario, "cuenta_bloqueada"):
        usuario.cuenta_bloqueada = False
    if hasattr(usuario, "intentos_fallidos"):
        usuario.intentos_fallidos = 0
    if hasattr(usuario, "intentos_fallidos_login"):
        usuario.intentos_fallidos_login = 0
    if hasattr(usuario, "fecha_bloqueo"):
        usuario.fecha_bloqueo = None
    if hasattr(usuario, "bloqueado_hasta"):
        usuario.bloqueado_hasta = None
    if hasattr(usuario, "bloqueado_en"):
        usuario.bloqueado_en = None


@enrutador.post("/solicitar-recuperacion")
def solicitar_recuperacion_clave(
    datos: SolicitarRecuperacionEntrada,
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Solicita recuperación de clave: envía código SMTP (15 min) o registra alerta para Administración."""
    usuario = _buscar_usuario(bd, datos.usuario)
    if usuario is None or not usuario.activo:
        return {
            "enviado_correo": False,
            "requiere_codigo": False,
            "mensaje": (
                "Si el usuario existe en el sistema, se registró la solicitud de recuperación. "
                "Contacta a Administración / Dirección para recibir tu clave temporal."
            ),
        }

    ahora = datetime.now(timezone.utc)
    codigo = f"{secrets.randbelow(900000) + 100000}"
    correo = (getattr(usuario, "correo", "") or "").strip()
    enviado_smtp = False
    if correo and "@" in correo:
        enviado_smtp = _enviar_codigo_smtp(correo, usuario.nombre, codigo)

    sol = SolicitudRecuperacionClave(
        usuario_id=usuario.id,
        usuario_nombre=usuario.nombre,
        correo=correo,
        codigo_hash=generar_hash_clave(codigo),
        expira_en=ahora + timedelta(minutes=15),
        usado=False,
        via_smtp=enviado_smtp,
        atendida=enviado_smtp,
    )
    bd.add(sol)
    bd.commit()

    if enviado_smtp:
        return {
            "enviado_correo": True,
            "requiere_codigo": True,
            "mensaje": "Enviamos un código temporal de 6 dígitos (válido por 15 minutos) a tu correo registrado.",
        }

    return {
        "enviado_correo": False,
        "requiere_codigo": False,
        "mensaje": (
            "Se registró una alerta de recuperación de clave para Dirección / Administración. "
            "Contacta a tu Administrador para que regenere tu clave temporal."
        ),
    }


@enrutador.post("/confirmar-recuperacion")
def confirmar_recuperacion_clave(
    datos: ConfirmarRecuperacionEntrada,
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Valida el código de 15 minutos, establece la nueva contraseña y desbloquea la cuenta."""
    usuario = _buscar_usuario(bd, datos.usuario)
    if usuario is None or not usuario.activo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Código inválido o expirado.")

    sol = (
        bd.query(SolicitudRecuperacionClave)
        .filter(
            SolicitudRecuperacionClave.usuario_id == usuario.id,
            SolicitudRecuperacionClave.usado.is_(False),
        )
        .order_by(SolicitudRecuperacionClave.id.desc())
        .first()
    )
    if sol is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No existe una solicitud de recuperación activa.")

    ahora = datetime.now(timezone.utc)
    exp = sol.expira_en
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if ahora > exp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El código de recuperación expiró (15 minutos). Solicita uno nuevo.")

    if not verificar_clave(datos.codigo.strip(), sol.codigo_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El código de verificación es incorrecto.")

    usuario.clave_hash = generar_hash_clave(datos.nueva_clave)
    usuario.debe_cambiar_clave = False
    _desbloquear_usuario_obj(usuario)
    sol.usado = True
    sol.atendida = True
    bd.commit()

    return {
        "mensaje": "Contraseña actualizada y cuenta desbloqueada correctamente. Ya puedes iniciar sesión.",
    }


@enrutador.get("/solicitudes-recuperacion")
def listar_solicitudes_recuperacion(
    _admin: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, Any]]:
    """Lista alertas pendientes de recuperación de clave para Dirección / Administración."""
    filas = (
        bd.query(SolicitudRecuperacionClave)
        .filter(SolicitudRecuperacionClave.atendida.is_(False))
        .order_by(SolicitudRecuperacionClave.id.desc())
        .limit(30)
        .all()
    )
    return [
        {
            "id": f.id,
            "usuario_id": f.usuario_id,
            "nombre": f.usuario_nombre,
            "correo": f.correo,
            "creado_en": f.creado_en.isoformat() if f.creado_en else None,
            "mensaje": f"Solicitud de recuperación de clave para {f.usuario_nombre}. Regenera su clave temporal en Usuarios.",
        }
        for f in filas
    ]
