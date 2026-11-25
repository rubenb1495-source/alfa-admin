from __future__ import annotations

import io
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy.orm import Session

from app.base_datos import obtener_bd
from app.modelos import Sucursal, Usuario
from app.modelos_admin import ActivoFijo, FacturaGastoFiscal, ObligacionLegal
from app.modelos_finanzas import ExtractoBancario, InstrumentoFinanciero
from app.rutas.administracion import _q2, _tasa_bcv_fecha, registrar_auditoria
from app.rutas.logistica_avanzada import _leer_filas_archivo, parsear_decimal_seguro, parsear_entero_seguro
from app.rutas.tasas import obtener_fecha_hoy
from app.seguridad import requerir_admin, requerir_direccion_lectura


enrutador = APIRouter(prefix="/api/admin", tags=["Carga Masiva Administración"])

TIPOS_ADMIN_VALIDOS: set[str] = {
    "FACTURAS_GASTOS_CXP",
    "EXTRACTO_BANCARIO",
    "NOMINA_PERSONAL",
    "OBLIGACIONES_FISCALES",
    "ACTIVOS_FIJOS",
}


def _parsear_fecha(valor: str, defecto: date | None = None) -> date | None:
    txt = (valor or "").strip()
    if not txt:
        return defecto
    txt = txt[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha inválida '{valor}'. Usa formato YYYY-MM-DD.")


@enrutador.get("/plantilla/{tipo}")
def descargar_plantilla_admin(
    tipo: str,
    _usuario: Usuario = Depends(requerir_direccion_lectura),
    bd: Session = Depends(obtener_bd),
) -> StreamingResponse:
    tipo_norm = tipo.strip().upper()
    if tipo_norm not in TIPOS_ADMIN_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo inválido. Usa: {', '.join(sorted(TIPOS_ADMIN_VALIDOS))}.",
        )

    hoy_str = obtener_fecha_hoy().isoformat()
    wb = Workbook()
    ws = wb.active
    ws.title = "Datos"

    fill = PatternFill(start_color="003566", end_color="003566", fill_type="solid")
    font = Font(color="FFFFFF", bold=True, size=11)

    definiciones: dict[str, tuple[list[str], list[list[Any]], list[str]]] = {
        "FACTURAS_GASTOS_CXP": (
            [
                "rif_proveedor",
                "razon_social",
                "numero_factura",
                "numero_control",
                "fecha_emision",
                "fecha_vencimiento",
                "categoria",
                "es_deducible",
                "base_imponible_bs",
                "monto_exento_bs",
                "alicuota_iva",
                "tasa_bcv_fecha",
                "observaciones",
            ],
            [
                [
                    "J-12345678-9",
                    "Servicios Eléctricos CA",
                    "FAC-0010",
                    "00-0010",
                    hoy_str,
                    hoy_str,
                    "Electricidad/Agua/Internet",
                    "SI",
                    5000.00,
                    0.00,
                    16.00,
                    50.00,
                    "Servicio mensual local",
                ]
            ],
            [
                "razon_social y fecha_emision (YYYY-MM-DD) son obligatorios.",
                "es_deducible: SI o NO.",
                "alicuota_iva: 16, 8 o 0.",
            ],
        ),
        "EXTRACTO_BANCARIO": (
            ["fecha", "referencia", "descripcion", "debito", "credito", "saldo"],
            [[hoy_str, "REF-88912", "Transferencia recibida cliente", 0.00, 1500.00, 1500.00]],
            [
                "Debes seleccionar la cuenta bancaria en el modal antes de subir el extracto.",
                "Indica monto en columna debito (salida) o credito (entrada).",
            ],
        ),
        "NOMINA_PERSONAL": (
            [
                "nombre_o_correo",
                "cargo",
                "fecha_ingreso",
                "salario_base_usd",
                "bono_alimentacion_usd",
                "bonos_fijos_usd",
                "tipo_contrato",
                "cuenta_bancaria_pago",
            ],
            [["Ana Asesora", "Asesora de Ventas", hoy_str, 200.00, 40.00, 50.00, "TIEMPO_INDETERMINADO", "0102-0000-..."]],
            [
                "nombre_o_correo debe coincidir con un colaborador registrado en Personal y Usuarios.",
                "Actualiza los datos laborales base para el cálculo de nómina y provisiones LOTTT.",
            ],
        ),
        "OBLIGACIONES_FISCALES": (
            ["organismo", "tipo_obligacion", "descripcion", "periodo", "fecha_vencimiento", "monto_estimado_usd"],
            [["SENIAT", "Declaración IVA", "1ra Quincena", "2026-11", hoy_str, 120.00]],
            [
                "organismo: SENIAT, ALCALDIA, PARAFISCAL o PERMISOLOGIA.",
                "fecha_vencimiento en formato YYYY-MM-DD.",
            ],
        ),
        "ACTIVOS_FIJOS": (
            ["codigo_activo", "descripcion", "categoria", "responsable", "fecha_compra", "costo_usd", "vida_util_meses", "estado"],
            [["AF-0001", "Aire Acondicionado 24000 BTU", "Equipos", "Encargado T38", hoy_str, 650.00, 60, "ACTIVO"]],
            [
                "codigo_activo debe ser único.",
                "estado: ACTIVO, EN_REPARACION o DESINCORPORADO.",
            ],
        ),
    }

    headers, ejemplos, notas = definiciones[tipo_norm]
    ws.append(headers)
    for col_i in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_i)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = 22
    for row in ejemplos:
        ws.append(row)

    ws_i = wb.create_sheet("Instrucciones")
    ws_i.append([f"Plantilla Oficial Administración ALFA — {tipo_norm}"])
    ws_i["A1"].font = Font(bold=True, size=13, color="003566")
    for n in notas:
        ws_i.append([f"• {n}"])
    ws_i.column_dimensions["A"].width = 70

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="plantilla_{tipo_norm.lower()}.xlsx"'},
    )


