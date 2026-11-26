"use client";

import React, { useMemo, useState } from "react";
import {
  ArrowDownCircle,
  ArrowUpCircle,
  BarChart3,
  Building2,
  Check,
  Copy,
  CreditCard,
  Filter,
  Landmark,
  MessageCircle,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { formatearBs, formatearUsd } from "@/servicios/api";
import type { CierreDiarioSnapshot } from "@/tipos/finanzas";

interface Props {
  cierre: CierreDiarioSnapshot;
  mensajeWhatsApp: string;
  onAbrirWhatsApp: () => void;
  onCopiarResumen: () => void;
  copiadoOk: boolean;
}

const COLORES_BARRAS = [
  "bg-[#003566]",
  "bg-emerald-600",
  "bg-indigo-600",
  "bg-amber-500",
  "bg-sky-500",
  "bg-violet-600",
  "bg-rose-500",
];

export default function DashboardCierreDiario({
  cierre,
  mensajeWhatsApp,
  onAbrirWhatsApp,
  onCopiarResumen,
  copiadoOk,
}: Props) {
  const [filtroCaja, setFiltroCaja] = useState<string>("TODAS");
  const [filtroSede, setFiltroSede] = useState<string>("TODAS");

  const esGeneral = cierre.alcance === "GENERAL";
  const rf = cierre.resumen_financiero;
  const cajas = useMemo(
    () => (cierre.saldos_cajas || []).filter((c) => c.es_liquidez),
    [cierre.saldos_cajas]
  );
  const comparativa = useMemo(
    () => cierre.comparativa_tiendas || [],
    [cierre.comparativa_tiendas]
  );
  const movimientos = useMemo(
    () => cierre.movimientos_dia || [],
    [cierre.movimientos_dia]
  );

  const opcionesCajas = useMemo(() => {
    const mapa = new Map<string, string>();
    for (const m of movimientos) {
      mapa.set(String(m.instrumento_id), m.instrumento_nombre);
    }
    return Array.from(mapa.entries()).sort((a, b) => a[1].localeCompare(b[1]));
  }, [movimientos]);

  const opcionesSedes = useMemo(() => {
    const set = new Set<string>();
    for (const m of movimientos) {
      set.add(m.sede_nombre);
    }
    return Array.from(set).sort();
  }, [movimientos]);

  const movimientosFiltrados = useMemo(() => {
    return movimientos.filter((m) => {
      if (filtroCaja !== "TODAS" && String(m.instrumento_id) !== filtroCaja) {
        return false;
      }
      if (filtroSede !== "TODAS" && m.sede_nombre !== filtroSede) {
        return false;
      }
      return true;
    });
  }, [movimientos, filtroCaja, filtroSede]);

  const maxIngEgr = Math.max(
    rf?.ingresos_totales_usd || 0,
    rf?.egresos_totales_usd || 0,
    1
  );

  const totalInstrumentos = Math.max(
    cierre.recibido_por_instrumento.total_usd || 0,
    1
  );

  const maxTienda = Math.max(
    ...comparativa.map((c) => Math.max(c.ventas_promo_usd, c.ingresos_usd)),
    1
  );

  return (
    <div className="space-y-6">
      {/* 1. Tarjetas KPI de Saldos por Caja/Banco (solo vista GENERAL) */}
      {esGeneral && rf && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="rounded-2xl bg-gradient-to-br from-[#001D3D] to-[#003566] p-5 text-white shadow-sm">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold uppercase tracking-wider text-sky-200">
                  Liquidez Total Disponible
                </span>
                <Wallet className="w-5 h-5 text-sky-300" />
              </div>
              <p className="mt-2 text-2xl font-black cifra-tabular">
                {formatearUsd(rf.liquidez_total_usd)}
              </p>
              <p className="mt-1 text-[11px] text-sky-200/90">
                Suma de todas las cajas y bancos activos
              </p>
            </div>

            <div className="rounded-2xl border border-emerald-200 bg-emerald-50/60 p-5">
              <div className="flex items-center justify-between text-emerald-700">
                <span className="text-[11px] font-bold uppercase tracking-wider">
                  Ingresos Totales del Día
                </span>
                <ArrowUpCircle className="w-5 h-5" />
              </div>
              <p className="mt-2 text-2xl font-black text-emerald-800 cifra-tabular">
                {formatearUsd(rf.ingresos_totales_usd)}
              </p>
              <p className="mt-1 text-[11px] text-emerald-700/80">
                Tiendas + Cashea inicial + CxC
              </p>
            </div>

            <div className="rounded-2xl border border-rose-200 bg-rose-50/60 p-5">
              <div className="flex items-center justify-between text-rose-700">
                <span className="text-[11px] font-bold uppercase tracking-wider">
                  Egresos Totales del Día
                </span>
                <ArrowDownCircle className="w-5 h-5" />
              </div>
              <p className="mt-2 text-2xl font-black text-rose-800 cifra-tabular">
                {formatearUsd(rf.egresos_totales_usd)}
              </p>
              <p className="mt-1 text-[11px] text-rose-700/80">
                Gastos, envíos, nómina, comisiones e impuestos
              </p>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="flex items-center justify-between text-[#003566]">
                <span className="text-[11px] font-bold uppercase tracking-wider">
                  Flujo Neto del Día
                </span>
                <TrendingUp className="w-5 h-5" />
              </div>
              <p
                className={`mt-2 text-2xl font-black cifra-tabular ${
                  rf.flujo_neto_usd >= 0 ? "text-emerald-700" : "text-rose-700"
                }`}
              >
                {rf.flujo_neto_usd >= 0 ? "+" : ""}
                {formatearUsd(rf.flujo_neto_usd)}
              </p>
              <p className="mt-1 text-[11px] text-slate-500">
                Ingresos menos egresos consolidados
              </p>
            </div>
          </div>

          {/* Grid de Saldos por Caja / Banco */}
          {cajas.length > 0 && (
            <div className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-black text-[#001D3D] flex items-center gap-2">
                  <Landmark className="w-4 h-4 text-[#003566]" />
                  Saldos Actuales por Caja y Banco ({cajas.length} cuentas)
                </h3>
                <span className="text-[11px] text-slate-500">
                  Saldo Inicial + Entradas - Salidas = Saldo Final
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {cajas.map((c) => (
                  <div
                    key={c.instrumento_id}
                    className="rounded-xl border border-slate-200 bg-slate-50/60 p-3.5 space-y-1.5"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-bold text-[#001D3D] truncate">
                        {c.nombre}
                      </span>
                      <span className="px-1.5 py-0.5 rounded bg-slate-200/80 text-[10px] font-bold text-slate-700">
                        {c.moneda}
                      </span>
                    </div>
                    <p className="text-lg font-black text-[#000814] cifra-tabular">
                      {c.moneda === "BS"
                        ? formatearBs(c.saldo_final)
                        : formatearUsd(c.saldo_final)}
                    </p>
                    {c.moneda === "BS" && (
                      <p className="text-[11px] font-semibold text-[#003566] cifra-tabular">
                        Equiv. {formatearUsd(c.saldo_final_usd)}
                      </p>
                    )}
                    <div className="pt-1.5 border-t border-slate-200/70 flex items-center justify-between text-[10px] text-slate-600 cifra-tabular">
                      <span>Ini: {c.saldo_inicial.toFixed(2)}</span>
                      <span className="text-emerald-700">
                        +{c.entradas.toFixed(2)}
                      </span>
                      <span className="text-rose-700">
                        -{c.salidas.toFixed(2)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 2. Gráficos claros del día */}
      {(rf || cierre.recibido_por_instrumento.items.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Gráfico A: Ingresos vs. Egresos */}
          {rf && (
            <div className="rounded-2xl border border-slate-200 bg-white p-5 space-y-4">
              <h3 className="text-sm font-black text-[#001D3D] flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-[#003566]" />
                Ingresos vs. Egresos del Día
              </h3>
              <div className="space-y-3">
                <div>
                  <div className="flex justify-between text-xs font-bold mb-1">
                    <span className="text-emerald-700">Ingresos</span>
                    <span className="cifra-tabular text-emerald-800">
                      {formatearUsd(rf.ingresos_totales_usd)}
                    </span>
                  </div>
                  <div className="h-3 w-full rounded-full bg-slate-100 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-emerald-500 transition-all"
                      style={{
                        width: `${Math.min(100, (rf.ingresos_totales_usd / maxIngEgr) * 100)}%`,
                      }}
                    />
                  </div>
                </div>

                <div>
                  <div className="flex justify-between text-xs font-bold mb-1">
                    <span className="text-rose-700">Egresos</span>
                    <span className="cifra-tabular text-rose-800">
                      {formatearUsd(rf.egresos_totales_usd)}
                    </span>
                  </div>
                  <div className="h-3 w-full rounded-full bg-slate-100 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-rose-500 transition-all"
                      style={{
                        width: `${Math.min(100, (rf.egresos_totales_usd / maxIngEgr) * 100)}%`,
                      }}
                    />
                  </div>
                </div>

                <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs">
                  <span className="font-semibold text-slate-600">Flujo Neto</span>
                  <span
                    className={`font-black cifra-tabular ${
                      rf.flujo_neto_usd >= 0 ? "text-emerald-700" : "text-rose-700"
                    }`}
                  >
                    {formatearUsd(rf.flujo_neto_usd)}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Gráfico B: Distribución de ingresos por instrumento */}
          <div
            className={`rounded-2xl border border-slate-200 bg-white p-5 space-y-3 ${
              !rf ? "lg:col-span-3" : ""
            }`}
          >
            <h3 className="text-sm font-black text-[#001D3D] flex items-center gap-2">
              <CreditCard className="w-4 h-4 text-[#003566]" />
              Ingresos por Instrumento de Pago
            </h3>
            {cierre.recibido_por_instrumento.items.length === 0 ? (
              <p className="text-xs text-slate-500 py-6 text-center">
                Sin ingresos registrados en esta fecha.
              </p>
            ) : (
              <div className="space-y-2.5">
                {cierre.recibido_por_instrumento.items.map((it, idx) => {
                  const pct = Math.round((it.total_usd / totalInstrumentos) * 100);
                  return (
                    <div key={it.instrumento_id} className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="font-semibold text-slate-700 truncate pr-2">
                          {it.instrumento}
                        </span>
                        <span className="font-bold text-[#001D3D] cifra-tabular shrink-0">
                          {formatearUsd(it.total_usd)} ({pct}%)
                        </span>
                      </div>
                      <div className="h-2.5 w-full rounded-full bg-slate-100 overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            COLORES_BARRAS[idx % COLORES_BARRAS.length]
                          }`}
                          style={{ width: `${Math.max(2, pct)}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Gráfico C: Comparativa de ventas por tienda (solo GENERAL) */}
          {esGeneral && comparativa.length > 0 && (
            <div className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3">
              <h3 className="text-sm font-black text-[#001D3D] flex items-center gap-2">
                <Building2 className="w-4 h-4 text-[#003566]" />
                Comparativa por Tienda y Admin
              </h3>
              <div className="space-y-3">
                {comparativa.map((c) => {
                  const baseVal = Math.max(c.ventas_promo_usd, c.ingresos_usd);
                  const pct = Math.round((baseVal / maxTienda) * 100);
                  return (
                    <div key={c.nombre} className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="font-bold text-slate-800 truncate pr-2">
                          {c.nombre}
                        </span>
                        <span className="cifra-tabular font-bold text-[#003566]">
                          {c.cantidad_ventas} vtas · {formatearUsd(c.ingresos_usd)}
                        </span>
                      </div>
                      <div className="h-2.5 w-full rounded-full bg-slate-100 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-[#003566]"
                          style={{ width: `${baseVal > 0 ? Math.max(4, pct) : 0}%` }}
                        />
                      </div>
                      {c.egresos_usd > 0 && (
                        <p className="text-[10px] text-rose-700 cifra-tabular">
                          Egresos: -{formatearUsd(c.egresos_usd)} · Neto:{" "}
                          {formatearUsd(c.flujo_neto_usd)}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 3. Bitácora / Tabla de Movimientos del Día (visible para ADMIN / DIRECTOR) */}
      {cierre.movimientos_dia && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-sm font-black text-[#001D3D] flex items-center gap-2">
              <Filter className="w-4 h-4 text-[#003566]" />
              Bitácora de Movimientos del Día ({movimientosFiltrados.length})
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={filtroCaja}
                onChange={(e) => setFiltroCaja(e.target.value)}
                className="px-3 py-1.5 rounded-xl border border-slate-300 text-xs font-semibold bg-white"
              >
                <option value="TODAS">Todas las cajas/bancos</option>
                {opcionesCajas.map(([id, nom]) => (
                  <option key={id} value={id}>
                    {nom}
                  </option>
                ))}
              </select>
              {esGeneral && (
                <select
                  value={filtroSede}
                  onChange={(e) => setFiltroSede(e.target.value)}
                  className="px-3 py-1.5 rounded-xl border border-slate-300 text-xs font-semibold bg-white"
                >
                  <option value="TODAS">Todas las sedes</option>
                  {opcionesSedes.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>

          {movimientosFiltrados.length === 0 ? (
            <p className="text-xs text-slate-500 text-center py-6">
              No hay movimientos que coincidan con el filtro seleccionado.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 text-[11px] uppercase text-slate-600">
                  <tr>
                    <th className="px-3 py-2">Hora</th>
                    <th className="px-3 py-2">Sede</th>
                    <th className="px-3 py-2">Caja / Banco</th>
                    <th className="px-3 py-2">Tipo</th>
                    <th className="px-3 py-2">Concepto</th>
                    <th className="px-3 py-2 text-right">Monto</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {movimientosFiltrados.map((m) => {
                    const esIng = m.tipo_movimiento === "INGRESO";
                    return (
                      <tr key={m.id} className="hover:bg-slate-50/70">
                        <td className="px-3 py-2 text-slate-500 cifra-tabular">
                          {m.hora}
                        </td>
                        <td className="px-3 py-2 font-semibold text-slate-700">
                          {m.sede_nombre}
                        </td>
                        <td className="px-3 py-2 text-slate-700">
                          {m.instrumento_nombre}
                        </td>
                        <td className="px-3 py-2">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold ${
                              esIng
                                ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                : "bg-rose-50 text-rose-700 border border-rose-200"
                            }`}
                          >
                            {m.tipo_movimiento}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-slate-800">
                          {m.concepto}
                          {m.referencia && (
                            <span className="ml-1.5 text-[10px] text-slate-400 font-mono">
                              ({m.referencia})
                            </span>
                          )}
                        </td>
                        <td
                          className={`px-3 py-2 text-right font-bold cifra-tabular ${
                            esIng ? "text-emerald-700" : "text-rose-700"
                          }`}
                        >
                          {esIng ? "+" : "-"}
                          {formatearUsd(m.monto_usd)}
                          {m.moneda === "BS" && (
                            <span className="block text-[10px] font-normal text-slate-500">
                              {formatearBs(m.monto_moneda_origen)}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* 4. Vista previa del Mensaje de WhatsApp */}
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50/40 p-5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-black text-emerald-900 flex items-center gap-2">
            <MessageCircle className="w-4 h-4 text-emerald-600" />
            Vista Previa del Mensaje de WhatsApp (
            {esGeneral ? "Consolidado General" : cierre.jornada.sucursal_nombre})
          </h3>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onCopiarResumen}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-emerald-300 bg-white hover:bg-emerald-50 text-emerald-800 text-xs font-bold cursor-pointer"
            >
              {copiadoOk ? (
                <Check className="w-3.5 h-3.5 text-emerald-600" />
              ) : (
                <Copy className="w-3.5 h-3.5" />
              )}
              {copiadoOk ? "¡Copiado!" : "Copiar mensaje"}
            </button>
            <button
              type="button"
              onClick={onAbrirWhatsApp}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold cursor-pointer"
            >
              <MessageCircle className="w-3.5 h-3.5" />
              {esGeneral
                ? "Enviar Cierre General por WhatsApp"
                : "Enviar Cierre de Tienda por WhatsApp"}
            </button>
          </div>
        </div>
        <pre className="whitespace-pre-wrap rounded-xl border border-emerald-200/80 bg-white p-4 text-xs font-mono text-slate-800 max-h-72 overflow-y-auto leading-relaxed">
          {mensajeWhatsApp}
        </pre>
      </div>
    </div>
  );
}
