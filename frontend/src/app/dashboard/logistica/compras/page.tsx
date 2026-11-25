"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Globe2,
  Handshake,
  Loader2,
  Plus,
  ShoppingBag,
  Trash2,
} from "lucide-react";
import ModalCargaMasiva, {
  descargarPlantillaLogistica,
  type TipoCargaMasiva,
} from "@/components/ModalCargaMasiva";
import { ErrorApi, formatearUsd, solicitarApi } from "@/servicios/api";
import type { ArticuloCatalogo, CatalogoPaginado, Sucursal } from "@/tipos/dominio";

type TipoIngresoTab = "COMPRA_NACIONAL" | "COMPRA_INTERNACIONAL" | "CONSIGNACION";

interface IngresoResumen {
  id: number;
  codigo: string;
  tipo_ingreso: string;
  estado: string;
  proveedor_nombre: string;
  tracking_guia: string;
  costo_flete_usd: number;
  total_compra_usd: number;
  equipos_cantidad: number;
  productos_cantidad: number;
  registrado_por: string;
  nota: string;
  creado_en: string | null;
}

interface FilaItemIngreso {
  sku: string;
  serial: string;
  cantidad: string;
  costo_unitario_usd: string;
  precio_venta_usd: string;
  estado_inicial: string;
  nota: string;
}

const ETIQUETAS_TAB: Record<
  TipoIngresoTab,
  { titulo: string; subtitulo: string; badge: string; labelProveedor: string }
> = {
  COMPRA_NACIONAL: {
    titulo: "Compras Nacionales",
    subtitulo: "Ingresos locales de equipos y productos con correlativo CN-XXXX.",
    badge: "Nacional",
    labelProveedor: "Proveedor Nacional *",
  },
  COMPRA_INTERNACIONAL: {
    titulo: "Compras Internacionales",
    subtitulo:
      "Importaciones con flete, aduana y prorrateo automático al costo unitario (CI-XXXX).",
    badge: "Importación",
    labelProveedor: "Proveedor Internacional *",
  },
  CONSIGNACION: {
    titulo: "Recepción de Consignación",
    subtitulo:
      "Equipos recibidos en consignación con costo acordado y etiqueta automática (CON-XXXX).",
    badge: "Consignación",
    labelProveedor: "Nombre del Consignante *",
  },
};

