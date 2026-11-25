#!/usr/bin/env python3
"""
Simulación General Completa (End-to-End) de Alfa Digital Store (`[SIM-ALFA]`).

Ejecuta los 11 pasos cronológicos (operativos, financieros y contables) para
validar el sistema de punta a punta y visualizar los resultados reales en la
interfaz web (Balance General, Estado de Resultados y Cierre Diario).

Todos los registros generados llevan el prefijo `[SIM-ALFA]` para que
`scripts/limpiar_simulacion_alfa.py` los elimine sin tocar datos reales.

Uso:
  # Contra la API en producción (Vercel / Neon):
  python scripts/simulacion_general_alfa.py --api-url https://alfa-admin-api.vercel.app

  # Contra el backend local (TestClient sobre la BD configurada):
  python scripts/simulacion_general_alfa.py --local
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

PREFIJO = "[SIM-ALFA]"


def _req(client: Any, method: str, url: str, headers: dict[str, str], **kwargs: Any) -> dict[str, Any] | list[Any]:
    resp = client.request(method, url, headers=headers, **kwargs)
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} en {method} {url}: {resp.text}")
    return resp.json()


def _asegurar_articulo(
    client: Any,
    headers: dict[str, str],
    existentes: dict[str, dict[str, Any]],
    sku: str,
    nombre: str,
    tipo: str,
    costo_ref: float,
    precio_promo: float,
) -> int:
    if sku in existentes:
        return int(existentes[sku]["id"])
    r = _req(
        client,
        "POST",
        "/api/catalogo",
        headers,
        json={
            "sku": sku,
            "descripcion": nombre,
            "tipo": tipo,
            "categoria": "Equipos" if tipo == "EQUIPO" else "Componentes",
            "costo_referencia_usd": costo_ref,
            "precio_promo_usd": precio_promo,
            "stock_minimo": 2,
        },
    )
    return int(r["id"])


def _asegurar_usuario(
    client: Any,
    headers: dict[str, str],
    existentes: list[dict[str, Any]],
    nombre: str,
    rol: str,
    sucursal_id: int,
    modalidad: str = "PRESENCIAL",
    tiene_acceso: bool = True,
    correo: str | None = None,
    clave: str | None = None,
    cargo: str = "",
    salario_base_usd: float = 0.0,
    bono_alimentacion_usd: float = 40.0,
) -> int:
    for u in existentes:
        if u["nombre"] == nombre:
            return int(u["id"])
    payload: dict[str, Any] = {
        "nombre": nombre,
        "rol": rol,
        "sucursal_id": sucursal_id,
        "modalidad": modalidad,
        "tiene_acceso": tiene_acceso,
        "cargo": cargo or rol,
        "salario_base_usd": salario_base_usd,
        "bono_alimentacion_usd": bono_alimentacion_usd,
        "bonos_fijos_usd": 0.0,
    }
    if tiene_acceso and correo:
        payload["correo"] = correo
        payload["clave"] = clave or "SimAlfa2026!"
    r = _req(client, "POST", "/api/usuarios", headers, json=payload)
    return int(r["id"])


def ejecutar_simulacion(client: Any, correo: str, clave: str, limpiar_previo: bool = True) -> dict[str, Any]:
    # Login inicial como ADMIN
    r_login = client.post("/api/auth/login", json={"correo": correo, "clave": clave})
    if r_login.status_code != 200:
        raise RuntimeError(f"Error login ({r_login.status_code}): {r_login.text}")
    data_login = r_login.json()
    token = data_login.get("token") or data_login.get("access_token") or data_login["token_acceso"]
    headers = {"Authorization": f"Bearer {token}"}

    if limpiar_previo:
        print("0. Limpiando restos previos de [SIM-ALFA] (si existieran)...")
        _req(
            client,
            "POST",
            "/api/admin/limpiar-simulacion",
            headers,
            json={"confirmacion": "ELIMINAR-SIM-ALFA", "prefijo": PREFIJO},
        )

    # =========================================================================
    # PASO 1: Apertura del Día, Sedes, Personal, Inversión Inicial y Préstamo
    # =========================================================================
    print("1. Apertura del día, tasas, sedes, personal, inversión inicial y préstamo...")
    tasa_resp = _req(
        client,
        "POST",
        "/api/tasas/hoy/confirmar",
        headers,
        json={
            "tasa_bcv": 52.50,
            "tasa_usdt": 54.00,
            "porcentaje_recargo": 20.0,
        },
    )
    hoy_str = tasa_resp["fecha"]
    hoy_date = date.fromisoformat(hoy_str)
    tasa_bcv = float(tasa_resp["tasa_bcv"])

    sucursales = _req(client, "GET", "/api/sucursales", headers)
    suc_activas = [s for s in sucursales if s.get("estado") == "ACTIVA"]
    almacen = next((s for s in suc_activas if "ALMAC" in s["nombre"].upper()), suc_activas[0])
    tiendas = [s for s in suc_activas if s["id"] != almacen["id"]]
    if len(tiendas) < 2:
        # Si hay menos de 2 tiendas activas, reutilizar las disponibles
        sede_1 = tiendas[0] if tiendas else almacen
        sede_2 = tiendas[1] if len(tiendas) > 1 else sede_1
    else:
        sede_1 = tiendas[0]
        sede_2 = tiendas[1]
    almacen_id, sede1_id, sede2_id = int(almacen["id"]), int(sede_1["id"]), int(sede_2["id"])

    # Instrumentos de pago
    insts = _req(client, "GET", "/api/finanzas/instrumentos", headers)

    def _buscar_inst(palabras: list[str], moneda: str | None = None) -> dict[str, Any]:
        for i in insts:
            nom = i["nombre"].upper()
            if any(p in nom for p in palabras) and (moneda is None or i["moneda"] == moneda):
                return i
        for i in insts:
            if moneda is None or i["moneda"] == moneda:
                return i
        return insts[0]

    inst_efectivo = _buscar_inst(["EFECTIVO"], "USD")
    inst_zelle = _buscar_inst(["ZELLE"], "USD")
    inst_binance = _buscar_inst(["BINANCE", "USDT"])
    inst_pago_movil = _buscar_inst(["PAGO MOVIL", "PAGO MÓVIL"], "BS")
    inst_transf_bs = _buscar_inst(["TRANSFERENCIA"], "BS")
    inst_pos = _buscar_inst(["PUNTO", "POS"], "BS")
    inst_cashea = _buscar_inst(["CASHEA"])

    # Personal de la simulación (con salarios base para Nómina Paso 8)
    usuarios_exist = _req(client, "GET", "/api/usuarios", headers)
    enc1_id = _asegurar_usuario(
        client, headers, usuarios_exist,
        nombre=f"{PREFIJO} Carlos Encargado S1",
        rol="ENCARGADO_TIENDA", sucursal_id=sede1_id,
        correo="encargado1.sim-alfa@alfadigitalstore.com",
        cargo="Encargado de Tienda Sede 1", salario_base_usd=450.0,
    )
    enc2_id = _asegurar_usuario(
        client, headers, usuarios_exist,
        nombre=f"{PREFIJO} Laura Encargada S2",
        rol="ENCARGADO_TIENDA", sucursal_id=sede2_id,
        correo="encargado2.sim-alfa@alfadigitalstore.com",
        cargo="Encargada de Tienda Sede 2", salario_base_usd=450.0,
    )
    asesora_pres_id = _asegurar_usuario(
        client, headers, usuarios_exist,
        nombre=f"{PREFIJO} Valentina Asesora Presencial",
        rol="ASESORA", sucursal_id=sede1_id, modalidad="PRESENCIAL",
        correo="asesora.sim-alfa@alfadigitalstore.com",
        cargo="Asesora Presencial", salario_base_usd=260.0,
    )
    asesor_online_id = _asegurar_usuario(
        client, headers, usuarios_exist,
        nombre=f"{PREFIJO} Diego Asesor Online",
        rol="ASESORA", sucursal_id=sede2_id, modalidad="ONLINE",
        tiene_acceso=False, correo=None,
        cargo="Asesor Online (Sin Acceso)", salario_base_usd=220.0,
    )
    tecnico_id = _asegurar_usuario(
        client, headers, usuarios_exist,
        nombre=f"{PREFIJO} Miguel Técnico Taller",
        rol="TECNICO", sucursal_id=almacen_id,
        correo="tecnico.sim-alfa@alfadigitalstore.com",
        cargo="Técnico Especialista", salario_base_usd=380.0,
    )
    admin_usr_id = _asegurar_usuario(
        client, headers, usuarios_exist,
        nombre=f"{PREFIJO} Sofía Administradora",
        rol="ADMINISTRACION", sucursal_id=sede1_id,
        correo="administradora.sim-alfa@alfadigitalstore.com",
        cargo="Administradora", salario_base_usd=520.0,
    )
    chofer_id = _asegurar_usuario(
        client, headers, usuarios_exist,
        nombre=f"{PREFIJO} José Chofer Motorizado",
        rol="TECNICO", sucursal_id=almacen_id,
        tiene_acceso=False, correo=None,
        cargo="Chofer / Motorizado Logística", salario_base_usd=300.0,
    )
    director_id = _asegurar_usuario(
        client, headers, usuarios_exist,
        nombre=f"{PREFIJO} Rubén Socio Director",
        rol="DIRECTOR", sucursal_id=sede1_id,
        correo="director.sim-alfa@alfadigitalstore.com",
        cargo="Accionista / Director General", salario_base_usd=800.0,
    )

    # Inversión Inicial (Capital Social 3.1.01) en USD y Bs
    _req(
        client, "POST", "/api/contabilidad/movimiento-patrimonial", headers,
        json={
            "tipo": "APORTE_CAPITAL",
            "instrumento_pago_id": inst_efectivo["id"],
            "monto_usd": 15000.00,
            "socio_nombre": f"{PREFIJO} Socio A (60%)",
            "referencia": f"{PREFIJO} CAP-USD-001",
            "descripcion": f"{PREFIJO} Aporte de Capital Inicial en Efectivo USD",
            "fecha": hoy_str,
        },
    )
    _req(
        client, "POST", "/api/contabilidad/movimiento-patrimonial", headers,
        json={
            "tipo": "APORTE_CAPITAL",
            "instrumento_pago_id": inst_zelle["id"],
            "monto_usd": 5000.00,
            "socio_nombre": f"{PREFIJO} Socio B (40%)",
            "referencia": f"{PREFIJO} CAP-ZELLE-002",
            "descripcion": f"{PREFIJO} Aporte de Capital Inicial en Zelle USD",
            "fecha": hoy_str,
        },
    )
    _req(
        client, "POST", "/api/contabilidad/movimiento-patrimonial", headers,
        json={
            "tipo": "APORTE_CAPITAL",
            "instrumento_pago_id": inst_transf_bs["id"],
            "monto_usd": 3000.00,
            "socio_nombre": f"{PREFIJO} Socios Fondo Operativo Bs",
            "referencia": f"{PREFIJO} CAP-BS-003",
            "descripcion": f"{PREFIJO} Aporte de Capital Inicial en Bolívares",
            "fecha": hoy_str,
        },
    )

    # Préstamo Recibido (PREST-SIM-001) + Pago Cuota #1 (Capital 2.2.01 + Intereses 8.1.02)
    prestamo = _req(
        client, "POST", "/api/contabilidad/prestamos", headers,
        json={
            "acreedor": f"{PREFIJO} Fondo Financiero Aliado",
            "concepto": f"{PREFIJO} PREST-SIM-001 Financiamiento capital de trabajo (12 cuotas)",
            "fecha_desembolso": hoy_str,
            "fecha_vencimiento": (hoy_date + timedelta(days=365)).isoformat(),
            "capital_usd": 5000.00,
            "tasa_interes_mensual_pct": 1.0,
            "instrumento_ingreso_id": inst_efectivo["id"],
        },
    )
    _req(
        client, "POST", f"/api/contabilidad/prestamos/{prestamo['id']}/pagar", headers,
        json={
            "monto_capital_usd": 416.67,
            "monto_interes_usd": 50.00,
            "instrumento_pago_id": inst_efectivo["id"],
            "referencia": f"{PREFIJO} CUOTA-1-PREST",
            "nota": f"{PREFIJO} Pago Cuota #1 Préstamo (Capital + Interés)",
        },
    )

    # =========================================================================
    # PASO 2: Compra Internacional (22 equipos + 20 comp.) + Consignación (5 eq.)
    # =========================================================================
    print("2. Cargando Compra Internacional (22 equipos + 20 componentes) y Consignación (5 equipos)...")
    cat_resp = _req(client, "GET", "/api/catalogo", headers)
    cat_lista = cat_resp.get("items", []) if isinstance(cat_resp, dict) else cat_resp
    cat_map = {a["sku"]: a for a in cat_lista}

    art_lap_pro = _asegurar_articulo(
        client, headers, cat_map,
        "SIM-LAP-PRO", f"{PREFIJO} Laptop Alfa Pro 14 i7", "EQUIPO", 250.0, 480.0,
    )
    art_lap_air = _asegurar_articulo(
        client, headers, cat_map,
        "SIM-LAP-AIR", f"{PREFIJO} Laptop Alfa Air 15 i5", "EQUIPO", 210.0, 410.0,
    )
    art_ssd = _asegurar_articulo(
        client, headers, cat_map,
        "SIM-SSD-512", f"{PREFIJO} SSD NVMe 512GB", "COMPONENTE", 25.0, 55.0,
    )
    art_ram = _asegurar_articulo(
        client, headers, cat_map,
        "SIM-RAM-16", f"{PREFIJO} Memoria RAM 16GB DDR4", "COMPONENTE", 20.0, 45.0,
    )
    art_carg = _asegurar_articulo(
        client, headers, cat_map,
        "SIM-CARG-USB", f"{PREFIJO} Cargador USB-C 65W", "ACCESORIO", 12.0, 30.0,
    )

    items_ci: list[dict[str, Any]] = []
    seriales_intl: list[str] = []
    for idx in range(1, 23):
        ser = f"SIM-INT-{idx:03d}"
        seriales_intl.append(ser)
        items_ci.append(
            {
                "tipo_item": "EQUIPO",
                "sku": "SIM-LAP-PRO" if idx <= 12 else "SIM-LAP-AIR",
                "descripcion": f"{PREFIJO} Laptop Alfa Pro 14 i7" if idx <= 12 else f"{PREFIJO} Laptop Alfa Air 15 i5",
                "serial": ser,
                "cantidad": 1,
                "costo_unitario_usd": 250.0 if idx <= 12 else 210.0,
                "precio_promo_usd": 480.0 if idx <= 12 else 410.0,
                "estado_inicial": "PENDIENTE_REVISION",
            }
        )
    # 20 componentes / accesorios (8 SSD + 6 RAM + 6 Cargadores)
    items_ci.extend(
        [
            {"tipo_item": "COMPONENTE", "sku": "SIM-SSD-512", "descripcion": f"{PREFIJO} SSD NVMe 512GB", "cantidad": 8, "costo_unitario_usd": 25.0, "precio_promo_usd": 55.0},
            {"tipo_item": "COMPONENTE", "sku": "SIM-RAM-16", "descripcion": f"{PREFIJO} Memoria RAM 16GB DDR4", "cantidad": 6, "costo_unitario_usd": 20.0, "precio_promo_usd": 45.0},
            {"tipo_item": "ACCESORIO", "sku": "SIM-CARG-USB", "descripcion": f"{PREFIJO} Cargador USB-C 65W", "cantidad": 6, "costo_unitario_usd": 12.0, "precio_promo_usd": 30.0},
        ]
    )

    ing_ci = _req(
        client, "POST", "/api/logistica/ingresos", headers,
        json={
            "tipo_ingreso": "COMPRA_INTERNACIONAL",
            "proveedor_nombre": f"{PREFIJO} Miami Wholesale Tech LLC",
            "almacen_destino_id": almacen_id,
            "fecha": hoy_str,
            "referencia_factura": f"{PREFIJO} CI-SIM-001",
            "costo_flete_usd": 440.00,
            "costo_aduana_otros_usd": 220.00,
            "tracking_guia": "TRK-MIA-001, TRK-MIA-002, TRK-CCS-003",
            "observaciones": f"{PREFIJO} Compra internacional con 3 trackings y prorrateo automático",
            "items": items_ci,
        },
    )
    assert ing_ci["equipos_creados"] == 22, ing_ci

    # Consignación (5 equipos serializados)
    seriales_con = [f"SIM-CON-{idx:03d}" for idx in range(1, 6)]
    ing_con = _req(
        client, "POST", "/api/logistica/ingresos", headers,
        json={
            "tipo_ingreso": "CONSIGNACION",
            "proveedor_nombre": f"{PREFIJO} Proveedor Consignante Tech",
            "almacen_destino_id": almacen_id,
            "fecha": hoy_str,
            "referencia_factura": f"{PREFIJO} CON-SIM-001",
            "observaciones": f"{PREFIJO} Recepción de 5 equipos en consignación",
            "items": [
                {
                    "tipo_item": "EQUIPO",
                    "sku": "SIM-LAP-PRO",
                    "descripcion": f"{PREFIJO} Laptop Alfa Pro 14 i7 (Consignación)",
                    "serial": ser,
                    "cantidad": 1,
                    "costo_unitario_usd": 280.0,
                    "precio_promo_usd": 500.0,
                    "estado_inicial": "PENDIENTE_REVISION",
                }
                for ser in seriales_con
            ],
        },
    )
    assert ing_con["equipos_creados"] == 5, ing_con

    # =========================================================================
    # PASO 3: Recepción y Preparación con Componentes (costeo real)
    # =========================================================================
    print("3. Preparando equipos con instalación de componentes y pasando a DISPONIBLE...")
    equipos_alm = _req(client, "GET", f"/api/logistica/inventario/equipos?sucursal_id={almacen_id}", headers)
    eq_by_serial = {e["serial"]: e for e in equipos_alm if e["serial"].startswith("SIM-")}

    # Verificar prorrateo automático en el primer equipo internacional
    eq1 = eq_by_serial["SIM-INT-001"]
    assert float(eq1["costo_flete_usd"]) > 0, f"Prorrateo esperado > 0, recibido: {eq1}"

    # 6 equipos pasan a EN_PREPARACION con instalación de SSD o RAM
    prep_ids = [eq_by_serial[f"SIM-INT-{i:03d}"]["id"] for i in range(1, 7)]
    _req(
        client, "PATCH", "/api/preparaciones/estado-masivo", headers,
        json={
            "equipo_ids": prep_ids[:3],
            "nuevo_estado": "EN_PREPARACION",
            "observacion": f"{PREFIJO} Instalación de SSD NVMe 512GB en preparación",
            "componentes_instalados": [{"articulo_id": art_ssd, "cantidad": 1}],
        },
    )
    _req(
        client, "PATCH", "/api/preparaciones/estado-masivo", headers,
        json={
            "equipo_ids": prep_ids[3:6],
            "nuevo_estado": "EN_PREPARACION",
            "observacion": f"{PREFIJO} Instalación de RAM 16GB en preparación",
            "componentes_instalados": [{"articulo_id": art_ram, "cantidad": 1}],
        },
    )

    # Pasar todos los 27 equipos (22 intl + 5 consignación) a DISPONIBLE (LISTO)
    todos_eq_ids = [eq_by_serial[s]["id"] for s in (seriales_intl + seriales_con)]
    _req(
        client, "PATCH", "/api/preparaciones/estado-masivo", headers,
        json={
            "equipo_ids": todos_eq_ids,
            "nuevo_estado": "DISPONIBLE",
            "observacion": f"{PREFIJO} Control de calidad aprobado · Disponible para despacho",
        },
    )

    # =========================================================================
    # PASO 4: 2 Traslados Mixtos a Sede Principal y Sede 2 (Despacho + Recepción)
    # =========================================================================
    print("4. Creando 2 traslados mixtos a las sedes, generando comprobantes y confirmando recepción...")
    eq_sede1_seriales = seriales_intl[:11] + seriales_con[:3]   # 14 equipos -> Sede 1
    eq_sede2_seriales = seriales_intl[11:20] + seriales_con[3:5]  # 11 equipos -> Sede 2 (2 quedan en Almacén)

    trs1 = _req(
        client, "POST", "/api/logistica/traslados", headers,
        json={
            "origen_id": almacen_id,
            "destino_id": sede1_id,
            "equipos_ids": [eq_by_serial[s]["id"] for s in eq_sede1_seriales],
            "componentes": [
                {"articulo_id": art_carg, "cantidad": 4},
                {"articulo_id": art_ssd, "cantidad": 2},
            ],
            "nota": f"{PREFIJO} Comprobante de Despacho #1 hacia {sede_1['nombre']}",
        },
    )
    assert trs1["estado"] == "EN_TRANSITO"
    _req(
        client, "POST", f"/api/logistica/traslados/{trs1['id']}/confirmar", headers,
        json={"nota": f"{PREFIJO} Recepción conforme en {sede_1['nombre']}"},
    )

    trs2 = _req(
        client, "POST", "/api/logistica/traslados", headers,
        json={
            "origen_id": almacen_id,
            "destino_id": sede2_id,
            "equipos_ids": [eq_by_serial[s]["id"] for s in eq_sede2_seriales],
            "componentes": [
                {"articulo_id": art_carg, "cantidad": 2},
                {"articulo_id": art_ram, "cantidad": 2},
            ],
            "nota": f"{PREFIJO} Comprobante de Despacho #2 hacia {sede_2['nombre']}",
        },
    )
    assert trs2["estado"] == "EN_TRANSITO"
    _req(
        client, "POST", f"/api/logistica/traslados/{trs2['id']}/confirmar", headers,
        json={"nota": f"{PREFIJO} Recepción conforme en {sede_2['nombre']}"},
    )

    # =========================================================================
    # PASO 5: 20 Ventas Reales (todos los instrumentos, 4 Cashea, 2 CxC)
    # =========================================================================
    print("5. Registrando 20 ventas reales (todos los instrumentos, 4 Cashea, 2 CxC)...")
    cli_resp = _req(
        client, "POST", "/api/clientes", headers,
        json={
            "nombre": f"{PREFIJO} Cliente Corporativo Demo",
            "tipo_persona": "JURIDICO",
            "tipo_documento": "J",
            "documento": "SIM-50001234-1",
            "telefono": "0414-5550001",
            "direccion": "Valencia, Carabobo",
        },
    )
    cliente_id = int(cli_resp["id"])

    # Configuración de las 20 ventas:
    # (sucursal_id, serial, incluir_cargador, asesor_id, origen, modo_pago)
    # modo_pago: EFECTIVO | ZELLE | BINANCE | PAGO_MOVIL | TRANSF_BS | POS | CASHEA | CXC
    plan_ventas = [
        # 11 ventas en Sede 1 (9 intl + 2 consignación)
        (sede1_id, eq_sede1_seriales[0], True,  asesora_pres_id, "PASILLO", "EFECTIVO"),
        (sede1_id, eq_sede1_seriales[1], False, asesora_pres_id, "LEAD",    "ZELLE"),
        (sede1_id, eq_sede1_seriales[2], True,  enc1_id,         "PASILLO", "BINANCE"),
        (sede1_id, eq_sede1_seriales[3], False, enc1_id,         "LEAD",    "PAGO_MOVIL"),
        (sede1_id, eq_sede1_seriales[4], False, asesor_online_id,"LEAD",    "TRANSF_BS"),
        (sede1_id, eq_sede1_seriales[5], False, asesora_pres_id, "PASILLO", "POS"),
        (sede1_id, eq_sede1_seriales[6], False, asesora_pres_id, "LEAD",    "CASHEA"),
        (sede1_id, eq_sede1_seriales[7], False, enc1_id,         "PASILLO", "CASHEA"),
        (sede1_id, eq_sede1_seriales[8], False, asesor_online_id,"LEAD",    "CXC"),
        (sede1_id, eq_sede1_seriales[11],False, enc1_id,         "LEAD",    "EFECTIVO"),   # Consignación #1
        (sede1_id, eq_sede1_seriales[12],True,  asesora_pres_id, "PASILLO", "ZELLE"),      # Consignación #2
        # 9 ventas en Sede 2 (8 intl + 1 consignación)
        (sede2_id, eq_sede2_seriales[0], True,  enc2_id,         "PASILLO", "EFECTIVO"),
        (sede2_id, eq_sede2_seriales[1], False, enc2_id,         "LEAD",    "ZELLE"),
        (sede2_id, eq_sede2_seriales[2], False, asesor_online_id,"LEAD",    "BINANCE"),
        (sede2_id, eq_sede2_seriales[3], False, asesora_pres_id, "LEAD",    "PAGO_MOVIL"),
        (sede2_id, eq_sede2_seriales[4], False, enc2_id,         "PASILLO", "TRANSF_BS"),
        (sede2_id, eq_sede2_seriales[5], False, enc2_id,         "PASILLO", "POS"),
        (sede2_id, eq_sede2_seriales[6], False, asesor_online_id,"LEAD",    "CASHEA"),
        (sede2_id, eq_sede2_seriales[7], False, enc2_id,         "LEAD",    "CASHEA"),
        (sede2_id, eq_sede2_seriales[9], False, asesora_pres_id, "PASILLO", "CXC"),        # Consignación #4
    ]

    ventas_creadas: list[dict[str, Any]] = []
    total_pos_usd = 0.0

    for idx, (suc_v, ser_v, con_carg, as_id, orig_v, modo) in enumerate(plan_ventas, start=1):
        eq_obj = eq_by_serial[ser_v]
        art_id = int(eq_obj["articulo_id"])
        precio_promo = 500.0 if ser_v.startswith("SIM-CON-") else (480.0 if art_id == art_lap_pro else 410.0)
        items_v: list[dict[str, Any]] = [
            {"articulo_id": art_id, "equipo_id": eq_obj["id"], "cantidad": 1, "es_obsequio": False}
        ]
        if con_carg:
            items_v.append({"articulo_id": art_carg, "cantidad": 1, "es_obsequio": False})
            precio_promo += 30.0

        precio_reg = round(precio_promo * 1.20, 2)
        pagos_v: list[dict[str, Any]] = []
        es_cashea = modo == "CASHEA"
        es_cxc = modo == "CXC"
        cashea_fin = 0.0

        if modo == "EFECTIVO":
            pagos_v.append({"instrumento_id": inst_efectivo["id"], "monto_moneda_origen": precio_promo, "referencia": f"{PREFIJO} VTA-{idx:02d}-EFE"})
        elif modo == "ZELLE":
            pagos_v.append({"instrumento_id": inst_zelle["id"], "monto_moneda_origen": precio_promo, "referencia": f"{PREFIJO} VTA-{idx:02d}-ZEL"})
        elif modo == "BINANCE":
            pagos_v.append({"instrumento_id": inst_binance["id"], "monto_moneda_origen": precio_promo, "referencia": f"{PREFIJO} VTA-{idx:02d}-BIN"})
        elif modo == "PAGO_MOVIL":
            pagos_v.append({"instrumento_id": inst_pago_movil["id"], "monto_moneda_origen": round(precio_reg * tasa_bcv, 2), "referencia": f"{PREFIJO} VTA-{idx:02d}-PM"})
        elif modo == "TRANSF_BS":
            pagos_v.append({"instrumento_id": inst_transf_bs["id"], "monto_moneda_origen": round(precio_reg * tasa_bcv, 2), "referencia": f"{PREFIJO} VTA-{idx:02d}-TRF"})
        elif modo == "POS":
            total_pos_usd += precio_reg
            pagos_v.append({"instrumento_id": inst_pos["id"], "monto_moneda_origen": round(precio_reg * tasa_bcv, 2), "referencia": f"{PREFIJO} VTA-{idx:02d}-POS"})
        elif modo == "CASHEA":
            inicial = round(precio_reg * 0.40, 2)
            cashea_fin = round(precio_reg - inicial, 2)
            pagos_v.append({"instrumento_id": inst_efectivo["id"], "monto_moneda_origen": inicial, "referencia": f"{PREFIJO} VTA-{idx:02d}-CASHEA-INI"})
            pagos_v.append({"instrumento_id": inst_cashea["id"], "monto_moneda_origen": cashea_fin, "referencia": f"{PREFIJO} VTA-{idx:02d}-CASHEA-FIN"})
        elif modo == "CXC":
            abono = round(precio_promo * 0.50, 2)
            pagos_v.append({"instrumento_id": inst_zelle["id"], "monto_moneda_origen": abono, "referencia": f"{PREFIJO} VTA-{idx:02d}-CXC-ABO"})

        payload_vta: dict[str, Any] = {
            "sucursal_id": suc_v,
            "cliente_id": cliente_id,
            "asesor_id": as_id,
            "origen_venta": orig_v,
            "queda_con_saldo": es_cxc,
            "nota": f"{PREFIJO} Venta #{idx:02d} ({modo})",
            "items": items_v,
            "pagos": pagos_v,
        }
        vta = _req(client, "POST", "/api/ventas", headers, json=payload_vta)
        ventas_creadas.append(vta)

    assert len(ventas_creadas) == 20

    # =========================================================================
    # PASO 6: 2 Recepciones por Garantía (1 RESUELTA hoy, 1 PENDIENTE)
    # =========================================================================
    print("6. Registrando 2 casos de garantía (1 resuelta hoy, 1 pendiente)...")
    gar1 = _req(
        client, "POST", "/api/taller/casos", headers,
        json={
            "tipo": "GARANTIA",
            "sucursal_id": sede1_id,
            "cliente_id": cliente_id,
            "serial_o_codigo": eq_sede1_seriales[0],
            "descripcion_equipo": f"{PREFIJO} Laptop Alfa Pro 14 i7",
            "tipo_marca_color": "Laptop Alfa Gris",
            "accesorios_recibidos": "Cargador original",
            "estado_fisico": "Óptimo",
            "falla_reportada": f"{PREFIJO} Garantía #1: Tecla intermitente (Resuelta mismo día)",
        },
    )
    _req(
        client, "PATCH", f"/api/taller/casos/{gar1['id']}/actualizar", headers,
        json={
            "resultado_estado": "ENTREGADO",
            "tecnico_id": tecnico_id,
            "diagnostico": f"{PREFIJO} Ajuste de flex teclado y limpieza interna. Equipo 100% operativo.",
        },
    )

    gar2 = _req(
        client, "POST", "/api/taller/casos", headers,
        json={
            "tipo": "GARANTIA",
            "sucursal_id": sede2_id,
            "cliente_id": cliente_id,
            "serial_o_codigo": eq_sede2_seriales[0],
            "descripcion_equipo": f"{PREFIJO} Laptop Alfa Air 15 i5",
            "tipo_marca_color": "Laptop Alfa Plata",
            "accesorios_recibidos": "Sin accesorios",
            "estado_fisico": "Bueno",
            "falla_reportada": f"{PREFIJO} Garantía #2: Revisión de puerto USB-C (Pendiente al cierre)",
        },
    )
    _req(
        client, "PATCH", f"/api/taller/casos/{gar2['id']}/actualizar", headers,
        json={
            "resultado_estado": "EN_DIAGNOSTICO",
            "tecnico_id": tecnico_id,
            "diagnostico": f"{PREFIJO} En banco de pruebas de taller para diagnóstico de placa.",
        },
    )

    # =========================================================================
    # PASO 7: Pagos de Envíos Nacionales y Delivery Local (6.1.02)
    # =========================================================================
    print("7. Registrando pagos de envíos nacionales y delivery local (6.1.02)...")
    for num_f, prov, desc, monto in [
        ("SIM-ENV-001", f"{PREFIJO} MRW / Zoom Envíos", f"{PREFIJO} Envíos nacionales a clientes del interior", 85.00),
        ("SIM-DEL-002", f"{PREFIJO} Delivery Express Valencia", f"{PREFIJO} Delivery local y entregas motorizadas", 45.00),
    ]:
        g = _req(
            client, "POST", "/api/admin/gastos", headers,
            json={
                "numero_factura": num_f,
                "rif_proveedor": "J-40123456-0",
                "razon_social": prov,
                "categoria": "Envíos y Delivery",
                "observaciones": desc,
                "fecha_emision": hoy_str,
                "fecha_vencimiento": hoy_str,
                "base_imponible_bs": round(monto * tasa_bcv, 2),
                "monto_exento_bs": 0.0,
                "alicuota_iva": 0.0,
            },
        )
        _req(
            client, "POST", f"/api/admin/gastos/{g['id']}/pagar", headers,
            json={
                "instrumento_pago_id": inst_efectivo["id"],
                "monto_usd": monto,
                "referencia": f"{PREFIJO} {num_f}",
                "nota": desc,
            },
        )

    # =========================================================================
    # PASO 8: Nómina (7.1.01–7.1.04) + Liquidación y Pago de Comisiones (6.1.01)
    # =========================================================================
    print("8. Calculando y pagando Nómina (4 grupos) y Liquidación de Comisiones...")
    nom = _req(
        client, "POST", "/api/admin/nominas", headers,
        json={
            "tipo_periodo": "QUINCENAL",
            "fecha_inicio": hoy_str,
            "fecha_fin": hoy_str,
            "observaciones": f"{PREFIJO} Nómina quincenal completa (Encargados, Administradora, Director, Chofer)",
            "items": [
                {"personal_id": enc1_id, "observacion": f"{PREFIJO} Encargado S1"},
                {"personal_id": enc2_id, "observacion": f"{PREFIJO} Encargada S2"},
                {"personal_id": admin_usr_id, "observacion": f"{PREFIJO} Administradora"},
                {"personal_id": director_id, "observacion": f"{PREFIJO} Accionista / Director"},
                {"personal_id": chofer_id, "observacion": f"{PREFIJO} Chofer / Motorizado"},
            ],
        },
    )
    _req(
        client, "POST", f"/api/admin/nominas/{nom['id']}/pagar", headers,
        json={
            "instrumento_pago_id": inst_zelle["id"],
            "referencia_pago": f"{PREFIJO} NOM-Q1-PAGADA",
        },
    )

    # Liquidar y pagar comisiones de las 20 ventas por asesor/encargado
    ventas_por_asesor: dict[int, list[int]] = {}
    for v_info, (_, _, _, as_id, _, _) in zip(ventas_creadas, plan_ventas):
        ventas_por_asesor.setdefault(as_id, []).append(int(v_info["id"]))

    total_comisiones_liquidadas = 0.0
    for as_id, v_ids in ventas_por_asesor.items():
        liq = _req(
            client, "POST", "/api/comisiones/liquidaciones", headers,
            json={
                "personal_id": as_id,
                "fecha_inicio": hoy_str,
                "fecha_fin": hoy_str,
                "venta_ids": v_ids,
                "instrumento_pago_id": inst_efectivo["id"],
                "referencia": f"{PREFIJO} LIQ-COM-{as_id}",
                "observaciones": f"{PREFIJO} Liquidación quincenal de comisiones",
            },
        )
        total_comisiones_liquidadas += float(liq["monto_total_usd"])

    # =========================================================================
    # PASO 9: Alquileres, Condominio, Comisiones Bancarias e Impuestos
    # =========================================================================
    print("9. Registrando y pagando Alquileres, Condominio, Comisiones POS e Impuestos...")
    gastos_fijos_y_fin = [
        ("SIM-ALQ-LOC", f"{PREFIJO} Inmobiliaria CC Free Market", "Alquiler de Locales Comerciales", f"{PREFIJO} Alquiler mensual locales Sede 1 y Sede 2", 650.00),
        ("SIM-ALQ-ALM", f"{PREFIJO} Depósitos Industriales Carabobo", "Alquiler de Almacén", f"{PREFIJO} Alquiler mensual Almacén Central", 250.00),
        ("SIM-CON-001", f"{PREFIJO} Junta de Condominio Free Market", "Condominio", f"{PREFIJO} Condominio locales comerciales y almacén", 120.00),
    ]
    if total_pos_usd > 0:
        com_pos_usd = round(total_pos_usd * 0.025, 2)
        gastos_fijos_y_fin.append(
            ("SIM-COM-POS", f"{PREFIJO} Banco Nacional Punto de Venta", "Comisiones Bancarias", f"{PREFIJO} Comisiones bancarias 2.5% sobre ventas POS", com_pos_usd)
        )

    for num_f, prov, cat, desc, monto in gastos_fijos_y_fin:
        g = _req(
            client, "POST", "/api/admin/gastos", headers,
            json={
                "numero_factura": num_f,
                "rif_proveedor": "J-30987654-2",
                "razon_social": prov,
                "categoria": cat,
                "observaciones": desc,
                "fecha_emision": hoy_str,
                "fecha_vencimiento": hoy_str,
                "base_imponible_bs": round(monto * tasa_bcv, 2),
                "monto_exento_bs": 0.0,
                "alicuota_iva": 0.0,
            },
        )
        _req(
            client, "POST", f"/api/admin/gastos/{g['id']}/pagar", headers,
            json={
                "instrumento_pago_id": inst_transf_bs["id"],
                "monto_usd": monto,
                "referencia": f"{PREFIJO} {num_f}",
                "nota": desc,
            },
        )

    # Obligaciones fiscales: SENIAT (9.1.01) y Alcaldía (9.1.02)
    periodo_mes = hoy_str[:7]
    for org, tipo_ob, monto_ob in [
        ("SENIAT", f"{PREFIJO} Declaración ISLR / IGTF", 180.00),
        ("ALCALDIA", f"{PREFIJO} Patente Municipal ISAE", 95.00),
    ]:
        ob = _req(
            client, "POST", "/api/admin/fiscal/obligaciones", headers,
            json={
                "organismo": org,
                "tipo_obligacion": tipo_ob,
                "periodo": periodo_mes,
                "fecha_vencimiento": hoy_str,
                "monto_estimado_usd": monto_ob,
                "descripcion": f"{PREFIJO} Pago tributario {org}",
            },
        )
        _req(
            client, "POST", f"/api/admin/fiscal/obligaciones/{ob['id']}/pagar", headers,
            json={
                "instrumento_pago_id": inst_transf_bs["id"],
                "monto_pagado_usd": monto_ob,
                "referencia_pago": f"{PREFIJO} IMP-{org}",
            },
        )

    # =========================================================================
    # PASO 10: Repartición de Ganancias entre Socios (3.2.01)
    # =========================================================================
    print("10. Calculando utilidad distribuible y registrando Repartición de Ganancias...")
    pnl_prev = _req(client, "GET", f"/api/contabilidad/estado-resultados?fecha_inicio={hoy_str}&fecha_fin={hoy_str}", headers)
    utilidad_distribuible = max(0.0, round(float(pnl_prev["utilidad_neta_usd"]) * 0.30, 2))
    if utilidad_distribuible <= 0:
        utilidad_distribuible = 300.00

    div_a = round(utilidad_distribuible * 0.60, 2)
    div_b = round(utilidad_distribuible - div_a, 2)
    _req(
        client, "POST", "/api/contabilidad/movimiento-patrimonial", headers,
        json={
            "tipo": "REPARTICION_GANANCIAS",
            "instrumento_pago_id": inst_efectivo["id"],
            "monto_usd": div_a,
            "socio_nombre": f"{PREFIJO} Socio A (60%)",
            "referencia": f"{PREFIJO} DIV-SOCIO-A",
            "descripcion": f"{PREFIJO} Repartición de Ganancias Socio A (60%)",
            "fecha": hoy_str,
        },
    )
    _req(
        client, "POST", "/api/contabilidad/movimiento-patrimonial", headers,
        json={
            "tipo": "REPARTICION_GANANCIAS",
            "instrumento_pago_id": inst_zelle["id"],
            "monto_usd": div_b,
            "socio_nombre": f"{PREFIJO} Socio B (40%)",
            "referencia": f"{PREFIJO} DIV-SOCIO-B",
            "descripcion": f"{PREFIJO} Repartición de Ganancias Socio B (40%)",
            "fecha": hoy_str,
        },
    )

    # =========================================================================
    # PASO 11: Cierre Diario de Tienda (ambas sedes)
    # =========================================================================
    print("11. Ejecutando y guardando Cierre Diario de Tienda...")
    cierre_global = _req(client, "GET", f"/api/cierre-diario?fecha={hoy_str}", headers)
    assert cierre_global["ventas_dia"]["cantidad_total"] >= 20
    resueltas_raw = cierre_global["garantias_casos"]["resueltas_hoy"]
    resueltas_cnt = len(resueltas_raw) if isinstance(resueltas_raw, list) else int(resueltas_raw)
    assert resueltas_cnt >= 1
    assert cierre_global["garantias_casos"]["pendientes"]["total"] >= 1

    _req(
        client, "POST", "/api/cierre-diario/cerrar", headers,
        json={
            "fecha": hoy_str,
            "sucursal_id": sede1_id,
            "encargado_tienda_id": enc1_id,
            "observaciones": f"{PREFIJO} Cierre diario consolidado {sede_1['nombre']}",
        },
    )
    if sede2_id != sede1_id:
        _req(
            client, "POST", "/api/cierre-diario/cerrar", headers,
            json={
                "fecha": hoy_str,
                "sucursal_id": sede2_id,
                "encargado_tienda_id": enc2_id,
                "observaciones": f"{PREFIJO} Cierre diario consolidado {sede_2['nombre']}",
            },
        )

    # =========================================================================
    # REPORTE FINAL AUDITADO
    # =========================================================================
    pnl = _req(client, "GET", f"/api/contabilidad/estado-resultados?fecha_inicio={hoy_str}&fecha_fin={hoy_str}", headers)
    bal = _req(client, "GET", "/api/contabilidad/balance-general", headers)
    assert bal["ecuacion_cuadrada"] is True, f"Balance descuadrado: {bal}"

    print("\n" + "=" * 72)
    print("  REPORTE AUDITADO · SIMULACIÓN GENERAL ALFA [SIM-ALFA]")
    print("=" * 72)
    print(f"Fecha de operación (America/Caracas): {hoy_str} | Tasa BCV: Bs {tasa_bcv:.2f}")
    print(f"Ventas registradas: 20 (4 Cashea, 2 CxC) | Comisiones liquidadas: ${total_comisiones_liquidadas:,.2f}")
    print(f"Garantías del día: {resueltas_cnt} resuelta(s), {cierre_global['garantias_casos']['pendientes']['total']} pendiente(s)")
    print(f"Repartición a socios: ${utilidad_distribuible:,.2f} (Socio A: ${div_a:,.2f} / Socio B: ${div_b:,.2f})")

    print("\n--- 1. ESTADO DE RESULTADOS ESCALONADO (P&L) ---")
    print(f"  Total Ingresos:                  $ {pnl['ingresos_usd']:>12,.2f}")
    print(f"  (-) Costo de Ventas (COGS):      $ {pnl['costo_ventas_usd']:>12,.2f}")
    print(f"  = UTILIDAD BRUTA:                $ {pnl['utilidad_bruta_usd']:>12,.2f}")
    print(f"  (-) Gastos Variables:            $ {pnl['gastos_variables_usd']:>12,.2f}")
    print(f"  = MARGEN DE CONTRIBUCIÓN:        $ {pnl['margen_contribucion_usd']:>12,.2f}")
    print(f"  (-) Gastos Fijos:                $ {pnl['gastos_fijos_usd']:>12,.2f}")
    print(f"  = UTILIDAD OPERATIVA (EBIT):     $ {pnl['utilidad_operativa_ebit_usd']:>12,.2f}")
    print(f"  (-) Gastos Financieros:          $ {pnl['gastos_financieros_usd']:>12,.2f}")
    print(f"  (-) Impuestos:                   $ {pnl['impuestos_usd']:>12,.2f}")
    print(f"  = UTILIDAD NETA REAL:            $ {pnl['utilidad_neta_usd']:>12,.2f}")

    print("\n--- 2. BALANCE GENERAL ---")
    print(f"  TOTAL ACTIVOS:                   $ {bal['activos']['total_usd']:>12,.2f}")
    for it in bal["activos"]["detalle"]:
        print(f"    [{it['codigo']}] {it['nombre']:<44} $ {it['saldo_usd']:>10,.2f}")
    print(f"  TOTAL PASIVOS:                   $ {bal['pasivos']['total_usd']:>12,.2f}")
    for it in bal["pasivos"]["detalle"]:
        print(f"    [{it['codigo']}] {it['nombre']:<44} $ {it['saldo_usd']:>10,.2f}")
    print(f"  TOTAL PATRIMONIO:                $ {bal['patrimonio']['total_usd']:>12,.2f}")
    for it in bal["patrimonio"]["detalle"]:
        print(f"    [{it['codigo']}] {it['nombre']:<44} $ {it['saldo_usd']:>10,.2f}")
    print(f"  CUADRE (Activo - Pasivo - Pat.): $ {bal['diferencia_cuadre_usd']:>12,.2f} | ECUACIÓN CUADRADA: {bal['ecuacion_cuadrada']}")
    print("=" * 72)

    return {"pnl": pnl, "balance": bal, "cierre": cierre_global}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecuta la Simulación General Completa de Alfa [SIM-ALFA].")
    parser.add_argument(
        "--api-url",
        default=os.getenv("ALFA_API_URL", "https://alfa-admin-api.vercel.app"),
        help="URL base de la API de Alfa (default: https://alfa-admin-api.vercel.app)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Ejecuta la simulación con TestClient sobre la BD local configurada.",
    )
    parser.add_argument(
        "--correo",
        default=os.getenv("ALFA_ADMIN_EMAIL", "direccion@alfaimportaciones.com"),
    )
    parser.add_argument(
        "--clave",
        default=os.getenv("ALFA_ADMIN_PASSWORD", "Alfa2026!"),
    )
    parser.add_argument(
        "--sin-limpieza-previa",
        action="store_true",
        help="No limpia datos [SIM-ALFA] anteriores antes de correr.",
    )
    args = parser.parse_args()

    if args.local:
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as client:
            ejecutar_simulacion(client, args.correo, args.clave, limpiar_previo=not args.sin_limpieza_previa)
    else:
        import httpx

        with httpx.Client(base_url=args.api_url.rstrip("/"), timeout=60.0) as client:
            ejecutar_simulacion(client, args.correo, args.clave, limpiar_previo=not args.sin_limpieza_previa)


if __name__ == "__main__":
    main()
