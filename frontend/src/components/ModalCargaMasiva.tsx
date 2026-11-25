"use client";

import React, { useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Loader2,
  Upload,
  X,
} from "lucide-react";
import { obtenerToken } from "@/servicios/api";

export type TipoCargaMasiva =
  | "COMPRA_NACIONAL"
  | "COMPRA_INTERNACIONAL"
  | "CONSIGNACION"
  | "TRASLADO"
  | "PREPARACION_ESTADOS";

interface SucursalSimple {
  id: number;
  nombre: string;
}

interface FilaPreview {
  fila: number;
  sku?: string;
  nombre_articulo?: string;
  serial?: string;
  modelo?: string;
  cantidad?: number;
  costo_unitario_usd?: number;
  estado_actual?: string;
  nuevo_estado?: string;
  estado_inicial?: string;
  observacion?: string;
  nota?: string;
  errores?: string[];
}

interface RespuestaPreview {
  tipo: string;
  nombre_archivo: string;
  total_filas: number;
  validas_count: number;
  errores_count: number;
  filas_validas: FilaPreview[];
  filas_con_error: FilaPreview[];
}

interface PropsModalCargaMasiva {
  abierto: boolean;
  alCerrar: () => void;
  tipo: TipoCargaMasiva;
  titulo: string;
  sucursales?: SucursalSimple[];
  alCompletar?: (resultado: Record<string, unknown>) => void;
}

const URL_BASE_API =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ||
  process.env.NEXT_PUBLIC_URL_API_PYTHON?.replace(/\/+$/, "") ||
  "http://localhost:8000";

