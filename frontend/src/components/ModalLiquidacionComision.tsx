"use client";

import React, { useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileDown,
  Loader2,
  MessageCircle,
  Wallet,
  X,
} from "lucide-react";
import {
  construirUrlWhatsApp,
  formatearWhatsAppLiquidacion,
} from "@/lib/whatsapp";
import {
  descargarPdfApi,
  ErrorApi,
  formatearBs,
  formatearUsd,
  solicitarApi,
} from "@/servicios/api";
import type {
  ComisionPorPersonaReporte,
  DetalleVentaComision,
  LiquidacionComisionResumen,
} from "@/tipos/finanzas";

const METODOS_PAGO = [
  { valor: "EFECTIVO_USD", etiqueta: "Efectivo USD", esBs: false },
  { valor: "ZELLE", etiqueta: "Zelle (USD)", esBs: false },
  { valor: "BINANCE", etiqueta: "Binance (USDT)", esBs: false },
  { valor: "PAGO_MOVIL", etiqueta: "Pago Móvil (Bs)", esBs: true },
  { valor: "TRANSFERENCIA_BS", etiqueta: "Transferencia Bancaria (Bs)", esBs: true },
];

interface ModalLiquidacionComisionProps {
  persona: ComisionPorPersonaReporte;
  ventasPendientes: DetalleVentaComision[];
  fechaInicio: string;
  fechaFin: string;
  tasaBcvInicial: number | null;
  alCerrar: () => void;
  alLiquidarExito: () => void;
}

