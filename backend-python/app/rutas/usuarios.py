from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.base_datos import obtener_bd
from app.esquemas import (
    SucursalSalida,
    UsuarioActualizarEntrada,
    UsuarioCrearEntrada,
    UsuarioEstadoEntrada,
    UsuarioSalida,
)
from app.modelos import RolUsuario, Sucursal, Usuario
from app.seguridad import (
    ROLES_ADMINISTRATIVOS,
    generar_hash_clave,
    obtener_usuario_actual,
    requerir_roles,
)


enrutador = APIRouter(prefix="/api", tags=["Usuarios y Sucursales"])


@enrutador.get("/sucursales", response_model=list[SucursalSalida])
def listar_sucursales(
    _usuario: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> list[SucursalSalida]:
    sucursales = bd.query(Sucursal).order_by(Sucursal.id.asc()).all()
    return [SucursalSalida.model_validate(s) for s in sucursales]


@enrutador.get("/usuarios/operativos")
def listar_usuarios_operativos(
    _usuario: Usuario = Depends(obtener_usuario_actual),
    bd: Session = Depends(obtener_bd),
) -> list[dict[str, object]]:
    """Lista todo el personal activo (con o sin acceso al sistema) para selectores del POS y cotizaciones."""
    usuarios = (
        bd.query(Usuario)
        .filter(Usuario.activo.is_(True))
        .order_by(Usuario.nombre.asc(), Usuario.id.asc())
        .all()
    )
    return [
        {
            "id": u.id,
            "nombre": u.nombre,
            "rol": u.rol,
            "modalidad": getattr(u, "modalidad", "PRESENCIAL") or "PRESENCIAL",
            "telefono": getattr(u, "telefono", "") or "",
            "tiene_acceso": bool(getattr(u, "tiene_acceso", True)),
            "es_lider": u.rol == RolUsuario.LIDER.value,
            "es_encargado": u.rol in (RolUsuario.ENCARGADO_TIENDA.value, RolUsuario.LIDER.value),
            "sucursal_id": u.sucursal_id,
        }
        for u in usuarios
    ]


@enrutador.get("/usuarios", response_model=list[UsuarioSalida])
def listar_usuarios(
    rol: RolUsuario | None = Query(default=None),
    activo: bool | None = Query(default=None),
    tiene_acceso: bool | None = Query(default=None),
    _usuario: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> list[UsuarioSalida]:
    consulta = bd.query(Usuario).options(joinedload(Usuario.sucursal))
    if rol is not None:
        consulta = consulta.filter(Usuario.rol == rol.value)
    if activo is not None:
        consulta = consulta.filter(Usuario.activo == activo)
    if tiene_acceso is not None:
        consulta = consulta.filter(Usuario.tiene_acceso == tiene_acceso)
    usuarios = consulta.order_by(Usuario.id.asc()).all()
    return [UsuarioSalida.model_validate(u) for u in usuarios]


@enrutador.post("/usuarios", response_model=UsuarioSalida, status_code=status.HTTP_201_CREATED)
def crear_usuario(
    datos: UsuarioCrearEntrada,
    _usuario: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> UsuarioSalida:
    tiene_acceso = bool(datos.tiene_acceso)
    usuario_acceso: str | None = None
    correo_normalizado: str | None = None
    clave_hash: str | None = None

    if tiene_acceso:
        if not datos.clave:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La contraseña es obligatoria al dar acceso al sistema.",
            )
        usuario_acceso = " ".join((datos.usuario or datos.nombre).split())
        from sqlalchemy import func as sqla_func

        dup_usr = (
            bd.query(Usuario)
            .filter(sqla_func.lower(Usuario.usuario) == usuario_acceso.lower())
            .first()
        )
        if dup_usr is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un usuario de acceso con el nombre '{usuario_acceso}'. Elige uno distinto.",
            )
        if datos.correo:
            correo_normalizado = str(datos.correo).strip().lower()
            existente = bd.query(Usuario).filter(Usuario.correo == correo_normalizado).first()
            if existente is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Ya existe un usuario registrado con el correo '{correo_normalizado}'.",
                )
        clave_hash = generar_hash_clave(datos.clave)

    if datos.sucursal_id is not None:
        sucursal = bd.query(Sucursal).filter(Sucursal.id == datos.sucursal_id).first()
        if sucursal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La sucursal indicada no existe.",
            )

    nuevo = Usuario(
        nombre=datos.nombre,
        usuario=usuario_acceso,
        correo=correo_normalizado,
        clave_hash=clave_hash,
        rol=datos.rol.value,
        modalidad=datos.modalidad.value,
        telefono=datos.telefono.strip(),
        cedula=datos.cedula.strip(),
        tiene_acceso=tiene_acceso,
        sucursal_id=datos.sucursal_id,
        cargo=datos.cargo.strip(),
        salario_base_usd=datos.salario_base_usd,
        bono_alimentacion_usd=datos.bono_alimentacion_usd,
        bonos_fijos_usd=datos.bonos_fijos_usd,
        activo=True,
    )
    bd.add(nuevo)
    bd.commit()
    bd.refresh(nuevo)

    usuario_completo = (
        bd.query(Usuario)
        .options(joinedload(Usuario.sucursal))
        .filter(Usuario.id == nuevo.id)
        .first()
    )
    return UsuarioSalida.model_validate(usuario_completo)


