"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  CreditCard,
  Download,
  Landmark,
  X,
} from "lucide-react";
import { usarSesion } from "@/contexto/SesionContexto";
import {
  ErrorApi,
  descargarPdfApi,
  esRolAdministrativo,
  fechaHoyCaracas,
  formatearBs,
  formatearUsd,
  solicitarApi,
} from "@/servicios/api";
import type { Sucursal } from "@/tipos/dominio";
import type { InstrumentoFinanciero } from "@/tipos/finanzas";

interface CasheaOperacionItem {
  id: number;
  venta_id: number;
  fecha_venta: string;
  numero_nota: string;
  sucursal_id: number;
  sucursal: string;
  cliente: string;
  tasa_bcv_aplicada: number;
  tasa_usdt_aplicada: number;
  total_precio_regular_usd: number;
  total_precio_regular_usdt: number;
  total_precio_regular_bs: number;
  inicial_cobrada_usd: number;
  monto_financiado_usd: number;
  cashea_comision_venta_usd: number;
  cashea_comision_financiado_usd: number;
  cashea_iva_usd: number;
  cashea_islr_usd: number;
  cashea_total_cargos_usd: number;
  cashea_neto_por_cobrar_usd: number;
  cashea_neto_usdt: number;
  cashea_neto_bs: number;
  monto_cobrado_usd: number;
  saldo_neto_pendiente_usd: number;
  estado: "PENDIENTE" | "PARCIAL" | "COBRADO";
  fecha_cobro: string | null;
  instrumento_cobro: string;
  referencia_cobro: string;
}

interface CasheaFinanzasRespuesta {
  resumen: {
    cantidad_operaciones: number;
    total_precio_regular_usd: number;
    total_precio_regular_usdt: number;
    total_precio_regular_bs: number;
    total_financiado_usd: number;
    total_comision_venta_usd: number;
    total_comision_financiado_usd: number;
    total_iva_usd: number;
    total_islr_usd: number;
    total_cargos_usd: number;
    total_neto_por_cobrar_usd: number;
    total_cobrado_usd: number;
    neto_pendiente_usd: number;
    neto_pendiente_usdt: number;
    neto_pendiente_bs: number;
  };
  items: CasheaOperacionItem[];
}

