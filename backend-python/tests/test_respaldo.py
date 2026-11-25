from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.base_datos import Base, obtener_bd
from app.main import app
from app.modelos import RolUsuario, Usuario
from app.modelos_admin import AuditLog
from app.seguridad import crear_token_acceso, generar_hash_clave
from app.semilla import ejecutar_semilla
from app.semilla_contabilidad import ejecutar_semilla_contabilidad
from app.semilla_finanzas import ejecutar_semilla_finanzas


@pytest.fixture()
def entorno():
    motor = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=motor)
    Sesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    bd = Sesion()
    ejecutar_semilla(bd)
    ejecutar_semilla_finanzas(bd)
    ejecutar_semilla_contabilidad(bd)

    # Crear usuarios de prueba para ADMIN, DIRECTOR y ENCARGADO_TIENDA
    usuarios_prueba = [
        Usuario(
            nombre="Admin Backup",
            usuario="admin_backup",
            correo="admin_backup@alfa.test",
            clave_hash=generar_hash_clave("Clave123!"),
            rol=RolUsuario.ADMINISTRACION.value,
            tiene_acceso=True,
            activo=True,
        ),
        Usuario(
            nombre="Director Backup",
            usuario="director_backup",
            correo="director_backup@alfa.test",
            clave_hash=generar_hash_clave("Clave123!"),
            rol=RolUsuario.DIRECTOR.value,
            tiene_acceso=True,
            activo=True,
        ),
        Usuario(
            nombre="Encargado Backup",
            usuario="encargado_backup",
            correo="encargado_backup@alfa.test",
            clave_hash=generar_hash_clave("Clave123!"),
            rol=RolUsuario.ENCARGADO_TIENDA.value,
            tiene_acceso=True,
            activo=True,
        ),
    ]
    bd.add_all(usuarios_prueba)
    bd.commit()
    for u in usuarios_prueba:
        bd.refresh(u)

    tokens = {
        "ADMIN": crear_token_acceso(usuarios_prueba[0]),
        "DIRECTOR": crear_token_acceso(usuarios_prueba[1]),
        "ENCARGADO": crear_token_acceso(usuarios_prueba[2]),
    }
    bd.close()

    def _override_bd():
        s = Sesion()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[obtener_bd] = _override_bd
    client = TestClient(app)
    yield client, Sesion, tokens
    app.dependency_overrides.clear()


def test_respaldo_solo_admin_y_contenido_zip_valido(entorno):
    client, Sesion, tokens = entorno

    # 1. DIRECTOR y ENCARGADO reciben 403 Forbidden en ambos endpoints
    for rol_no_admin in ("DIRECTOR", "ENCARGADO"):
        headers = {"Authorization": f"Bearer {tokens[rol_no_admin]}"}
        r_desc = client.get("/api/admin/respaldo/descargar", headers=headers)
        assert r_desc.status_code == 403, f"{rol_no_admin} debe recibir 403 al descargar"

        r_hist = client.get("/api/admin/respaldo/historial", headers=headers)
        assert r_hist.status_code == 403, f"{rol_no_admin} debe recibir 403 en historial"

    # 2. ADMIN consulta historial inicial (vacío)
    headers_admin = {"Authorization": f"Bearer {tokens['ADMIN']}"}
    r_hist_ini = client.get("/api/admin/respaldo/historial", headers=headers_admin)
    assert r_hist_ini.status_code == 200
    assert r_hist_ini.json()["ultimo_respaldo"] is None
    assert r_hist_ini.json()["historial"] == []

    # 3. ADMIN descarga respaldo completo (.zip)
    r_zip = client.get("/api/admin/respaldo/descargar", headers=headers_admin)
    assert r_zip.status_code == 200
    assert r_zip.headers["content-type"].startswith("application/zip")
    cd = r_zip.headers.get("content-disposition", "")
    assert "attachment; filename=\"respaldo_alfa_" in cd
    assert cd.endswith(".zip\"")

    # 4. Validar estructura interna del ZIP
    with zipfile.ZipFile(io.BytesIO(r_zip.content), "r") as zf:
        nombres = set(zf.namelist())
        assert "backup_completo.json" in nombres
        assert "resumen_legible_alfa.xlsx" in nombres

        # Validar JSON
        datos_json = json.loads(zf.read("backup_completo.json").decode("utf-8"))
        assert "metadatos" in datos_json
        assert "tablas" in datos_json
        meta = datos_json["metadatos"]
        assert meta["usuario"] == "Admin Backup"
        assert meta["total_tablas"] >= 15
        assert isinstance(meta["conteo_por_tabla"], dict)
        assert "usuarios" in datos_json["tablas"]
        assert "sucursales" in datos_json["tablas"]
        assert "instrumentos_financieros" in datos_json["tablas"]

        # Validar Excel legible
        wb = load_workbook(io.BytesIO(zf.read("resumen_legible_alfa.xlsx")))
        hojas_esperadas = {
            "Saldos Cajas y Bancos",
            "Inventario Equipos",
            "Inventario Componentes",
            "Ventas",
            "CxC y Cashea",
            "CxP y Préstamos",
            "Personal",
        }
        assert hojas_esperadas.issubset(set(wb.sheetnames))

        # Verificar que Personal NO exponga clave_hash
        encabezados_personal = [celda.value for celda in wb["Personal"][1]]
        assert "clave_hash" not in encabezados_personal
        assert "Nombre" in encabezados_personal
        assert wb["Personal"].max_row >= 4  # cabecera + usuarios

    # 5. Validar registro en audit_logs y endpoint /historial
    r_hist_fin = client.get("/api/admin/respaldo/historial", headers=headers_admin)
    assert r_hist_fin.status_code == 200
    body_hist = r_hist_fin.json()
    assert body_hist["ultimo_respaldo"] is not None
    assert body_hist["ultimo_respaldo"]["usuario_nombre"] == "Admin Backup"
    assert body_hist["ultimo_respaldo"]["tamano_bytes"] == len(r_zip.content)
    assert len(body_hist["historial"]) == 1

    bd = Sesion()
    logs = bd.query(AuditLog).filter(AuditLog.accion == "DESCARGA_RESPALDO").all()
    assert len(logs) == 1
    assert logs[0].modulo == "RESPALDO"
    bd.close()
