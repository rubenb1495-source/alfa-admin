from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader


MARCA_ALFA: dict[str, Any] = {
    "nombre_comercial": "Alfa Digital Store",
    "nombre_corto": "Alfa",
    "razon_social": "ALFA IMPORTACIONES, C.A.",
    "rif": "J-50793794-1",
    "direccion_principal": "CC Free Market, Local T38, Naguanagua, Valencia",
    "telefono_principal": "",
    "url_app": "https://alfa-admin-web.vercel.app",
    "sucursales": [
        "Almacén Guaparo Norte",
        "Local T38",
        "Local V30-V31",
    ],
    "colores": {
        "primario": "#003566",
        "secundario": "#001D3D",
        "tinta": "#000814",
        "superficie": "#EDF3FA",
        "fondo": "#F7F9FC",
    },
    "politica_garantia": (
        "POLÍTICAS DE GARANTÍA: Todos los equipos cuentan con garantía por defectos de fábrica "
        "según el periodo indicado en esta nota. La garantía no cubre daños físicos, humedad, "
        "sobrecargas eléctricas, manipulación por terceros ni sellos de seguridad removidos. "
        "Es indispensable presentar esta nota de entrega para cualquier revisión técnica."
    ),
}

DIRECTORIO_ASSETS = Path(__file__).resolve().parents[2] / "assets"
RUTA_LOGO_ALFA = DIRECTORIO_ASSETS / "logo-alfa.png"
RUTA_ISOTIPO_ALFA = DIRECTORIO_ASSETS / "isotipo-alfa.png"


def dibujar_encabezado_y_marca_agua_alfa(
    c: Any,
    titulo_documento: str,
    subtitulo: str = "",
    ancho: float = 612.0,
    alto: float = 792.0,
) -> float:
    """Dibuja marca de agua centrada (~7% opacidad) y encabezado oficial Alfa; retorna Y inicial."""
    # Marca de agua centrada con opacidad sutil (~7%)
    if RUTA_ISOTIPO_ALFA.exists():
        c.saveState()
        try:
            c.setFillAlpha(0.07)
            c.setStrokeAlpha(0.07)
        except Exception:
            pass
        tam_wm = 260
        c.drawImage(
            ImageReader(str(RUTA_ISOTIPO_ALFA)),
            (ancho - tam_wm) / 2,
            (alto - tam_wm) / 2,
            width=tam_wm,
            height=tam_wm,
            mask="auto",
            preserveAspectRatio=True,
        )
        c.restoreState()

    # Franja superior azul Alfa
    c.setFillColor(HexColor(MARCA_ALFA["colores"]["primario"]))
    c.rect(0, alto - 10, ancho, 10, fill=1, stroke=0)

    # Logo oficial izquierdo
    if RUTA_LOGO_ALFA.exists():
        c.drawImage(
            ImageReader(str(RUTA_LOGO_ALFA)),
            42,
            alto - 64,
            width=135,
            height=40,
            mask="auto",
            preserveAspectRatio=True,
        )

    # Datos fiscales alineados a la derecha
    c.setFillColor(HexColor(MARCA_ALFA["colores"]["tinta"]))
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(ancho - 42, alto - 34, MARCA_ALFA["razon_social"])
    c.setFont("Helvetica", 8.5)
    c.drawRightString(ancho - 42, alto - 47, f"RIF: {MARCA_ALFA['rif']}")
    c.drawRightString(ancho - 42, alto - 59, MARCA_ALFA["direccion_principal"])

    # Título del documento
    c.setStrokeColor(HexColor(MARCA_ALFA["colores"]["primario"]))
    c.setLineWidth(1.2)
    c.line(42, alto - 74, ancho - 42, alto - 74)

    c.setFillColor(HexColor(MARCA_ALFA["colores"]["primario"]))
    c.setFont("Helvetica-Bold", 13)
    c.drawString(42, alto - 94, titulo_documento)
    if subtitulo:
        c.setFillColor(HexColor("#475569"))
        c.setFont("Helvetica", 9.5)
        c.drawString(42, alto - 109, subtitulo)
        return alto - 128
    return alto - 114
