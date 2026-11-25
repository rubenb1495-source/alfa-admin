from __future__ import annotations

import io
import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.base_datos import obtener_bd
from app.modelos import Usuario
from app.modelos_admin import AuditLog
from app.seguridad import requerir_admin
from app.servicios.respaldo import generar_respaldo_completo_zip


enrutador = APIRouter(prefix="/api/admin/respaldo", tags=["Respaldo de Base de Datos"])


@enrutador.get("/descargar")
def descargar_respaldo_completo(
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> StreamingResponse:
    """Genera y descarga el respaldo completo (.zip) de la base de datos. Exclusivo ADMIN."""
    zip_bytes, nombre_archivo, metadatos = generar_respaldo_completo_zip(bd, usuario_actual)

    tamano_bytes = len(zip_bytes)
    tamano_kb = round(tamano_bytes / 1024.0, 2)

    registro_audit = AuditLog(
        usuario_id=usuario_actual.id,
        usuario_nombre=usuario_actual.nombre,
        rol=usuario_actual.rol,
        modulo="RESPALDO",
        accion="DESCARGA_RESPALDO",
        entidad_id=nombre_archivo,
        datos_anteriores_json="{}",
        datos_nuevos_json=json.dumps(
            {
                "archivo": nombre_archivo,
                "tamano_bytes": tamano_bytes,
                "tamano_kb": tamano_kb,
                "total_tablas": metadatos.get("total_tablas", 0),
                "total_registros": metadatos.get("total_registros", 0),
                "fecha_generacion": metadatos.get("fecha_generacion", ""),
            },
            ensure_ascii=False,
        ),
    )
    bd.add(registro_audit)
    bd.commit()

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre_archivo}"',
            "X-Backup-Filename": nombre_archivo,
            "Access-Control-Expose-Headers": "Content-Disposition, X-Backup-Filename",
        },
    )


@enrutador.get("/historial")
def historial_respaldos(
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    """Devuelve las últimas 10 descargas de respaldo registradas en audit_logs. Exclusivo ADMIN."""
    registros = (
        bd.query(AuditLog)
        .filter(AuditLog.accion == "DESCARGA_RESPALDO")
        .order_by(AuditLog.fecha_hora.desc(), AuditLog.id.desc())
        .limit(10)
        .all()
    )

    historial: list[dict[str, Any]] = []
    for r in registros:
        try:
            datos = json.loads(r.datos_nuevos_json or "{}")
        except json.JSONDecodeError:
            datos = {}
        historial.append(
            {
                "id": r.id,
                "fecha_hora": r.fecha_hora.isoformat() if r.fecha_hora else "",
                "usuario_nombre": r.usuario_nombre,
                "rol": r.rol,
                "archivo": datos.get("archivo") or r.entidad_id,
                "tamano_bytes": datos.get("tamano_bytes", 0),
                "tamano_kb": datos.get("tamano_kb", 0),
                "total_tablas": datos.get("total_tablas", 0),
                "total_registros": datos.get("total_registros", 0),
            }
        )

    return {
        "ultimo_respaldo": historial[0] if historial else None,
        "historial": historial,
    }
