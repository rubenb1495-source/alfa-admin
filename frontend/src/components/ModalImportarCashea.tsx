"use client";

import React, { useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, FileSpreadsheet, Upload, X } from "lucide-react";
import {
  ErrorApi,
  fechaHoyCaracas,
  formatearUsd,
  obtenerToken,
  solicitarApi,
} from "@/servicios/api";
import type { InstrumentoFinanciero } from "@/tipos/finanzas";

const URL_BASE_API =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ||
  process.env.NEXT_PUBLIC_URL_API_PYTHON?.replace(/\/+$/, "") ||
  "http://localhost:8000";

interface FilaPreviewCashea {
  fila: number;
  cashea_id: number | null;
  venta_id: number | null;
  cashea_numero_orden: string;
  numero_nota: string;
  cliente: string;
  neto_esperado_usd: number;
  monto_pagado_real_usd: number;
  diferencia_usd: number;
  estado_cruce: "LISTA_PARA_CONCILIAR" | "YA_COBRADA" | "NO_ENCONTRADA";
}

interface PreviewRespuesta {
  nombre_archivo: string;
  columnas: string[];
  mapeo_detectado: { col_orden: string; col_neto: string };
  resumen: {
    total_filas: number;
    listas_para_conciliar: number;
    ya_cobradas: number;
    no_encontradas: number;
  };
  filas: FilaPreviewCashea[];
}

