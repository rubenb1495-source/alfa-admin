"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  PackageCheck,
  Plane,
  Plus,
  ScanBarcode,
  Trash2,
  X,
} from "lucide-react";
import { ErrorApi, formatearUsd, solicitarApi } from "@/servicios/api";
import type { Sucursal } from "@/tipos/dominio";

interface LoteItem {
  id: number;
  tipo_item: "EQUIPO" | "COMPONENTE" | "ACCESORIO";
  sku: string;
  descripcion_esperada: string;
  especificaciones_esperadas: string;
  cantidad_esperada: number;
  costo_unitario_estimado_usd: number;
  precio_promo_usd: number;
  cantidad_recibida: number;
  cantidad_danada_faltante: number;
  descripcion_real: string;
  observacion_recepcion: string;
}

interface LoteTransito {
  id: number;
  codigo: string;
  proveedor_nombre: string;
  almacen_destino_id: number;
  almacen_destino: string;
  fecha_compra: string;
  trackings: string;
  costo_mercancia_estimado_usd: number;
  costo_flete_estimado_usd: number;
  costo_aduana_otros_usd: number;
  total_en_transito_usd: number;
  estado: string;
  observaciones: string;
  total_unidades_esperadas: number;
  total_unidades_recibidas: number;
  items: LoteItem[];
}

interface EquipoSerialDraft {
  serial: string;
  modelo: string;
  especificaciones: string;
  estado_inicial: "PENDIENTE_REVISION" | "EN_PREPARACION" | "POR_INCIDENCIA" | "LISTO";
}

interface ItemRecepcionDraft {
  item_id: number;
  tipo_item: "EQUIPO" | "COMPONENTE" | "ACCESORIO";
  descripcion_real: string;
  especificaciones_reales: string;
  cantidad_esperada: number;
  cantidad_recibida: number;
  cantidad_danada_faltante: number;
  costo_unitario_real_usd: number;
  observacion_recepcion: string;
  equipos_recibidos: EquipoSerialDraft[];
  input_serial: string;
  estado_nuevo_serial: "PENDIENTE_REVISION" | "EN_PREPARACION" | "POR_INCIDENCIA" | "LISTO";
}

