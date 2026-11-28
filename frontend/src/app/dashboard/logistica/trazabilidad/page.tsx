"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Clock,
  Cpu,
  Plane,
  ScanBarcode,
  Search,
  ShieldAlert,
  ShoppingCart,
  Truck,
  Wrench,
} from "lucide-react";
import { ErrorApi, formatearUsd, solicitarApi } from "@/servicios/api";

interface TrazabilidadRespuesta {
  equipo: {
    id: number;
    serial: string;
    modelo: string;
    configuracion: string;
    grado_estetico: string;
    categoria: string;
    ubicacion_actual: string;
    estado_actual: string;
    estado_etiqueta: string;
    precio_promo_usd: number;
    primer_costo_usd?: number;
    costo_componentes_usd?: number;
    comision_preparacion_usd?: number;
    costo_final_usd?: number;
  };
  compra_internacional: {
    tipo: string;
    codigo: string;
    fecha_compra: string;
    proveedor: string;
    referencia: string;
    descripcion_previa: string;
    cantidad_equipos_lote?: number;
    monto_compra_usd?: number;
    taxes_usd?: number;
    envio_miami_usd?: number;
    subtotal_miami_usd?: number;
    gastos_envio_venezuela_usd?: number;
    costo_total_aterrizado_usd?: number;
  } | null;
  recepcion: {
    fecha: string;
    ubicacion_actual: string;
    modelo: string;
    configuracion: string;
    grado_estetico: string;
    proceso_inicial: string;
    observaciones_iniciales: string;
    recibido_por: string;
    primer_costo_usd?: number;
  };
  historial_procesos: {
    id: number;
    fecha: string;
    estado_anterior: string;
    estado_nuevo: string;
    usuario: string;
    nota_tecnica: string;
  }[];
  preparacion_y_costos: {
    primer_costo_usd?: number;
    costo_componentes_usd?: number;
    comision_preparacion_usd?: number;
    costo_final_usd?: number;
    componentes: {
      id: number;
      sku: string;
      descripcion: string;
      cantidad: number;
      fecha: string;
      instalado_por: string;
      costo_unitario_usd?: number;
      costo_total_usd?: number;
    }[];
    preparaciones: {
      id: number;
      fecha: string;
      tecnico: string;
      tipo: string;
      resultado: string;
      nota: string;
      comision_usd?: number;
    }[];
  };
  traslados: {
    id: number;
    numero_traslado: string;
    fecha_envio: string;
    fecha_recepcion: string | null;
    origen: string;
    destino: string;
    estado: string;
    enviado_por: string;
    recibido_por: string;
    nota: string;
  }[];
  venta: {
    venta_id: number;
    numero_venta: string;
    fecha: string;
    sucursal: string;
    asesor: string;
    cliente: string;
    estado: string;
    sin_cargador?: boolean;
    precio_venta_usd: number;
    costo_final_usd?: number;
    ganancia_real_usd?: number;
  } | null;
  incidentes_postventa: {
    origen: string;
    codigo: string;
    tipo: string;
    fecha: string;
    falla_reportada: string;
    tecnico: string;
    resolucion: string;
    estado: string;
  }[];
  linea_tiempo: {
    fecha: string;
    tipo: string;
    titulo: string;
    detalle: string;
  }[];
}

