"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  History,
  Loader2,
  Search,
  Wrench,
  X,
} from "lucide-react";
import ModalCargaMasiva, {
  descargarPlantillaLogistica,
} from "@/components/ModalCargaMasiva";
import { ErrorApi, solicitarApi } from "@/servicios/api";
import type { Sucursal } from "@/tipos/dominio";
import type { EquipoInventario } from "@/tipos/logistica";

interface HistorialEstadoItem {
  id: number;
  equipo_id: number;
  estado_anterior: string;
  estado_nuevo: string;
  estado_nuevo_etiqueta: string;
  usuario_nombre: string;
  observacion: string;
  creado_en: string | null;
}

const OPCIONES_ESTADO: { valor: string; etiqueta: string; color: string }[] = [
  { valor: "PENDIENTE_REVISION", etiqueta: "Pendiente Revisión", color: "bg-amber-100 text-amber-800" },
  { valor: "POR_PREPARAR", etiqueta: "Por Preparar", color: "bg-orange-100 text-orange-800" },
  { valor: "EN_PREPARACION", etiqueta: "En Preparación", color: "bg-sky-100 text-sky-800" },
  { valor: "DISPONIBLE", etiqueta: "Disponible (POS)", color: "bg-emerald-100 text-emerald-800" },
  { valor: "DEFECTUOSO", etiqueta: "Defectuoso", color: "bg-red-100 text-red-700" },
  { valor: "RESERVADO", etiqueta: "Reservado", color: "bg-violet-100 text-violet-800" },
  { valor: "EN_GARANTIA", etiqueta: "En Garantía", color: "bg-indigo-100 text-indigo-800" },
];

function etiquetaDeEstado(estado: string): { texto: string; color: string } {
  if (estado === "LISTO" || estado === "DISPONIBLE") {
    return { texto: "Disponible (POS)", color: "bg-emerald-100 text-emerald-800" };
  }
  const found = OPCIONES_ESTADO.find((o) => o.valor === estado);
  if (found) return { texto: found.etiqueta, color: found.color };
  return { texto: estado, color: "bg-slate-100 text-slate-700" };
}

