"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { PackageCheck, RefreshCw } from "lucide-react";
import BuscadorTabla from "@/componentes/BuscadorTabla";
import { formatearUsd, solicitarApi } from "@/servicios/api";
import type { CompraResumen } from "@/tipos/logistica";

interface LoteTransitoSimple {
  id: number;
  codigo: string;
  proveedor_nombre: string;
  trackings: string;
  estado: string;
  fecha_salida: string | null;
  fecha_estimada_llegada: string | null;
  total_estimado_usd: number;
}

interface TrackingUnificado {
  id: string;
  fuente: "LOTE_TRANSITO" | "COMPRA_IMPORTACION";
  documento: string;
  proveedor: string;
  tracking: string;
  estado: string;
  fecha_estimada: string;
  monto_usd: number;
}

export default function PanelTrackingsInternacionales({
  compras,
}: {
  compras: CompraResumen[];
}) {
  const [lotes, setLotes] = useState<LoteTransitoSimple[]>([]);
  const [busqueda, setBusqueda] = useState("");
  const [cargando, setCargando] = useState(false);

  const cargarLotes = useCallback(async () => {
    setCargando(true);
    try {
      const data = await solicitarApi<LoteTransitoSimple[]>("/api/logistica/transito");
      setLotes(data);
    } catch {
      setLotes([]);
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void cargarLotes();
  }, [cargarLotes]);

  const filas = useMemo<TrackingUnificado[]>(() => {
    const out: TrackingUnificado[] = [];
    for (const l of lotes) {
      const listaTrk = (l.trackings || "")
        .split(/[,;\n]+/)
        .map((t) => t.trim())
        .filter(Boolean);
      if (listaTrk.length === 0) {
        out.push({
          id: `lote-${l.id}`,
          fuente: "LOTE_TRANSITO",
          documento: l.codigo,
          proveedor: l.proveedor_nombre || "Importación",
          tracking: "Sin tracking asignado",
          estado: l.estado,
          fecha_estimada: l.fecha_estimada_llegada || l.fecha_salida || "—",
          monto_usd: l.total_estimado_usd || 0,
        });
      } else {
        listaTrk.forEach((trk, idx) => {
          out.push({
            id: `lote-${l.id}-${idx}`,
            fuente: "LOTE_TRANSITO",
            documento: l.codigo,
            proveedor: l.proveedor_nombre || "Importación",
            tracking: trk,
            estado: l.estado,
            fecha_estimada: l.fecha_estimada_llegada || l.fecha_salida || "—",
            monto_usd: l.total_estimado_usd || 0,
          });
        });
      }
    }
    for (const c of compras) {
      const cExtra = c as CompraResumen & {
        tracking_guia?: string;
        proveedor_nombre?: string;
      };
      if (cExtra.tracking_guia?.trim()) {
        out.push({
          id: `cmp-${c.id}`,
          fuente: "COMPRA_IMPORTACION",
          documento: c.numero_compra,
          proveedor: cExtra.proveedor_nombre || c.proveedor || "Importación",
          tracking: cExtra.tracking_guia.trim(),
          estado: c.estado,
          fecha_estimada: c.fecha,
          monto_usd: c.monto_mercancia_usd || 0,
        });
      }
    }
    return out;
  }, [lotes, compras]);

  const filtrados = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    if (!q) return filas;
    return filas.filter((f) =>
      [f.tracking, f.documento, f.proveedor, f.estado].join(" ").toLowerCase().includes(q)
    );
  }, [filas, busqueda]);

  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-black text-[#001D3D] flex items-center gap-2">
            <PackageCheck className="w-4 h-4 text-[#003566]" />
            Seguimiento de Trackings Internacionales ({filas.length})
          </h3>
          <p className="text-xs text-slate-500">
            Consolidado en tiempo real de trackings registrados en Lotes en Tránsito y Compras de Importación.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void cargarLotes()}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-slate-200 text-xs font-bold text-slate-700 hover:bg-slate-50 cursor-pointer"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${cargando ? "animate-spin" : ""}`} />
          Actualizar
        </button>
      </div>

      <BuscadorTabla
        valor={busqueda}
        alCambiar={setBusqueda}
        placeholder="Buscar por tracking, lote, compra o proveedor..."
      />

      {filtrados.length === 0 ? (
        <p className="text-xs text-slate-500 text-center py-6">
          No hay trackings internacionales registrados todavía.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-[11px] uppercase text-slate-600">
              <tr>
                <th className="px-3 py-2">Tracking</th>
                <th className="px-3 py-2">Lote / Compra</th>
                <th className="px-3 py-2">Proveedor</th>
                <th className="px-3 py-2">Fecha Est.</th>
                <th className="px-3 py-2 text-right">Valor USD</th>
                <th className="px-3 py-2">Estado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtrados.map((f) => (
                <tr key={f.id} className="hover:bg-slate-50/70">
                  <td className="px-3 py-2 font-mono font-bold text-[#001D3D]">{f.tracking}</td>
                  <td className="px-3 py-2 font-semibold text-slate-700">{f.documento}</td>
                  <td className="px-3 py-2 text-slate-600">{f.proveedor}</td>
                  <td className="px-3 py-2 text-slate-500">{f.fecha_estimada}</td>
                  <td className="px-3 py-2 text-right font-bold cifra-tabular">
                    {formatearUsd(f.monto_usd)}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                        f.estado === "RECIBIDO" || f.estado === "RECIBIDA"
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-sky-50 text-[#003566]"
                      }`}
                    >
                      {f.estado}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