export default function PaginaComprasIngresos() {
  const [tab, setTab] = useState<TipoIngresoTab>("COMPRA_NACIONAL");
  const [ingresos, setIngresos] = useState<IngresoResumen[]>([]);
  const [sucursales, setSucursales] = useState<Sucursal[]>([]);
  const [catalogo, setCatalogo] = useState<ArticuloCatalogo[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);

  // Modal carga masiva
  const [modalMasivoAbierto, setModalMasivoAbierto] = useState(false);

  // Formulario nuevo ingreso manual
  const [mostrarForm, setMostrarForm] = useState(false);
  const [proveedorNombre, setProveedorNombre] = useState("");
  const [almacenDestinoId, setAlmacenDestinoId] = useState("");
  const [referenciaFactura, setReferenciaFactura] = useState("");
  const [observaciones, setObservaciones] = useState("");
  const [costoFleteUsd, setCostoFleteUsd] = useState("0");
  const [costoAduanaUsd, setCostoAduanaUsd] = useState("0");
  const [trackingGuia, setTrackingGuia] = useState("");
  const [items, setItems] = useState<FilaItemIngreso[]>([
    {
      sku: "",
      serial: "",
      cantidad: "1",
      costo_unitario_usd: "",
      precio_venta_usd: "",
      estado_inicial: "PENDIENTE_REVISION",
      nota: "",
    },
  ]);
  const [guardando, setGuardando] = useState(false);

  const cargarDatos = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const [respIng, respSuc, respCat] = await Promise.all([
        solicitarApi<IngresoResumen[]>(`/api/logistica/ingresos?tipo_ingreso=${tab}`),
        solicitarApi<Sucursal[]>("/api/sucursales"),
        solicitarApi<CatalogoPaginado>("/api/catalogo?por_pagina=200"),
      ]);
      setIngresos(respIng);
      setSucursales(respSuc);
      setCatalogo(respCat.elementos);
      if (!almacenDestinoId && respSuc.length > 0) {
        setAlmacenDestinoId(String(respSuc[0].id));
      }
    } catch (err) {
      setError(
        err instanceof ErrorApi ? err.message : "No se pudieron cargar los ingresos."
      );
    } finally {
      setCargando(false);
    }
  }, [tab, almacenDestinoId]);

  useEffect(() => {
    void cargarDatos();
  }, [cargarDatos]);

  const mapaCatalogo = useMemo(() => {
    const m = new Map<string, ArticuloCatalogo>();
    catalogo.forEach((a) => m.set(a.sku.toUpperCase(), a));
    return m;
  }, [catalogo]);

  // Cálculo en vivo del prorrateo internacional
  const calculoProrrateo = useMemo(() => {
    const totalUnidades = items.reduce((acc, it) => {
      const cant = it.serial.trim() ? 1 : Math.max(0, parseInt(it.cantidad || "0", 10) || 0);
      return acc + cant;
    }, 0);
    const subtotalMercancia = items.reduce((acc, it) => {
      const cant = it.serial.trim() ? 1 : Math.max(0, parseInt(it.cantidad || "0", 10) || 0);
      const costo = parseFloat(it.costo_unitario_usd || "0") || 0;
      return acc + cant * costo;
    }, 0);
    const gastosImportacion =
      tab === "COMPRA_INTERNACIONAL"
        ? (parseFloat(costoFleteUsd || "0") || 0) +
          (parseFloat(costoAduanaUsd || "0") || 0)
        : 0;
    const prorrateoUnitario =
      totalUnidades > 0 ? gastosImportacion / totalUnidades : 0;
    return {
      totalUnidades,
      subtotalMercancia,
      gastosImportacion,
      prorrateoUnitario,
      totalGeneral: subtotalMercancia + gastosImportacion,
    };
  }, [items, tab, costoFleteUsd, costoAduanaUsd]);

  const agregarFila = () => {
    setItems((prev) => [
      ...prev,
      {
        sku: "",
        serial: "",
        cantidad: "1",
        costo_unitario_usd: "",
        precio_venta_usd: "",
        estado_inicial: "PENDIENTE_REVISION",
        nota: "",
      },
    ]);
  };

  const eliminarFila = (idx: number) => {
    setItems((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== idx) : prev));
  };

  const actualizarFila = (idx: number, campo: keyof FilaItemIngreso, valor: string) => {
    setItems((prev) =>
      prev.map((fila, i) => {
        if (i !== idx) return fila;
        const nueva = { ...fila, [campo]: valor };
        if (campo === "sku") {
          const art = mapaCatalogo.get(valor.trim().toUpperCase());
          if (art && !nueva.precio_venta_usd && art.precio_promo_usd) {
            nueva.precio_venta_usd = String(art.precio_promo_usd);
          }
        }
        return nueva;
      })
    );
  };

  const manejarGuardarIngreso = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setExito(null);

    if (!proveedorNombre.trim() || !almacenDestinoId) {
      setError("Completa el proveedor/consignante y el almacén de destino.");
      return;
    }

    const itemsLimpios = items
      .filter((it) => it.sku.trim())
      .map((it) => ({
        sku: it.sku.trim().toUpperCase(),
        serial: it.serial.trim() || null,
        cantidad: it.serial.trim() ? 1 : Math.max(1, parseInt(it.cantidad || "1", 10) || 1),
        costo_unitario_usd: parseFloat(it.costo_unitario_usd || "0") || 0,
        precio_venta_usd: it.precio_venta_usd.trim()
          ? parseFloat(it.precio_venta_usd)
          : null,
        estado_inicial: it.estado_inicial || "PENDIENTE_REVISION",
        nota: it.nota.trim(),
      }));

    if (itemsLimpios.length === 0) {
      setError("Agrega al menos un artículo con SKU.");
      return;
    }

    setGuardando(true);
    try {
      const resp = await solicitarApi<{ codigo: string; total_unidades: number }>(
        "/api/logistica/ingresos",
        {
          method: "POST",
          body: JSON.stringify({
            tipo_ingreso: tab,
            proveedor_nombre: proveedorNombre.trim(),
            almacen_destino_id: Number(almacenDestinoId),
            referencia_factura: referenciaFactura.trim(),
            observaciones: observaciones.trim(),
            costo_flete_usd:
              tab === "COMPRA_INTERNACIONAL" ? parseFloat(costoFleteUsd || "0") || 0 : 0,
            costo_aduana_otros_usd:
              tab === "COMPRA_INTERNACIONAL" ? parseFloat(costoAduanaUsd || "0") || 0 : 0,
            tracking_guia: tab === "COMPRA_INTERNACIONAL" ? trackingGuia.trim() : "",
            items: itemsLimpios,
          }),
        }
      );
      setExito(
        `Ingreso ${resp.codigo} registrado correctamente (${resp.total_unidades} unidades).`
      );
      setProveedorNombre("");
      setReferenciaFactura("");
      setObservaciones("");
      setCostoFleteUsd("0");
      setCostoAduanaUsd("0");
      setTrackingGuia("");
      setItems([
        {
          sku: "",
          serial: "",
          cantidad: "1",
          costo_unitario_usd: "",
          precio_venta_usd: "",
          estado_inicial: "PENDIENTE_REVISION",
          nota: "",
        },
      ]);
      setMostrarForm(false);
      void cargarDatos();
    } catch (err) {
      setError(
        err instanceof ErrorApi ? err.message : "No se pudo registrar el ingreso."
      );
    } finally {
      setGuardando(false);
    }
  };

  const infoTab = ETIQUETAS_TAB[tab];

  return (
    <div className="space-y-6">
      {/* Encabezado */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#001D3D]">
            Ingresos de Inventario
          </h1>
          <p className="text-sm text-slate-600">{infoTab.subtitulo}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void descargarPlantillaLogistica(tab as TipoCargaMasiva)}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
          >
            <Download className="h-4 w-4 text-[#003566]" />
            Descargar Plantilla (.xlsx)
          </button>
          <button
            type="button"
            onClick={() => setModalMasivoAbierto(true)}
            className="inline-flex items-center gap-2 rounded-xl border border-[#003566]/30 bg-sky-50 px-3.5 py-2 text-xs font-semibold text-[#003566] hover:bg-sky-100"
          >
            <FileSpreadsheet className="h-4 w-4" />
            Carga Masiva
          </button>
          <button
            type="button"
            onClick={() => setMostrarForm((v) => !v)}
            className="inline-flex items-center gap-2 rounded-xl bg-[#003566] px-4 py-2 text-xs font-semibold text-white hover:bg-[#001D3D]"
          >
            <Plus className="h-4 w-4" />
            {mostrarForm ? "Ocultar Formulario" : `Nuevo ${infoTab.badge}`}
          </button>
        </div>
      </div>

      {/* Pestañas de flujo */}
      <div className="flex flex-wrap gap-2 border-b border-slate-200 pb-3">
        {(
          [
            {
              id: "COMPRA_NACIONAL",
              label: "Compras Nacionales",
              icono: <ShoppingBag className="h-4 w-4" />,
            },
            {
              id: "COMPRA_INTERNACIONAL",
              label: "Compras Internacionales",
              icono: <Globe2 className="h-4 w-4" />,
            },
            {
              id: "CONSIGNACION",
              label: "Consignación",
              icono: <Handshake className="h-4 w-4" />,
            },
          ] as const
        ).map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => {
              setTab(t.id);
              setError(null);
              setExito(null);
            }}
            className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-semibold transition ${
              tab === t.id
                ? "bg-[#003566] text-white shadow-xs"
                : "bg-white text-slate-700 border border-slate-200 hover:bg-slate-50"
            }`}
          >
            {t.icono}
            {t.label}
          </button>
        ))}
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

      {/* Formulario de Ingreso Manual */}
      {mostrarForm && (
        <form
          onSubmit={manejarGuardarIngreso}
          className="space-y-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs"
        >
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <h2 className="text-base font-bold text-[#001D3D]">
              Registrar {infoTab.titulo}
            </h2>
            {tab === "CONSIGNACION" && (
              <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-amber-800">
                Marcado automático como Consignación
              </span>
            )}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-700">
                {infoTab.labelProveedor}
              </label>
              <input
                type="text"
                required
                value={proveedorNombre}
                onChange={(e) => setProveedorNombre(e.target.value)}
                placeholder="Nombre del proveedor o consignante"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-700">
                Almacén de Destino *
              </label>
              <select
                required
                value={almacenDestinoId}
                onChange={(e) => setAlmacenDestinoId(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              >
                {sucursales.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.nombre}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-700">
                Referencia / Factura
              </label>
              <input
                type="text"
                value={referenciaFactura}
                onChange={(e) => setReferenciaFactura(e.target.value)}
                placeholder="Ej. FAC-00124"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
          </div>

          {tab === "COMPRA_INTERNACIONAL" && (
            <div className="grid grid-cols-1 gap-4 rounded-xl border border-sky-200 bg-sky-50/60 p-4 sm:grid-cols-3">
              <div>
                <label className="mb-1 block text-xs font-semibold text-[#001D3D]">
                  Costo Flete Internacional (USD)
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={costoFleteUsd}
                  onChange={(e) => setCostoFleteUsd(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-[#001D3D]">
                  Aduana / Otros Gastos (USD)
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={costoAduanaUsd}
                  onChange={(e) => setCostoAduanaUsd(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-[#001D3D]">
                  Tracking / Guía Casillero
                </label>
                <input
                  type="text"
                  value={trackingGuia}
                  onChange={(e) => setTrackingGuia(e.target.value)}
                  placeholder="Ej. 1Z999AA101234"
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                />
              </div>
              <div className="sm:col-span-3 flex flex-wrap items-center justify-between gap-2 border-t border-sky-200 pt-2 text-xs text-[#001D3D]">
                <span>
                  Gastos a prorratear:{" "}
                  <strong>{formatearUsd(calculoProrrateo.gastosImportacion)}</strong>{" "}
                  entre <strong>{calculoProrrateo.totalUnidades}</strong> unidad(es)
                </span>
                <span className="rounded-lg bg-[#003566] px-3 py-1 font-bold text-white">
                  Prorrateo automático: +{formatearUsd(calculoProrrateo.prorrateoUnitario)} / unidad
                </span>
              </div>
            </div>
          )}

          {/* Líneas de ítems */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                Equipos y Productos a Ingresar
              </h3>
              <button
                type="button"
                onClick={agregarFila}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                <Plus className="h-3.5 w-3.5" />
                Agregar Línea
              </button>
            </div>

            <datalist id="catalogo-skus-ingreso">
              {catalogo.map((a) => (
                <option key={a.id} value={a.sku}>
                  {a.descripcion} ({a.tipo})
                </option>
              ))}
            </datalist>

            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-xs">
                <thead className="bg-slate-50 text-left text-slate-600">
                  <tr>
                    <th className="px-3 py-2">SKU *</th>
                    <th className="px-3 py-2">Serial (equipos)</th>
                    <th className="px-3 py-2 w-20">Cant.</th>
                    <th className="px-3 py-2 w-28">
                      {tab === "CONSIGNACION" ? "Costo Acordado $" : "Costo Unit. $"}
                    </th>
                    {tab === "COMPRA_INTERNACIONAL" && (
                      <th className="px-3 py-2 w-28">Costo Final $</th>
                    )}
                    <th className="px-3 py-2 w-28">Precio Promo $</th>
                    <th className="px-3 py-2 w-40">Estado Inicial</th>
                    <th className="px-2 py-2"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {items.map((it, idx) => {
                    const costoFinal =
                      (parseFloat(it.costo_unitario_usd || "0") || 0) +
                      calculoProrrateo.prorrateoUnitario;
                    return (
                      <tr key={idx}>
                        <td className="p-2">
                          <input
                            list="catalogo-skus-ingreso"
                            value={it.sku}
                            onChange={(e) => actualizarFila(idx, "sku", e.target.value)}
                            placeholder="SKU..."
                            className="w-full min-w-[140px] rounded-md border border-slate-300 px-2 py-1.5 text-xs"
                          />
                        </td>
                        <td className="p-2">
                          <input
                            value={it.serial}
                            onChange={(e) => actualizarFila(idx, "serial", e.target.value)}
                            placeholder="Vacío si es por cantidad"
                            className="w-full min-w-[140px] rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs"
                          />
                        </td>
                        <td className="p-2">
                          <input
                            type="number"
                            min="1"
                            disabled={Boolean(it.serial.trim())}
                            value={it.serial.trim() ? "1" : it.cantidad}
                            onChange={(e) => actualizarFila(idx, "cantidad", e.target.value)}
                            className="w-16 rounded-md border border-slate-300 px-2 py-1.5 text-xs disabled:bg-slate-100"
                          />
                        </td>
                        <td className="p-2">
                          <input
                            type="number"
                            step="0.01"
                            min="0"
                            value={it.costo_unitario_usd}
                            onChange={(e) =>
                              actualizarFila(idx, "costo_unitario_usd", e.target.value)
                            }
                            placeholder="0.00"
                            className="w-24 rounded-md border border-slate-300 px-2 py-1.5 text-xs"
                          />
                        </td>
                        {tab === "COMPRA_INTERNACIONAL" && (
                          <td className="p-2 font-semibold text-[#003566]">
                            {formatearUsd(costoFinal)}
                          </td>
                        )}
                        <td className="p-2">
                          <input
                            type="number"
                            step="0.01"
                            min="0"
                            value={it.precio_venta_usd}
                            onChange={(e) =>
                              actualizarFila(idx, "precio_venta_usd", e.target.value)
                            }
                            placeholder="Catálogo"
                            className="w-24 rounded-md border border-slate-300 px-2 py-1.5 text-xs"
                          />
                        </td>
                        <td className="p-2">
                          <select
                            value={it.estado_inicial}
                            onChange={(e) =>
                              actualizarFila(idx, "estado_inicial", e.target.value)
                            }
                            className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
                          >
                            <option value="PENDIENTE_REVISION">Pendiente Revisión</option>
                            <option value="EN_PREPARACION">En Preparación</option>
                            <option value="DISPONIBLE">Disponible (POS)</option>
                          </select>
                        </td>
                        <td className="p-2 text-center">
                          <button
                            type="button"
                            onClick={() => eliminarFila(idx)}
                            className="rounded-md p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-4 border-t border-slate-100 pt-4">
            <div className="text-sm text-slate-700">
              Total del Ingreso:{" "}
              <strong className="text-lg text-[#001D3D]">
                {formatearUsd(calculoProrrateo.totalGeneral)}
              </strong>{" "}
              <span className="text-xs text-slate-500">
                ({calculoProrrateo.totalUnidades} unidades)
              </span>
            </div>
            <button
              type="submit"
              disabled={guardando}
              className="inline-flex items-center gap-2 rounded-xl bg-[#003566] px-6 py-2.5 text-sm font-semibold text-white hover:bg-[#001D3D] disabled:opacity-50"
            >
              {guardando ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              Confirmar Ingreso
            </button>
          </div>
        </form>
      )}

      {/* Historial de ingresos del tab activo */}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xs">
        <div className="border-b border-slate-200 bg-slate-50/80 px-5 py-3.5">
          <h2 className="text-sm font-bold text-[#001D3D]">
            Historial de {infoTab.titulo}
          </h2>
        </div>
        {cargando ? (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Cargando registros...
          </div>
        ) : ingresos.length === 0 ? (
          <div className="py-12 text-center text-sm text-slate-500">
            No hay registros de {infoTab.titulo.toLowerCase()} todavía.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3">Código</th>
                  <th className="px-4 py-3">Proveedor / Consignante</th>
                  {tab === "COMPRA_INTERNACIONAL" && (
                    <th className="px-4 py-3">Tracking / Flete</th>
                  )}
                  <th className="px-4 py-3 text-center">Equipos / Prod.</th>
                  <th className="px-4 py-3 text-right">Total USD</th>
                  <th className="px-4 py-3">Registrado por</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {ingresos.map((ing) => (
                  <tr key={ing.id} className="hover:bg-slate-50/70">
                    <td className="px-4 py-3 font-mono text-xs font-bold text-[#003566]">
                      {ing.codigo}
                      {ing.tipo_ingreso === "CONSIGNACION" && (
                        <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800">
                          Consignación
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-800">
                      <div className="font-medium">{ing.proveedor_nombre || "—"}</div>
                      {ing.nota && (
                        <div className="text-xs text-slate-500">{ing.nota}</div>
                      )}
                    </td>
                    {tab === "COMPRA_INTERNACIONAL" && (
                      <td className="px-4 py-3 text-xs text-slate-600">
                        <div>{ing.tracking_guia || "Sin tracking"}</div>
                        <div className="text-slate-500">
                          Flete/Aduana: {formatearUsd(ing.costo_flete_usd)}
                        </div>
                      </td>
                    )}
                    <td className="px-4 py-3 text-center text-xs text-slate-700">
                      <span className="font-semibold">{ing.equipos_cantidad}</span> eq ·{" "}
                      <span className="font-semibold">{ing.productos_cantidad}</span> prod
                    </td>
                    <td className="px-4 py-3 text-right font-bold text-[#001D3D]">
                      {formatearUsd(ing.total_compra_usd)}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-600">
                      {ing.registrado_por || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal de Carga Masiva */}
      <ModalCargaMasiva
        abierto={modalMasivoAbierto}
        alCerrar={() => setModalMasivoAbierto(false)}
        tipo={tab as TipoCargaMasiva}
        titulo={`Carga Masiva — ${infoTab.titulo}`}
        sucursales={sucursales}
        alCompletar={() => {
          void cargarDatos();
        }}
      />
    </div>
  );
}