export default function PaginaPreparaciones() {
  const [equipos, setEquipos] = useState<EquipoInventario[]>([]);
  const [sucursales, setSucursales] = useState<Sucursal[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);

  // Filtros
  const [busqueda, setBusqueda] = useState("");
  const [filtroSucursal, setFiltroSucursal] = useState("");
  const [filtroEstado, setFiltroEstado] = useState("");

  // Selección masiva
  const [seleccionados, setSeleccionados] = useState<number[]>([]);
  const [estadoMasivo, setEstadoMasivo] = useState("DISPONIBLE");
  const [observacionMasiva, setObservacionMasiva] = useState("");
  const [procesando, setProcesando] = useState(false);

  // Modal carga masiva e historial
  const [modalMasivo, setModalMasivo] = useState(false);
  const [historialEquipo, setHistorialEquipo] = useState<EquipoInventario | null>(null);
  const [historialItems, setHistorialItems] = useState<HistorialEstadoItem[]>([]);
  const [cargandoHistorial, setCargandoHistorial] = useState(false);

  const cargarDatos = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const [respEq, respSuc] = await Promise.all([
        solicitarApi<EquipoInventario[]>("/api/logistica/inventario/equipos"),
        solicitarApi<Sucursal[]>("/api/sucursales"),
      ]);
      setEquipos(
        respEq.filter((e) => e.estado !== "VENDIDO" && e.estado !== "CEMENTERIO")
      );
      setSucursales(respSuc);
    } catch (err) {
      setError(
        err instanceof ErrorApi ? err.message : "No se pudieron cargar los equipos."
      );
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void cargarDatos();
  }, [cargarDatos]);

  const equiposFiltrados = useMemo(() => {
    return equipos.filter((eq) => {
      if (filtroSucursal && String(eq.ubicacion_id) !== filtroSucursal) return false;
      if (filtroEstado) {
        const estadoTarget = filtroEstado === "DISPONIBLE" ? "LISTO" : filtroEstado;
        if (eq.estado !== estadoTarget) return false;
      }
      if (busqueda.trim()) {
        const q = busqueda.trim().toLowerCase();
        const texto = `${eq.serial} ${eq.modelo} ${eq.sku || ""} ${eq.ubicacion || ""}`.toLowerCase();
        if (!texto.includes(q)) return false;
      }
      return true;
    });
  }, [equipos, filtroSucursal, filtroEstado, busqueda]);

  const toggleSeleccion = (id: number) => {
    setSeleccionados((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const toggleSeleccionTodos = () => {
    const editables = equiposFiltrados
      .filter((e) => e.estado !== "EN_TRANSITO")
      .map((e) => e.id);
    if (seleccionados.length === editables.length && editables.length > 0) {
      setSeleccionados([]);
    } else {
      setSeleccionados(editables);
    }
  };

  const aplicarCambioEstado = async (
    ids: number[],
    nuevoEstado: string,
    observacion: string
  ) => {
    if (ids.length === 0) return;
    setProcesando(true);
    setError(null);
    setExito(null);
    try {
      const resp = await solicitarApi<{ actualizados: number; estado_etiqueta: string }>(
        "/api/preparaciones/estado-masivo",
        {
          method: "PATCH",
          body: JSON.stringify({
            equipo_ids: ids,
            nuevo_estado: nuevoEstado,
            observacion: observacion.trim(),
          }),
        }
      );
      setExito(
        `${resp.actualizados} equipo(s) actualizados a "${resp.estado_etiqueta}".`
      );
      setSeleccionados([]);
      setObservacionMasiva("");
      await cargarDatos();
    } catch (err) {
      setError(
        err instanceof ErrorApi ? err.message : "No se pudo actualizar el estado."
      );
    } finally {
      setProcesando(false);
    }
  };

  const abrirHistorial = async (eq: EquipoInventario) => {
    setHistorialEquipo(eq);
    setHistorialItems([]);
    setCargandoHistorial(true);
    try {
      const data = await solicitarApi<HistorialEstadoItem[]>(
        `/api/preparaciones/equipos/${eq.id}/historial`
      );
      setHistorialItems(data);
    } catch {
      setHistorialItems([]);
    } finally {
      setCargandoHistorial(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Encabezado */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-[#001D3D]">
            <Wrench className="h-6 w-6 text-[#003566]" />
            Preparaciones y Alistamiento
          </h1>
          <p className="text-sm text-slate-600">
            Cambia estados individualmente o en lote. Los equipos marcados como{" "}
            <strong>Disponible (POS)</strong> aparecen de inmediato para la venta.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void descargarPlantillaLogistica("PREPARACION_ESTADOS")}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
          >
            <Download className="h-4 w-4 text-[#003566]" />
            Descargar Plantilla (.xlsx)
          </button>
          <button
            type="button"
            onClick={() => setModalMasivo(true)}
            className="inline-flex items-center gap-2 rounded-xl border border-[#003566]/30 bg-sky-50 px-3.5 py-2 text-xs font-semibold text-[#003566] hover:bg-sky-100"
          >
            <FileSpreadsheet className="h-4 w-4" />
            Carga Masiva
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {exito && (
        <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{exito}</span>
        </div>
      )}

      {/* Filtros */}
      <div className="grid grid-cols-1 gap-3 rounded-2xl border border-slate-200 bg-white p-4 md:grid-cols-4">
        <div className="relative md:col-span-2">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar por serial, modelo o SKU..."
            className="w-full rounded-xl border border-slate-300 py-2 pl-9 pr-3 text-sm"
          />
        </div>
        <select
          value={filtroSucursal}
          onChange={(e) => setFiltroSucursal(e.target.value)}
          className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
        >
          <option value="">Todos los almacenes</option>
          {sucursales.map((s) => (
            <option key={s.id} value={s.id}>
              {s.nombre}
            </option>
          ))}
        </select>
        <select
          value={filtroEstado}
          onChange={(e) => setFiltroEstado(e.target.value)}
          className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
        >
          <option value="">Todos los estados</option>
          {OPCIONES_ESTADO.map((o) => (
            <option key={o.valor} value={o.valor}>
              {o.etiqueta}
            </option>
          ))}
        </select>
      </div>

      {/* Barra de acción masiva */}
      {seleccionados.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#003566]/30 bg-[#EDF3FA] px-5 py-3.5 shadow-xs">
          <div className="text-sm font-bold text-[#001D3D]">
            {seleccionados.length} equipo(s) seleccionado(s)
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={estadoMasivo}
              onChange={(e) => setEstadoMasivo(e.target.value)}
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800"
            >
              {OPCIONES_ESTADO.map((o) => (
                <option key={o.valor} value={o.valor}>
                  Cambiar a: {o.etiqueta}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={observacionMasiva}
              onChange={(e) => setObservacionMasiva(e.target.value)}
              placeholder="Observación opcional..."
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs"
            />
            <button
              type="button"
              disabled={procesando}
              onClick={() =>
                void aplicarCambioEstado(seleccionados, estadoMasivo, observacionMasiva)
              }
              className="inline-flex items-center gap-1.5 rounded-xl bg-[#003566] px-4 py-2 text-xs font-bold text-white hover:bg-[#001D3D] disabled:opacity-50"
            >
              {procesando ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5" />
              )}
              Aplicar Cambio Masivo
            </button>
          </div>
        </div>
      )}

      {/* Tabla de equipos */}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xs">
        {cargando ? (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Cargando equipos...
          </div>
        ) : equiposFiltrados.length === 0 ? (
          <div className="py-12 text-center text-sm text-slate-500">
            No se encontraron equipos con los filtros seleccionados.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3 w-10">
                    <input
                      type="checkbox"
                      checked={
                        seleccionados.length > 0 &&
                        seleccionados.length ===
                          equiposFiltrados.filter((e) => e.estado !== "EN_TRANSITO").length
                      }
                      onChange={toggleSeleccionTodos}
                    />
                  </th>
                  <th className="px-4 py-3">Serial</th>
                  <th className="px-4 py-3">Modelo / SKU</th>
                  <th className="px-4 py-3">Almacén</th>
                  <th className="px-4 py-3">Estado Actual</th>
                  <th className="px-4 py-3">Cambio Rápido</th>
                  <th className="px-4 py-3 text-right">Historial</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {equiposFiltrados.map((eq) => {
                  const badge = etiquetaDeEstado(eq.estado);
                  const bloqueado = eq.estado === "EN_TRANSITO";
                  const valorSelect = eq.estado === "LISTO" ? "DISPONIBLE" : eq.estado;
                  return (
                    <tr key={eq.id} className="hover:bg-slate-50/70">
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          disabled={bloqueado}
                          checked={seleccionados.includes(eq.id)}
                          onChange={() => toggleSeleccion(eq.id)}
                        />
                      </td>
                      <td className="px-4 py-3 font-mono text-xs font-bold text-[#001D3D]">
                        <div>{eq.serial}</div>
                        {eq.es_consignacion && (
                          <span className="mt-0.5 inline-block rounded-full bg-amber-100 px-2 py-0.5 font-sans text-[10px] font-bold text-amber-800">
                            Consignación
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-slate-800">{eq.modelo}</div>
                        <div className="text-xs text-slate-500">{eq.sku || "—"}</div>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-600">
                        {eq.ubicacion || "—"}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-bold ${badge.color}`}
                        >
                          {badge.texto}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <select
                          disabled={bloqueado || procesando}
                          value={valorSelect}
                          onChange={(e) =>
                            void aplicarCambioEstado(
                              [eq.id],
                              e.target.value,
                              "Cambio rápido desde Preparaciones"
                            )
                          }
                          className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 disabled:bg-slate-100"
                        >
                          {OPCIONES_ESTADO.map((o) => (
                            <option key={o.valor} value={o.valor}>
                              {o.etiqueta}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => void abrirHistorial(eq)}
                          className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-100"
                        >
                          <History className="h-3.5 w-3.5" />
                          Ver
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal Historial de Estados */}
      {historialEquipo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4">
          <div className="w-full max-w-lg overflow-hidden rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center justify-between bg-[#003566] px-5 py-3.5 text-white">
              <div>
                <h3 className="text-sm font-bold">
                  Historial de Estados — {historialEquipo.serial}
                </h3>
                <p className="text-xs text-sky-200">{historialEquipo.modelo}</p>
              </div>
              <button
                type="button"
                onClick={() => setHistorialEquipo(null)}
                className="rounded-lg p-1 hover:bg-white/10"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-96 overflow-y-auto p-5">
              {cargandoHistorial ? (
                <div className="flex items-center justify-center py-8 text-xs text-slate-500">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Cargando historial...
                </div>
              ) : historialItems.length === 0 ? (
                <p className="py-6 text-center text-xs text-slate-500">
                  Sin transiciones registradas aún para este equipo.
                </p>
              ) : (
                <ol className="space-y-3">
                  {historialItems.map((h) => (
                    <li
                      key={h.id}
                      className="rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-xs"
                    >
                      <div className="flex items-center justify-between font-semibold text-[#001D3D]">
                        <span>
                          {h.estado_anterior || "INGRESO"} → {h.estado_nuevo_etiqueta}
                        </span>
                        <span className="text-[11px] font-normal text-slate-500">
                          {h.creado_en
                            ? new Date(h.creado_en).toLocaleString("es-VE")
                            : ""}
                        </span>
                      </div>
                      <div className="mt-1 text-slate-600">
                        Responsable: <strong>{h.usuario_nombre || "Sistema"}</strong>
                      </div>
                      {h.observacion && (
                        <div className="mt-1 text-slate-500">{h.observacion}</div>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Modal Carga Masiva */}
      <ModalCargaMasiva
        abierto={modalMasivo}
        alCerrar={() => setModalMasivo(false)}
        tipo="PREPARACION_ESTADOS"
        titulo="Carga Masiva — Cambio de Estado de Equipos"
        sucursales={sucursales}
        alCompletar={() => {
          void cargarDatos();
        }}
      />
    </div>
  );
}