export default function PanelLotesTransito() {
  const [lotes, setLotes] = useState<LoteTransito[]>([]);
  const [sucursales, setSucursales] = useState<Sucursal[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);

  // Modal Crear Lote en Tránsito (sin seriales)
  const [modalCrear, setModalCrear] = useState(false);
  const [proveedor, setProveedor] = useState("");
  const [almacenId, setAlmacenId] = useState("");
  const [trackings, setTrackings] = useState("");
  const [fleteEst, setFleteEst] = useState("0");
  const [aduanaEst, setAduanaEst] = useState("0");
  const [obsLote, setObsLote] = useState("");
  const [itemsCrear, setItemsCrear] = useState<
    {
      tipo_item: "EQUIPO" | "COMPONENTE" | "ACCESORIO";
      sku: string;
      descripcion_esperada: string;
      especificaciones_esperadas: string;
      cantidad_esperada: string;
      costo_unitario_estimado_usd: string;
      precio_promo_usd: string;
    }[]
  >([
    {
      tipo_item: "EQUIPO",
      sku: "",
      descripcion_esperada: "",
      especificaciones_esperadas: "",
      cantidad_esperada: "1",
      costo_unitario_estimado_usd: "0",
      precio_promo_usd: "0",
    },
  ]);
  const [guardando, setGuardando] = useState(false);

  // Modal Recepción Flexible en Almacén
  const [loteRecibir, setLoteRecibir] = useState<LoteTransito | null>(null);
  const [almacenRecId, setAlmacenRecId] = useState("");
  const [fleteReal, setFleteReal] = useState("0");
  const [aduanaReal, setAduanaReal] = useState("0");
  const [obsRecepcion, setObsRecepcion] = useState("");
  const [itemsRec, setItemsRec] = useState<ItemRecepcionDraft[]>([]);
  const [recibiendo, setRecibiendo] = useState(false);

  const cargar = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const [respLotes, respSuc] = await Promise.all([
        solicitarApi<LoteTransito[]>("/api/logistica/transito"),
        solicitarApi<Sucursal[]>("/api/sucursales"),
      ]);
      setLotes(respLotes);
      setSucursales(respSuc);
      const alm = respSuc.find((s) => s.nombre.toUpperCase().includes("ALMAC")) || respSuc[0];
      if (alm && !almacenId) setAlmacenId(String(alm.id));
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "No se pudieron cargar los lotes en tránsito.");
    } finally {
      setCargando(false);
    }
  }, [almacenId]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  const totalCrearEstimado =
    itemsCrear.reduce(
      (acc, it) =>
        acc + Number(it.cantidad_esperada || 0) * Number(it.costo_unitario_estimado_usd || 0),
      0
    ) +
    Number(fleteEst || 0) +
    Number(aduanaEst || 0);

  const guardarLote = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setExito(null);
    setGuardando(true);
    try {
      const creado = await solicitarApi<LoteTransito>("/api/logistica/transito", {
        method: "POST",
        body: JSON.stringify({
          proveedor_nombre: proveedor.trim(),
          almacen_destino_id: almacenId ? Number(almacenId) : null,
          trackings: trackings.trim(),
          costo_flete_estimado_usd: Number(fleteEst || 0),
          costo_aduana_otros_usd: Number(aduanaEst || 0),
          observaciones: obsLote.trim(),
          items: itemsCrear.map((it) => ({
            tipo_item: it.tipo_item,
            sku: it.sku.trim(),
            descripcion_esperada: it.descripcion_esperada.trim(),
            especificaciones_esperadas: it.especificaciones_esperadas.trim(),
            cantidad_esperada: Number(it.cantidad_esperada || 1),
            costo_unitario_estimado_usd: Number(it.costo_unitario_estimado_usd || 0),
            precio_promo_usd: Number(it.precio_promo_usd || 0),
          })),
        }),
      });
      setExito(
        `Lote ${creado.codigo} registrado en tránsito (${formatearUsd(creado.total_en_transito_usd)} en cuenta 1.1.04).`
      );
      setModalCrear(false);
      setProveedor("");
      setTrackings("");
      setFleteEst("0");
      setAduanaEst("0");
      setObsLote("");
      setItemsCrear([
        {
          tipo_item: "EQUIPO",
          sku: "",
          descripcion_esperada: "",
          especificaciones_esperadas: "",
          cantidad_esperada: "1",
          costo_unitario_estimado_usd: "0",
          precio_promo_usd: "0",
        },
      ]);
      await cargar();
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "No se pudo registrar el lote en tránsito.");
    } finally {
      setGuardando(false);
    }
  };

  const abrirRecepcion = (lote: LoteTransito) => {
    setLoteRecibir(lote);
    setAlmacenRecId(String(lote.almacen_destino_id));
    setFleteReal(String(lote.costo_flete_estimado_usd));
    setAduanaReal(String(lote.costo_aduana_otros_usd));
    setObsRecepcion("");
    setItemsRec(
      lote.items.map((it) => ({
        item_id: it.id,
        tipo_item: it.tipo_item,
        descripcion_real: it.descripcion_esperada,
        especificaciones_reales: it.especificaciones_esperadas,
        cantidad_esperada: it.cantidad_esperada,
        cantidad_recibida: it.tipo_item === "EQUIPO" ? 0 : it.cantidad_esperada,
        cantidad_danada_faltante: 0,
        costo_unitario_real_usd: it.costo_unitario_estimado_usd,
        observacion_recepcion: "",
        equipos_recibidos: [],
        input_serial: "",
        estado_nuevo_serial: "PENDIENTE_REVISION",
      }))
    );
  };

  const agregarSerialItem = (idx: number) => {
    setItemsRec((prev) =>
      prev.map((it, i) => {
        if (i !== idx) return it;
        const ser = it.input_serial.trim().replace(/\s+/g, "").toUpperCase();
        if (!ser) return it;
        if (it.equipos_recibidos.some((e) => e.serial === ser)) return it;
        const nuevaLista = [
          ...it.equipos_recibidos,
          {
            serial: ser,
            modelo: it.descripcion_real,
            especificaciones: it.especificaciones_reales,
            estado_inicial: it.estado_nuevo_serial,
          },
        ];
        return {
          ...it,
          equipos_recibidos: nuevaLista,
          cantidad_recibida: nuevaLista.length,
          cantidad_danada_faltante: Math.max(0, it.cantidad_esperada - nuevaLista.length),
          input_serial: "",
        };
      })
    );
  };

  const totalUnidadesRec = itemsRec.reduce((acc, it) => acc + Number(it.cantidad_recibida || 0), 0);
  const fleteUnitarioLive =
    totalUnidadesRec > 0
      ? (Number(fleteReal || 0) + Number(aduanaReal || 0)) / totalUnidadesRec
      : 0;

  const confirmarRecepcion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!loteRecibir) return;
    setError(null);
    setExito(null);
    setRecibiendo(true);
    try {
      const resp = await solicitarApi<{
        codigo: string;
        equipos_creados: number;
        componentes_recibidos: number;
        flete_prorrateado_por_unidad_usd: number;
        total_reclasificado_usd: number;
      }>(`/api/logistica/transito/${loteRecibir.id}/recibir`, {
        method: "POST",
        body: JSON.stringify({
          almacen_destino_id: almacenRecId ? Number(almacenRecId) : null,
          costo_flete_real_usd: Number(fleteReal || 0),
          costo_aduana_real_usd: Number(aduanaReal || 0),
          observaciones: obsRecepcion.trim(),
          items: itemsRec.map((it) => ({
            item_id: it.item_id,
            descripcion_real: it.descripcion_real,
            especificaciones_reales: it.especificaciones_reales,
            cantidad_recibida: it.tipo_item === "EQUIPO" ? it.equipos_recibidos.length : it.cantidad_recibida,
            cantidad_danada_faltante: it.cantidad_danada_faltante,
            costo_unitario_real_usd: it.costo_unitario_real_usd,
            observacion_recepcion: it.observacion_recepcion,
            equipos_recibidos: it.equipos_recibidos,
          })),
        }),
      });
      setExito(
        `Lote ${resp.codigo} recibido: ${resp.equipos_creados} equipos + ${resp.componentes_recibidos} comp. · Flete prorrateado: ${formatearUsd(resp.flete_prorrateado_por_unidad_usd)}/u · Reclasificado de 1.1.04: ${formatearUsd(resp.total_reclasificado_usd)}.`
      );
      setLoteRecibir(null);
      await cargar();
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "No se pudo confirmar la recepción del lote.");
    } finally {
      setRecibiendo(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-black text-slate-900 flex items-center gap-2">
            <Plane className="w-5 h-5 text-[#003566]" />
            Lotes en Tránsito (Sin Seriales) → Recepción Flexible en Almacén
          </h3>
          <p className="text-xs text-slate-500">
            Registra compras internacionales con cantidades y trackings (cuenta 1.1.04). Al llegar a
            almacén, ajusta variaciones reales, escanea los seriales y reclasifica el inventario.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setModalCrear(true)}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[#003566] hover:bg-[#001D3D] text-white text-xs font-bold shadow-sm cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          Nuevo Lote en Tránsito
        </button>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-xs text-red-700 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {exito && (
        <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-800 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{exito}</span>
        </div>
      )}

      {cargando ? (
        <div className="p-8 text-center text-xs text-slate-500">Cargando lotes en tránsito...</div>
      ) : lotes.length === 0 ? (
        <div className="p-8 text-center text-xs text-slate-500 bg-white rounded-2xl border border-slate-200">
          No hay lotes en tránsito registrados todavía. Usa &quot;Nuevo Lote en Tránsito&quot; para
          cargar una compra internacional sin seriales.
        </div>
      ) : (
        <div className="space-y-3">
          {lotes.map((l) => (
            <div
              key={l.id}
              className="bg-white rounded-2xl border border-slate-200 p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4"
            >
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono font-black text-slate-900">{l.codigo}</span>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                      l.estado === "RECIBIDO"
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-amber-100 text-amber-800"
                    }`}
                  >
                    {l.estado.replace("_", " ")}
                  </span>
                  <span className="text-xs font-semibold text-slate-700">
                    {l.proveedor_nombre}
                  </span>
                  <span className="text-xs text-slate-500">→ {l.almacen_destino}</span>
                </div>
                <div className="text-xs text-slate-600">
                  Trackings: <strong>{l.trackings || "Sin tracking"}</strong> · Esperado:{" "}
                  <strong>{l.total_unidades_esperadas} u.</strong>
                  {l.estado === "RECIBIDO" && (
                    <>
                      {" "}
                      · Recibido: <strong>{l.total_unidades_recibidas} u.</strong>
                    </>
                  )}{" "}
                  · Valor Tránsito (1.1.04):{" "}
                  <strong className="text-[#003566]">
                    {formatearUsd(l.total_en_transito_usd)}
                  </strong>
                </div>
              </div>

              {l.estado === "EN_TRANSITO" && (
                <button
                  type="button"
                  onClick={() => abrirRecepcion(l)}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold cursor-pointer shrink-0"
                >
                  <PackageCheck className="w-4 h-4" />
                  Recibir en Almacén
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Modal Crear Lote en Tránsito (Sin Seriales) */}
      {modalCrear && (
        <div className="fixed inset-0 z-50 bg-black/45 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-3xl w-full shadow-2xl border border-slate-200 max-h-[90vh] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between bg-[#003566] px-5 py-3.5 text-white">
              <span className="font-bold text-sm">
                Registrar Lote en Tránsito (Sin Seriales · Cuenta 1.1.04)
              </span>
              <button
                type="button"
                onClick={() => setModalCrear(false)}
                className="text-white/80 hover:text-white cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={guardarLote} className="p-5 space-y-4 overflow-y-auto">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Proveedor *</label>
                  <input
                    required
                    value={proveedor}
                    onChange={(e) => setProveedor(e.target.value)}
                    placeholder="Ej. Miami Wholesale Tech"
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Almacén Destino
                  </label>
                  <select
                    value={almacenId}
                    onChange={(e) => setAlmacenId(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm bg-white"
                  >
                    {sucursales.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.nombre}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="sm:col-span-2">
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Números de Tracking / Guías
                  </label>
                  <input
                    value={trackings}
                    onChange={(e) => setTrackings(e.target.value)}
                    placeholder="TRK-001, TRK-002..."
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Flete Estimado (USD)
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={fleteEst}
                    onChange={(e) => setFleteEst(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Aduana / Otros (USD)
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={aduanaEst}
                    onChange={(e) => setAduanaEst(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-700">
                    Mercancía Esperada (sin seriales todavía)
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setItemsCrear((prev) => [
                        ...prev,
                        {
                          tipo_item: "EQUIPO",
                          sku: "",
                          descripcion_esperada: "",
                          especificaciones_esperadas: "",
                          cantidad_esperada: "1",
                          costo_unitario_estimado_usd: "0",
                          precio_promo_usd: "0",
                        },
                      ])
                    }
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-slate-300 text-xs font-bold text-slate-700 cursor-pointer"
                  >
                    <Plus className="w-3 h-3" /> Agregar línea
                  </button>
                </div>

                {itemsCrear.map((it, idx) => (
                  <div
                    key={idx}
                    className="grid grid-cols-1 sm:grid-cols-12 gap-2 p-2.5 rounded-xl bg-slate-50 border border-slate-200 items-center"
                  >
                    <select
                      value={it.tipo_item}
                      onChange={(e) =>
                        setItemsCrear((prev) =>
                          prev.map((x, i) =>
                            i === idx
                              ? {
                                  ...x,
                                  tipo_item: e.target.value as "EQUIPO" | "COMPONENTE" | "ACCESORIO",
                                }
                              : x
                          )
                        )
                      }
                      className="sm:col-span-2 px-2 py-1.5 rounded-lg border border-slate-300 bg-white text-xs"
                    >
                      <option value="EQUIPO">Equipo</option>
                      <option value="COMPONENTE">Componente</option>
                      <option value="ACCESORIO">Accesorio</option>
                    </select>
                    <input
                      required
                      value={it.descripcion_esperada}
                      onChange={(e) =>
                        setItemsCrear((prev) =>
                          prev.map((x, i) =>
                            i === idx ? { ...x, descripcion_esperada: e.target.value } : x
                          )
                        )
                      }
                      placeholder="Modelo / descripción esperada *"
                      className="sm:col-span-4 px-2 py-1.5 rounded-lg border border-slate-300 bg-white text-xs"
                    />
                    <input
                      type="number"
                      min="1"
                      required
                      value={it.cantidad_esperada}
                      onChange={(e) =>
                        setItemsCrear((prev) =>
                          prev.map((x, i) =>
                            i === idx ? { ...x, cantidad_esperada: e.target.value } : x
                          )
                        )
                      }
                      placeholder="Cant."
                      className="sm:col-span-2 px-2 py-1.5 rounded-lg border border-slate-300 bg-white text-xs"
                    />
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={it.costo_unitario_estimado_usd}
                      onChange={(e) =>
                        setItemsCrear((prev) =>
                          prev.map((x, i) =>
                            i === idx
                              ? { ...x, costo_unitario_estimado_usd: e.target.value }
                              : x
                          )
                        )
                      }
                      placeholder="Costo USD"
                      className="sm:col-span-2 px-2 py-1.5 rounded-lg border border-slate-300 bg-white text-xs"
                    />
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={it.precio_promo_usd}
                      onChange={(e) =>
                        setItemsCrear((prev) =>
                          prev.map((x, i) =>
                            i === idx ? { ...x, precio_promo_usd: e.target.value } : x
                          )
                        )
                      }
                      placeholder="Promo USD"
                      className="sm:col-span-1 px-2 py-1.5 rounded-lg border border-slate-300 bg-white text-xs"
                    />
                    <button
                      type="button"
                      onClick={() =>
                        setItemsCrear((prev) =>
                          prev.length > 1 ? prev.filter((_, i) => i !== idx) : prev
                        )
                      }
                      className="sm:col-span-1 text-red-600 hover:text-red-800 flex justify-center cursor-pointer"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>

              <div className="p-3 rounded-xl bg-blue-50 border border-blue-200 flex items-center justify-between text-xs">
                <span className="font-semibold text-blue-900">
                  Total estimado a contabilizar en 1.1.04 (Inventario en Tránsito):
                </span>
                <strong className="text-sm text-[#003566]">
                  {formatearUsd(totalCrearEstimado)}
                </strong>
              </div>

              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setModalCrear(false)}
                  className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-bold text-slate-700 cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={guardando}
                  className="px-4 py-2 rounded-xl bg-[#003566] text-white text-xs font-bold cursor-pointer disabled:opacity-60"
                >
                  {guardando ? "Registrando..." : "Guardar Lote en Tránsito"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Recepción Flexible en Almacén */}
      {loteRecibir && (
        <div className="fixed inset-0 z-50 bg-black/45 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-4xl w-full shadow-2xl border border-slate-200 max-h-[92vh] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between bg-emerald-700 px-5 py-3.5 text-white">
              <div>
                <h3 className="font-bold text-sm">
                  Recepción Flexible en Almacén · {loteRecibir.codigo}
                </h3>
                <p className="text-[11px] text-emerald-100">
                  {loteRecibir.proveedor_nombre} · Trackings: {loteRecibir.trackings || "N/D"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setLoteRecibir(null)}
                className="text-white/80 hover:text-white cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={confirmarRecepcion} className="p-5 space-y-4 overflow-y-auto">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 p-3 rounded-xl bg-slate-50 border border-slate-200">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Almacén de Recepción
                  </label>
                  <select
                    value={almacenRecId}
                    onChange={(e) => setAlmacenRecId(e.target.value)}
                    className="w-full px-2.5 py-1.5 rounded-lg border border-slate-300 bg-white text-xs"
                  >
                    {sucursales.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.nombre}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Flete Real (USD)
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={fleteReal}
                    onChange={(e) => setFleteReal(e.target.value)}
                    className="w-full px-2.5 py-1.5 rounded-lg border border-slate-300 bg-white text-xs"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Aduana / Otros Real (USD)
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={aduanaReal}
                    onChange={(e) => setAduanaReal(e.target.value)}
                    className="w-full px-2.5 py-1.5 rounded-lg border border-slate-300 bg-white text-xs"
                  />
                </div>
                <div className="sm:col-span-3 text-xs text-emerald-800 font-semibold">
                  Prorrateo recalculado sobre {totalUnidadesRec} unidad(es) recibida(s):{" "}
                  <strong>+{formatearUsd(fleteUnitarioLive)} USD / unidad</strong>
                </div>
              </div>

              {itemsRec.map((it, idx) => (
                <div
                  key={it.item_id}
                  className="p-3.5 rounded-xl border border-slate-200 space-y-3 bg-white"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-black text-slate-900">
                      [{it.tipo_item}] Esperado: {it.cantidad_esperada} u.
                    </span>
                    <div className="flex items-center gap-2 text-xs">
                      <span>Faltantes/Dañados:</span>
                      <input
                        type="number"
                        min={0}
                        value={it.cantidad_danada_faltante}
                        onChange={(e) =>
                          setItemsRec((prev) =>
                            prev.map((x, i) =>
                              i === idx
                                ? { ...x, cantidad_danada_faltante: Number(e.target.value || 0) }
                                : x
                            )
                          )
                        }
                        className="w-16 px-2 py-1 rounded-lg border border-slate-300 text-center"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    <input
                      value={it.descripcion_real}
                      onChange={(e) =>
                        setItemsRec((prev) =>
                          prev.map((x, i) =>
                            i === idx ? { ...x, descripcion_real: e.target.value } : x
                          )
                        )
                      }
                      placeholder="Modelo / descripción real recibida"
                      className="px-2.5 py-1.5 rounded-lg border border-slate-300 text-xs"
                    />
                    <input
                      value={it.especificaciones_reales}
                      onChange={(e) =>
                        setItemsRec((prev) =>
                          prev.map((x, i) =>
                            i === idx ? { ...x, especificaciones_reales: e.target.value } : x
                          )
                        )
                      }
                      placeholder="Specs reales (RAM/SSD/CPU)"
                      className="px-2.5 py-1.5 rounded-lg border border-slate-300 text-xs"
                    />
                    <input
                      value={it.observacion_recepcion}
                      onChange={(e) =>
                        setItemsRec((prev) =>
                          prev.map((x, i) =>
                            i === idx ? { ...x, observacion_recepcion: e.target.value } : x
                          )
                        )
                      }
                      placeholder="Observación / novedad real"
                      className="px-2.5 py-1.5 rounded-lg border border-slate-300 text-xs"
                    />
                  </div>

                  {it.tipo_item === "EQUIPO" ? (
                    <div className="space-y-2 p-2.5 rounded-xl bg-slate-50 border border-slate-200">
                      <div className="flex flex-wrap gap-2">
                        <div className="relative flex-1 min-w-[180px]">
                          <ScanBarcode className="w-4 h-4 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                          <input
                            value={it.input_serial}
                            onChange={(e) =>
                              setItemsRec((prev) =>
                                prev.map((x, i) =>
                                  i === idx ? { ...x, input_serial: e.target.value } : x
                                )
                              )
                            }
                            onKeyDown={(e) => {
                              if (e.key === "Enter") {
                                e.preventDefault();
                                agregarSerialItem(idx);
                              }
                            }}
                            placeholder="Escanea o escribe el serial real y presiona Enter..."
                            className="w-full pl-8 pr-3 py-1.5 rounded-lg border border-slate-300 bg-white text-xs font-mono uppercase"
                          />
                        </div>
                        <select
                          value={it.estado_nuevo_serial}
                          onChange={(e) =>
                            setItemsRec((prev) =>
                              prev.map((x, i) =>
                                i === idx
                                  ? {
                                      ...x,
                                      estado_nuevo_serial: e.target
                                        .value as EquipoSerialDraft["estado_inicial"],
                                    }
                                  : x
                              )
                            )
                          }
                          className="px-2.5 py-1.5 rounded-lg border border-slate-300 bg-white text-xs"
                        >
                          <option value="PENDIENTE_REVISION">Pendiente Revisión</option>
                          <option value="EN_PREPARACION">En Preparación</option>
                          <option value="POR_INCIDENCIA">Por Incidencia</option>
                          <option value="LISTO">Listo / Disponible</option>
                        </select>
                        <button
                          type="button"
                          onClick={() => agregarSerialItem(idx)}
                          className="px-3 py-1.5 rounded-lg bg-[#003566] text-white text-xs font-bold cursor-pointer"
                        >
                          + Agregar
                        </button>
                      </div>

                      {it.equipos_recibidos.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 pt-1">
                          {it.equipos_recibidos.map((eq, eqIdx) => (
                            <span
                              key={eq.serial}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white border border-slate-300 text-[11px] font-mono"
                            >
                              <strong>{eq.serial}</strong>
                              <span className="text-[10px] text-slate-500">
                                ({eq.estado_inicial})
                              </span>
                              <button
                                type="button"
                                onClick={() =>
                                  setItemsRec((prev) =>
                                    prev.map((x, i) => {
                                      if (i !== idx) return x;
                                      const filt = x.equipos_recibidos.filter(
                                        (_, j) => j !== eqIdx
                                      );
                                      return {
                                        ...x,
                                        equipos_recibidos: filt,
                                        cantidad_recibida: filt.length,
                                      };
                                    })
                                  )
                                }
                                className="text-red-500 hover:text-red-700 cursor-pointer"
                              >
                                ×
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="flex items-center gap-3 text-xs">
                      <span className="font-semibold text-slate-700">
                        Cantidad real recibida:
                      </span>
                      <input
                        type="number"
                        min={0}
                        value={it.cantidad_recibida}
                        onChange={(e) =>
                          setItemsRec((prev) =>
                            prev.map((x, i) =>
                              i === idx
                                ? { ...x, cantidad_recibida: Number(e.target.value || 0) }
                                : x
                            )
                          )
                        }
                        className="w-24 px-2.5 py-1 rounded-lg border border-slate-300 font-bold"
                      />
                    </div>
                  )}
                </div>
              ))}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setLoteRecibir(null)}
                  className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-bold text-slate-700 cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={recibiendo || totalUnidadesRec === 0}
                  className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold disabled:opacity-50 cursor-pointer"
                >
                  {recibiendo
                    ? "Recibiendo y contabilizando..."
                    : "Confirmar Recepción y Reclasificar (1.1.04 → 1.1.03/1.1.05)"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