export default function PaginaTrazabilidadSerial() {
  const [serialInput, setSerialInput] = useState("");
  const [datos, setDatos] = useState<TrazabilidadRespuesta | null>(null);
  const [buscando, setBuscando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const buscarSerial = useCallback(async (serialObjetivo: string) => {
    const limpio = serialObjetivo.trim();
    if (!limpio) return;
    setBuscando(true);
    setError(null);
    try {
      const res = await solicitarApi<TrazabilidadRespuesta>(
        `/api/inventario/trazabilidad/${encodeURIComponent(limpio)}`
      );
      setDatos(res);
    } catch (err) {
      setDatos(null);
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se encontró trazabilidad para ese serial."
      );
    } finally {
      setBuscando(false);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const s = params.get("serial");
    if (s) {
      setSerialInput(s);
      void buscarSerial(s);
    }
  }, [buscarSerial]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-black text-[#001D3D] flex items-center gap-2">
          <ScanBarcode className="w-6 h-6 text-[#003566]" />
          Trazabilidad Total por Serial (Hoja de Vida del Equipo)
        </h1>
        <p className="text-sm text-slate-500">
          Consulta el historial cronológico completo y el desglose financiero de cualquier serial:
          compra internacional, recepción, procesos, componentes, traslados, venta y post-venta.
        </p>
      </div>

      {/* Buscador */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void buscarSerial(serialInput);
        }}
        className="bg-white rounded-2xl border border-slate-200 p-4 flex flex-col sm:flex-row gap-3"
      >
        <div className="relative flex-1">
          <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={serialInput}
            onChange={(e) => setSerialInput(e.target.value)}
            placeholder="Escanea o escribe el serial del equipo (ej. SN-INT-001)..."
            className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-300 text-sm font-mono font-bold"
          />
        </div>
        <button
          type="submit"
          disabled={buscando || !serialInput.trim()}
          className="px-6 py-2.5 rounded-xl bg-[#003566] hover:bg-[#001D3D] disabled:opacity-50 text-white text-xs font-bold cursor-pointer"
        >
          {buscando ? "Buscando..." : "Consultar Hoja de Vida"}
        </button>
      </form>

      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {datos && (
        <div className="space-y-6">
          {/* Resumen del equipo + Desglose de Costo Final */}
          <div className="rounded-2xl bg-gradient-to-br from-[#001D3D] to-[#003566] p-5 text-white space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <span className="font-mono text-xs bg-white/15 px-2.5 py-1 rounded-full">
                  {datos.equipo.serial}
                </span>
                <h2 className="text-xl font-black mt-1.5">{datos.equipo.modelo}</h2>
                <p className="text-xs text-sky-200">
                  {datos.equipo.configuracion || "Sin especificaciones adicionales"}
                  {datos.equipo.grado_estetico ? ` · ${datos.equipo.grado_estetico}` : ""} · Ubicación:{" "}
                  <strong>{datos.equipo.ubicacion_actual}</strong>
                </p>
              </div>
              <span className="px-3.5 py-1.5 rounded-xl bg-white/15 border border-white/20 text-xs font-black">
                Estado: {datos.equipo.estado_etiqueta} ({datos.equipo.estado_actual})
              </span>
            </div>

            {datos.equipo.costo_final_usd !== undefined && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-3 border-t border-white/15 text-xs">
                <div className="bg-white/10 rounded-xl p-3">
                  <p className="text-sky-200">Primer Costo (Aterrizado)</p>
                  <p className="text-lg font-black cifra-tabular">
                    {formatearUsd(datos.equipo.primer_costo_usd || 0)}
                  </p>
                </div>
                <div className="bg-white/10 rounded-xl p-3">
                  <p className="text-sky-200">+ Componentes</p>
                  <p className="text-lg font-black cifra-tabular">
                    {formatearUsd(datos.equipo.costo_componentes_usd || 0)}
                  </p>
                </div>
                <div className="bg-white/10 rounded-xl p-3">
                  <p className="text-sky-200">+ Comisión Preparación</p>
                  <p className="text-lg font-black cifra-tabular">
                    {formatearUsd(datos.equipo.comision_preparacion_usd || 0)}
                  </p>
                </div>
                <div className="bg-emerald-500/25 border border-emerald-300/40 rounded-xl p-3">
                  <p className="text-emerald-200 font-bold">= COSTO FINAL OFICIAL</p>
                  <p className="text-lg font-black cifra-tabular">
                    {formatearUsd(datos.equipo.costo_final_usd || 0)}
                  </p>
                </div>
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* 1. Compra Internacional */}
            <div className="bg-white rounded-2xl border border-slate-200 p-5 space-y-2 text-xs">
              <h3 className="text-sm font-black text-[#001D3D] flex items-center gap-2">
                <Plane className="w-4 h-4 text-[#003566]" />
                1. Origen / Compra Internacional
              </h3>
              {datos.compra_internacional ? (
                <div className="space-y-1 text-slate-700">
                  <p>
                    <strong>Lote / Doc:</strong> {datos.compra_internacional.codigo} (
                    {datos.compra_internacional.fecha_compra})
                  </p>
                  <p>
                    <strong>Proveedor:</strong> {datos.compra_internacional.proveedor}
                    {datos.compra_internacional.referencia
                      ? ` · Ref: ${datos.compra_internacional.referencia}`
                      : ""}
                  </p>
                  <p>
                    <strong>Descripción previa:</strong>{" "}
                    {datos.compra_internacional.descripcion_previa || "—"}
                  </p>
                  {datos.compra_internacional.monto_compra_usd !== undefined && (
                    <div className="pt-2 mt-2 border-t border-slate-100 grid grid-cols-2 gap-1.5 cifra-tabular">
                      <span>Compra lote: {formatearUsd(datos.compra_internacional.monto_compra_usd)}</span>
                      <span>Taxes: {formatearUsd(datos.compra_internacional.taxes_usd || 0)}</span>
                      <span>Envío Miami: {formatearUsd(datos.compra_internacional.envio_miami_usd || 0)}</span>
                      <span>Envío Vzla: {formatearUsd(datos.compra_internacional.gastos_envio_venezuela_usd || 0)}</span>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-slate-500">Sin lote de compra vinculado.</p>
              )}
            </div>

            {/* 2. Venta y Rentabilidad Real */}
            <div className="bg-white rounded-2xl border border-slate-200 p-5 space-y-2 text-xs">
              <h3 className="text-sm font-black text-[#001D3D] flex items-center gap-2">
                <ShoppingCart className="w-4 h-4 text-emerald-600" />
                6. Venta y Utilidad Real
              </h3>
              {datos.venta ? (
                <div className="space-y-1 text-slate-700">
                  <p>
                    <strong>Nota:</strong> {datos.venta.numero_venta} ({datos.venta.fecha}) ·{" "}
                    <strong>{datos.venta.sucursal}</strong>
                  </p>
                  <p>
                    <strong>Cliente:</strong> {datos.venta.cliente} · <strong>Asesor:</strong>{" "}
                    {datos.venta.asesor}
                  </p>
                  <p className="cifra-tabular">
                    <strong>Precio Venta:</strong> {formatearUsd(datos.venta.precio_venta_usd)}
                    {datos.venta.ganancia_real_usd !== undefined && (
                      <>
                        {" "}
                        · <strong className="text-emerald-700">Ganancia Real: {formatearUsd(datos.venta.ganancia_real_usd)}</strong>
                      </>
                    )}
                  </p>
                  {datos.venta.sin_cargador && (
                    <p className="text-amber-800 font-bold">
                      ⚠️ Entregado SIN cargador (autorizado en POS).
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-slate-500">Este equipo aún no ha sido vendido.</p>
              )}
            </div>

            {/* 4. Componentes instalados */}
            <div className="bg-white rounded-2xl border border-slate-200 p-5 space-y-2 text-xs">
              <h3 className="text-sm font-black text-[#001D3D] flex items-center gap-2">
                <Cpu className="w-4 h-4 text-[#003566]" />
                4. Componentes y Preparación ({datos.preparacion_y_costos.componentes.length})
              </h3>
              {datos.preparacion_y_costos.componentes.length === 0 ? (
                <p className="text-slate-500">Sin componentes instalados en taller.</p>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {datos.preparacion_y_costos.componentes.map((c) => (
                    <li key={c.id} className="py-1.5 flex items-center justify-between gap-2">
                      <div>
                        <span className="font-mono font-bold text-[#001D3D]">{c.sku}</span>{" "}
                        · {c.descripcion} ({c.cantidad}x)
                      </div>
                      {c.costo_total_usd !== undefined && (
                        <strong className="cifra-tabular">{formatearUsd(c.costo_total_usd)}</strong>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* 5 & 7. Traslados e Incidentes Post-venta */}
            <div className="bg-white rounded-2xl border border-slate-200 p-5 space-y-3 text-xs">
              <div>
                <h3 className="text-sm font-black text-[#001D3D] flex items-center gap-2 mb-1.5">
                  <Truck className="w-4 h-4 text-[#003566]" />
                  5. Traslados ({datos.traslados.length})
                </h3>
                {datos.traslados.length === 0 ? (
                  <p className="text-slate-500">Sin traslados registrados.</p>
                ) : (
                  <ul className="space-y-1">
                    {datos.traslados.map((t) => (
                      <li key={t.id}>
                        <strong>{t.numero_traslado}</strong> ({t.estado}): {t.origen} → {t.destino}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="pt-2 border-t border-slate-100">
                <h3 className="text-sm font-black text-rose-800 flex items-center gap-2 mb-1.5">
                  <ShieldAlert className="w-4 h-4 text-rose-600" />
                  7. Incidentes Post-venta / Garantías ({datos.incidentes_postventa.length})
                </h3>
                {datos.incidentes_postventa.length === 0 ? (
                  <p className="text-slate-500">Sin incidentes de garantía ni servicio técnico.</p>
                ) : (
                  <ul className="space-y-1.5">
                    {datos.incidentes_postventa.map((inc, i) => (
                      <li key={i} className="p-2 rounded-lg bg-rose-50/70 border border-rose-200">
                        <p className="font-bold text-rose-900">
                          {inc.codigo} ({inc.tipo} · {inc.estado}) — {inc.fecha.slice(0, 10)}
                        </p>
                        <p className="text-slate-700">Falla: {inc.falla_reportada}</p>
                        {inc.resolucion && (
                          <p className="text-slate-600">Resolución: {inc.resolucion}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>

          {/* Línea de Tiempo Cronológica Unificada */}
          <div className="bg-white rounded-2xl border border-slate-200 p-5 space-y-3">
            <h3 className="text-sm font-black text-[#001D3D] flex items-center gap-2">
              <Clock className="w-4 h-4 text-[#003566]" />
              Línea de Tiempo Cronológica Completa ({datos.linea_tiempo.length} eventos)
            </h3>
            <ol className="relative border-l-2 border-slate-200 ml-2 space-y-3 pl-5">
              {datos.linea_tiempo.map((ev, idx) => (
                <li key={idx} className="relative text-xs">
                  <span className="absolute -left-[27px] top-1 w-3 h-3 rounded-full bg-[#003566] border-2 border-white" />
                  <p className="text-[11px] font-mono text-slate-400">
                    {ev.fecha.slice(0, 19).replace("T", " ")} · {ev.tipo}
                  </p>
                  <p className="font-bold text-slate-900">{ev.titulo}</p>
                  <p className="text-slate-600">{ev.detalle}</p>
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}
    </div>
  );
}
