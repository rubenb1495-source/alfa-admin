"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  ArrowDownLeft,
  ArrowUpRight,
  Boxes,
  Building2,
  Loader2,
  RefreshCw,
  ShoppingBag,
  TrendingUp,
  Truck,
  Users,
  Wallet,
} from "lucide-react";
import {
  ErrorApi,
  fechaHoyCaracas,
  formatearBs,
  formatearUsd,
  solicitarApi,
} from "@/servicios/api";
import type { Sucursal } from "@/tipos/dominio";

interface ResumenDireccion {
  periodo: {
    fecha_inicio: string;
    fecha_fin: string;
    sucursal_id: number | null;
    total_ventas: number;
    facturacion_usd: number;
  };
  tasas: {
    tasa_bcv: number;
    tasa_usdt: number;
  };
  disponible_cuentas: {
    total_consolidado_usd: number;
    cuentas: {
      id: number;
      nombre: string;
      moneda: string;
      saldo_nativo: number;
      saldo_usd: number;
    }[];
  };
  inventario: {
    fisico: {
      equipos: number;
      productos: number;
      valor_costo_usd: number;
      valor_promo_usd: number;
      por_sucursal: {
        sucursal_id: number;
        sucursal: string;
        equipos: number;
        productos: number;
        valor_costo_usd: number;
        valor_promo_usd: number;
      }[];
    };
    en_transito: {
      equipos: number;
      valor_costo_usd: number;
      valor_promo_usd: number;
      traslados_en_transito: number;
      compras_pendientes: number;
      compras_pendientes_usd: number;
    };
  };
  cuentas_por_cobrar: {
    total_cxc_usd: number;
    clientes_usd: number;
    cashea_usd: number;
    listado: {
      id: number;
      tipo: string;
      cliente: string;
      numero_venta: string;
      saldo_pendiente_usd: number;
      fecha_vencimiento: string | null;
    }[];
  };
  cuentas_por_pagar: {
    total_cxp_usd: number;
    consignaciones_usd: number;
    comisiones_pendientes_usd: number;
    compras_pendientes_usd: number;
  };
  mas_vendidos: {
    sku: string;
    descripcion: string;
    unidades: number;
    monto_usd: number;
  }[];
  ventas_por_asesor: {
    asesor_id: number | null;
    nombre: string;
    rol: string;
    modalidad: string;
    ventas_pasillo: number;
    ventas_lead: number;
    total_ventas: number;
    monto_usd: number;
  }[];
  ventas_por_tienda: {
    sucursal_id: number;
    sucursal: string;
    cantidad_ventas: number;
    monto_usd: number;
    ticket_promedio_usd: number;
  }[];
}

type RangoRapido = "hoy" | "semana" | "quincena" | "mes" | "personalizado";

function calcularRango(tipo: RangoRapido): { inicio: string; fin: string } {
  const hoyStr = fechaHoyCaracas();
  const [anio, mes, dia] = hoyStr.split("-").map(Number);
  const fin = hoyStr;

  if (tipo === "hoy") return { inicio: hoyStr, fin };
  if (tipo === "semana") {
    const d = new Date(anio, mes - 1, dia - 6);
    const ini = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    return { inicio: ini, fin };
  }
  if (tipo === "quincena") {
    const iniDia = dia <= 15 ? 1 : 16;
    const ini = `${anio}-${String(mes).padStart(2, "0")}-${String(iniDia).padStart(2, "0")}`;
    return { inicio: ini, fin };
  }
  // mes
  const ini = `${anio}-${String(mes).padStart(2, "0")}-01`;
  return { inicio: ini, fin };
}

