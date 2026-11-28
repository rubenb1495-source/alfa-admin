"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  PackageCheck,
  Plane,
  Plus,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { ErrorApi, formatearUsd, solicitarApi } from "@/servicios/api";
import type { ArticuloCatalogo, CatalogoPaginado, Sucursal } from "@/tipos/dominio";

interface EquipoLote {
  id: number;
  serial: string;
  modelo: string;
  configuracion: string;
  grado_estetico: string;
  proceso_inicial: string;
  estado: string;
  ubicacion_id: number;
  primer_costo_usd?: number;
  costo_final_usd?: number;
}

interface LoteInternacional {
  id: number;
  codigo: string;
  proveedor_nombre: string;
  referencia: string;
  descripcion_previa: string;
  cantidad_equipos_esperados: number;
  cantidad_equipos_recibidos: number;
  cantidad_pendiente: number;
  estado: string;
  fecha_compra: string;
  fecha_recepcion: string | null;
  observaciones: string;
  monto_compra_usd?: number;
  taxes_usd?: number;
  envio_miami_usd?: number;
  subtotal_miami_usd?: number;
  gastos_envio_venezuela_usd?: number;
  costo_total_aterrizado_usd?: number;
  equipos: EquipoLote[];
}

interface FilaSerialRecepcion {
  serial: string;
  modelo: string;
  configuracion: string;
  grado_estetico: string;
  ubicacion_id: string;
  proceso_inicial: "REVISION" | "PREPARACION" | "HOSPITAL" | "CEMENTERIO";
  precio_promo_usd: string;
  primer_costo_manual_usd: string;
  observaciones: string;
}

interface EquipoInventarioItem {
  id: number;
  serial: string;
  modelo: string;
  configuracion: string;
  estado: string;
  ubicacion_id: number;
  ubicacion?: string;
  costo_compra_usd?: number;
  costo_taller_usd?: number;
  precio_promo_usd?: number;
}

const PROCESOS_OPCIONES = [
  { val: "REVISION", label: "Revisión" },
  { val: "PREPARACION", label: "Preparación" },
  { val: "HOSPITAL", label: "Hospital" },
  { val: "CEMENTERIO", label: "Cementerio" },
] as const;

