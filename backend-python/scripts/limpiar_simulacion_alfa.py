#!/usr/bin/env python3
"""
Limpieza segura de la Simulación General de Alfa (`[SIM-ALFA]`).

Elimina ÚNICAMENTE los registros etiquetados con `[SIM-ALFA]` sin tocar datos
reales de producción.

Uso:
  # Contra la API en producción (Vercel / Neon):
  python scripts/limpiar_simulacion_alfa.py --api-url https://alfa-admin-api.vercel.app

  # Contra la base de datos local (POSTGRES_URL / DATABASE_URL / SQLite):
  python scripts/limpiar_simulacion_alfa.py --local
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def limpiar_remoto(api_url: str, correo: str, clave: str) -> None:
    import httpx

    base = api_url.rstrip("/")
    with httpx.Client(base_url=base, timeout=60.0) as client:
        r_login = client.post("/api/auth/login", json={"correo": correo, "clave": clave})
        if r_login.status_code != 200:
            raise SystemExit(f"Error de autenticación ({r_login.status_code}): {r_login.text}")
        data_login = r_login.json()
        token = data_login.get("token") or data_login.get("access_token") or data_login["token_acceso"]
        headers = {"Authorization": f"Bearer {token}"}

        r = client.post(
            "/api/admin/limpiar-simulacion",
            headers=headers,
            json={"confirmacion": "ELIMINAR-SIM-ALFA", "prefijo": "[SIM-ALFA]"},
        )
        if r.status_code != 200:
            raise SystemExit(f"Error al limpiar simulación ({r.status_code}): {r.text}")
        res = r.json()
        print("============================================================")
        print("  LIMPIEZA REMOTA [SIM-ALFA] COMPLETADA")
        print("============================================================")
        print(f"API: {base}")
        print(f"Total registros eliminados: {res['total_registros_eliminados']}")
        for tabla, cant in sorted(res.get("detalle", {}).items()):
            print(f"  - {tabla}: {cant}")


def limpiar_local() -> None:
    from app.base_datos import SesionLocal
    from app.servicios.limpieza_simulacion import limpiar_datos_simulacion

    bd = SesionLocal()
    try:
        res = limpiar_datos_simulacion(bd, prefijo="[SIM-ALFA]")
    finally:
        bd.close()

    print("============================================================")
    print("  LIMPIEZA LOCAL [SIM-ALFA] COMPLETADA")
    print("============================================================")
    print(f"Total registros eliminados: {res['total_registros_eliminados']}")
    for tabla, cant in sorted(res.get("detalle", {}).items()):
        print(f"  - {tabla}: {cant}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Elimina únicamente los datos [SIM-ALFA].")
    parser.add_argument(
        "--api-url",
        default=os.getenv("ALFA_API_URL", "https://alfa-admin-api.vercel.app"),
        help="URL base de la API de Alfa (default: https://alfa-admin-api.vercel.app)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Ejecuta la limpieza directamente sobre la BD configurada en el backend local.",
    )
    parser.add_argument(
        "--correo",
        default=os.getenv("ALFA_ADMIN_EMAIL", "direccion@alfaimportaciones.com"),
        help="Correo de administrador para limpieza remota.",
    )
    parser.add_argument(
        "--clave",
        default=os.getenv("ALFA_ADMIN_PASSWORD", "Alfa2026!"),
        help="Clave de administrador para limpieza remota.",
    )
    args = parser.parse_args()

    if args.local:
        limpiar_local()
    else:
        limpiar_remoto(args.api_url, args.correo, args.clave)


if __name__ == "__main__":
    main()
