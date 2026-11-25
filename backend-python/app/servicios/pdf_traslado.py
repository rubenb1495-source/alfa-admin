from __future__ import annotations

import io
from datetime import timezone
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.configuracion import configuracion
from app.core.brand import dibujar_encabezado_y_marca_agua_alfa
from app.modelos_logistica import Traslado

AZUL_ALFA = colors.HexColor("#003566")
AZUL_CLARO = colors.HexColor("#EFF6FF")
GRIS_BORDE = colors.HexColor("#CBD5E1")
GRIS_TEXTO = colors.HexColor("#475569")
NEGRO = colors.HexColor("#0F172A")


def _fmt_dt(dt) -> str:
    if dt is None:
        return "-"
    tz = ZoneInfo(configuracion.ZONA_HORARIA)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%d/%m/%Y %I:%M %p")


def generar_pdf_hoja_traslado(traslado: Traslado) -> bytes:
    """Genera la Hoja de Traslado / Guía de Despacho en PDF con branding y marca de agua de Alfa."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    ancho, _alto = letter
    mx = 38
    w = ancho - 2 * mx

    subtitulo = (
        f"Código: {traslado.numero_traslado}  ·  Estado: {traslado.estado.replace('_', ' ')}  ·  "
        f"Despacho: {_fmt_dt(traslado.fecha_envio)}"
    )
    y = dibujar_encabezado_y_marca_agua_alfa(c, "HOJA DE TRASLADO / GUÍA DE DESPACHO", subtitulo)

    # Bloque Origen / Destino
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.setStrokeColor(GRIS_BORDE)
    c.setLineWidth(0.7)
    c.roundRect(mx, y - 52, w, 52, 4, fill=1, stroke=1)

    origen_nom = traslado.origen.nombre if traslado.origen else f"Sucursal #{traslado.origen_id}"
    destino_nom = traslado.destino.nombre if traslado.destino else f"Sucursal #{traslado.destino_id}"
    envia_nom = traslado.enviado_por.nombre if traslado.enviado_por else "-"
    recibe_nom = traslado.recibido_por.nombre if traslado.recibido_por else "Pendiente de recepción"

    c.setFillColor(AZUL_ALFA)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(mx + 8, y - 13, "ORIGEN (DESPACHA)")
    c.drawString(mx + w / 2 + 8, y - 13, "DESTINO (RECIBE)")

    c.setFillColor(NEGRO)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(mx + 8, y - 26, origen_nom[:36])
    c.drawString(mx + w / 2 + 8, y - 26, destino_nom[:36])

    c.setFont("Helvetica", 8)
    c.setFillColor(GRIS_TEXTO)
    c.drawString(mx + 8, y - 38, f"Despachado por: {envia_nom[:34]}")
    c.drawString(mx + w / 2 + 8, y - 38, f"Recibido por: {recibe_nom[:34]}")
    if traslado.fecha_recepcion:
        c.drawString(mx + w / 2 + 8, y - 48, f"Fecha recepción: {_fmt_dt(traslado.fecha_recepcion)}")
    if traslado.nota:
        c.drawString(mx + 8, y - 48, f"Nota: {traslado.nota[:40]}")

    y -= 66

    # Encabezado de tabla detallada
    cols = [
        ("#", 22),
        ("Tipo", 62),
        ("SKU / Descripción", 176),
        ("Serial", 92),
        ("Env.", 34),
        ("Check / Rec.", 64),
        ("Observaciones", w - (22 + 62 + 176 + 92 + 34 + 64)),
    ]

    def _dibujar_header_tabla(yp: float) -> float:
        c.setFillColor(AZUL_ALFA)
        c.rect(mx, yp - 18, w, 18, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 7.8)
        cx = mx
        for titulo_c, cw in cols:
            c.drawString(cx + 4, yp - 12, titulo_c)
            cx += cw
        return yp - 22

    y = _dibujar_header_tabla(y)
    total_equipos = 0
    total_productos = 0

    for idx, d in enumerate(traslado.detalles, start=1):
        if y < 120:
            c.showPage()
            y = dibujar_encabezado_y_marca_agua_alfa(c, "HOJA DE TRASLADO / GUÍA DE DESPACHO (CONT.)", subtitulo)
            y = _dibujar_header_tabla(y)

        es_eq = d.equipo is not None
        if es_eq:
            total_equipos += 1
            tipo_txt = "EQUIPO"
            desc_txt = (d.equipo.modelo or "Equipo")[:34]
            ser_txt = (d.equipo.serial or "-")[:18]
        else:
            total_productos += int(d.cantidad or 0)
            tipo_txt = (d.articulo.tipo if d.articulo else "PRODUCTO")[:11]
            sku_p = d.articulo.sku if d.articulo else ""
            nom_p = d.articulo.descripcion if d.articulo else f"Art #{d.articulo_id}"
            desc_txt = f"{sku_p} · {nom_p}".strip(" ·")[:34]
            ser_txt = "Por cantidad"

        verif_txt = (
            f"[OK] x{d.cantidad_recibida if d.cantidad_recibida is not None else d.cantidad}"
            if d.verificado
            else "[   ] ____"
        )
        obs_txt = (d.observacion_recepcion or "")[:20]

        if idx % 2 == 0:
            c.setFillColor(colors.HexColor("#F8FAFC"))
            c.rect(mx, y - 14, w, 16, fill=1, stroke=0)

        c.setFillColor(NEGRO)
        c.setFont("Helvetica", 7.8)
        vals = [str(idx), tipo_txt, desc_txt, ser_txt, str(d.cantidad), verif_txt, obs_txt]
        cx = mx
        for val, (_, cw) in zip(vals, cols):
            c.drawString(cx + 4, y - 9, val)
            cx += cw
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.setLineWidth(0.4)
        c.line(mx, y - 14, mx + w, y - 14)
        y -= 16

    # Resumen de totales
    y -= 10
    c.setFillColor(AZUL_CLARO)
    c.setStrokeColor(GRIS_BORDE)
    c.roundRect(mx, y - 22, w, 22, 4, fill=1, stroke=1)
    c.setFillColor(AZUL_ALFA)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(
        mx + 10,
        y - 14,
        f"RESUMEN:  {total_equipos} Equipo(s) serializado(s)   ·   {total_productos} Unidad(es) por cantidad   ·   Total líneas: {len(traslado.detalles)}",
    )

    # Bloque de Firmas al pie
    y_firmas = 64
    tercio = w / 3
    c.setStrokeColor(GRIS_TEXTO)
    c.setLineWidth(0.7)
    for i, (etq, sub) in enumerate(
        [
            ("DESPACHADO POR", envia_nom[:26]),
            ("TRANSPORTADO POR", "Nombre / C.I.: ____________"),
            ("RECIBIDO CONFORME (DESTINO)", recibe_nom[:26]),
        ]
    ):
        x0 = mx + i * tercio + 10
        x1 = mx + (i + 1) * tercio - 10
        xc = (x0 + x1) / 2
        c.line(x0, y_firmas + 18, x1, y_firmas + 18)
        c.setFillColor(NEGRO)
        c.setFont("Helvetica-Bold", 7.8)
        c.drawCentredString(xc, y_firmas + 6, etq)
        c.setFillColor(GRIS_TEXTO)
        c.setFont("Helvetica", 7.2)
        c.drawCentredString(xc, y_firmas - 5, sub)

    c.showPage()
    c.save()
    return buf.getvalue()