@enrutador.put("/usuarios/{usuario_id}", response_model=UsuarioSalida)
def actualizar_usuario(
    usuario_id: int,
    datos: UsuarioActualizarEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> UsuarioSalida:
    usuario = (
        bd.query(Usuario)
        .options(joinedload(Usuario.sucursal))
        .filter(Usuario.id == usuario_id)
        .first()
    )
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Colaborador no encontrado.",
        )

    if usuario.id == usuario_actual.id and not datos.tiene_acceso:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes quitar el acceso al sistema a tu propia cuenta activa.",
        )

    if datos.sucursal_id is not None:
        sucursal = bd.query(Sucursal).filter(Sucursal.id == datos.sucursal_id).first()
        if sucursal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La sucursal indicada no existe.",
            )

    usuario.nombre = datos.nombre
    usuario.rol = datos.rol.value
    usuario.modalidad = datos.modalidad.value
    usuario.telefono = datos.telefono.strip()
    usuario.cedula = datos.cedula.strip()
    usuario.sucursal_id = datos.sucursal_id
    usuario.tiene_acceso = datos.tiene_acceso

    if datos.tiene_acceso:
        from sqlalchemy import func as sqla_func

        usuario_acceso = " ".join((datos.usuario or datos.nombre).split())
        dup_usr = (
            bd.query(Usuario)
            .filter(sqla_func.lower(Usuario.usuario) == usuario_acceso.lower(), Usuario.id != usuario.id)
            .first()
        )
        if dup_usr is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe otro usuario de acceso con el nombre '{usuario_acceso}'.",
            )
        usuario.usuario = usuario_acceso

        if datos.correo:
            correo_norm = str(datos.correo).strip().lower()
            duplicado = (
                bd.query(Usuario)
                .filter(Usuario.correo == correo_norm, Usuario.id != usuario.id)
                .first()
            )
            if duplicado is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Ya existe otro usuario con el correo '{correo_norm}'.",
                )
            usuario.correo = correo_norm
        else:
            usuario.correo = None

        if datos.clave:
            usuario.clave_hash = generar_hash_clave(datos.clave)
        elif not usuario.clave_hash:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes asignar una contraseña inicial (mín. 6 caracteres) al habilitar el acceso por primera vez.",
            )
    else:
        usuario.usuario = None
        usuario.correo = None
        usuario.clave_hash = None

    bd.commit()
    bd.refresh(usuario)
    usuario_actualizado = (
        bd.query(Usuario)
        .options(joinedload(Usuario.sucursal))
        .filter(Usuario.id == usuario.id)
        .first()
    )
    return UsuarioSalida.model_validate(usuario_actualizado)


@enrutador.patch("/usuarios/{usuario_id}/estado", response_model=UsuarioSalida)
def cambiar_estado_usuario(
    usuario_id: int,
    datos: UsuarioEstadoEntrada,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> UsuarioSalida:
    usuario = (
        bd.query(Usuario)
        .options(joinedload(Usuario.sucursal))
        .filter(Usuario.id == usuario_id)
        .first()
    )
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado.",
        )

    if usuario.id == usuario_actual.id and not datos.activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes desactivar tu propia cuenta mientras tienes sesión activa.",
        )

    usuario.activo = datos.activo
    usuario.motivo_estado = datos.motivo
    bd.commit()
    bd.refresh(usuario)
    return UsuarioSalida.model_validate(usuario)