export async function descargarPlantillaLogistica(tipo: TipoCargaMasiva): Promise<void> {
  const token = obtenerToken();
  const res = await fetch(`${URL_BASE_API}/api/logistica/plantilla/${tipo}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    throw new Error("No se pudo descargar la plantilla.");
  }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `plantilla_${tipo.toLowerCase()}.xlsx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export default function ModalCargaMasiva({
  abierto,
  alCerrar,
  tipo,
  titulo,
  sucursales = [],
  alCompletar,
}: PropsModalCargaMasiva) {
  const [archivo, setArchivo] = useState<File | null>(null);
  const [almacenOrigenId, setAlmacenOrigenId] = useState<string>("");
  const [almacenDestinoId, setAlmacenDestinoId] = useState<string>(
    sucursales[0] ? String(sucursales[0].id) : ""
  );
  const [proveedorNombre, setProveedorNombre] = useState("");
  const [referenciaFactura, setReferenciaFactura] = useState("");
  const [costoFleteUsd, setCostoFleteUsd] = useState("0");
  const [costoAduanaUsd, setCostoAduanaUsd] = useState("0");
  const [trackingGuia, setTrackingGuia] = useState("");
  const [observaciones, setObservaciones] = useState("");

  const [validando, setValidando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [descargando, setDescargando] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [exitoMsg, setExitoMsg] = useState<string | null>(null);
  const [preview, setPreview] = useState<RespuestaPreview | null>(null);

  if (!abierto) return null;

  const esIngreso =
    tipo === "COMPRA_NACIONAL" ||
    tipo === "COMPRA_INTERNACIONAL" ||
    tipo === "CONSIGNACION";
  const esInternacional = tipo === "COMPRA_INTERNACIONAL";
  const esTraslado = tipo === "TRASLADO";

  const construirFormData = (): FormData => {
    const fd = new FormData();
    if (archivo) fd.append("archivo", archivo);
    if (almacenOrigenId) fd.append("almacen_origen_id", almacenOrigenId);
    if (almacenDestinoId) fd.append("almacen_destino_id", almacenDestinoId);
    if (proveedorNombre.trim()) fd.append("proveedor_nombre", proveedorNombre.trim());
    if (referenciaFactura.trim()) fd.append("referencia_factura", referenciaFactura.trim());
    if (esInternacional) {
      fd.append("costo_flete_usd", costoFleteUsd || "0");
      fd.append("costo_aduana_otros_usd", costoAduanaUsd || "0");
      if (trackingGuia.trim()) fd.append("tracking_guia", trackingGuia.trim());
    }
    if (observaciones.trim()) fd.append("observaciones", observaciones.trim());
    return fd;
  };

  const manejarDescargarPlantilla = async () => {
    setDescargando(true);
    setErrorMsg(null);
    try {
      await descargarPlantillaLogistica(tipo);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Error al descargar plantilla.");
    } finally {
      setDescargando(false);
    }
  };

  const manejarValidar = async () => {
    if (!archivo) {
      setErrorMsg("Selecciona primero un archivo .xlsx o .csv.");
      return;
    }
    if (esTraslado && (!almacenOrigenId || !almacenDestinoId)) {
      setErrorMsg("Selecciona almacén de origen y almacén de destino.");
      return;
    }
    setValidando(true);
    setErrorMsg(null);
    setExitoMsg(null);
    setPreview(null);
    try {
      const token = obtenerToken();
      const res = await fetch(`${URL_BASE_API}/api/logistica/importar/${tipo}/preview`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: construirFormData(),
      });
      const data = await res.json();
      if (!res.ok) {
        const det =
          typeof data?.detail === "string"
            ? data.detail
            : data?.detail?.mensaje || "Error al validar el archivo.";
        throw new Error(det);
      }
      setPreview(data as RespuestaPreview);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Error al validar el archivo.");
    } finally {
      setValidando(false);
    }
  };

  const manejarConfirmar = async () => {
    if (!archivo || !preview || preview.errores_count > 0 || preview.validas_count === 0) {
      return;
    }
    if (esIngreso && (!almacenDestinoId || !proveedorNombre.trim())) {
      setErrorMsg(
        tipo === "CONSIGNACION"
          ? "Indica el nombre del consignante y el almacén de destino."
          : "Indica el nombre del proveedor y el almacén de destino."
      );
      return;
    }
    setConfirmando(true);
    setErrorMsg(null);
    try {
      const token = obtenerToken();
      const res = await fetch(`${URL_BASE_API}/api/logistica/importar/${tipo}/confirmar`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: construirFormData(),
      });
      const data = await res.json();
      if (!res.ok) {
        const det =
          typeof data?.detail === "string"
            ? data.detail
            : data?.detail?.mensaje || "Error al confirmar la carga masiva.";
        throw new Error(det);
      }
      setExitoMsg(
        `Carga masiva confirmada con éxito (${data.filas_procesadas ?? preview.validas_count} filas procesadas${data.codigo ? ` · Código ${data.codigo}` : ""}).`
      );
      if (alCompletar) alCompletar(data);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Error al confirmar la importación.");
    } finally {
      setConfirmando(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-xs">
      <div className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
        {/* Cabecera */}
        <div className="flex items-center justify-between border-b border-slate-200 bg-[#003566] px-6 py-4 text-white">
          <div className="flex items-center gap-3">
            <FileSpreadsheet className="h-5 w-5 text-sky-300" />
            <div>
              <h2 className="text-base font-bold">{titulo}</h2>
              <p className="text-xs text-sky-200">
                Plantilla oficial (.xlsx) y carga masiva validada (.xlsx / .csv)
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={alCerrar}
            className="rounded-lg p-1.5 text-white/80 hover:bg-white/10 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Contenido */}
        <div className="flex-1 space-y-5 overflow-y-auto p-6">
          {/* Paso 1: Descargar plantilla */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-sky-200 bg-sky-50/70 p-4">
            <div>
              <p className="text-sm font-semibold text-[#001D3D]">
                1. Descarga la plantilla oficial con instrucciones y SKUs activos
              </p>
              <p className="text-xs text-slate-600">
                Llena la hoja <strong>Datos</strong> respetando los encabezados y súbela abajo.
              </p>
            </div>
            <button
              type="button"
              onClick={manejarDescargarPlantilla}
              disabled={descargando}
              className="inline-flex items-center gap-2 rounded-lg bg-[#003566] px-4 py-2 text-xs font-semibold text-white hover:bg-[#001D3D] disabled:opacity-50"
            >
              {descargando ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              Descargar Plantilla (.xlsx)
            </button>
          </div>

          {/* Paso 2: Datos de contexto */}
          {(esIngreso || esTraslado) && (
            <div className="grid grid-cols-1 gap-3 rounded-xl border border-slate-200 bg-slate-50/70 p-4 sm:grid-cols-2">
              {esTraslado && (
                <div>
                  <label className="mb-1 block text-xs font-semibold text-slate-700">
                    Almacén de Origen *
                  </label>
                  <select
                    value={almacenOrigenId}
                    onChange={(e) => {
                      setAlmacenOrigenId(e.target.value);
                      setPreview(null);
                    }}
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                  >
                    <option value="">Selecciona origen...</option>
                    {sucursales.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.nombre}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-700">
                  Almacén de Destino *
                </label>
                <select
                  value={almacenDestinoId}
                  onChange={(e) => {
                    setAlmacenDestinoId(e.target.value);
                    setPreview(null);
                  }}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                >
                  <option value="">Selecciona destino...</option>
                  {sucursales.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.nombre}
                    </option>
                  ))}
                </select>
              </div>

              {esIngreso && (
                <>
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-700">
                      {tipo === "CONSIGNACION" ? "Nombre del Consignante *" : "Proveedor *"}
                    </label>
                    <input
                      type="text"
                      value={proveedorNombre}
                      onChange={(e) => setProveedorNombre(e.target.value)}
                      placeholder={
                        tipo === "CONSIGNACION"
                          ? "Ej. Distribuidora Tech VE"
                          : "Ej. TechSupply USA"
                      }
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-700">
                      Referencia / Factura
                    </label>
                    <input
                      type="text"
                      value={referenciaFactura}
                      onChange={(e) => setReferenciaFactura(e.target.value)}
                      placeholder="Ej. FAC-2026-0091"
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                    />
                  </div>
                </>
              )}

              {esInternacional && (
                <>
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-700">
                      Flete Internacional (USD)
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={costoFleteUsd}
                      onChange={(e) => setCostoFleteUsd(e.target.value)}
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-700">
                      Aduana / Otros Gastos (USD)
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={costoAduanaUsd}
                      onChange={(e) => setCostoAduanaUsd(e.target.value)}
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label className="mb-1 block text-xs font-semibold text-slate-700">
                      Tracking / Guía de Casillero
                    </label>
                    <input
                      type="text"
                      value={trackingGuia}
                      onChange={(e) => setTrackingGuia(e.target.value)}
                      placeholder="Ej. 1Z999AA10123456784"
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                    />
                  </div>
                </>
              )}

              <div className="sm:col-span-2">
                <label className="mb-1 block text-xs font-semibold text-slate-700">
                  Observaciones (opcional)
                </label>
                <input
                  type="text"
                  value={observaciones}
                  onChange={(e) => setObservaciones(e.target.value)}
                  placeholder="Notas generales del lote..."
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                />
              </div>
            </div>
          )}

          {/* Paso 3: Subir archivo */}
          <div className="space-y-3 rounded-xl border border-dashed border-slate-300 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-800">
                  2. Sube tu archivo (.xlsx o .csv) para previsualizar y validar
                </p>
                <p className="text-xs text-slate-500">
                  Se validarán seriales duplicados, SKUs, stock disponible y estados antes de guardar.
                </p>
              </div>
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 bg-slate-50 px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100">
                <Upload className="h-4 w-4" />
                {archivo ? archivo.name : "Seleccionar archivo"}
                <input
                  type="file"
                  accept=".xlsx,.xls,.csv"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0] || null;
                    setArchivo(f);
                    setPreview(null);
                    setErrorMsg(null);
                    setExitoMsg(null);
                  }}
                />
              </label>
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={manejarValidar}
                disabled={!archivo || validando}
                className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-40"
              >
                {validando ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-4 w-4" />
                )}
                Validar y Previsualizar
              </button>
            </div>
          </div>

          {errorMsg && (
            <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {exitoMsg && (
            <div className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-medium text-emerald-800">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{exitoMsg}</span>
            </div>
          )}

          {/* Tabla de previsualización */}
          {preview && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
                  Total filas: {preview.total_filas}
                </span>
                <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-800">
                  Válidas: {preview.validas_count}
                </span>
                <span
                  className={`rounded-full px-3 py-1 text-xs font-semibold ${
                    preview.errores_count > 0
                      ? "bg-red-100 text-red-700"
                      : "bg-slate-100 text-slate-500"
                  }`}
                >
                  Con error: {preview.errores_count}
                </span>
              </div>

              {preview.filas_con_error.length > 0 && (
                <div className="overflow-x-auto rounded-xl border border-red-200">
                  <div className="bg-red-50 px-4 py-2 text-xs font-bold text-red-800">
                    Filas con errores (corrige en tu archivo y vuelve a validar)
                  </div>
                  <table className="min-w-full divide-y divide-red-100 text-xs">
                    <thead className="bg-red-50/50 text-left text-red-700">
                      <tr>
                        <th className="px-3 py-2">Fila</th>
                        <th className="px-3 py-2">SKU / Serial</th>
                        <th className="px-3 py-2">Detalle de Errores</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-red-100 bg-white">
                      {preview.filas_con_error.map((f) => (
                        <tr key={`err-${f.fila}`}>
                          <td className="px-3 py-2 font-mono font-semibold text-red-700">
                            #{f.fila}
                          </td>
                          <td className="px-3 py-2 text-slate-700">
                            {f.sku || "—"} {f.serial ? `· ${f.serial}` : ""}
                          </td>
                          <td className="px-3 py-2 text-red-700">
                            {(f.errores || []).join(" | ")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {preview.filas_validas.length > 0 && (
                <div className="overflow-x-auto rounded-xl border border-emerald-200">
                  <div className="bg-emerald-50 px-4 py-2 text-xs font-bold text-emerald-800">
                    Filas válidas listas para importar ({preview.validas_count})
                  </div>
                  <table className="min-w-full divide-y divide-emerald-100 text-xs">
                    <thead className="bg-emerald-50/40 text-left text-emerald-900">
                      <tr>
                        <th className="px-3 py-2">Fila</th>
                        <th className="px-3 py-2">SKU / Modelo</th>
                        <th className="px-3 py-2">Serial</th>
                        <th className="px-3 py-2">
                          {tipo === "PREPARACION_ESTADOS" ? "Nuevo Estado" : "Cant."}
                        </th>
                        {esIngreso && <th className="px-3 py-2">Costo USD</th>}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-emerald-100 bg-white">
                      {preview.filas_validas.slice(0, 50).map((f) => (
                        <tr key={`ok-${f.fila}`}>
                          <td className="px-3 py-2 font-mono text-emerald-700">#{f.fila}</td>
                          <td className="px-3 py-2 text-slate-800">
                            <span className="font-semibold">{f.sku || f.modelo || "—"}</span>
                            {f.nombre_articulo ? (
                              <span className="ml-1 text-slate-500">({f.nombre_articulo})</span>
                            ) : null}
                          </td>
                          <td className="px-3 py-2 font-mono text-slate-700">
                            {f.serial || "Por cantidad"}
                          </td>
                          <td className="px-3 py-2 text-slate-700">
                            {tipo === "PREPARACION_ESTADOS"
                              ? `${f.estado_actual || ""} → ${f.nuevo_estado || ""}`
                              : f.cantidad ?? 1}
                          </td>
                          {esIngreso && (
                            <td className="px-3 py-2 font-semibold text-slate-800">
                              ${Number(f.costo_unitario_usd || 0).toFixed(2)}
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Pie */}
        <div className="flex items-center justify-end gap-3 border-t border-slate-200 bg-slate-50 px-6 py-3">
          <button
            type="button"
            onClick={alCerrar}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100"
          >
            Cerrar
          </button>
          <button
            type="button"
            onClick={manejarConfirmar}
            disabled={
              confirmando ||
              !preview ||
              preview.errores_count > 0 ||
              preview.validas_count === 0 ||
              Boolean(exitoMsg)
            }
            className="inline-flex items-center gap-2 rounded-lg bg-[#003566] px-5 py-2 text-xs font-semibold text-white hover:bg-[#001D3D] disabled:opacity-40"
          >
            {confirmando ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <CheckCircle2 className="h-4 w-4" />
            )}
            Confirmar e Importar
          </button>
        </div>
      </div>
    </div>
  );
}
