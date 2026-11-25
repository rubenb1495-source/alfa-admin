from __future__ import annotations

import io
import json
from datetime import timezone
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.configuracion import configuracion
from app.core.brand import dibujar_encabezado_y_marca_agua_alfa
from app.modelos_taller import OrdenRecepcionTecnica, TipoOrdenRecepcion

AZUL_ALFA = colors.HexColor("#1D4ED8")
AZUL_CLARO = colors.HexColor("#EFF6FF")
AMBAR_BORDE = colors.HexColor("#D97706")
AMBAR_FONDO = colors.HexColor("#FFFBEB")
ROJO_ALERTA = colors.HexColor("#B91C1C")
VERDE_OK = colors.HexColor("#15803D")
GRIS_BORDE = colors.HexColor("#CBD5E1")
GRIS_TEXTO = colors.HexColor("#475569")
NEGRO = colors.HexColor("#0F172A")


def _wrap_text(c: canvas.Canvas, texto: str, font: str, size: int, max_width: float) -> list[str]:
    if not texto:
        return ["-"]
    lineas: list[str] = []
    for parrafo in str(texto).splitlines():
        palabras = parrafo.split()
        if not palabras:
            lineas.append("")
            continue
        actual = palabras[0]
        for pal in palabras[1:]:
            prueba = f"{actual} {pal}"
            if c.stringWidth(prueba, font, size) <= max_width:
                actual = prueba
            else:
                lineas.append(actual)
                actual = pal
        lineas.append(actual)
    return lineas or ["-"]


def _dibujar_parrafo_justificado(
    c: canvas.Canvas,
    texto: str,
    x: float,
    y: float,
    width: float,
    font: str = "Helvetica",
    size: int = 8,
    leading: float = 11.5,
    color=NEGRO,
) -> float:
    c.setFont(font, size)
    c.setFillColor(color)
    lineas = _wrap_text(c, texto, font, size, width)
    for idx, linea in enumerate(lineas):
        es_ultima = idx == len(lineas) - 1
        palabras = linea.split()
        if es_ultima or len(palabras) <= 1:
            c.drawString(x, y, linea)
        else:
            ancho_palabras = sum(c.stringWidth(p, font, size) for p in palabras)
            espacio = (width - ancho_palabras) / (len(palabras) - 1)
            cx = x
            for p in palabras:
                c.drawString(cx, y, p)
                cx += c.stringWidth(p, font, size) + espacio
        y -= leading
    return y


def _dibujar_seccion(c: canvas.Canvas, titulo: str, x: float, y: float, w: float) -> float:
    c.setFillColor(AZUL_CLARO)
    c.setStrokeColor(GRIS_BORDE)
    c.setLineWidth(0.6)
    c.rect(x, y - 16, w, 16, fill=1, stroke=1)
    c.setFillColor(AZUL_ALFA)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(x + 6, y - 11.5, titulo.upper())
    c.setFillColor(NEGRO)
    return y - 28