@enrutador.post("/usuarios/{usuario_id}/restablecer-clave")
def restablecer_clave_usuario(
    usuario_id: int,
    payload: dict | None = None,
    _usuario_actual: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> dict[str, object]:
    """Genera una contraseña temporal compartible para un usuario con acceso al sistema."""
    import secrets
    import string

    usuario = (
        bd.query(Usuario)
        .options(joinedload(Usuario.sucursal))
        .filter(Usuario.id == usuario_id)
        .first()
    )
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado.",
        )
    if not getattr(usuario, "tiene_acceso", True) or not usuario.correo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este colaborador no tiene acceso al sistema habilitado. Habilita su acceso y correo primero.",
        )

    clave_manual = (payload or {}).get("nueva_clave") if isinstance(payload, dict) else None
    if clave_manual and isinstance(clave_manual, str) and len(clave_manual.strip()) >= 6:
        clave_temporal = clave_manual.strip()
    else:
        alfabeto = string.ascii_uppercase + string.digits
        sufijo = "".join(secrets.choice(alfabeto) for _ in range(5))
        clave_temporal = f"Alfa-{sufijo}!"

    usuario.clave_hash = generar_hash_clave(clave_temporal)
    usuario.debe_cambiar_clave = True
    usuario.cuenta_bloqueada = False
    usuario.intentos_fallidos = 0
    usuario.fecha_bloqueo = None
    bd.commit()

    return {
        "usuario_id": usuario.id,
        "nombre": usuario.nombre,
        "usuario": usuario.usuario or usuario.nombre,
        "correo": usuario.correo,
        "rol": usuario.rol,
        "telefono": usuario.telefono or "",
        "clave_temporal": clave_temporal,
        "debe_cambiar_clave": True,
        "url_app": "https://alfa-admin-web.vercel.app",
    }


@enrutador.post("/personal/{usuario_id}/desbloquear")
@enrutador.post("/usuarios/{usuario_id}/desbloquear")
def desbloquear_acceso_usuario(
    usuario_id: int,
    payload: dict | None = None,
    usuario_actual: Usuario = Depends(requerir_roles(*ROLES_ADMINISTRATIVOS)),
    bd: Session = Depends(obtener_bd),
) -> dict:
    """Desbloquea una cuenta bloqueada tras 5 intentos fallidos y opcionalmente asigna clave temporal. Solo ADMIN."""
    import json
    from app.modelos_admin import AuditLog

    usuario = bd.query(Usuario).filter(Usuario.id == usuario_id).first()
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")

    usuario.cuenta_bloqueada = False
    usuario.intentos_fallidos = 0
    usuario.fecha_bloqueo = None

    clave_asignada: str | None = None
    nueva_clave = (payload or {}).get("nueva_clave_temporal") if isinstance(payload, dict) else None
    if not nueva_clave and isinstance(payload, dict):
        nueva_clave = payload.get("nueva_clave")
    if isinstance(nueva_clave, str) and len(nueva_clave.strip()) >= 6:
        clave_asignada = nueva_clave.strip()
        usuario.clave_hash = generar_hash_clave(clave_asignada)
        usuario.debe_cambiar_clave = True

    bd.add(
        AuditLog(
            usuario_id=usuario_actual.id,
            usuario_nombre=usuario_actual.nombre,
            modulo="SEGURIDAD",
            accion="DESBLOQUEO_ACCESO",
            entidad_id=str(usuario.id),
            datos_anteriores_json=json.dumps({"cuenta_bloqueada": True}, ensure_ascii=False),
            datos_nuevos_json=json.dumps(
                {
                    "cuenta_bloqueada": False,
                    "usuario_desbloqueado": usuario.usuario or usuario.nombre,
                    "clave_temporal_asignada": bool(clave_asignada),
                },
                ensure_ascii=False,
            ),
        )
    )
    bd.commit()

    return {
        "usuario_id": usuario.id,
        "nombre": usuario.nombre,
        "usuario": usuario.usuario or usuario.nombre,
        "cuenta_bloqueada": False,
        "intentos_fallidos": 0,
        "clave_temporal": clave_asignada,
        "mensaje": f"Acceso desbloqueado correctamente para {usuario.nombre}.",
    }
