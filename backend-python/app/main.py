from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.base_datos import Base, SesionLocal, motor
from app.configuracion import configuracion
from app import modelos_admin as _modelos_admin  # noqa: F401
from app import modelos_contabilidad as _modelos_contabilidad  # noqa: F401
from app import modelos_finanzas as _modelos_finanzas  # noqa: F401
from app import modelos_logistica as _modelos_logistica  # noqa: F401
from app import modelos_operaciones as _modelos_operaciones  # noqa: F401
from app import modelos_taller as _modelos_taller  # noqa: F401
from app.rutas import admin_importacion, administracion, alertas, autenticacion, cashea_finanzas, catalogo, cierre_diario, contabilidad, direccion, finanzas, logistica, logistica_avanzada, operaciones, recepcion_tecnica, taller, tasas, tesoreria, usuarios, ventas
from app.semilla import ejecutar_semilla
from app.semilla_contabilidad import ejecutar_semilla_contabilidad
from app.semilla_finanzas import ejecutar_semilla_finanzas


def asegurar_columnas_compatibles() -> None:
    """Agrega columnas nuevas de forma idempotente en PostgreSQL y SQLite sin perder datos."""
    inspector = inspect(motor)
    if inspector.has_table("ventas_detalle"):
        columnas = {col["name"] for col in inspector.get_columns("ventas_detalle")}
        if "descripcion_servicio" not in columnas:
            with motor.begin() as conexion:
                conexion.execute(
                    text(
                        "ALTER TABLE ventas_detalle "
                        "ADD COLUMN descripcion_servicio TEXT NOT NULL DEFAULT ''"
                    )
                )
    if inspector.has_table("terceros"):
        columnas_ter = {col["name"] for col in inspector.get_columns("terceros")}
        nuevas_terceros = [
            ("tipo_persona", "VARCHAR(20) NOT NULL DEFAULT 'NATURAL'"),
            ("tipo_documento", "VARCHAR(5) NOT NULL DEFAULT ''"),
            ("documento", "VARCHAR(40) NOT NULL DEFAULT ''"),
            ("direccion", "VARCHAR(255) NOT NULL DEFAULT ''"),
            ("saldo_favor_usd", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
        ]
        for nombre_col, ddl_col in nuevas_terceros:
            if nombre_col not in columnas_ter:
                with motor.begin() as conexion:
                    conexion.execute(
                        text(f"ALTER TABLE terceros ADD COLUMN {nombre_col} {ddl_col}")
                    )
    if inspector.has_table("ventas"):
        columnas_vta = {col["name"] for col in inspector.get_columns("ventas")}
        if "datos_entrega_json" not in columnas_vta:
            with motor.begin() as conexion:
                conexion.execute(
                    text(
                        "ALTER TABLE ventas "
                        "ADD COLUMN datos_entrega_json TEXT NOT NULL DEFAULT ''"
                    )
                )
        if "origen_venta" not in columnas_vta:
            with motor.begin() as conexion:
                conexion.execute(
                    text(
                        "ALTER TABLE ventas "
                        "ADD COLUMN origen_venta VARCHAR(20) NOT NULL DEFAULT 'PASILLO'"
                    )
                )
        if "estado_comision" not in columnas_vta:
            with motor.begin() as conexion:
                conexion.execute(
                    text(
                        "ALTER TABLE ventas "
                        "ADD COLUMN estado_comision VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE'"
                    )
                )
        if "liquidacion_id" not in columnas_vta:
            with motor.begin() as conexion:
                conexion.execute(
                    text(
                        "ALTER TABLE ventas "
                        "ADD COLUMN liquidacion_id INTEGER NULL"
                    )
                )
        nuevas_cashea_vta = [
            ("es_cashea", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("cashea_inicial_usd", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("cashea_financiado_usd", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("cashea_comision_venta_usd", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("cashea_comision_financiado_usd", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("cashea_iva_usd", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("cashea_islr_usd", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("cashea_total_cargos_usd", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("cashea_neto_por_cobrar_usd", "NUMERIC(14, 2) NOT NULL DEFAULT 0"),
            ("tasa_bcv_aplicada", "NUMERIC(14, 4) NOT NULL DEFAULT 0"),
            ("tasa_usdt_aplicada", "NUMERIC(14, 4) NOT NULL DEFAULT 0"),
        ]
        for nombre_col, ddl_col in nuevas_cashea_vta:
            if nombre_col not in columnas_vta:
                with motor.begin() as conexion:
                    conexion.execute(
                        text(f"ALTER TABLE ventas ADD COLUMN {nombre_col} {ddl_col}")
                    )
    if inspector.has_table("tasas_diarias"):
        columnas_tasas = {col["name"] for col in inspector.get_columns("tasas_diarias")}
        if "recargo_confirmado" not in columnas_tasas:
            with motor.begin() as conexion:
                conexion.execute(
                    text(
                        "ALTER TABLE tasas_diarias "
                        "ADD COLUMN recargo_confirmado BOOLEAN NOT NULL DEFAULT FALSE"
                    )
                )
        if "fuente_tasa" not in columnas_tasas:
            with motor.begin() as conexion:
                conexion.execute(
                    text(
                        "ALTER TABLE tasas_diarias "
                        "ADD COLUMN fuente_tasa VARCHAR(30) NOT NULL DEFAULT 'MANUAL'"
                    )
                )
    if inspector.has_table("usuarios"):
        columnas_usr = {col["name"] for col in inspector.get_columns("usuarios")}
        nuevas_usuarios = [
            ("modalidad", "VARCHAR(20) NOT NULL DEFAULT 'PRESENCIAL'"),
            ("telefono", "VARCHAR(40) NOT NULL DEFAULT ''"),
            ("cedula", "VARCHAR(40) NOT NULL DEFAULT ''"),
            ("tiene_acceso", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("debe_cambiar_clave", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("usuario", "VARCHAR(120) NULL"),
            ("intentos_fallidos", "INTEGER NOT NULL DEFAULT 0"),
            ("cuenta_bloqueada", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("fecha_bloqueo", "TIMESTAMP NULL"),
            ("fecha_ingreso", "DATE NULL"),
            ("cargo", "VARCHAR(120) NOT NULL DEFAULT ''"),
            ("salario_base_usd", "NUMERIC(12, 2) NOT NULL DEFAULT 0"),
            ("bono_alimentacion_usd", "NUMERIC(12, 2) NOT NULL DEFAULT 0"),
            ("bonos_fijos_usd", "NUMERIC(12, 2) NOT NULL DEFAULT 0"),
            ("tipo_contrato", "VARCHAR(40) NOT NULL DEFAULT ''"),
            ("cuenta_bancaria_pago", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ]
        for nombre_col, ddl_col in nuevas_usuarios:
            if nombre_col not in columnas_usr:
                with motor.begin() as conexion:
                    conexion.execute(
                        text(f"ALTER TABLE usuarios ADD COLUMN {nombre_col} {ddl_col}")
                    )
        if motor.dialect.name == "postgresql":
            with motor.begin() as conexion:
                conexion.execute(
                    text("ALTER TABLE usuarios ALTER COLUMN correo DROP NOT NULL")
                )
                conexion.execute(
                    text("ALTER TABLE usuarios ALTER COLUMN clave_hash DROP NOT NULL")
                )
    if inspector.has_table("pagos"):
        columnas_pagos = {col["name"] for col in inspector.get_columns("pagos")}
        nuevas_pagos = [
            ("categoria", "VARCHAR(80) NOT NULL DEFAULT ''"),
            ("origen_tipo", "VARCHAR(40) NOT NULL DEFAULT ''"),
            ("origen_id", "INTEGER NULL"),
        ]
        for nombre_col, ddl_col in nuevas_pagos:
            if nombre_col not in columnas_pagos:
                with motor.begin() as conexion:
                    conexion.execute(
                        text(f"ALTER TABLE pagos ADD COLUMN {nombre_col} {ddl_col}")
                    )
    if inspector.has_table("liquidaciones_comisiones"):
        columnas_liq = {col["name"] for col in inspector.get_columns("liquidaciones_comisiones")}
        nuevas_liq = [
            ("instrumento_pago_id", "INTEGER NULL"),
            ("movimiento_financiero_id", "INTEGER NULL"),
        ]
        for nombre_col, ddl_col in nuevas_liq:
            if nombre_col not in columnas_liq:
                with motor.begin() as conexion:
                    conexion.execute(
                        text(f"ALTER TABLE liquidaciones_comisiones ADD COLUMN {nombre_col} {ddl_col}")
                    )
    if inspector.has_table("equipos"):
        columnas_eq = {col["name"] for col in inspector.get_columns("equipos")}
        nuevas_eq = [
            ("es_consignacion", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("consignante_nombre", "VARCHAR(160) NOT NULL DEFAULT ''"),
            ("costo_acordado_usd", "NUMERIC(12, 2) NULL"),
        ]
        for nombre_col, ddl_col in nuevas_eq:
            if nombre_col not in columnas_eq:
                with motor.begin() as conexion:
                    conexion.execute(
                        text(f"ALTER TABLE equipos ADD COLUMN {nombre_col} {ddl_col}")
                    )
        # Normalización segura de estados en equipos existentes
        with motor.begin() as conexion:
            conexion.execute(
                text(
                    "UPDATE equipos SET estado = 'PENDIENTE_REVISION' "
                    "WHERE estado IS NULL OR TRIM(estado) = ''"
                )
            )
            conexion.execute(
                text(
                    "UPDATE equipos SET estado = 'LISTO' "
                    "WHERE UPPER(TRIM(estado)) = 'DISPONIBLE'"
                )
            )
    if inspector.has_table("compras"):
        columnas_cmp = {col["name"] for col in inspector.get_columns("compras")}
        nuevas_cmp = [
            ("proveedor_nombre", "VARCHAR(160) NOT NULL DEFAULT ''"),
            ("tracking_guia", "VARCHAR(120) NOT NULL DEFAULT ''"),
            ("fecha_vencimiento", "DATE NULL"),
        ]
        for nombre_col, ddl_col in nuevas_cmp:
            if nombre_col not in columnas_cmp:
                with motor.begin() as conexion:
                    conexion.execute(
                        text(f"ALTER TABLE compras ADD COLUMN {nombre_col} {ddl_col}")
                    )
    if inspector.has_table("catalogo_articulos"):
        columnas_cat = {col["name"] for col in inspector.get_columns("catalogo_articulos")}
        if "stock_minimo" not in columnas_cat:
            with motor.begin() as conexion:
                conexion.execute(
                    text(
                        "ALTER TABLE catalogo_articulos "
                        "ADD COLUMN stock_minimo INTEGER NOT NULL DEFAULT 2"
                    )
                )
    if inspector.has_table("traslados_detalle"):
        columnas_td = {col["name"] for col in inspector.get_columns("traslados_detalle")}
        nuevas_td = [
            ("verificado", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("cantidad_recibida", "INTEGER NULL"),
            ("observacion_recepcion", "VARCHAR(255) NOT NULL DEFAULT ''"),
        ]
        for nombre_col, ddl_col in nuevas_td:
            if nombre_col not in columnas_td:
                with motor.begin() as conexion:
                    conexion.execute(
                        text(f"ALTER TABLE traslados_detalle ADD COLUMN {nombre_col} {ddl_col}")
                    )


@asynccontextmanager
async def ciclo_vida(_app: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=motor)
    asegurar_columnas_compatibles()
    bd = SesionLocal()
    try:
        ejecutar_semilla(bd)
        ejecutar_semilla_finanzas(bd)
        ejecutar_semilla_contabilidad(bd)
        # Migración segura: asignar usuario = nombre a usuarios existentes con acceso sin usuario
        from app.modelos import Usuario

        usrs_sin_usuario = (
            bd.query(Usuario)
            .filter(
                Usuario.tiene_acceso.is_(True),
                (Usuario.usuario.is_(None)) | (Usuario.usuario == ""),
            )
            .all()
        )
        if usrs_sin_usuario:
            existentes_lower = {
                (u.usuario or "").strip().lower()
                for u in bd.query(Usuario.usuario).filter(Usuario.usuario.isnot(None)).all()
                if u.usuario
            }
            for u in usrs_sin_usuario:
                base_u = " ".join((u.nombre or f"usuario_{u.id}").split())
                candidato = base_u
                if candidato.lower() in existentes_lower:
                    candidato = f"{base_u} {u.id}"
                u.usuario = candidato
                existentes_lower.add(candidato.lower())
            bd.commit()
    finally:
        bd.close()
    yield


app = FastAPI(
    title=configuracion.NOMBRE_APP,
    version="1.0.0",
    lifespan=ciclo_vida,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=configuracion.lista_origenes_cors,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/salud", tags=["Sistema"])
def verificar_salud() -> dict[str, str]:
    return {"estado": "activo", "servicio": "Alfa Importaciones API"}


app.include_router(autenticacion.enrutador)
app.include_router(usuarios.enrutador)
app.include_router(tasas.enrutador)
app.include_router(catalogo.enrutador)
app.include_router(logistica.enrutador)
app.include_router(logistica_avanzada.enrutador)
app.include_router(taller.enrutador)
app.include_router(recepcion_tecnica.enrutador)
app.include_router(ventas.enrutador)
app.include_router(finanzas.enrutador)
app.include_router(cashea_finanzas.enrutador)
app.include_router(finanzas.enrutador_comisiones)
app.include_router(tesoreria.enrutador)
app.include_router(direccion.enrutador)
app.include_router(alertas.enrutador)
app.include_router(administracion.enrutador)
app.include_router(admin_importacion.enrutador)
app.include_router(contabilidad.enrutador)
app.include_router(cierre_diario.enrutador)
app.include_router(operaciones.enrutador)