def _validar_admin_lote(
    bd: Session,
    tipo: str,
    filas_crudas: list[tuple[int, dict[str, str]]],
    instrumento_id: int | None,
) -> dict[str, Any]:
    validas: list[dict[str, Any]] = []
    errores_lista: list[dict[str, Any]] = []
    hoy = obtener_fecha_hoy()

    if tipo == "FACTURAS_GASTOS_CXP":
        for num, raw in filas_crudas:
            errs: list[str] = []
            razon = raw.get("razon_social", "").strip()
            if len(razon) < 2:
                errs.append("razon_social es obligatorio.")
            try:
                f_em = _parsear_fecha(raw.get("fecha_emision", ""), hoy)
                f_venc = _parsear_fecha(raw.get("fecha_vencimiento", ""), None)
            except ValueError as exc:
                f_em, f_venc = hoy, None
                errs.append(str(exc))
            try:
                base_bs = parsear_decimal_seguro(raw.get("base_imponible_bs"), Decimal("0"))
                exento_bs = parsear_decimal_seguro(raw.get("monto_exento_bs"), Decimal("0"))
                alicuota = parsear_decimal_seguro(raw.get("alicuota_iva"), Decimal("16"))
                tasa = parsear_decimal_seguro(raw.get("tasa_bcv_fecha"), Decimal("0"))
                if base_bs < 0 or exento_bs < 0:
                    errs.append("Los montos no pueden ser negativos.")
                if base_bs == 0 and exento_bs == 0:
                    errs.append("Debe indicar base_imponible_bs o monto_exento_bs > 0.")
            except ValueError as exc:
                base_bs = exento_bs = alicuota = tasa = Decimal("0")
                errs.append(str(exc))

            ded_txt = raw.get("es_deducible", "SI").strip().upper()
            es_ded = ded_txt not in ("NO", "FALSE", "0")
            item = {
                "fila": num,
                "rif_proveedor": raw.get("rif_proveedor", "").strip().upper(),
                "razon_social": razon,
                "numero_factura": raw.get("numero_factura", "").strip(),
                "numero_control": raw.get("numero_control", "").strip(),
                "fecha_emision": f_em.isoformat() if f_em else hoy.isoformat(),
                "fecha_vencimiento": f_venc.isoformat() if f_venc else None,
                "categoria": raw.get("categoria", "Varios").strip() or "Varios",
                "es_deducible": es_ded,
                "base_imponible_bs": float(base_bs),
                "monto_exento_bs": float(exento_bs),
                "alicuota_iva": float(alicuota),
                "tasa_bcv_fecha": float(tasa),
                "observaciones": raw.get("observaciones", "").strip(),
            }
            if errs:
                item["errores"] = errs
                errores_lista.append(item)
            else:
                validas.append(item)

    elif tipo == "EXTRACTO_BANCARIO":
        if not instrumento_id:
            raise HTTPException(status_code=400, detail="Debes seleccionar la cuenta bancaria (instrumento_id).")
        for num, raw in filas_crudas:
            errs = []
            try:
                f_mov = _parsear_fecha(raw.get("fecha", ""), None)
                if f_mov is None:
                    errs.append("fecha es obligatoria (YYYY-MM-DD).")
            except ValueError as exc:
                f_mov = None
                errs.append(str(exc))
            try:
                debito = parsear_decimal_seguro(raw.get("debito"), Decimal("0"))
                credito = parsear_decimal_seguro(raw.get("credito"), Decimal("0"))
                if debito < 0 or credito < 0:
                    errs.append("debito y credito deben ser >= 0.")
                if debito == 0 and credito == 0:
                    errs.append("Debe indicar un monto en debito o credito.")
            except ValueError as exc:
                debito = credito = Decimal("0")
                errs.append(str(exc))
            monto_signo = credito - debito
            item = {
                "fila": num,
                "fecha": f_mov.isoformat() if f_mov else "",
                "referencia": raw.get("referencia", "").strip(),
                "descripcion": raw.get("descripcion", "").strip() or "Movimiento bancario",
                "monto_con_signo": float(monto_signo),
            }
            if errs:
                item["errores"] = errs
                errores_lista.append(item)
            else:
                validas.append(item)

    elif tipo == "NOMINA_PERSONAL":
        usuarios = bd.query(Usuario).all()
        por_nombre = {u.nombre.strip().lower(): u for u in usuarios}
        por_correo = {(u.correo or "").strip().lower(): u for u in usuarios if u.correo}
        for num, raw in filas_crudas:
            errs = []
            clave_u = raw.get("nombre_o_correo", "").strip().lower()
            usr = por_correo.get(clave_u) or por_nombre.get(clave_u)
            if usr is None:
                errs.append(f"Colaborador '{raw.get('nombre_o_correo', '')}' no encontrado en Personal y Usuarios.")
            try:
                f_ing = _parsear_fecha(raw.get("fecha_ingreso", ""), None)
                sal = parsear_decimal_seguro(raw.get("salario_base_usd"), Decimal("0"))
                cesta = parsear_decimal_seguro(raw.get("bono_alimentacion_usd"), Decimal("0"))
                bono = parsear_decimal_seguro(raw.get("bonos_fijos_usd"), Decimal("0"))
                if sal < 0 or cesta < 0 or bono < 0:
                    errs.append("Montos salariales no pueden ser negativos.")
            except ValueError as exc:
                f_ing = None
                sal = cesta = bono = Decimal("0")
                errs.append(str(exc))
            item = {
                "fila": num,
                "usuario_id": usr.id if usr else None,
                "nombre_articulo": usr.nombre if usr else raw.get("nombre_o_correo", ""),
                "cargo": raw.get("cargo", "").strip(),
                "fecha_ingreso": f_ing.isoformat() if f_ing else None,
                "salario_base_usd": float(sal),
                "bono_alimentacion_usd": float(cesta),
                "bonos_fijos_usd": float(bono),
                "tipo_contrato": raw.get("tipo_contrato", "").strip(),
                "cuenta_bancaria_pago": raw.get("cuenta_bancaria_pago", "").strip(),
            }
            if errs:
                item["errores"] = errs
                errores_lista.append(item)
            else:
                validas.append(item)

    elif tipo == "OBLIGACIONES_FISCALES":
        for num, raw in filas_crudas:
            errs = []
            org = raw.get("organismo", "").strip().upper()
            if org not in {"SENIAT", "ALCALDIA", "PARAFISCAL", "PERMISOLOGIA"}:
                errs.append(f"Organismo '{org}' inválido (usa SENIAT, ALCALDIA, PARAFISCAL o PERMISOLOGIA).")
            tipo_ob = raw.get("tipo_obligacion", "").strip()
            if len(tipo_ob) < 2:
                errs.append("tipo_obligacion es obligatorio.")
            try:
                f_venc = _parsear_fecha(raw.get("fecha_vencimiento", ""), None)
                if f_venc is None:
                    errs.append("fecha_vencimiento es obligatoria.")
                monto = parsear_decimal_seguro(raw.get("monto_estimado_usd"), Decimal("0"))
            except ValueError as exc:
                f_venc = None
                monto = Decimal("0")
                errs.append(str(exc))
            item = {
                "fila": num,
                "organismo": org,
                "tipo_obligacion": tipo_ob,
                "descripcion": raw.get("descripcion", "").strip(),
                "periodo": raw.get("periodo", "").strip(),
                "fecha_vencimiento": f_venc.isoformat() if f_venc else "",
                "monto_estimado_usd": float(monto),
            }
            if errs:
                item["errores"] = errs
                errores_lista.append(item)
            else:
                validas.append(item)

    elif tipo == "ACTIVOS_FIJOS":
        cods_db = {r[0].upper() for r in bd.query(ActivoFijo.codigo_activo).all()}
        cods_arch: set[str] = set()
        for num, raw in filas_crudas:
            errs = []
            cod = raw.get("codigo_activo", "").strip().upper()
            if not cod:
                errs.append("codigo_activo es obligatorio.")
            elif cod in cods_db or cod in cods_arch:
                errs.append(f"codigo_activo '{cod}' duplicado.")
            else:
                cods_arch.add(cod)
            desc = raw.get("descripcion", "").strip()
            if not desc:
                errs.append("descripcion es obligatoria.")
            try:
                f_comp = _parsear_fecha(raw.get("fecha_compra", ""), hoy)
                costo = parsear_decimal_seguro(raw.get("costo_usd"), Decimal("0"))
                vida = parsear_entero_seguro(raw.get("vida_util_meses"), 60)
                if costo <= 0:
                    errs.append("costo_usd debe ser mayor a 0.")
            except ValueError as exc:
                f_comp = hoy
                costo = Decimal("0")
                vida = 60
                errs.append(str(exc))
            est = raw.get("estado", "ACTIVO").strip().upper() or "ACTIVO"
            if est not in {"ACTIVO", "EN_REPARACION", "DESINCORPORADO"}:
                errs.append(f"estado '{est}' inválido.")
            item = {
                "fila": num,
                "codigo_activo": cod,
                "descripcion": desc,
                "categoria": raw.get("categoria", "Mobiliario").strip() or "Mobiliario",
                "responsable": raw.get("responsable", "").strip(),
                "fecha_compra": f_comp.isoformat() if f_comp else hoy.isoformat(),
                "costo_usd": float(costo),
                "vida_util_meses": vida,
                "estado": est,
            }
            if errs:
                item["errores"] = errs
                errores_lista.append(item)
            else:
                validas.append(item)

    return {
        "tipo": tipo,
        "total_filas": len(filas_crudas),
        "validas_count": len(validas),
        "errores_count": len(errores_lista),
        "filas_validas": validas,
        "filas_con_error": errores_lista,
    }