export default function ModalImportarCashea({
  abierto,
  instrumentos,
  alCerrar,
  alConfirmarExito,
}: {
  abierto: boolean;
  instrumentos: InstrumentoFinanciero[];
  alCerrar: () => void;
  alConfirmarExito: (mensaje: string) => void;
}) {
  const [archivo, setArchivo] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewRespuesta | null>(null);
  const [seleccionados, setSeleccionados] = useState<number[]>([]);
  const [destinoId, setDestinoId] = useState("");
  const [fechaDeposito, setFechaDeposito] = useState(fechaHoyCaracas());
  const [referenciaBancaria, setReferenciaBancaria] = useState("");
  const [analizando, setAnalizando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const destinoEfectivo = destinoId || (instrumentos[0] ? String(instrumentos[0].id) : "");

  const filasSeleccionadas = useMemo(() => {
    if (!preview) return [];
    return preview.filas.filter(
      (f) =>
        f.estado_cruce === "LISTA_PARA_CONCILIAR" &&
        f.cashea_id !== null &&
        seleccionados.includes(f.cashea_id)
    );
  }, [preview, seleccionados]);

  const totalSeleccion = useMemo(
    () => filasSeleccionadas.reduce((acc, f) => acc + f.monto_pagado_real_usd, 0),
    [filasSeleccionadas]
  );

  if (!abierto) return null;

  const analizar = async (file: File) => {
    setAnalizando(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("archivo", file);
      const token = obtenerToken();
      const res = await fetch(
        `${URL_BASE_API}/api/finanzas/cashea/importar-reporte/preview`,
        {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: fd,
        }
      );
      if (!res.ok) {
        const errJ = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(errJ.detail || "No se pudo analizar el reporte de Cashea.");
      }
      const data = (await res.json()) as PreviewRespuesta;
      setPreview(data);
      setSeleccionados(
        data.filas
          .filter((f) => f.estado_cruce === "LISTA_PARA_CONCILIAR" && f.cashea_id !== null)
          .map((f) => f.cashea_id as number)
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error analizando el archivo.");
    } finally {
      setAnalizando(false);
    }
  };

  const confirmar = async () => {
    if (!preview || filasSeleccionadas.length === 0) {
      setError("Selecciona al menos una orden lista para conciliar.");
      return;
    }
    setConfirmando(true);
    setError(null);
    try {
      const res = await solicitarApi<{
        notas_conciliadas: number;
        total_pagado_real_usd: number;
      }>("/api/finanzas/cashea/importar-reporte/confirmar", {
        method: "POST",
        body: JSON.stringify({
          nombre_archivo: preview.nombre_archivo,
          instrumento_destino_id: Number(destinoEfectivo),
          fecha_deposito: fechaDeposito,
          referencia_bancaria: referenciaBancaria.trim(),
          ordenes: filasSeleccionadas.map((f) => ({
            cashea_id: f.cashea_id,
            cashea_numero_orden: f.cashea_numero_orden,
            monto_pagado_real_usd: f.monto_pagado_real_usd,
          })),
        }),
      });
      alConfirmarExito(
        `Liquidación en lote aplicada: ${res.notas_conciliadas} nota(s) conciliadas por ${formatearUsd(res.total_pagado_real_usd)}.`
      );
      alCerrar();
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "Error al confirmar la liquidación en lote.");
    } finally {
      setConfirmando(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl border border-slate-200 max-w-4xl w-full max-h-[90vh] flex flex-col shadow-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between bg-[#001D3D] text-white">
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="w-5 h-5 text-sky-300" />
            <div>
              <h3 className="text-sm font-black">Importar Liquidación Cashea en Lote</h3>
              <p className="text-[11px] text-sky-200">
                Sube el reporte .xlsx o .csv de Cashea para conciliar múltiples notas en 1 clic
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={alCerrar}
            className="p-1.5 rounded-lg hover:bg-white/10 cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 overflow-y-auto space-y-4">
          {error && (
            <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-xs text-red-700 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="text-xs text-slate-600">
              <p className="font-bold text-slate-800">Archivo de liquidación Cashea (.xlsx o .csv)</p>
              <p>Columnas esperadas: N° de Orden/Nota y Monto Neto Pagado USD.</p>
            </div>
            <label className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#003566] hover:bg-[#001D3D] text-white text-xs font-bold cursor-pointer shrink-0">
              <Upload className="w-4 h-4" />
              {analizando ? "Analizando..." : archivo ? "Cambiar archivo" : "Seleccionar archivo"}
              <input
                type="file"
                accept=".xlsx,.csv"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    setArchivo(f);
                    void analizar(f);
                  }
                }}
              />
            </label>
          </div>

          {preview && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                <div className="p-3 rounded-xl bg-slate-50 border border-slate-200">
                  <p className="text-slate-500">Total filas</p>
                  <p className="text-lg font-black text-slate-900">{preview.resumen.total_filas}</p>
                </div>
                <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200">
                  <p className="text-emerald-700">Listas para conciliar</p>
                  <p className="text-lg font-black text-emerald-800">{preview.resumen.listas_para_conciliar}</p>
                </div>
                <div className="p-3 rounded-xl bg-amber-50 border border-amber-200">
                  <p className="text-amber-700">Ya cobradas</p>
                  <p className="text-lg font-black text-amber-800">{preview.resumen.ya_cobradas}</p>
                </div>
                <div className="p-3 rounded-xl bg-rose-50 border border-rose-200">
                  <p className="text-rose-700">No encontradas</p>
                  <p className="text-lg font-black text-rose-800">{preview.resumen.no_encontradas}</p>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="block text-[11px] font-bold uppercase text-slate-500 mb-1">
                    Banco / Instrumento destino *
                  </label>
                  <select
                    value={destinoEfectivo}
                    onChange={(e) => setDestinoId(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs font-semibold bg-white"
                  >
                    {instrumentos.map((i) => (
                      <option key={i.id} value={String(i.id)}>
                        {i.nombre} ({i.moneda})
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-bold uppercase text-slate-500 mb-1">
                    Fecha del depósito
                  </label>
                  <input
                    type="date"
                    value={fechaDeposito}
                    onChange={(e) => setFechaDeposito(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs font-semibold"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-bold uppercase text-slate-500 mb-1">
                    Referencia bancaria
                  </label>
                  <input
                    type="text"
                    value={referenciaBancaria}
                    onChange={(e) => setReferenciaBancaria(e.target.value)}
                    placeholder="Ej. TRF-CASHEA-001"
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs"
                  />
                </div>
              </div>

              <div className="overflow-x-auto rounded-xl border border-slate-200 max-h-60">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 text-[11px] uppercase text-slate-600 sticky top-0">
                    <tr>
                      <th className="px-3 py-2">Sel</th>
                      <th className="px-3 py-2">Orden / Nota</th>
                      <th className="px-3 py-2">Cliente</th>
                      <th className="px-3 py-2 text-right">Esperado USD</th>
                      <th className="px-3 py-2 text-right">Pagado USD</th>
                      <th className="px-3 py-2">Cruce</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {preview.filas.map((f) => {
                      const lista = f.estado_cruce === "LISTA_PARA_CONCILIAR" && f.cashea_id !== null;
                      const marcada = lista && seleccionados.includes(f.cashea_id as number);
                      return (
                        <tr key={f.fila}>
                          <td className="px-3 py-2">
                            {lista && (
                              <input
                                type="checkbox"
                                checked={marcada}
                                onChange={(e) => {
                                  const cid = f.cashea_id as number;
                                  setSeleccionados((prev) =>
                                    e.target.checked
                                      ? [...prev, cid]
                                      : prev.filter((x) => x !== cid)
                                  );
                                }}
                              />
                            )}
                          </td>
                          <td className="px-3 py-2 font-mono font-bold">
                            {f.cashea_numero_orden} {f.numero_nota ? `(${f.numero_nota})` : ""}
                          </td>
                          <td className="px-3 py-2">{f.cliente}</td>
                          <td className="px-3 py-2 text-right cifra-tabular">
                            {formatearUsd(f.neto_esperado_usd)}
                          </td>
                          <td className="px-3 py-2 text-right font-bold text-emerald-700 cifra-tabular">
                            {formatearUsd(f.monto_pagado_real_usd)}
                          </td>
                          <td className="px-3 py-2">
                            <span
                              className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                                f.estado_cruce === "LISTA_PARA_CONCILIAR"
                                  ? "bg-emerald-50 text-emerald-700"
                                  : f.estado_cruce === "YA_COBRADA"
                                  ? "bg-amber-50 text-amber-800"
                                  : "bg-rose-50 text-rose-700"
                              }`}
                            >
                              {f.estado_cruce}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>

        <div className="px-5 py-3.5 border-t border-slate-200 bg-slate-50 flex items-center justify-between">
          <div className="text-xs text-slate-600">
            Seleccionadas: <strong>{filasSeleccionadas.length}</strong> · Total a ingresar:{" "}
            <strong className="text-emerald-700">{formatearUsd(totalSeleccion)}</strong>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={alCerrar}
              className="px-3.5 py-2 rounded-xl border border-slate-300 bg-white text-xs font-bold text-slate-700 cursor-pointer"
            >
              Cancelar
            </button>
            <button
              type="button"
              disabled={confirmando || filasSeleccionadas.length === 0}
              onClick={() => void confirmar()}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[#003566] hover:bg-[#001D3D] disabled:opacity-50 text-white text-xs font-bold cursor-pointer"
            >
              <CheckCircle2 className="w-4 h-4" />
              {confirmando ? "Conciliando..." : "Confirmar Liquidación en Lote"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
