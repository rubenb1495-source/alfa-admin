from __future__ import annotations

from sqlalchemy.orm import Session

from app.modelos import EstadoSucursal, RolUsuario, Sucursal, Usuario
from app.seguridad import generar_hash_clave


SUCURSALES_INICIALES = [
    {
        "nombre": "Almacén Guaparo Norte",
        "direccion": "Guaparo Norte, Valencia, Edo. Carabobo",
        "estado": EstadoSucursal.ACTIVA.value,
        "fecha_cierre": None,
    },
    {
        "nombre": "Local T38",
        "direccion": "CC Free Market, Local T38, Naguanagua, Valencia",
        "estado": EstadoSucursal.ACTIVA.value,
        "fecha_cierre": None,
    },
    {
        "nombre": "Local V30-V31",
        "direccion": "CC Free Market, Locales V30-V31, Naguanagua, Valencia",
        "estado": EstadoSucursal.ACTIVA.value,
        "fecha_cierre": None,
    },
]


def ejecutar_semilla(bd: Session) -> None:
    """Crea de forma idempotente las 3 sucursales/almacenes de Alfa Importaciones y el usuario DIRECCION inicial."""
    for datos in SUCURSALES_INICIALES:
        existente = bd.query(Sucursal).filter(Sucursal.nombre == datos["nombre"]).first()
        if existente is None:
            bd.add(Sucursal(**datos))
    bd.flush()

    sucursal_central = bd.query(Sucursal).filter(Sucursal.nombre == "Local T38").first()

    correo_admin = "direccion@alfaimportaciones.com"
    admin_existente = bd.query(Usuario).filter(Usuario.correo == correo_admin).first()
    if admin_existente is None:
        bd.add(
            Usuario(
                nombre="Dirección General Alfa",
                correo=correo_admin,
                clave_hash=generar_hash_clave("Alfa2026!"),
                rol=RolUsuario.DIRECCION.value,
                sucursal_id=sucursal_central.id if sucursal_central else None,
                activo=True,
            )
        )

    bd.commit()