@enrutador.post("/importar/{tipo}/preview")
async def preview_importar_admin(
    tipo: str,
    archivo: UploadFile = File(...),
    instrumento_id: int | None = Form(default=None),
    _usuario: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    tipo_norm = tipo.strip().upper()
    if tipo_norm not in TIPOS_ADMIN_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Tipo de importación inválido: '{tipo}'.")
    contenido = await archivo.read()
    filas_crudas = _leer_filas_archivo(contenido, archivo.filename or "archivo.xlsx")
    if not filas_crudas:
        raise HTTPException(status_code=400, detail="El archivo no contiene filas.")
    res = _validar_admin_lote(bd, tipo_norm, filas_crudas, instrumento_id)
    res["nombre_archivo"] = archivo.filename or "archivo.xlsx"
    return res


@enrutador.post("/importar/{tipo}/confirmar", status_code=status.HTTP_201_CREATED)
async def confirmar_importar_admin(
    tipo: str,
    archivo: UploadFile = File(...),
    instrumento_id: int | None = Form(default=None),
    usuario_actual: Usuario = Depends(requerir_admin),
    bd: Session = Depends(obtener_bd),
) -> dict[str, Any]:
    tipo_norm = tipo.strip().upper()
    if tipo_norm not in TIPOS_ADMIN_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Tipo de importación inválido: '{tipo}'.")
    contenido = await archivo.read()
    filas_crudas = _leer_filas_archivo(contenido, archivo.filename or "archivo.xlsx")
    validacion = _validar_admin_lote(bd, tipo_norm, filas_crudas, instrumento_id)
    if validacion["errores_count"] > 0:
        raise HTTPException(
            status_code=400,
            detail={
                "mensaje": f"Se detectaron {validacion['errores_count']} fila(s) con error. Corrige antes de importar.",
                "filas_con_error": validacion["filas_con_error"],
            },
        )

    procesadas = 0
    if tipo_norm == "FACTURAS_GASTOS_CXP":
        for f in validacion["filas_validas"]:
            f_em = date.fromisoformat(f["fecha_emision"])
            f_venc = date.fromisoformat(f["fecha_vencimiento"]) if f["fecha_vencimiento"] else None
            tasa = Decimal(str(f["tasa_bcv_fecha"])) if f["tasa_bcv_fecha"] > 0 else _tasa_bcv_fecha(bd, f_em)
            base_bs = Decimal(str(f["base_imponible_bs"]))
            exento_bs = Decimal(str(f["monto_exento_bs"]))
            alic = Decimal(str(f["alicuota_iva"]))
            iva_bs = _q2(base_bs * (alic / Decimal("100")))
            tot_bs = _q2(base_bs + exento_bs + iva_bs)
            tot_usd = _q2(tot_bs / tasa) if tasa > 0 else Decimal("0")
            bd.add(
                FacturaGastoFiscal(
                    rif_proveedor=f["rif_proveedor"],
                    razon_social=f["razon_social"],
                    numero_factura=f["numero_factura"],
                    numero_control=f["numero_control"],
                    fecha_emision=f_em,
                    fecha_vencimiento=f_venc,
                    categoria=f["categoria"],
                    es_deducible=f["es_deducible"],
                    base_imponible_bs=base_bs,
                    monto_exento_bs=exento_bs,
                    alicuota_iva=alic,
                    monto_iva_bs=iva_bs,
                    monto_total_bs=tot_bs,
                    tasa_bcv_fecha=tasa,
                    monto_total_usd=tot_usd,
                    estado="PENDIENTE",
                    observaciones=f["observaciones"],
                    registrado_por_id=usuario_actual.id,
                )
            )
            procesadas += 1

    elif tipo_norm == "EXTRACTO_BANCARIO":
        assert instrumento_id is not None
        inst = bd.query(InstrumentoFinanciero).filter(InstrumentoFinanciero.id == instrumento_id).first()
        if inst is None:
            raise HTTPException(status_code=404, detail="Instrumento bancario no encontrado.")
        for f in validacion["filas_validas"]:
            bd.add(
                ExtractoBancario(
                    instrumento_id=instrumento_id,
                    fecha=date.fromisoformat(f["fecha"]),
                    referencia=f["referencia"],
                    descripcion=f["descripcion"],
                    monto_con_signo=_q2(Decimal(str(f["monto_con_signo"]))),
                    conciliado=False,
                )
            )
            procesadas += 1

    elif tipo_norm == "NOMINA_PERSONAL":
        for f in validacion["filas_validas"]:
            usr = bd.query(Usuario).filter(Usuario.id == f["usuario_id"]).first()
            if usr is not None:
                usr.cargo = f["cargo"] or usr.cargo
                if f["fecha_ingreso"]:
                    usr.fecha_ingreso = date.fromisoformat(f["fecha_ingreso"])
                usr.salario_base_usd = _q2(Decimal(str(f["salario_base_usd"])))
                usr.bono_alimentacion_usd = _q2(Decimal(str(f["bono_alimentacion_usd"])))
                usr.bonos_fijos_usd = _q2(Decimal(str(f["bonos_fijos_usd"])))
                usr.tipo_contrato = f["tipo_contrato"] or usr.tipo_contrato
                usr.cuenta_bancaria_pago = f["cuenta_bancaria_pago"] or usr.cuenta_bancaria_pago
                procesadas += 1

    elif tipo_norm == "OBLIGACIONES_FISCALES":
        for f in validacion["filas_validas"]:
            bd.add(
                ObligacionLegal(
                    organismo=f["organismo"],
                    tipo_obligacion=f["tipo_obligacion"],
                    descripcion=f["descripcion"],
                    periodo=f["periodo"],
                    fecha_vencimiento=date.fromisoformat(f["fecha_vencimiento"]),
                    monto_estimado_usd=_q2(Decimal(str(f["monto_estimado_usd"]))),
                    estado="PENDIENTE",
                )
            )
            procesadas += 1

    elif tipo_norm == "ACTIVOS_FIJOS":
        for f in validacion["filas_validas"]:
            bd.add(
                ActivoFijo(
                    codigo_activo=f["codigo_activo"],
                    descripcion=f["descripcion"],
                    categoria=f["categoria"],
                    responsable=f["responsable"],
                    fecha_compra=date.fromisoformat(f["fecha_compra"]),
                    costo_usd=_q2(Decimal(str(f["costo_usd"]))),
                    vida_util_meses=f["vida_util_meses"],
                    estado=f["estado"],
                )
            )
            procesadas += 1

    registrar_auditoria(
        bd,
        usuario_actual,
        f"IMPORTACION_{tipo_norm}",
        "IMPORTAR",
        tipo_norm,
        datos_nuevos={"archivo": archivo.filename, "filas_procesadas": procesadas},
    )
    bd.commit()
    return {"tipo": tipo_norm, "filas_procesadas": procesadas}