export default function PaginaImportacionesCosteo() {
  const [tab, setTab] = useState<"lotes" | "preparacion">("lotes");
  const [lotes, setLotes] = useState<LoteInternacional[]>([]);
  const [sucursales, setSucursales] = useState<Sucursal[]>([]);
  const [equiposEnProceso, setEquiposEnProceso] = useState<EquipoInventarioItem[]>([]);
  const [componentesCat, setComponentesCat] = useState<ArticuloCatalogo[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);

  // Formulario nuevo lote internacional
  const [proveedor, setProveedor] = useState("");
  const [referencia, setReferencia] = useState("");
  const [descripcionPrevia, setDescripcionPrevia] = useState("");
  const [cantidadEsperada, setCantidadEsperada] = useState("3");
  const [montoCompra, setMontoCompra] = useState("");
  const [taxesUsd, setTaxesUsd] = useState("0");
  const [envioMiamiUsd, setEnvioMiamiUsd] = useState("0");
  const [guardandoLote, setGuardandoLote] = useState(false);

  // Modal recepción en Venezuela
  const [loteRecibir, setLoteRecibir] = useState<LoteInternacional | null>(null);
  const [gastosEnvioVzla, setGastosEnvioVzla] = useState("0");
  const [filasRec, setFilasRec] = useState<FilaSerialRecepcion[]>([]);
  const [usarCostoManual, setUsarCostoManual] = useState(false);
  const [guardandoRec, setGuardandoRec] = useState(false);

  // Modal preparación / costo final
  const [eqPrep, setEqPrep] = useState<EquipoInventarioItem | null>(null);
  const [compsSel, setCompsSel] = useState<{ articulo_id: string; cantidad: number }[]>([]);
  const [comisionPrep, setComisionPrep] = useState("10");
  const [precioPromoPrep, setPrecioPromoPrep] = useState("");
  const [marcarDisponible, setMarcarDisponible] = useState(true);
  const [notaPrep, setNotaPrep] = useState("");
  const [guardandoPrep, setGuardandoPrep] = useState(false);

  const cargarTodo = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const [rLotes, rSuc, rEqs, rCat] = await Promise.all([
        solicitarApi<LoteInternacional[]>("/api/importaciones/lotes"),
        solicitarApi<Sucursal[]>("/api/sucursales"),
        solicitarApi<EquipoInventarioItem[]>("/api/logistica/inventario/equipos?por_pagina=200"),
        solicitarApi<CatalogoPaginado>("/api/catalogo?por_pagina=200"),
      ]);
      setLotes(rLotes);
      setSucursales(rSuc.filter((s) => s.estado === "ACTIVA"));
      setEquiposEnProceso(
        rEqs.filter((e) =>
          ["PENDIENTE_REVISION", "POR_PREPARAR", "EN_PREPARACION", "HOSPITAL", "CEMENTERIO"].includes(
            e.estado
          )
        )
      );
      setComponentesCat(
        rCat.elementos.filter((a) => a.tipo === "COMPONENTE" || a.tipo === "ACCESORIO")
      );
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "No se pudieron cargar las importaciones.");
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void cargarTodo();
  }, [cargarTodo]);

  const subtotalMiamiPreview = useMemo(() => {
    return (Number(montoCompra) || 0) + (Number(taxesUsd) || 0) + (Number(envioMiamiUsd) || 0);
  }, [montoCompra, taxesUsd, envioMiamiUsd]);

  const crearLote = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setGuardandoLote(true);
    setError(null);
    setExito(null);
    try {
      const res = await solicitarApi<LoteInternacional>("/api/importaciones/lotes", {
        method: "POST",
        body: JSON.stringify({
          proveedor_nombre: proveedor.trim(),
          referencia: referencia.trim(),
          descripcion_previa: descripcionPrevia.trim(),
          cantidad_equipos_esperados: Number(cantidadEsperada),
          monto_compra_usd: Number(montoCompra),
          taxes_usd: Number(taxesUsd || 0),
          envio_miami_usd: Number(envioMiamiUsd || 0),
        }),
      });
      setExito(
        `Lote internacional ${res.codigo} registrado en Tránsito (Subtotal Miami: ${formatearUsd(res.subtotal_miami_usd || 0)}).`
      );
      setProveedor("");
      setReferencia("");
      setDescripcionPrevia("");
      setMontoCompra("");
      setTaxesUsd("0");
      setEnvioMiamiUsd("0");
      await cargarTodo();
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "No se pudo registrar el lote.");
    } finally {
      setGuardandoLote(false);
    }
  };

  const abrirRecepcion = (lote: LoteInternacional) => {
    const sucDef = sucursales[0] ? String(sucursales[0].id) : "";
    const cant = Math.max(1, lote.cantidad_pendiente);
    const iniciales: FilaSerialRecepcion[] = Array.from({ length: cant }, () => ({
      serial: "",
      modelo: "",
      configuracion: "",
      grado_estetico: "Grado A",
      ubicacion_id: sucDef,
      proceso_inicial: "PREPARACION",
      precio_promo_usd: "0",
      primer_costo_manual_usd: "",
      observaciones: "",
    }));
    setLoteRecibir(lote);
    setGastosEnvioVzla("0");
    setUsarCostoManual(false);
    setFilasRec(iniciales);
  };

  const costoPorcionRecepcion = useMemo(() => {
    if (!loteRecibir || filasRec.length === 0) return 0;
    const prop = filasRec.length / Math.max(1, loteRecibir.cantidad_equipos_esperados);
    return (loteRecibir.subtotal_miami_usd || 0) * prop + (Number(gastosEnvioVzla) || 0);
  }, [loteRecibir, filasRec.length, gastosEnvioVzla]);

  const primerCostoAuto = useMemo(() => {
    if (filasRec.length === 0) return 0;
    return costoPorcionRecepcion / filasRec.length;
  }, [costoPorcionRecepcion, filasRec.length]);

  const confirmarRecepcion = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!loteRecibir) return;
    setGuardandoRec(true);
    setError(null);
    setExito(null);
    try {
      const payload = {
        gastos_envio_venezuela_usd: Number(gastosEnvioVzla || 0),
        equipos: filasRec.map((f) => ({
          serial: f.serial.trim(),
          modelo: f.modelo.trim(),
          configuracion: f.configuracion.trim(),
          grado_estetico: f.grado_estetico.trim(),
          ubicacion_id: Number(f.ubicacion_id),
          proceso_inicial: f.proceso_inicial,
          precio_promo_usd: Number(f.precio_promo_usd || 0),
          primer_costo_manual_usd:
            usarCostoManual && f.primer_costo_manual_usd !== ""
              ? Number(f.primer_costo_manual_usd)
              : null,
          observaciones: f.observaciones.trim(),
        })),
      };
      const res = await solicitarApi<{
        equipos_recibidos: { serial: string }[];
        costo_aterrizado_recepcion_usd: number;
      }>(`/api/importaciones/lotes/${loteRecibir.id}/recibir`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setExito(
        `Recepción completada: ${res.equipos_recibidos.length} seriales ingresados (Costo aterrizado: ${formatearUsd(res.costo_aterrizado_recepcion_usd)}).`
      );
      setLoteRecibir(null);
      await cargarTodo();
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "No se pudo confirmar la recepción.");
    } finally {
      setGuardandoRec(false);
    }
  };

  const cambiarProcesoRapido = async (eqId: number, nuevoProceso: string) => {
    setError(null);
    try {
      await solicitarApi(`/api/importaciones/equipos/${eqId}/proceso`, {
        method: "PATCH",
        body: JSON.stringify({ nuevo_proceso: nuevoProceso }),
      });
      setExito("Estado del equipo actualizado con trazabilidad.");
      await cargarTodo();
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "No se pudo cambiar el estado.");
    }
  };

  const confirmarPreparacion = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!eqPrep) return;
    setGuardandoPrep(true);
    setError(null);
    setExito(null);
    try {
      const res = await solicitarApi<{
        serial: string;
        costo_final_usd: number;
        estado: string;
      }>(`/api/importaciones/equipos/${eqPrep.id}/preparacion`, {
        method: "POST",
        body: JSON.stringify({
          componentes: compsSel
            .filter((c) => c.articulo_id)
            .map((c) => ({ articulo_id: Number(c.articulo_id), cantidad: c.cantidad })),
          comision_preparacion_usd: Number(comisionPrep || 0),
          precio_promo_usd: precioPromoPrep ? Number(precioPromoPrep) : null,
          marcar_disponible: marcarDisponible,
          nota_tecnica: notaPrep.trim(),
        }),
      });
      setExito(
        `Equipo ${res.serial} actualizado a ${res.estado} · Costo Final oficial: ${formatearUsd(res.costo_final_usd)}.`
      );
      setEqPrep(null);
      await cargarTodo();
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "Error al guardar la preparación.");
    } finally {
      setGuardandoPrep(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-[#001D3D] flex items-center gap-2">
            <Plane className="w-6 h-6 text-[#003566]" />
            Compras Internacionales, Costeo y Preparación
          </h1>
          <p className="text-sm text-slate-500">
            Lote en Tránsito (Miami) → Recepción en Venezuela (Primer Costo) → Preparación (Componentes + Comisión = Costo Final).
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-xl bg-slate-100 p-1 border border-slate-200">
            <button
              type="button"
              onClick={() => setTab("lotes")}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-bold cursor-pointer ${
                tab === "lotes" ? "bg-[#003566] text-white" : "text-slate-600"
              }`}
            >
              1. Compras y Recepción ({lotes.length})
            </button>
            <button
              type="button"
              onClick={() => setTab("preparacion")}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-bold cursor-pointer ${
                tab === "preparacion" ? "bg-[#003566] text-white" : "text-slate-600"
              }`}
            >
              2. Preparación y Costo Final ({equiposEnProceso.length})
            </button>
          </div>
          <Link
            href="/dashboard/logistica/trazabilidad"
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl border border-[#003566] text-[#003566] text-xs font-bold hover:bg-[#EDF3FA]"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            Trazabilidad por Serial
          </Link>
        </div>
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

      {tab === "lotes" && (
        <div className="space-y-6">
          {/* Formulario de Compra Internacional sin seriales */}
          <form
            onSubmit={crearLote}
            className="bg-white rounded-2xl border border-slate-200 p-5 space-y-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-black text-[#001D3D]">
                Registrar Compra Internacional (En Tránsito / Sin Seriales)
              </h2>
              <span className="px-3 py-1 rounded-full bg-[#EDF3FA] text-[#003566] text-xs font-black cifra-tabular">
                Subtotal en Miami: {formatearUsd(subtotalMiamiPreview)}
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
              <div>
                <label className="block font-bold text-slate-600 mb-1">Proveedor *</label>
                <input
                  type="text"
                  required
                  value={proveedor}
                  onChange={(e) => setProveedor(e.target.value)}
                  placeholder="Ej. Miami Wholesale Tech"
                  className="w-full px-3 py-2 rounded-xl border border-slate-300"
                />
              </div>
              <div>
                <label className="block font-bold text-slate-600 mb-1">Referencia / Invoice</label>
                <input
                  type="text"
                  value={referencia}
                  onChange={(e) => setReferencia(e.target.value)}
                  placeholder="Ej. INV-2026-884"
                  className="w-full px-3 py-2 rounded-xl border border-slate-300"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="block font-bold text-slate-600 mb-1">Descripción previa del lote *</label>
                <input
                  type="text"
                  required
                  value={descripcionPrevia}
                  onChange={(e) => setDescripcionPrevia(e.target.value)}
                  placeholder="Ej. Lote de 3 Laptops Dell Latitude i5 11va"
                  className="w-full px-3 py-2 rounded-xl border border-slate-300"
                />
              </div>
              <div>
                <label className="block font-bold text-slate-600 mb-1">Cantidad de equipos *</label>
                <input
                  type="number"
                  min={1}
                  required
                  value={cantidadEsperada}
                  onChange={(e) => setCantidadEsperada(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 font-bold"
                />
              </div>
              <div>
                <label className="block font-bold text-slate-600 mb-1">Monto total compra (USD) *</label>
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  required
                  value={montoCompra}
                  onChange={(e) => setMontoCompra(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 font-bold"
                />
              </div>
              <div>
                <label className="block font-bold text-slate-600 mb-1">Taxes EE.UU. (USD)</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={taxesUsd}
                  onChange={(e) => setTaxesUsd(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300"
                />
              </div>
              <div>
                <label className="block font-bold text-slate-600 mb-1">Envío a Miami (USD)</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={envioMiamiUsd}
                  onChange={(e) => setEnvioMiamiUsd(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300"
                />
              </div>
            </div>

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={guardandoLote}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#003566] hover:bg-[#001D3D] disabled:opacity-60 text-white text-xs font-bold cursor-pointer"
              >
                <Plus className="w-4 h-4" />
                {guardandoLote ? "Guardando lote..." : "Registrar Lote en Tránsito"}
              </button>
            </div>
          </form>

          {/* Tabla de lotes */}
          <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
            <div className="px-5 py-3.5 border-b border-slate-200 font-black text-sm text-[#001D3D]">
              Lotes Internacionales ({lotes.length})
            </div>
            {cargando ? (
              <p className="p-6 text-xs text-slate-500">Cargando lotes...</p>
            ) : lotes.length === 0 ? (
              <p className="p-8 text-xs text-slate-500 text-center">
                No hay lotes internacionales registrados todavía.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
                    <tr>
                      <th className="px-4 py-2.5">Código / Fecha</th>
                      <th className="px-4 py-2.5">Proveedor / Descripción</th>
                      <th className="px-4 py-2.5 text-center">Recibidos</th>
                      <th className="px-4 py-2.5 text-right">Subtotal Miami</th>
                      <th className="px-4 py-2.5 text-right">Envío Vzla</th>
                      <th className="px-4 py-2.5 text-right">Total Aterrizado</th>
                      <th className="px-4 py-2.5">Estado</th>
                      <th className="px-4 py-2.5 text-right">Acción</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {lotes.map((l) => (
                      <tr key={l.id} className="hover:bg-slate-50/70">
                        <td className="px-4 py-3 font-mono font-bold text-[#001D3D]">
                          {l.codigo}
                          <span className="block font-sans font-normal text-slate-500">
                            {l.fecha_compra}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <p className="font-bold text-slate-800">{l.proveedor_nombre}</p>
                          <p className="text-slate-500">{l.descripcion_previa}</p>
                        </td>
                        <td className="px-4 py-3 text-center font-bold cifra-tabular">
                          {l.cantidad_equipos_recibidos} / {l.cantidad_equipos_esperados}
                        </td>
                        <td className="px-4 py-3 text-right cifra-tabular">
                          {formatearUsd(l.subtotal_miami_usd || 0)}
                        </td>
                        <td className="px-4 py-3 text-right cifra-tabular">
                          {formatearUsd(l.gastos_envio_venezuela_usd || 0)}
                        </td>
                        <td className="px-4 py-3 text-right font-bold text-[#003566] cifra-tabular">
                          {formatearUsd(l.costo_total_aterrizado_usd || 0)}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                              l.estado === "RECIBIDO"
                                ? "bg-emerald-50 text-emerald-700"
                                : "bg-amber-50 text-amber-800"
                            }`}
                          >
                            {l.estado}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          {l.cantidad_pendiente > 0 && (
                            <button
                              type="button"
                              onClick={() => abrirRecepcion(l)}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#003566] hover:bg-[#001D3D] text-white text-xs font-bold cursor-pointer"
                            >
                              <PackageCheck className="w-3.5 h-3.5" />
                              Recibir ({l.cantidad_pendiente})
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "preparacion" && (
        <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
          <div className="px-5 py-3.5 border-b border-slate-200 font-black text-sm text-[#001D3D] flex items-center gap-2">
            <Wrench className="w-4 h-4 text-[#003566]" />
            Equipos en Revisión, Preparación, Hospital y Cementerio ({equiposEnProceso.length})
          </div>
          {equiposEnProceso.length === 0 ? (
            <p className="p-8 text-xs text-slate-500 text-center">
              No hay equipos en procesos de taller/revisión en este momento.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-2.5">Serial / Modelo</th>
                    <th className="px-4 py-2.5">Ubicación</th>
                    <th className="px-4 py-2.5">Estado Actual</th>
                    <th className="px-4 py-2.5">Mover Proceso</th>
                    <th className="px-4 py-2.5 text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {equiposEnProceso.map((eq) => (
                    <tr key={eq.id} className="hover:bg-slate-50/70">
                      <td className="px-4 py-3">
                        <p className="font-mono font-bold text-[#001D3D]">{eq.serial}</p>
                        <p className="text-slate-600">{eq.modelo}</p>
                      </td>
                      <td className="px-4 py-3 text-slate-600">{eq.ubicacion || "—"}</td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 text-[10px] font-bold">
                          {eq.estado}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <select
                          defaultValue=""
                          onChange={(e) => {
                            if (e.target.value) {
                              void cambiarProcesoRapido(eq.id, e.target.value);
                              e.target.value = "";
                            }
                          }}
                          className="px-2.5 py-1 rounded-lg border border-slate-300 text-xs bg-white"
                        >
                          <option value="">Cambiar a...</option>
                          {PROCESOS_OPCIONES.map((op) => (
                            <option key={op.val} value={op.val}>
                              {op.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-4 py-3 text-right space-x-2">
                        <button
                          type="button"
                          onClick={() => {
                            setEqPrep(eq);
                            setCompsSel([]);
                            setComisionPrep("10");
                            setPrecioPromoPrep(String(eq.precio_promo_usd || ""));
                            setMarcarDisponible(true);
                            setNotaPrep("");
                          }}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-[#003566] text-white text-xs font-bold cursor-pointer"
                        >
                          <Wrench className="w-3.5 h-3.5" />
                          Preparar / Costo Final
                        </button>
                        <Link
                          href={`/dashboard/logistica/trazabilidad?serial=${encodeURIComponent(eq.serial)}`}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-slate-300 text-slate-700 text-xs font-bold hover:bg-slate-50"
                        >
                          Hoja de Vida
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Modal Recepción en Venezuela */}
      {loteRecibir && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
          <form
            onSubmit={confirmarRecepcion}
            className="bg-white rounded-2xl border border-slate-200 max-w-5xl w-full max-h-[90vh] flex flex-col shadow-xl overflow-hidden"
          >
            <div className="px-5 py-4 bg-[#001D3D] text-white flex items-center justify-between">
              <div>
                <h3 className="text-sm font-black">
                  Recepción en Venezuela · Lote {loteRecibir.codigo}
                </h3>
                <p className="text-[11px] text-sky-200">
                  Primer Costo prorrateado estimado: {formatearUsd(primerCostoAuto)} por equipo
                </p>
              </div>
              <button
                type="button"
                onClick={() => setLoteRecibir(null)}
                className="p-1.5 rounded-lg hover:bg-white/10 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-5 overflow-y-auto space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs bg-slate-50 p-3.5 rounded-xl border border-slate-200">
                <div>
                  <label className="block font-bold text-slate-600 mb-1">
                    Gastos de envío a Venezuela (USD)
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={gastosEnvioVzla}
                    onChange={(e) => setGastosEnvioVzla(e.target.value)}
                    className="w-full px-3 py-1.5 rounded-lg border border-slate-300 bg-white font-bold"
                  />
                </div>
                <div className="flex flex-col justify-center">
                  <span className="text-slate-500">Costo Aterrizado a Distribuir:</span>
                  <strong className="text-base text-[#003566] cifra-tabular">
                    {formatearUsd(costoPorcionRecepcion)}
                  </strong>
                </div>
                <label className="flex items-center gap-2 font-bold text-slate-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={usarCostoManual}
                    onChange={(e) => setUsarCostoManual(e.target.checked)}
                  />
                  Ajustar Primer Costo manual por serial
                </label>
              </div>

              <div className="space-y-2.5">
                {filasRec.map((f, idx) => (
                  <div
                    key={idx}
                    className="p-3 rounded-xl border border-slate-200 bg-white grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-6 gap-2 text-xs items-end"
                  >
                    <div>
                      <label className="block font-bold text-slate-500 mb-0.5">Serial #{idx + 1} *</label>
                      <input
                        type="text"
                        required
                        value={f.serial}
                        onChange={(e) => {
                          const c = [...filasRec];
                          c[idx] = { ...c[idx], serial: e.target.value };
                          setFilasRec(c);
                        }}
                        placeholder="SN-001"
                        className="w-full px-2.5 py-1.5 rounded-lg border border-slate-300 font-mono"
                      />
                    </div>
                    <div>
                      <label className="block font-bold text-slate-500 mb-0.5">Modelo *</label>
                      <input
                        type="text"
                        required
                        value={f.modelo}
                        onChange={(e) => {
                          const c = [...filasRec];
                          c[idx] = { ...c[idx], modelo: e.target.value };
                          setFilasRec(c);
                        }}
                        placeholder="Dell 5420"
                        className="w-full px-2.5 py-1.5 rounded-lg border border-slate-300"
                      />
                    </div>
                    <div>
                      <label className="block font-bold text-slate-500 mb-0.5">Specs / Grado</label>
                      <input
                        type="text"
                        value={f.configuracion}
                        onChange={(e) => {
                          const c = [...filasRec];
                          c[idx] = { ...c[idx], configuracion: e.target.value };
                          setFilasRec(c);
                        }}
                        placeholder="i5 / 8GB / 256GB"
                        className="w-full px-2.5 py-1.5 rounded-lg border border-slate-300"
                      />
                    </div>
                    <div>
                      <label className="block font-bold text-slate-500 mb-0.5">Ubicación *</label>
                      <select
                        required
                        value={f.ubicacion_id}
                        onChange={(e) => {
                          const c = [...filasRec];
                          c[idx] = { ...c[idx], ubicacion_id: e.target.value };
                          setFilasRec(c);
                        }}
                        className="w-full px-2 py-1.5 rounded-lg border border-slate-300 bg-white"
                      >
                        {sucursales.map((s) => (
                          <option key={s.id} value={String(s.id)}>
                            {s.nombre}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block font-bold text-slate-500 mb-0.5">Proceso Inicial *</label>
                      <select
                        required
                        value={f.proceso_inicial}
                        onChange={(e) => {
                          const c = [...filasRec];
                          c[idx] = {
                            ...c[idx],
                            proceso_inicial: e.target.value as FilaSerialRecepcion["proceso_inicial"],
                          };
                          setFilasRec(c);
                        }}
                        className="w-full px-2 py-1.5 rounded-lg border border-slate-300 bg-white font-bold"
                      >
                        {PROCESOS_OPCIONES.map((op) => (
                          <option key={op.val} value={op.val}>
                            {op.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block font-bold text-slate-500 mb-0.5">
                        {usarCostoManual ? "Primer Costo $" : "Precio Promo $"}
                      </label>
                      {usarCostoManual ? (
                        <input
                          type="number"
                          step="0.01"
                          required
                          value={f.primer_costo_manual_usd}
                          onChange={(e) => {
                            const c = [...filasRec];
                            c[idx] = { ...c[idx], primer_costo_manual_usd: e.target.value };
                            setFilasRec(c);
                          }}
                          className="w-full px-2.5 py-1.5 rounded-lg border border-amber-400 font-bold"
                        />
                      ) : (
                        <input
                          type="number"
                          step="0.01"
                          value={f.precio_promo_usd}
                          onChange={(e) => {
                            const c = [...filasRec];
                            c[idx] = { ...c[idx], precio_promo_usd: e.target.value };
                            setFilasRec(c);
                          }}
                          className="w-full px-2.5 py-1.5 rounded-lg border border-slate-300"
                        />
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="px-5 py-3.5 border-t border-slate-200 bg-slate-50 flex items-center justify-between">
              <button
                type="button"
                onClick={() => {
                  if (filasRec.length > 1) setFilasRec(filasRec.slice(0, -1));
                }}
                className="text-xs font-bold text-slate-600 hover:underline cursor-pointer"
              >
                Recibir parcial (quitar última fila)
              </button>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setLoteRecibir(null)}
                  className="px-4 py-2 rounded-xl border border-slate-300 bg-white text-xs font-bold cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={guardandoRec}
                  className="px-5 py-2 rounded-xl bg-[#003566] hover:bg-[#001D3D] disabled:opacity-60 text-white text-xs font-bold cursor-pointer"
                >
                  {guardandoRec ? "Registrando..." : "Confirmar Recepción y Primer Costo"}
                </button>
              </div>
            </div>
          </form>
        </div>
      )}

      {/* Modal Ficha de Preparación y Costo Final */}
      {eqPrep && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
          <form
            onSubmit={confirmarPreparacion}
            className="bg-white rounded-2xl border border-slate-200 max-w-xl w-full p-5 space-y-4 shadow-xl"
          >
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-base font-black text-[#001D3D]">
                  Ficha de Preparación · {eqPrep.serial}
                </h3>
                <p className="text-xs text-slate-500">{eqPrep.modelo}</p>
              </div>
              <button type="button" onClick={() => setEqPrep(null)} className="cursor-pointer">
                <X className="w-4 h-4 text-slate-400" />
              </button>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-700">
                  Componentes / Repuestos agregados del inventario
                </span>
                <button
                  type="button"
                  onClick={() =>
                    setCompsSel([...compsSel, { articulo_id: componentesCat[0] ? String(componentesCat[0].id) : "", cantidad: 1 }])
                  }
                  className="inline-flex items-center gap-1 text-xs font-bold text-[#003566] cursor-pointer"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Agregar componente
                </button>
              </div>

              {compsSel.map((cs, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <select
                    value={cs.articulo_id}
                    onChange={(e) => {
                      const c = [...compsSel];
                      c[idx] = { ...c[idx], articulo_id: e.target.value };
                      setCompsSel(c);
                    }}
                    className="flex-1 px-2.5 py-1.5 rounded-lg border border-slate-300 text-xs bg-white"
                  >
                    <option value="">Selecciona componente...</option>
                    {componentesCat.map((a) => (
                      <option key={a.id} value={String(a.id)}>
                        {a.sku} · {a.descripcion}
                      </option>
                    ))}
                  </select>
                  <input
                    type="number"
                    min={1}
                    value={cs.cantidad}
                    onChange={(e) => {
                      const c = [...compsSel];
                      c[idx] = { ...c[idx], cantidad: Number(e.target.value || 1) };
                      setCompsSel(c);
                    }}
                    className="w-16 px-2 py-1.5 rounded-lg border border-slate-300 text-xs text-center font-bold"
                  />
                  <button
                    type="button"
                    onClick={() => setCompsSel(compsSel.filter((_, i) => i !== idx))}
                    className="text-rose-500 cursor-pointer"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <label className="block font-bold text-slate-600 mb-1">
                  Comisión de Preparación (USD)
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={comisionPrep}
                  onChange={(e) => setComisionPrep(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 font-bold"
                />
              </div>
              <div>
                <label className="block font-bold text-slate-600 mb-1">
                  Precio Promo de Venta (USD)
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={precioPromoPrep}
                  onChange={(e) => setPrecioPromoPrep(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 font-bold"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-600 mb-1">Nota técnica</label>
              <textarea
                rows={2}
                value={notaPrep}
                onChange={(e) => setNotaPrep(e.target.value)}
                placeholder="Detalle del trabajo realizado..."
                className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs"
              />
            </div>

            <label className="flex items-center gap-2 text-xs font-bold text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-xl px-3 py-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={marcarDisponible}
                onChange={(e) => setMarcarDisponible(e.target.checked)}
              />
              Marcar como Disponible (Listo para la venta) y fijar Costo Final oficial
            </label>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEqPrep(null)}
                className="px-4 py-2 rounded-xl border border-slate-300 text-xs font-bold cursor-pointer"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={guardandoPrep}
                className="px-5 py-2 rounded-xl bg-[#003566] hover:bg-[#001D3D] disabled:opacity-60 text-white text-xs font-bold cursor-pointer"
              >
                {guardandoPrep ? "Guardando..." : "Guardar Preparación y Costo Final"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