export default function PaginaPanelDireccion() {
  const rangoInicial = calcularRango("mes");
  const [rango, setRango] = useState<RangoRapido>("mes");
  const [fechaInicio, setFechaInicio] = useState(rangoInicial.inicio);
  const [fechaFin, setFechaFin] = useState(rangoInicial.fin);
  const [sucursalId, setSucursalId] = useState("");
  const [sucursales, setSucursales] = useState<Sucursal[]>([]);
  const [resumen, setResumen] = useState<ResumenDireccion | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        fecha_inicio: fechaInicio,
        fecha_fin: fechaFin,
      });
      if (sucursalId) qs.set("sucursal_id", sucursalId);

      const [respRes, respSuc] = await Promise.all([
        solicitarApi<ResumenDireccion>(`/api/direccion/resumen?${qs.toString()}`),
        solicitarApi<Sucursal[]>("/api/sucursales"),
      ]);
      setResumen(respRes);
      setSucursales(respSuc);
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo cargar el Panel Ejecutivo."
      );
    } finally {
      setCargando(false);
    }
  }, [fechaInicio, fechaFin, sucursalId]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  const seleccionarRango = (nuevo: RangoRapido) => {
    setRango(nuevo);
    if (nuevo !== "personalizado") {
      const { inicio, fin } = calcularRango(nuevo);
      setFechaInicio(inicio);
      setFechaFin(fin);
    }
  };

  return (
    <div className="space-y-6">
      {/* Cabecera */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-[#EDF3FA] px-3 py-1 text-[11px] font-bold uppercase tracking-wider text-[#003566]">
            <TrendingUp className="h-3.5 w-3.5" />
            Dirección Ejecutiva · Solo Lectura
          </span>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-[#001D3D]">
            Panel Ejecutivo ALFA
          </h1>
          <p className="text-xs text-slate-600">
            Disponibilidad de cajas, inventario físico/tránsito, CxC/CxP y desempeño comercial en vivo.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void cargar()}
          disabled={cargando}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
        >
          <RefreshCw className={`h-4 w-4 ${cargando ? "animate-spin" : ""}`} />
          Actualizar
        </button>
      </div>

      {/* Filtros rápidos de fecha y sucursal */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
        <div className="flex flex-wrap gap-1.5">
          {(
            [
              { id: "hoy", label: "Hoy" },
              { id: "semana", label: "Semana" },
              { id: "quincena", label: "Quincena" },
              { id: "mes", label: "Mes" },
              { id: "personalizado", label: "Personalizado" },
            ] as const
          ).map((btn) => (
            <button
              key={btn.id}
              type="button"
              onClick={() => seleccionarRango(btn.id)}
              className={`rounded-xl px-3.5 py-1.5 text-xs font-bold transition cursor-pointer ${
                rango === btn.id
                  ? "bg-[#003566] text-white"
                  : "bg-slate-100 text-slate-700 hover:bg-slate-200"
              }`}
            >
              {btn.label}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {rango === "personalizado" && (
            <>
              <input
                type="date"
                value={fechaInicio}
                onChange={(e) => setFechaInicio(e.target.value)}
                className="rounded-xl border border-slate-300 px-3 py-1.5 text-xs"
              />
              <span className="text-xs text-slate-400">a</span>
              <input
                type="date"
                value={fechaFin}
                onChange={(e) => setFechaFin(e.target.value)}
                className="rounded-xl border border-slate-300 px-3 py-1.5 text-xs"
              />
            </>
          )}
          <select
            value={sucursalId}
            onChange={(e) => setSucursalId(e.target.value)}
            className="rounded-xl border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700"
          >
            <option value="">Todas las tiendas / almacenes</option>
            {sucursales.map((s) => (
              <option key={s.id} value={s.id}>
                {s.nombre}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {cargando || !resumen ? (
        <div className="flex items-center justify-center gap-2 py-20 text-sm text-slate-500">
          <Loader2 className="h-5 w-5 animate-spin text-[#003566]" />
          Consolidando indicadores ejecutivos...
        </div>
      ) : (
        <>
          {/* KPIs principales */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-2xl border border-[#003566]/20 bg-[#003566] p-5 text-white shadow-sm">
              <div className="flex items-center justify-between text-xs text-sky-200">
                <span>Disponible en Cajas / Cuentas</span>
                <Wallet className="h-4 w-4" />
              </div>
              <p className="mt-2 text-2xl font-black cifra-tabular">
                {formatearUsd(resumen.disponible_cuentas.total_consolidado_usd)}
              </p>
              <p className="mt-1 text-[11px] text-sky-200">
                Consolidado USD · BCV {formatearBs(resumen.tasas.tasa_bcv)}
              </p>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs">
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>Facturación del Periodo</span>
                <TrendingUp className="h-4 w-4 text-emerald-600" />
              </div>
              <p className="mt-2 text-2xl font-black text-[#001D3D] cifra-tabular">
                {formatearUsd(resumen.periodo.facturacion_usd)}
              </p>
              <p className="mt-1 text-[11px] text-slate-500">
                {resumen.periodo.total_ventas} venta(s) · {resumen.periodo.fecha_inicio} al{" "}
                {resumen.periodo.fecha_fin}
              </p>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs">
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>Inventario Físico (Costo)</span>
                <Boxes className="h-4 w-4 text-[#003566]" />
              </div>
              <p className="mt-2 text-2xl font-black text-[#001D3D] cifra-tabular">
                {formatearUsd(resumen.inventario.fisico.valor_costo_usd)}
              </p>
              <p className="mt-1 text-[11px] text-slate-500">
                Promo: {formatearUsd(resumen.inventario.fisico.valor_promo_usd)} ·{" "}
                {resumen.inventario.fisico.equipos} eq / {resumen.inventario.fisico.productos} prod
              </p>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs">
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>CxC vs CxP</span>
                <ArrowDownLeft className="h-4 w-4 text-amber-600" />
              </div>
              <div className="mt-2 flex items-baseline justify-between">
                <div>
                  <span className="text-[10px] font-bold uppercase text-emerald-700">
                    Por Cobrar
                  </span>
                  <p className="text-lg font-black text-emerald-700 cifra-tabular">
                    {formatearUsd(resumen.cuentas_por_cobrar.total_cxc_usd)}
                  </p>
                </div>
                <div className="text-right">
                  <span className="text-[10px] font-bold uppercase text-red-600">
                    Por Pagar
                  </span>
                  <p className="text-lg font-black text-red-600 cifra-tabular">
                    {formatearUsd(resumen.cuentas_por_pagar.total_cxp_usd)}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* 1. Disponible en Cajas y Cuentas + 2. Inventario Físico y en Tránsito */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-xs">
              <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-5 py-3.5">
                <h2 className="flex items-center gap-2 text-sm font-bold text-[#001D3D]">
                  <Wallet className="h-4 w-4 text-[#003566]" />
                  Disponible en Cajas y Cuentas
                </h2>
                <span className="text-xs font-bold text-[#003566]">
                  {formatearUsd(resumen.disponible_cuentas.total_consolidado_usd)}
                </span>
              </div>
              <div className="divide-y divide-slate-100">
                {resumen.disponible_cuentas.cuentas.map((c) => (
                  <div
                    key={c.id}
                    className="flex items-center justify-between px-5 py-3 text-sm"
                  >
                    <div>
                      <p className="font-semibold text-slate-800">{c.nombre}</p>
                      <span className="text-[11px] font-medium text-slate-500">
                        Moneda: {c.moneda}
                      </span>
                    </div>
                    <div className="text-right cifra-tabular">
                      <p className="font-bold text-[#001D3D]">
                        {c.moneda === "BS"
                          ? formatearBs(c.saldo_nativo)
                          : formatearUsd(c.saldo_nativo)}
                      </p>
                      {c.moneda === "BS" && (
                        <p className="text-[11px] text-slate-500">
                          ≈ {formatearUsd(c.saldo_usd)}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-xs">
              <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-5 py-3.5">
                <h2 className="flex items-center gap-2 text-sm font-bold text-[#001D3D]">
                  <Boxes className="h-4 w-4 text-[#003566]" />
                  Inventario Físico y en Tránsito
                </h2>
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-bold text-amber-800">
                  <Truck className="h-3 w-3" />
                  Tránsito: {resumen.inventario.en_transito.equipos} eq (
                  {formatearUsd(resumen.inventario.en_transito.valor_costo_usd)})
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-50/70 text-slate-500 uppercase">
                    <tr>
                      <th className="px-4 py-2.5">Tienda / Almacén</th>
                      <th className="px-4 py-2.5 text-center">Eq / Prod</th>
                      <th className="px-4 py-2.5 text-right">Costo USD</th>
                      <th className="px-4 py-2.5 text-right">Promo USD</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {resumen.inventario.fisico.por_sucursal.map((s) => (
                      <tr key={s.sucursal_id}>
                        <td className="px-4 py-2.5 font-semibold text-slate-800">
                          {s.sucursal}
                        </td>
                        <td className="px-4 py-2.5 text-center text-slate-600">
                          {s.equipos} / {s.productos}
                        </td>
                        <td className="px-4 py-2.5 text-right font-semibold text-slate-700 cifra-tabular">
                          {formatearUsd(s.valor_costo_usd)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-bold text-emerald-700 cifra-tabular">
                          {formatearUsd(s.valor_promo_usd)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="border-t border-slate-100 bg-slate-50/60 px-4 py-2.5 text-[11px] text-slate-600 flex flex-wrap justify-between gap-2">
                <span>
                  Traslados en camino:{" "}
                  <strong>{resumen.inventario.en_transito.traslados_en_transito}</strong>
                </span>
                <span>
                  Compras en tránsito:{" "}
                  <strong>
                    {resumen.inventario.en_transito.compras_pendientes} (
                    {formatearUsd(resumen.inventario.en_transito.compras_pendientes_usd)})
                  </strong>
                </span>
              </div>
            </div>
          </div>

          {/* 3. Cuentas por Cobrar y Cuentas por Pagar */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-xs">
              <div className="flex items-center justify-between border-b border-slate-100 bg-emerald-50/60 px-5 py-3.5">
                <h2 className="flex items-center gap-2 text-sm font-bold text-emerald-900">
                  <ArrowDownLeft className="h-4 w-4 text-emerald-700" />
                  Cuentas por Cobrar (CxC)
                </h2>
                <span className="text-sm font-black text-emerald-800">
                  {formatearUsd(resumen.cuentas_por_cobrar.total_cxc_usd)}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3 p-4 border-b border-slate-100 text-xs">
                <div className="rounded-xl bg-slate-50 p-3">
                  <p className="text-slate-500">Clientes / Créditos</p>
                  <p className="mt-1 text-base font-bold text-[#001D3D]">
                    {formatearUsd(resumen.cuentas_por_cobrar.clientes_usd)}
                  </p>
                </div>
                <div className="rounded-xl bg-slate-50 p-3">
                  <p className="text-slate-500">Cashea por Liquidar</p>
                  <p className="mt-1 text-base font-bold text-[#001D3D]">
                    {formatearUsd(resumen.cuentas_por_cobrar.cashea_usd)}
                  </p>
                </div>
              </div>
              {resumen.cuentas_por_cobrar.listado.length === 0 ? (
                <p className="p-5 text-center text-xs text-slate-500">
                  Sin cuentas por cobrar pendientes.
                </p>
              ) : (
                <div className="divide-y divide-slate-100 max-h-56 overflow-y-auto">
                  {resumen.cuentas_por_cobrar.listado.map((c) => (
                    <div
                      key={c.id}
                      className="flex items-center justify-between px-4 py-2.5 text-xs"
                    >
                      <div>
                        <p className="font-semibold text-slate-800">{c.cliente}</p>
                        <p className="text-[11px] text-slate-500">
                          {c.tipo} · Nota {c.numero_venta}
                        </p>
                      </div>
                      <span className="font-bold text-emerald-700 cifra-tabular">
                        {formatearUsd(c.saldo_pendiente_usd)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-xs">
              <div className="flex items-center justify-between border-b border-slate-100 bg-red-50/60 px-5 py-3.5">
                <h2 className="flex items-center gap-2 text-sm font-bold text-red-900">
                  <ArrowUpRight className="h-4 w-4 text-red-700" />
                  Cuentas por Pagar (CxP)
                </h2>
                <span className="text-sm font-black text-red-700">
                  {formatearUsd(resumen.cuentas_por_pagar.total_cxp_usd)}
                </span>
              </div>
              <div className="divide-y divide-slate-100 text-sm">
                <div className="flex items-center justify-between px-5 py-3.5">
                  <span className="text-slate-700">Comisiones pendientes de pago</span>
                  <span className="font-bold text-red-700 cifra-tabular">
                    {formatearUsd(resumen.cuentas_por_pagar.comisiones_pendientes_usd)}
                  </span>
                </div>
                <div className="flex items-center justify-between px-5 py-3.5">
                  <span className="text-slate-700">
                    Consignaciones vendidas por liquidar
                  </span>
                  <span className="font-bold text-red-700 cifra-tabular">
                    {formatearUsd(resumen.cuentas_por_pagar.consignaciones_usd)}
                  </span>
                </div>
                <div className="flex items-center justify-between px-5 py-3.5">
                  <span className="text-slate-700">
                    Compras pendientes / por recibir
                  </span>
                  <span className="font-bold text-red-700 cifra-tabular">
                    {formatearUsd(resumen.cuentas_por_pagar.compras_pendientes_usd)}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* 4. Top 10 Lo Más Vendido + 6. Ventas por Tienda */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-xs">
              <div className="border-b border-slate-100 bg-slate-50 px-5 py-3.5">
                <h2 className="flex items-center gap-2 text-sm font-bold text-[#001D3D]">
                  <ShoppingBag className="h-4 w-4 text-[#003566]" />
                  Top 10 · Lo Más Vendido
                </h2>
              </div>
              {resumen.mas_vendidos.length === 0 ? (
                <p className="p-6 text-center text-xs text-slate-500">
                  Sin ventas registradas en este periodo.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left">
                    <thead className="bg-slate-50/70 text-slate-500 uppercase">
                      <tr>
                        <th className="px-4 py-2.5">Producto / SKU</th>
                        <th className="px-4 py-2.5 text-center">Und.</th>
                        <th className="px-4 py-2.5 text-right">Monto USD</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {resumen.mas_vendidos.map((p, idx) => (
                        <tr key={`${p.sku}-${idx}`}>
                          <td className="px-4 py-2.5">
                            <p className="font-semibold text-slate-800">{p.descripcion}</p>
                            <p className="font-mono text-[10px] text-slate-500">{p.sku}</p>
                          </td>
                          <td className="px-4 py-2.5 text-center font-bold text-[#003566]">
                            {p.unidades}
                          </td>
                          <td className="px-4 py-2.5 text-right font-bold text-[#001D3D] cifra-tabular">
                            {formatearUsd(p.monto_usd)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-xs">
              <div className="border-b border-slate-100 bg-slate-50 px-5 py-3.5">
                <h2 className="flex items-center gap-2 text-sm font-bold text-[#001D3D]">
                  <Building2 className="h-4 w-4 text-[#003566]" />
                  Ventas por Tienda / Sucursal
                </h2>
              </div>
              {resumen.ventas_por_tienda.length === 0 ? (
                <p className="p-6 text-center text-xs text-slate-500">
                  Sin ventas registradas en este periodo.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left">
                    <thead className="bg-slate-50/70 text-slate-500 uppercase">
                      <tr>
                        <th className="px-4 py-2.5">Sucursal</th>
                        <th className="px-4 py-2.5 text-center">Ventas</th>
                        <th className="px-4 py-2.5 text-right">Ticket Prom.</th>
                        <th className="px-4 py-2.5 text-right">Facturación</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {resumen.ventas_por_tienda.map((t) => (
                        <tr key={t.sucursal_id}>
                          <td className="px-4 py-2.5 font-semibold text-slate-800">
                            {t.sucursal}
                          </td>
                          <td className="px-4 py-2.5 text-center text-slate-700">
                            {t.cantidad_ventas}
                          </td>
                          <td className="px-4 py-2.5 text-right text-slate-600 cifra-tabular">
                            {formatearUsd(t.ticket_promedio_usd)}
                          </td>
                          <td className="px-4 py-2.5 text-right font-bold text-[#003566] cifra-tabular">
                            {formatearUsd(t.monto_usd)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          {/* 5. Ventas por Asesor */}
          <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-xs">
            <div className="border-b border-slate-100 bg-slate-50 px-5 py-3.5">
              <h2 className="flex items-center gap-2 text-sm font-bold text-[#001D3D]">
                <Users className="h-4 w-4 text-[#003566]" />
                Ventas por Asesor (Presenciales y Online)
              </h2>
            </div>
            {resumen.ventas_por_asesor.length === 0 ? (
              <p className="p-6 text-center text-xs text-slate-500">
                Sin ventas por asesor en este periodo.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-50/70 text-slate-500 uppercase">
                    <tr>
                      <th className="px-4 py-2.5">Asesor</th>
                      <th className="px-4 py-2.5">Modalidad</th>
                      <th className="px-4 py-2.5 text-center">Pasillo</th>
                      <th className="px-4 py-2.5 text-center">Lead</th>
                      <th className="px-4 py-2.5 text-center">Total Ventas</th>
                      <th className="px-4 py-2.5 text-right">Monto Vendido USD</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {resumen.ventas_por_asesor.map((a, idx) => (
                      <tr key={`${a.asesor_id ?? "tienda"}-${idx}`}>
                        <td className="px-4 py-2.5">
                          <span className="font-semibold text-slate-800">{a.nombre}</span>
                          <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold text-slate-600">
                            {a.rol}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-slate-600">{a.modalidad}</td>
                        <td className="px-4 py-2.5 text-center">{a.ventas_pasillo}</td>
                        <td className="px-4 py-2.5 text-center font-semibold text-[#003566]">
                          {a.ventas_lead}
                        </td>
                        <td className="px-4 py-2.5 text-center font-bold">
                          {a.total_ventas}
                        </td>
                        <td className="px-4 py-2.5 text-right font-bold text-emerald-700 cifra-tabular">
                          {formatearUsd(a.monto_usd)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