def generar_pdf_recepcion_tecnica(orden: OrdenRecepcionTecnica) -> bytes:
    """Genera el Comprobante de Recepción (Garantía o Servicio Técnico) con branding y marca de agua de Alfa."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    ancho, alto = letter
    margen_x = 40
    ancho_util = ancho - 2 * margen_x

    es_garantia = orden.tipo_orden == TipoOrdenRecepcion.GARANTIA.value
    titulo_doc = (
        "COMPROBANTE DE RECEPCIÓN DE GARANTÍA"
        if es_garantia
        else "COMPROBANTE DE RECEPCIÓN DE SERVICIO TÉCNICO"
    )

    tz = ZoneInfo(configuracion.ZONA_HORARIA)
    f_rec = orden.fecha_recepcion
    if f_rec.tzinfo is None:
        f_rec = f_rec.replace(tzinfo=timezone.utc)
    f_rec_local = f_rec.astimezone(tz)
    fecha_str = f_rec_local.strftime("%d/%m/%Y %I:%M %p")

    sucursal_nom = orden.sucursal.nombre if orden.sucursal else "Sede Alfa"
    encargado_nom = orden.recibido_por.nombre if orden.recibido_por else "Encargado de Tienda"
    tecnico_nom = orden.tecnico_asignado.nombre if orden.tecnico_asignado else "Por asignar"

    subtitulo = f"Orden N° {orden.codigo}  ·  Sucursal: {sucursal_nom}  ·  Recepción: {fecha_str}"
    y = dibujar_encabezado_y_marca_agua_alfa(c, titulo_doc, subtitulo)

    # Banda resumen: Código, Encargado, Técnico, Estado
    c.setStrokeColor(GRIS_BORDE)
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.roundRect(margen_x, y - 30, ancho_util, 30, 4, fill=1, stroke=1)
    c.setFillColor(NEGRO)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen_x + 8, y - 12, f"Código: {orden.codigo}")
    c.drawString(margen_x + 150, y - 12, f"Tipo: {'GARANTÍA' if es_garantia else 'SERVICIO TÉCNICO'}")
    c.drawString(margen_x + 335, y - 12, f"Estado: {orden.estado.replace('_', ' ')}")
    c.setFont("Helvetica", 8.5)
    c.drawString(margen_x + 8, y - 24, f"Recibido por (Encargado): {encargado_nom}")
    c.drawString(margen_x + 285, y - 24, f"Técnico Asignado: {tecnico_nom}")
    y -= 42

    # 1. Datos del Cliente
    y = _dibujar_seccion(c, "1. Datos del Cliente", margen_x, y, ancho_util)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen_x + 6, y, "Nombre / Razón Social:")
    c.setFont("Helvetica", 8.5)
    c.drawString(margen_x + 115, y, (orden.cliente_nombre or "-")[:55])
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen_x + 355, y, "Cédula / RIF:")
    c.setFont("Helvetica", 8.5)
    c.drawString(margen_x + 418, y, orden.cliente_documento or "-")
    y -= 14
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen_x + 6, y, "Teléfono:")
    c.setFont("Helvetica", 8.5)
    c.drawString(margen_x + 115, y, orden.cliente_telefono or "-")
    y -= 18

    # 2. Datos de la Nota de Venta (SOLO GARANTÍA)
    if es_garantia:
        y = _dibujar_seccion(c, "2. Datos de la Nota de Venta (Respaldo de Garantía)", margen_x, y, ancho_util)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(margen_x + 6, y, "N° Nota de Venta:")
        c.setFont("Helvetica", 8.5)
        c.drawString(margen_x + 95, y, orden.numero_nota_venta or "No indicada")
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(margen_x + 225, y, "Fecha de Venta:")
        c.setFont("Helvetica", 8.5)
        c.drawString(
            margen_x + 300,
            y,
            orden.fecha_venta.strftime("%d/%m/%Y") if orden.fecha_venta else "-",
        )
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(margen_x + 390, y, "Días Transcurridos:")
        c.setFont("Helvetica", 8.5)
        dias_txt = (
            f"{orden.dias_transcurridos_garantia} días"
            if orden.dias_transcurridos_garantia is not None
            else "-"
        )
        c.drawString(margen_x + 478, y, dias_txt)
        y -= 18

    # 3. Detalles del Equipo
    num_sec_eq = "3" if es_garantia else "2"
    y = _dibujar_seccion(c, f"{num_sec_eq}. Detalles del Equipo Recibido", margen_x, y, ancho_util)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen_x + 6, y, "Marca:")
    c.setFont("Helvetica", 8.5)
    c.drawString(margen_x + 45, y, (orden.marca or "-")[:25])
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen_x + 170, y, "Modelo:")
    c.setFont("Helvetica", 8.5)
    c.drawString(margen_x + 212, y, (orden.modelo or "-")[:34])
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen_x + 375, y, "Serial:")
    c.setFont("Helvetica", 8.5)
    c.drawString(margen_x + 412, y, (orden.serial or "-")[:24])
    y -= 14
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen_x + 6, y, "Especificaciones:")
    c.setFont("Helvetica", 8.5)
    c.drawString(margen_x + 88, y, (orden.especificaciones or "No especificadas")[:65])
    if orden.clave_acceso:
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(margen_x + 405, y, "Clave:")
        c.setFont("Helvetica", 8.5)
        c.drawString(margen_x + 438, y, orden.clave_acceso[:18])
    y -= 18

    # 4. Estado de Recepción y Diagnóstico Inicial
    num_sec_est = "4" if es_garantia else "3"
    y = _dibujar_seccion(c, f"{num_sec_est}. Estado de Recepción y Falla Declarada", margen_x, y, ancho_util)

    # Indicador explícito ENCENDIDO / APAGADO
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen_x + 6, y, "Estado de encendido al recibir:")
    if orden.equipo_llega_apagado:
        c.setFillColor(ROJO_ALERTA)
        c.drawString(margen_x + 150, y, "APAGADO (No encendió al momento de la recepción)")
    else:
        c.setFillColor(VERDE_OK)
        c.drawString(margen_x + 150, y, "ENCENDIDO (Verificado al momento de la recepción)")
    c.setFillColor(NEGRO)
    y -= 15

    # Falla declarada
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen_x + 6, y, "Falla declarada por el cliente:")
    y -= 12
    y = _dibujar_parrafo_justificado(
        c, orden.falla_declarada_cliente or "-", margen_x + 6, y, ancho_util - 12, size=8.5, leading=11.5
    )
    y -= 6

    # Accesorios entregados
    try:
        acc_list = json.loads(orden.accesorios_entregados_json or "[]")
        if not isinstance(acc_list, list):
            acc_list = []
    except Exception:
        acc_list = []
    acc_txt = ", ".join(str(a) for a in acc_list if str(a).strip())
    if orden.accesorios_otros.strip():
        acc_txt = f"{acc_txt} · Otros: {orden.accesorios_otros.strip()}" if acc_txt else orden.accesorios_otros.strip()
    if not acc_txt:
        acc_txt = "Ninguno (solo equipo)"

    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen_x + 6, y, "Accesorios / componentes entregados:")
    y -= 12
    y = _dibujar_parrafo_justificado(c, acc_txt, margen_x + 6, y, ancho_util - 12, size=8.5, leading=11.5)
    y -= 6

    # Detalles estéticos
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen_x + 6, y, "Detalles estéticos al recibir:")
    y -= 12
    y = _dibujar_parrafo_justificado(
        c,
        orden.detalles_esteticos or "Sin observaciones estéticas adicionales.",
        margen_x + 6,
        y,
        ancho_util - 12,
        size=8.5,
        leading=11.5,
    )
    y -= 6

    # Detalles del sistema
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(margen_x + 6, y, "Detalles de sistema / funcionamiento en recepción:")
    y -= 12
    y = _dibujar_parrafo_justificado(
        c,
        orden.detalles_sistema_recepcion or "Pendiente de evaluación técnica detallada.",
        margen_x + 6,
        y,
        ancho_util - 12,
        size=8.5,
        leading=11.5,
    )
    y -= 10

    # Costo de revisión (SOLO SERVICIO TÉCNICO)
    if not es_garantia:
        costo_ef = 0.0 if orden.reparacion_aprobada else float(orden.costo_revision_usd or 10.0)
        estado_rev = (
            "EXONERADO (Reparación aprobada con Alfa)"
            if orden.reparacion_aprobada
            else f"${costo_ef:.2f} USD (Exonerado si realiza la reparación con nosotros)"
        )
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(margen_x + 6, y, f"Costo de revisión técnica: {estado_rev}")
        y -= 16

    # 5. Cláusulas Legales al pie (justificadas)
    y_clausulas = max(y - 6, 175)
    if not es_garantia:
        clausula_titulo = "CONDICIONES DEL SERVICIO TÉCNICO"
        clausula_texto = (
            "CONDICIONES DEL SERVICIO TÉCNICO: 1) El costo de la revisión técnica es de $10 USD; "
            "dicho monto NO se cancela si el cliente decide realizar la reparación con nosotros. "
            "2) En caso de que el equipo sea recibido apagado, no nos hacemos responsables por fallas "
            "adicionales, previas u ocultas que presente el equipo al momento de la revisión o encendido. "
            "3) Alfa Digital Store no se hace responsable por la pérdida de información o respaldo de datos; "
            "el cliente debe retirar su equipo en un plazo máximo de 30 días continuos tras ser notificado."
        )
        c.setFillColor(AMBAR_FONDO)
        c.setStrokeColor(AMBAR_BORDE)
    else:
        clausula_titulo = "POLÍTICAS DE GARANTÍA · ALFA DIGITAL STORE"
        clausula_texto = (
            "POLÍTICAS DE GARANTÍA: 1) La garantía cubre exclusivamente defectos de fabricación o hardware "
            "del equipo respaldado por su Nota de Venta original dentro del período vigente. "
            "2) La garantía queda anulada en casos de golpes, humedad, derrame de líquidos, fluctuaciones "
            "eléctricas, intervención de terceros o remoción de sellos de seguridad. "
            "3) El tiempo estimado de diagnóstico y respuesta técnica será informado por nuestros canales oficiales; "
            "Alfa no se hace responsable por respaldo de software o datos personales."
        )
        c.setFillColor(AZUL_CLARO)
        c.setStrokeColor(AZUL_ALFA)

    c.setLineWidth(1.0)
    caja_h = 74
    c.roundRect(margen_x, y_clausulas - caja_h, ancho_util, caja_h, 5, fill=1, stroke=1)
    c.setFillColor(NEGRO)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(margen_x + 8, y_clausulas - 13, clausula_titulo)
    _dibujar_parrafo_justificado(
        c,
        clausula_texto,
        margen_x + 8,
        y_clausulas - 25,
        ancho_util - 16,
        font="Helvetica",
        size=7.8,
        leading=10.8,
        color=NEGRO,
    )

    # 6. Bloque de Firmas
    y_firmas = 58
    c.setStrokeColor(GRIS_TEXTO)
    c.setLineWidth(0.7)
    c.line(margen_x + 20, y_firmas + 18, margen_x + 230, y_firmas + 18)
    c.line(ancho - margen_x - 230, y_firmas + 18, ancho - margen_x - 20, y_firmas + 18)

    c.setFillColor(NEGRO)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawCentredString(margen_x + 125, y_firmas + 6, "FIRMA DEL CLIENTE (CONFORME)")
    c.drawCentredString(ancho - margen_x - 125, y_firmas + 6, "RECIBIDO POR (ENCARGADO DE TIENDA)")

    c.setFont("Helvetica", 7.8)
    c.setFillColor(GRIS_TEXTO)
    c.drawCentredString(
        margen_x + 125,
        y_firmas - 6,
        f"{(orden.cliente_nombre or '')[:32]} · C.I./RIF: {orden.cliente_documento or '_______________'}",
    )
    c.drawCentredString(
        ancho - margen_x - 125,
        y_firmas - 6,
        f"{encargado_nom[:34]} · {sucursal_nom[:22]}",
    )

    c.showPage()
    c.save()
    return buf.getvalue()