export default function PaginaFinanzasCashea() {
  const { usuario } = usarSesion();
  const esAdmin = usuario ? esRolAdministrativo(usuario.rol) : false;

  const [datos, setDatos] = useState<CasheaFinanzasRespuesta | null>(null);
  const [sucursales, setSucursales] = useState<Sucursal[]>([]);
  const [instrumentos, setInstrumentos] = useState<InstrumentoFinanciero[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);

  // Filtros
  const [fechaInicio, setFechaInicio] = useState("");
  const [fechaFin, setFechaFin] = useState("");
  const [sucursalId, setSucursalId] = useState("");
  const [estadoFiltro, setEstadoFiltro] = useState("");
  const [busqueda, setBusqueda] = useState("");

  // Modal Registrar Cobro (solo ADMIN)
  const [itemCobro, setItemCobro] = useState<CasheaOperacionItem | null>(null);
  const [destinoId, setDestinoId] = useState("");
  const [montoCobro, setMontoCobro] = useState("");
  const [fechaCobro, setFechaCobro] = useState(fechaHoyCaracas());
  const [referenciaCobro, setReferenciaCobro] = useState("");
  const [guardandoCobro, setGuardandoCobro] = useState(false);

  const construirParams = useCallback(() => {
    const p = new URLSearchParams();
    if (fechaInicio) p.set("fecha_inicio", fechaInicio);
    if (fechaFin) p.set("fecha_fin", fechaFin);
    if (sucursalId) p.set("sucursal_id", sucursalId);
    if (estadoFiltro) p.set("estado", estadoFiltro);
    if (busqueda.trim()) p.set("q", busqueda.trim());
    return p.toString();
  }, [fechaInicio, fechaFin, sucursalId, estadoFiltro, busqueda]);

  const cargarDatos = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const qs = construirParams();
      const [respCashea, respSuc, respInst] = await Promise.all([
        solicitarApi<CasheaFinanzasRespuesta>(
          `/api/finanzas/cashea${qs ? `?${qs}` : ""}`
        ),
        solicitarApi<Sucursal[]>("/api/sucursales"),
        esAdmin
          ? solicitarApi<InstrumentoFinanciero[]>("/api/finanzas/instrumentos")
          : Promise.resolve([] as InstrumentoFinanciero[]),
      ]);
      setDatos(respCashea);
      setSucursales(respSuc);
      setInstrumentos(respInst);
      if (respInst[0] && !destinoId) setDestinoId(String(respInst[0].id));
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo cargar el módulo financiero de Cashea."
      );
    } finally {
      setCargando(false);
    }
  }, [construirParams, esAdmin, destinoId]);

  useEffect(() => {
    void cargarDatos();
  }, [cargarDatos]);

  const abrirModalCobro = (it: CasheaOperacionItem) => {
    setItemCobro(it);
    setMontoCobro(it.saldo_neto_pendiente_usd.toFixed(2));
    setFechaCobro(fechaHoyCaracas());
    setReferenciaCobro("");
    setError(null);
  };

  const confirmarCobro = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!itemCobro || !destinoId) return;
    setGuardandoCobro(true);
    setError(null);
    setExito(null);
    try {
      const resp = await solicitarApi<{
        numero_nota: string;
        estado: string;
        monto_cobrado_usd: number;
      }>(`/api/finanzas/cashea/${itemCobro.id}/registrar-cobro`, {
        method: "POST",
        body: JSON.stringify({
          instrumento_destino_id: Number(destinoId),
          monto_cobrado_usd: Number(montoCobro),
          fecha_cobro: fechaCobro,
          referencia: referenciaCobro.trim(),
        }),
      });
      setExito(
        `Cobro Cashea registrado para la nota ${resp.numero_nota} (${resp.estado}) · Total cobrado: ${formatearUsd(resp.monto_cobrado_usd)}.`
      );
      setItemCobro(null);
      await cargarDatos();
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo registrar el cobro de Cashea."
      );
    } finally {
      setGuardandoCobro(false);
    }
  };

  const exportarExcel = async () => {
    try {
      const qs = construirParams();
      await descargarPdfApi(
        `/api/finanzas/cashea/excel${qs ? `?${qs}` : ""}`,
        "cashea_finanzas_alfa.xlsx"
      );
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo exportar el archivo Excel."
      );
    }
  };

  const r = datos?.resumen;
  const items = datos?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-black text-slate-900 flex items-center gap-2">
            <CreditCard className="w-6 h-6 text-[#003566]" />
            Administración y Finanzas · Cashea
          </h1>
          <p className="text-sm text-slate-500">
            Alimentado automáticamente desde el POS · Conversiones de Precio Regular (USD / USDT /
            Bs), comisiones 4%+4%, IVA 16%, ISLR 2% y control de cobros.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void exportarExcel()}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white text-xs font-bold shadow-sm cursor-pointer"
        >
          <Download className="w-4 h-4" />
          Exportar Excel (.xlsx)
        </button>
      </div>

      {error && (
        <div className="p-3.5 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {exito && (
        <div className="p-3.5 rounded-xl bg-emerald-50 border border-emerald-200 text-sm text-emerald-800 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{exito}</span>
        </div>
      )}

      {/* 4 Tarjetas KPI */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="bg-white rounded-2xl border border-slate-200 p-4 space-y-1">
          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
            Total Ventas Precio Regular
          </p>
          <p className="text-2xl font-black text-[#003566] cifra-tabular">
            {formatearUsd(r?.total_precio_regular_usd ?? 0)}
          </p>
          <p className="text-xs text-slate-500 cifra-tabular">
            {(r?.total_precio_regular_usdt ?? 0).toFixed(2)} USDT ·{" "}
            {formatearBs(r?.total_precio_regular_bs ?? 0)}
          </p>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-4 space-y-1">
          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
            Total Financiado Bruto
          </p>
          <p className="text-2xl font-black text-slate-900 cifra-tabular">
            {formatearUsd(r?.total_financiado_usd ?? 0)}
          </p>
          <p className="text-xs text-slate-500">
            {r?.cantidad_operaciones ?? 0} operación(es) Cashea
          </p>
        </div>

        <div className="bg-white rounded-2xl border border-rose-200 p-4 space-y-1">
          <p className="text-[11px] font-bold uppercase tracking-wide text-rose-700">
            Total Cargos e Impuestos Cashea
          </p>
          <p className="text-2xl font-black text-rose-600 cifra-tabular">
            -{formatearUsd(r?.total_cargos_usd ?? 0)}
          </p>
          <p className="text-[11px] text-slate-500 cifra-tabular">
            4% Vta {formatearUsd(r?.total_comision_venta_usd ?? 0)} + 4% Fin{" "}
            {formatearUsd(r?.total_comision_financiado_usd ?? 0)} + IVA/ISLR{" "}
            {formatearUsd((r?.total_iva_usd ?? 0) + (r?.total_islr_usd ?? 0))}
          </p>
        </div>

        <div className="bg-emerald-50/70 rounded-2xl border border-emerald-300 p-4 space-y-1">
          <p className="text-[11px] font-bold uppercase tracking-wide text-emerald-800">
            Neto Real Pendiente por Cobrar
          </p>
          <p className="text-2xl font-black text-emerald-700 cifra-tabular">
            {formatearUsd(r?.neto_pendiente_usd ?? 0)}
          </p>
          <p className="text-xs text-emerald-800/80 cifra-tabular">
            {(r?.neto_pendiente_usdt ?? 0).toFixed(2)} USDT ·{" "}
            {formatearBs(r?.neto_pendiente_bs ?? 0)}
          </p>
        </div>
      </div>

      {/* Filtros */}
      <div className="bg-white rounded-2xl border border-slate-200 p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        <input
          type="text"
          value={busqueda}
          onChange={(e) => setBusqueda(e.target.value)}
          placeholder="Buscar # nota, cliente o ref..."
          className="px-3 py-2 rounded-xl border border-slate-300 text-sm"
        />
        <input
          type="date"
          value={fechaInicio}
          onChange={(e) => setFechaInicio(e.target.value)}
          className="px-3 py-2 rounded-xl border border-slate-300 text-sm"
        />
        <input
          type="date"
          value={fechaFin}
          onChange={(e) => setFechaFin(e.target.value)}
          className="px-3 py-2 rounded-xl border border-slate-300 text-sm"
        />
        <select
          value={sucursalId}
          onChange={(e) => setSucursalId(e.target.value)}
          className="px-3 py-2 rounded-xl border border-slate-300 text-sm bg-white"
        >
          <option value="">Todas las sucursales</option>
          {sucursales.map((s) => (
            <option key={s.id} value={s.id}>
              {s.nombre}
            </option>
          ))}
        </select>
        <select
          value={estadoFiltro}
          onChange={(e) => setEstadoFiltro(e.target.value)}
          className="px-3 py-2 rounded-xl border border-slate-300 text-sm bg-white"
        >
          <option value="">Todos los estados</option>
          <option value="PENDIENTE">Pendiente</option>
          <option value="PARCIAL">Parcial</option>
          <option value="COBRADO">Cobrado</option>
        </select>
      </div>

      {/* Tabla completa de Operaciones Cashea */}
      <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
        {cargando ? (
          <div className="p-8 text-center text-sm text-slate-500">
            Cargando operaciones Cashea...
          </div>
        ) : items.length === 0 ? (
          <div className="p-10 text-center text-sm text-slate-500">
            No hay operaciones Cashea registradas con los filtros seleccionados.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left whitespace-nowrap">
              <thead className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase text-slate-500">
                <tr>
                  <th className="px-3 py-3">Fecha</th>
                  <th className="px-3 py-3"># Nota</th>
                  <th className="px-3 py-3">Cliente</th>
                  <th className="px-3 py-3">Sucursal</th>
                  <th className="px-3 py-3 text-right">Regular (USD/USDT/Bs)</th>
                  <th className="px-3 py-3 text-right">Inicial</th>
                  <th className="px-3 py-3 text-right">Financiado</th>
                  <th className="px-3 py-3 text-right">4% Venta</th>
                  <th className="px-3 py-3 text-right">4% Financ.</th>
                  <th className="px-3 py-3 text-right">16% IVA</th>
                  <th className="px-3 py-3 text-right">2% ISLR</th>
                  <th className="px-3 py-3 text-right">Total Cargos</th>
                  <th className="px-3 py-3 text-right">Neto por Cobrar</th>
                  <th className="px-3 py-3">Estado</th>
                  {esAdmin && <th className="px-3 py-3 text-right">Acción</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 cifra-tabular">
                {items.map((it) => (
                  <tr key={it.id} className="hover:bg-slate-50/70">
                    <td className="px-3 py-2.5">{it.fecha_venta}</td>
                    <td className="px-3 py-2.5 font-mono font-bold text-[#003566]">
                      {it.numero_nota}
                    </td>
                    <td className="px-3 py-2.5 font-medium text-slate-800">{it.cliente}</td>
                    <td className="px-3 py-2.5 text-slate-600">{it.sucursal}</td>
                    <td className="px-3 py-2.5 text-right">
                      <div className="font-bold text-slate-900">
                        {formatearUsd(it.total_precio_regular_usd)}
                      </div>
                      <div className="text-[10px] text-slate-500">
                        {it.total_precio_regular_usdt.toFixed(2)} USDT ·{" "}
                        {formatearBs(it.total_precio_regular_bs)}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      {formatearUsd(it.inicial_cobrada_usd)}
                    </td>
                    <td className="px-3 py-2.5 text-right font-semibold">
                      {formatearUsd(it.monto_financiado_usd)}
                    </td>
                    <td className="px-3 py-2.5 text-right text-rose-600">
                      {formatearUsd(it.cashea_comision_venta_usd)}
                    </td>
                    <td className="px-3 py-2.5 text-right text-rose-600">
                      {formatearUsd(it.cashea_comision_financiado_usd)}
                    </td>
                    <td className="px-3 py-2.5 text-right text-rose-600">
                      {formatearUsd(it.cashea_iva_usd)}
                    </td>
                    <td className="px-3 py-2.5 text-right text-rose-600">
                      {formatearUsd(it.cashea_islr_usd)}
                    </td>
                    <td className="px-3 py-2.5 text-right font-bold text-rose-700">
                      -{formatearUsd(it.cashea_total_cargos_usd)}
                    </td>
                    <td className="px-3 py-2.5 text-right font-black text-emerald-700">
                      {formatearUsd(it.cashea_neto_por_cobrar_usd)}
                    </td>
                    <td className="px-3 py-2.5">
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                          it.estado === "COBRADO"
                            ? "bg-emerald-100 text-emerald-800"
                            : it.estado === "PARCIAL"
                            ? "bg-amber-100 text-amber-800"
                            : "bg-slate-100 text-slate-700"
                        }`}
                      >
                        {it.estado}
                      </span>
                    </td>
                    {esAdmin && (
                      <td className="px-3 py-2.5 text-right">
                        {it.estado !== "COBRADO" ? (
                          <button
                            type="button"
                            onClick={() => abrirModalCobro(it)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-[#003566] hover:bg-[#001D3D] text-white text-[11px] font-bold cursor-pointer"
                          >
                            <Landmark className="w-3 h-3" />
                            Registrar Cobro
                          </button>
                        ) : (
                          <span className="text-[10px] text-slate-400">
                            {it.fecha_cobro || "Cobrado"}
                          </span>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal Registrar Cobro de Cashea (solo ADMIN) */}
      {itemCobro && esAdmin && (
        <div className="fixed inset-0 z-50 bg-black/45 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full shadow-2xl border border-slate-200 overflow-hidden">
            <div className="flex items-center justify-between bg-[#003566] px-5 py-3.5 text-white">
              <span className="font-bold text-sm">
                Registrar Cobro Cashea · {itemCobro.numero_nota}
              </span>
              <button
                type="button"
                onClick={() => setItemCobro(null)}
                className="text-white/80 hover:text-white cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={confirmarCobro} className="p-5 space-y-4">
              <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-xs space-y-1">
                <div className="flex justify-between">
                  <span>Financiado Bruto:</span>
                  <strong>{formatearUsd(itemCobro.monto_financiado_usd)}</strong>
                </div>
                <div className="flex justify-between text-rose-700">
                  <span>Cargos Cashea (4%+4%+IVA+ISLR):</span>
                  <strong>-{formatearUsd(itemCobro.cashea_total_cargos_usd)}</strong>
                </div>
                <div className="flex justify-between text-emerald-800 font-black pt-1 border-t border-emerald-200">
                  <span>Neto Pendiente por Cobrar:</span>
                  <span>{formatearUsd(itemCobro.saldo_neto_pendiente_usd)}</span>
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Cuenta / Banco Destino *
                </label>
                <select
                  required
                  value={destinoId}
                  onChange={(e) => setDestinoId(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm bg-white"
                >
                  {instrumentos.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.nombre} ({i.moneda})
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Monto Cobrado (USD) *
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    required
                    value={montoCobro}
                    onChange={(e) => setMontoCobro(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Fecha Depósito *
                  </label>
                  <input
                    type="date"
                    required
                    value={fechaCobro}
                    onChange={(e) => setFechaCobro(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Referencia Bancaria
                </label>
                <input
                  type="text"
                  value={referenciaCobro}
                  onChange={(e) => setReferenciaCobro(e.target.value)}
                  placeholder="N° de transferencia o depósito Cashea"
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setItemCobro(null)}
                  className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-bold text-slate-700 cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={guardandoCobro}
                  className="px-4 py-2 rounded-xl bg-[#003566] hover:bg-[#001D3D] text-white text-xs font-bold disabled:opacity-60 cursor-pointer"
                >
                  {guardandoCobro ? "Registrando..." : "Confirmar Cobro"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