export default function ModalLiquidacionComision({
  persona,
  ventasPendientes,
  fechaInicio,
  fechaFin,
  tasaBcvInicial,
  alCerrar,
  alLiquidarExito,
}: ModalLiquidacionComisionProps) {
  const [seleccionadas, setSeleccionadas] = useState<Set<number>>(
    () => new Set(ventasPendientes.map((v) => v.venta_id))
  );
  const [metodoPago, setMetodoPago] = useState("EFECTIVO_USD");
  const [tasaBcv, setTasaBcv] = useState(
    tasaBcvInicial ? String(tasaBcvInicial) : ""
  );
  const [referencia, setReferencia] = useState("");
  const [observaciones, setObservaciones] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [liquidacionCreada, setLiquidacionCreada] =
    useState<LiquidacionComisionResumen | null>(null);

  const metodoActual = METODOS_PAGO.find((m) => m.valor === metodoPago);
  const esMetodoBs = Boolean(metodoActual?.esBs);

  const resumenSeleccion = useMemo(() => {
    let pasilloUsd = 0;
    let leadUsd = 0;
    let cantPasillo = 0;
    let cantLead = 0;
    for (const v of ventasPendientes) {
      if (!seleccionadas.has(v.venta_id)) continue;
      if (v.origen === "LEAD") {
        cantLead += 1;
        leadUsd += v.comision_usd;
      } else {
        cantPasillo += 1;
        pasilloUsd += v.comision_usd;
      }
    }
    const totalUsd = Math.round((pasilloUsd + leadUsd) * 100) / 100;
    const tasaNum = Number(tasaBcv);
    const totalBs =
      esMetodoBs && Number.isFinite(tasaNum) && tasaNum > 0
        ? Math.round(totalUsd * tasaNum * 100) / 100
        : null;
    return {
      cantPasillo,
      cantLead,
      pasilloUsd: Math.round(pasilloUsd * 100) / 100,
      leadUsd: Math.round(leadUsd * 100) / 100,
      totalUsd,
      totalBs,
    };
  }, [ventasPendientes, seleccionadas, esMetodoBs, tasaBcv]);

  const toggleVenta = (id: number) => {
    setSeleccionadas((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const manejarConfirmar = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    const ids = Array.from(seleccionadas);
    if (ids.length === 0) {
      setError("Debes seleccionar al menos una venta pendiente para liquidar.");
      return;
    }
    if (esMetodoBs && (!Number.isFinite(Number(tasaBcv)) || Number(tasaBcv) <= 0)) {
      setError("Indica una tasa BCV válida mayor a 0 para pagos en bolívares.");
      return;
    }

    setGuardando(true);
    try {
      const creada = await solicitarApi<LiquidacionComisionResumen>(
        "/api/comisiones/liquidaciones",
        {
          method: "POST",
          body: JSON.stringify({
            personal_id: persona.personal_id,
            venta_ids: ids,
            fecha_inicio: fechaInicio,
            fecha_fin: fechaFin,
            metodo_pago: metodoPago,
            tasa_bcv_aplicada: esMetodoBs ? Number(tasaBcv) : null,
            referencia: referencia.trim(),
            observaciones: observaciones.trim(),
          }),
        }
      );
      setLiquidacionCreada(creada);
      alLiquidarExito();
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo registrar la liquidación."
      );
    } finally {
      setGuardando(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#000814]/55 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="bg-white rounded-3xl max-w-2xl w-full shadow-2xl border border-slate-200 overflow-hidden max-h-[92vh] flex flex-col">
        <div className="h-1.5 w-full bg-[#003566]" />

        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between gap-3">
          <div>
            <h3 className="text-lg font-black text-[#000814] flex items-center gap-2">
              <Wallet className="w-5 h-5 text-[#003566]" />
              {liquidacionCreada
                ? `Liquidación ${liquidacionCreada.codigo} registrada`
                : `Liquidar comisiones — ${persona.nombre}`}
            </h3>
            <p className="text-xs text-slate-500">
              Período: {fechaInicio} al {fechaFin} ·{" "}
              {persona.es_encargado
                ? "Encargado de Tienda (5% / 8%)"
                : "Asesor (1% / 8%)"}
            </p>
          </div>
          <button
            type="button"
            onClick={alCerrar}
            className="p-1.5 rounded-lg text-slate-400 hover:text-[#000814] hover:bg-slate-100 cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 overflow-y-auto space-y-5">
          {liquidacionCreada ? (
            <div className="space-y-5 text-center py-3">
              <div className="w-14 h-14 rounded-2xl bg-emerald-50 border border-emerald-200 flex items-center justify-center mx-auto">
                <CheckCircle2 className="w-8 h-8 text-emerald-600" />
              </div>
              <div className="space-y-1">
                <p className="text-xs font-bold uppercase tracking-wider text-emerald-700">
                  Pago registrado exitosamente
                </p>
                <p className="text-2xl font-black text-[#000814] cifra-tabular">
                  {formatearUsd(liquidacionCreada.monto_total_usd)}
                </p>
                {liquidacionCreada.monto_bs && (
                  <p className="text-xs font-semibold text-slate-600">
                    Equivalente pagado: {formatearBs(liquidacionCreada.monto_bs)}{" "}
                    (BCV {liquidacionCreada.tasa_bcv_aplicada})
                  </p>
                )}
                <p className="text-xs text-slate-500">
                  Código <strong>{liquidacionCreada.codigo}</strong> ·{" "}
                  {liquidacionCreada.cantidad_ventas} venta(s) marcadas como{" "}
                  <strong>PAGADA</strong>.
                </p>
              </div>

              <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    const msg = formatearWhatsAppLiquidacion(liquidacionCreada);
                    const url = construirUrlWhatsApp(
                      msg,
                      liquidacionCreada.personal_telefono
                    );
                    window.open(url, "_blank", "noopener,noreferrer");
                  }}
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold shadow-xs cursor-pointer"
                >
                  <MessageCircle className="w-4 h-4" />
                  Enviar comprobante por WhatsApp
                </button>
                <button
                  type="button"
                  onClick={() =>
                    void descargarPdfApi(
                      `/api/comisiones/liquidaciones/${liquidacionCreada.id}/pdf`,
                      `${liquidacionCreada.codigo}.pdf`
                    )
                  }
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[#003566] hover:bg-[#001D3D] text-white text-xs font-bold shadow-xs cursor-pointer"
                >
                  <FileDown className="w-4 h-4" />
                  Descargar comprobante PDF
                </button>
              </div>

              <div className="pt-2">
                <button
                  type="button"
                  onClick={alCerrar}
                  className="text-xs font-bold text-slate-500 hover:text-[#000814] cursor-pointer"
                >
                  Cerrar y volver al reporte
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={manejarConfirmar} className="space-y-4">
              {error && (
                <div className="flex items-start gap-2 p-3 rounded-xl bg-red-50 border border-red-200 text-xs text-red-700 font-medium">
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {/* Resumen en vivo */}
              <div className="grid grid-cols-3 gap-3 p-3.5 rounded-2xl bg-[#EDF3FA]/70 border border-[#003566]/20 text-xs">
                <div>
                  <p className="text-slate-500 font-semibold">Pasillo</p>
                  <p className="font-black text-[#000814] text-sm mt-0.5">
                    {resumenSeleccion.cantPasillo} ·{" "}
                    {formatearUsd(resumenSeleccion.pasilloUsd)}
                  </p>
                </div>
                <div>
                  <p className="text-slate-500 font-semibold">Lead</p>
                  <p className="font-black text-[#000814] text-sm mt-0.5">
                    {resumenSeleccion.cantLead} ·{" "}
                    {formatearUsd(resumenSeleccion.leadUsd)}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-[#003566] font-bold">Total a Pagar</p>
                  <p className="font-black text-emerald-700 text-lg cifra-tabular">
                    {formatearUsd(resumenSeleccion.totalUsd)}
                  </p>
                </div>
              </div>

              {/* Checklist de ventas pendientes */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-bold text-slate-700">
                    Ventas pendientes incluidas ({seleccionadas.size} de{" "}
                    {ventasPendientes.length})
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setSeleccionadas(
                        seleccionadas.size === ventasPendientes.length
                          ? new Set()
                          : new Set(ventasPendientes.map((v) => v.venta_id))
                      )
                    }
                    className="text-[11px] font-bold text-[#003566] hover:underline cursor-pointer"
                  >
                    {seleccionadas.size === ventasPendientes.length
                      ? "Desmarcar todas"
                      : "Marcar todas"}
                  </button>
                </div>

                <div className="max-h-48 overflow-y-auto rounded-xl border border-slate-200 divide-y divide-slate-100">
                  {ventasPendientes.map((v) => {
                    const checked = seleccionadas.has(v.venta_id);
                    return (
                      <label
                        key={v.venta_id}
                        className={`flex items-center justify-between gap-3 px-3 py-2 text-xs cursor-pointer ${
                          checked ? "bg-white" : "bg-slate-50 opacity-60"
                        }`}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleVenta(v.venta_id)}
                            className="rounded border-slate-300 text-[#003566]"
                          />
                          <div className="min-w-0">
                            <p className="font-bold text-[#000814] truncate">
                              {v.numero_venta} · {v.producto}
                            </p>
                            <p className="text-[11px] text-slate-500">
                              {v.fecha} ·{" "}
                              {v.origen === "LEAD" ? "Lead" : "Pasillo"} (
                              {v.porcentaje_aplicado}%) · Promo{" "}
                              {formatearUsd(v.base_promo_usd)}
                            </p>
                          </div>
                        </div>
                        <span className="font-black text-emerald-700 shrink-0 cifra-tabular">
                          {formatearUsd(v.comision_usd)}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>

              {/* Datos de pago */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Método de pago *
                  </label>
                  <select
                    value={metodoPago}
                    onChange={(e) => setMetodoPago(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm bg-white"
                  >
                    {METODOS_PAGO.map((m) => (
                      <option key={m.valor} value={m.valor}>
                        {m.etiqueta}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Referencia (opcional)
                  </label>
                  <input
                    type="text"
                    value={referencia}
                    onChange={(e) => setReferencia(e.target.value)}
                    placeholder="Ej. ZEL-9921 / PM-4410"
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                  />
                </div>
              </div>

              {esMetodoBs && (
                <div className="p-3.5 rounded-xl bg-amber-50/70 border border-amber-200 grid grid-cols-1 sm:grid-cols-2 gap-3 items-center">
                  <div>
                    <label className="block text-xs font-bold text-amber-900 mb-1">
                      Tasa BCV aplicada (Bs / USD) *
                    </label>
                    <input
                      type="number"
                      step="0.0001"
                      min="0.0001"
                      required
                      value={tasaBcv}
                      onChange={(e) => setTasaBcv(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl border border-amber-300 bg-white text-sm font-bold cifra-tabular"
                    />
                  </div>
                  <div className="sm:text-right">
                    <p className="text-[11px] font-bold uppercase text-amber-800">
                      Equivalente a transferir en Bs
                    </p>
                    <p className="text-lg font-black text-amber-950 cifra-tabular">
                      {resumenSeleccion.totalBs !== null
                        ? formatearBs(resumenSeleccion.totalBs)
                        : "—"}
                    </p>
                  </div>
                </div>
              )}

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Observaciones (opcional)
                </label>
                <input
                  type="text"
                  value={observaciones}
                  onChange={(e) => setObservaciones(e.target.value)}
                  placeholder="Ej. Pago 1ra quincena noviembre"
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={alCerrar}
                  className="px-4 py-2.5 rounded-xl border border-slate-300 text-xs font-bold text-slate-700 cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={guardando || seleccionadas.size === 0}
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#003566] hover:bg-[#001D3D] disabled:opacity-60 text-white text-xs font-bold cursor-pointer"
                >
                  {guardando ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Wallet className="w-4 h-4" />
                  )}
                  Confirmar liquidación ({formatearUsd(resumenSeleccion.totalUsd)})
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
