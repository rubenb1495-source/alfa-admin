"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Boxes,
  Building2,
  Check,
  CheckCircle2,
  ClipboardCheck,
  Copy,
  CreditCard,
  Eye,
  Globe,
  History,
  Loader2,
  MessageCircle,
  PackageCheck,
  Save,
  ShieldCheck,
  Store,
  Users,
  X,
} from "lucide-react";
import DashboardCierreDiario from "@/components/DashboardCierreDiario";
import { usarSesion } from "@/contexto/SesionContexto";
import {
  construirUrlWhatsApp,
  copiarTextoPortapapeles,
  formatearWhatsAppCierreDiario,
} from "@/lib/whatsapp";
import {
  ErrorApi,
  fechaHoyCaracas,
  formatearBs,
  formatearUsd,
  solicitarApi,
} from "@/servicios/api";
import type { Sucursal } from "@/tipos/dominio";
import type {
  CierreDiarioHistorialItem,
  CierreDiarioSnapshot,
} from "@/tipos/finanzas";

export default function PaginaCierreDiario() {
  const { usuario } = usarSesion();
  const rolUsuario = usuario?.rol || "";
  const esEjecutivo = ["DIRECCION", "ADMINISTRACION", "DIRECTOR"].includes(rolUsuario);
  const esSoloLectura = rolUsuario === "DIRECTOR";

  const usuarioSucursalId = usuario?.sucursal?.id ?? null;

  const [pestana, setPestana] = useState<"hoy" | "historial">("hoy");
  const [fecha, setFecha] = useState(fechaHoyCaracas());
  const [alcance, setAlcance] = useState<"TIENDA" | "GENERAL">(
    esEjecutivo ? "GENERAL" : "TIENDA"
  );
  const [sucursalId, setSucursalId] = useState(
    !esEjecutivo && usuarioSucursalId ? String(usuarioSucursalId) : ""
  );
  const [sucursales, setSucursales] = useState<Sucursal[]>([]);

  const [cierre, setCierre] = useState<CierreDiarioSnapshot | null>(null);
  const [encargadoId, setEncargadoId] = useState("");
  const [observaciones, setObservaciones] = useState("");

  const [historial, setHistorial] = useState<CierreDiarioHistorialItem[]>([]);
  const [cargandoHistorial, setCargandoHistorial] = useState(false);
  const [histDetalle, setHistDetalle] =
    useState<CierreDiarioHistorialItem | null>(null);

  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [copiadoOk, setCopiadoOk] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);

  useEffect(() => {
    if (!esEjecutivo && usuarioSucursalId) {
      setAlcance("TIENDA");
      setSucursalId(String(usuarioSucursalId));
    }
  }, [esEjecutivo, usuarioSucursalId]);

  useEffect(() => {
    solicitarApi<Sucursal[]>("/api/sucursales")
      .then((res) => setSucursales(res.filter((s) => s.estado === "ACTIVA")))
      .catch(() => {});
  }, []);

  const cargarCierre = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (fecha) params.set("fecha", fecha);
      if (esEjecutivo) {
        params.set("alcance", alcance);
        if (alcance === "TIENDA" && sucursalId) {
          params.set("sucursal_id", sucursalId);
        }
      } else {
        params.set("alcance", "TIENDA");
        if (usuarioSucursalId) {
          params.set("sucursal_id", String(usuarioSucursalId));
        }
      }
      const data = await solicitarApi<CierreDiarioSnapshot>(
        `/api/cierre-diario?${params.toString()}`
      );
      setCierre(data);
      if (data.jornada.encargado_sugerido_id) {
        setEncargadoId(String(data.jornada.encargado_sugerido_id));
      } else {
        setEncargadoId("");
      }
      setObservaciones(data.jornada.observaciones_guardadas || "");
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo cargar el cierre diario."
      );
    } finally {
      setCargando(false);
    }
  }, [fecha, alcance, sucursalId, esEjecutivo, usuarioSucursalId]);

  const cargarHistorial = useCallback(async () => {
    setCargandoHistorial(true);
    try {
      const sid = esEjecutivo
        ? alcance === "TIENDA"
          ? sucursalId
          : ""
        : usuarioSucursalId
        ? String(usuarioSucursalId)
        : "";
      const qs = sid ? `?sucursal_id=${sid}` : "";
      const res = await solicitarApi<CierreDiarioHistorialItem[]>(
        `/api/cierre-diario/historial${qs}`
      );
      setHistorial(res);
    } catch {
      setHistorial([]);
    } finally {
      setCargandoHistorial(false);
    }
  }, [sucursalId, alcance, esEjecutivo, usuarioSucursalId]);

  useEffect(() => {
    void cargarCierre();
  }, [cargarCierre]);

  useEffect(() => {
    if (pestana === "historial") {
      void cargarHistorial();
    }
  }, [pestana, cargarHistorial]);

  const encargadoActualNombre =
    cierre?.jornada.encargados_disponibles.find(
      (e) => String(e.id) === encargadoId
    )?.nombre ||
    cierre?.jornada.encargado_sugerido_nombre ||
    "";

  const construirMensajeWhatsApp = (
    snap: CierreDiarioSnapshot,
    encNombre: string,
    obs?: string
  ) => {
    const base =
      snap.mensaje_whatsapp ||
      formatearWhatsAppCierreDiario(snap, encNombre, obs);
    const obsLimpia = (obs || "").trim();
    if (
      snap.mensaje_whatsapp &&
      obsLimpia &&
      !base.includes(obsLimpia)
    ) {
      return `${base}\n\n📝 *Observaciones:* ${obsLimpia}`;
    }
    return base;
  };

  const manejarGuardarCierre = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    setExito(null);
    if (!encargadoId) {
      setError("Debes seleccionar el Encargado de Tienda de turno.");
      return;
    }
    setGuardando(true);
    try {
      const sucGuardar = esEjecutivo
        ? alcance === "GENERAL"
          ? null
          : sucursalId
          ? Number(sucursalId)
          : null
        : usuarioSucursalId;
      await solicitarApi("/api/cierre-diario/cerrar", {
        method: "POST",
        body: JSON.stringify({
          fecha,
          sucursal_id: sucGuardar,
          encargado_tienda_id: Number(encargadoId),
          observaciones: observaciones.trim(),
        }),
      });
      setExito(
        `Cierre diario del ${fecha} guardado correctamente (Encargado: ${encargadoActualNombre}).`
      );
      await cargarCierre();
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo guardar el cierre diario."
      );
    } finally {
      setGuardando(false);
    }
  };

  const abrirWhatsApp = (
    snap: CierreDiarioSnapshot,
    encNombre: string,
    obs?: string
  ) => {
    const msg = construirMensajeWhatsApp(snap, encNombre, obs);
    window.open(construirUrlWhatsApp(msg), "_blank", "noopener,noreferrer");
  };

  const copiarResumen = async () => {
    if (!cierre) return;
    const msg = construirMensajeWhatsApp(
      cierre,
      encargadoActualNombre,
      observaciones
    );
    const ok = await copiarTextoPortapapeles(msg);
    if (ok) {
      setCopiadoOk(true);
      setTimeout(() => setCopiadoOk(false), 2200);
    }
  };

  const tiendasSelector = sucursales.filter(
    (s) => !s.nombre.toLowerCase().includes("almac")
  );

  return (
    <div className="space-y-6">
      {/* Cabecera */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black text-[#000814] flex items-center gap-2">
            <ClipboardCheck className="w-6 h-6 text-[#003566]" />
            Cierre Diario de Tienda
          </h2>
          <p className="text-sm text-slate-500">
            Consolidado operativo y comercial del día (hora Venezuela) — excluye
            liquidaciones y pagos de comisiones.
          </p>
        </div>

        <div className="inline-flex rounded-xl bg-slate-100 p-1 border border-slate-200">
          <button
            type="button"
            onClick={() => setPestana("hoy")}
            className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold cursor-pointer ${
              pestana === "hoy"
                ? "bg-[#003566] text-white shadow-xs"
                : "text-slate-600 hover:text-[#000814]"
            }`}
          >
            <ClipboardCheck className="w-3.5 h-3.5" />
            Cierre del Día
          </button>
          <button
            type="button"
            onClick={() => setPestana("historial")}
            className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold cursor-pointer ${
              pestana === "historial"
                ? "bg-[#003566] text-white shadow-xs"
                : "text-slate-600 hover:text-[#000814]"
            }`}
          >
            <History className="w-3.5 h-3.5" />
            Historial de Cierres
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2.5 p-4 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {exito && (
        <div className="flex items-center gap-2.5 p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-sm text-emerald-700">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{exito}</span>
        </div>
      )}

      {pestana === "hoy" && (
        <>
          {/* Selector rápido de Vista (ADMIN/DIRECTOR: Tienda 1 | Tienda 2 | Admin General; ENCARGADO: fija su tienda) */}
          <div className="bg-white rounded-2xl border border-slate-200 p-4 space-y-3">
            {esEjecutivo ? (
              <div className="flex flex-wrap items-center gap-2 pb-3 border-b border-slate-100">
                <span className="text-[11px] font-bold uppercase text-slate-500 mr-1">
                  Alcance del Cierre:
                </span>
                {tiendasSelector.map((t, idx) => {
                  const activo =
                    alcance === "TIENDA" && sucursalId === String(t.id);
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => {
                        setAlcance("TIENDA");
                        setSucursalId(String(t.id));
                      }}
                      className={`inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold transition cursor-pointer ${
                        activo
                          ? "bg-[#003566] text-white shadow-xs"
                          : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                      }`}
                    >
                      <Store className="w-3.5 h-3.5" />
                      Tienda {idx + 1} ({t.nombre})
                    </button>
                  );
                })}
                <button
                  type="button"
                  onClick={() => {
                    setAlcance("GENERAL");
                    setSucursalId("");
                  }}
                  className={`inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold transition cursor-pointer ${
                    alcance === "GENERAL"
                      ? "bg-[#001D3D] text-white shadow-xs"
                      : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                  }`}
                >
                  <Building2 className="w-3.5 h-3.5" />
                  Administración General (Completo)
                </button>
              </div>
            ) : (
              <div className="flex items-center justify-between pb-2 border-b border-slate-100">
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#EDF3FA] text-[#003566] text-xs font-bold">
                  <Store className="w-3.5 h-3.5" />
                  Cierre Operativo Exclusivo:{" "}
                  {cierre?.jornada.sucursal_nombre || "Mi Tienda"}
                </span>
                <span className="text-[11px] text-slate-500">
                  Vista restringida a tu tienda asignada
                </span>
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 items-end">
              <div>
                <label className="block text-[11px] font-bold uppercase text-slate-500 mb-1">
                  Fecha de jornada
                </label>
                <input
                  type="date"
                  value={fecha}
                  onChange={(e) => setFecha(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs font-bold bg-white"
                />
              </div>

              <div>
                <label className="block text-[11px] font-bold uppercase text-slate-500 mb-1">
                  Sucursal / Alcance
                </label>
                {esEjecutivo ? (
                  <select
                    value={alcance === "GENERAL" ? "GENERAL" : sucursalId}
                    onChange={(e) => {
                      if (e.target.value === "GENERAL") {
                        setAlcance("GENERAL");
                        setSucursalId("");
                      } else {
                        setAlcance("TIENDA");
                        setSucursalId(e.target.value);
                      }
                    }}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs font-semibold bg-white"
                  >
                    <option value="GENERAL">
                      Administración General (Completo)
                    </option>
                    {sucursales.map((s) => (
                      <option key={s.id} value={String(s.id)}>
                        {s.nombre}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    readOnly
                    value={cierre?.jornada.sucursal_nombre || "Tienda asignada"}
                    className="w-full px-3 py-2 rounded-xl border border-slate-200 bg-slate-50 text-xs font-bold text-slate-700"
                  />
                )}
              </div>

              <div className="sm:col-span-2">
                <label className="block text-[11px] font-bold uppercase text-[#003566] mb-1">
                  Encargado de Tienda de turno *
                </label>
                <select
                  required
                  value={encargadoId}
                  onChange={(e) => setEncargadoId(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-[#003566]/35 text-xs font-bold bg-[#EDF3FA]/40 text-[#000814]"
                >
                  <option value="">Selecciona el encargado...</option>
                  {(cierre?.jornada.encargados_disponibles ?? []).map((e) => (
                    <option key={e.id} value={String(e.id)}>
                      {e.nombre} ({e.rol})
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {cierre && (
              <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-100 text-xs">
                <div className="flex flex-wrap items-center gap-2 cifra-tabular">
                  <span className="px-2.5 py-1 rounded-lg bg-slate-100 font-bold text-[#000814]">
                    BCV: {formatearBs(cierre.jornada.tasa_bcv)}
                  </span>
                  <span className="px-2.5 py-1 rounded-lg bg-slate-100 font-bold text-[#000814]">
                    USDT: {formatearBs(cierre.jornada.tasa_usdt)}
                  </span>
                  <span className="px-2.5 py-1 rounded-lg bg-[#EDF3FA] text-[#003566] font-bold">
                    Recargo: {cierre.jornada.porcentaje_recargo}%
                  </span>
                  {cierre.jornada.ya_cerrado && (
                    <span className="px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-bold">
                      Cierre guardado
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      abrirWhatsApp(cierre, encargadoActualNombre, observaciones)
                    }
                    className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold cursor-pointer"
                  >
                    <MessageCircle className="w-4 h-4" />
                    Enviar Cierre por WhatsApp
                  </button>
                  <button
                    type="button"
                    onClick={() => void copiarResumen()}
                    className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-slate-300 bg-white hover:border-[#003566] text-[#003566] text-xs font-bold cursor-pointer"
                  >
                    {copiadoOk ? (
                      <Check className="w-3.5 h-3.5 text-emerald-600" />
                    ) : (
                      <Copy className="w-3.5 h-3.5" />
                    )}
                    {copiadoOk ? "¡Copiado!" : "Copiar resumen"}
                  </button>
                </div>
              </div>
            )}
          </div>

          {cargando || !cierre ? (
            <div className="grid grid-cols-1 sm:grid-cols-5 gap-4">
              {[1, 2, 3, 4, 5].map((i) => (
                <div
                  key={i}
                  className="h-24 rounded-2xl bg-slate-100 animate-pulse"
                />
              ))}
            </div>
          ) : (
            <>
              {/* Dashboard Visual de Saldos, Gráficos, Movimientos y Vista Previa WhatsApp */}
              <DashboardCierreDiario
                cierre={cierre}
                mensajeWhatsApp={construirMensajeWhatsApp(
                  cierre,
                  encargadoActualNombre,
                  observaciones
                )}
                onAbrirWhatsApp={() =>
                  abrirWhatsApp(cierre, encargadoActualNombre, observaciones)
                }
                onCopiarResumen={() => void copiarResumen()}
                copiadoOk={copiadoOk}
              />

              {/* 5 Tarjetas KPI Operativas */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
                <div className="bg-white p-4 rounded-2xl border border-slate-200 border-t-2 border-t-[#003566]">
                  <p className="text-[11px] font-bold uppercase text-slate-500">
                    Ventas del Día
                  </p>
                  <p className="text-xl font-black text-[#000814] mt-1 cifra-tabular">
                    {formatearUsd(cierre.ventas_dia.total_promo_usd)}
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {cierre.ventas_dia.cantidad_total} venta(s) · P:
                    {cierre.ventas_dia.pasillo_cantidad} / L:
                    {cierre.ventas_dia.lead_cantidad}
                  </p>
                </div>

                <div className="bg-white p-4 rounded-2xl border border-slate-200 border-t-2 border-t-emerald-600">
                  <p className="text-[11px] font-bold uppercase text-slate-500">
                    Recibido Instrumentos
                  </p>
                  <p className="text-xl font-black text-emerald-700 mt-1 cifra-tabular">
                    {formatearUsd(cierre.recibido_por_instrumento.total_usd)}
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {cierre.recibido_por_instrumento.items.length} cuenta(s)
                    activas hoy
                  </p>
                </div>

                <div className="bg-white p-4 rounded-2xl border border-slate-200 border-t-2 border-t-sky-600">
                  <p className="text-[11px] font-bold uppercase text-slate-500">
                    Recepciones Almacén
                  </p>
                  <p className="text-xl font-black text-[#003566] mt-1 cifra-tabular">
                    {cierre.recepciones_almacen.total_unidades} und.
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {cierre.recepciones_almacen.items.length} registro(s) hoy
                  </p>
                </div>

                <div className="bg-white p-4 rounded-2xl border border-slate-200 border-t-2 border-t-[#000814]">
                  <p className="text-[11px] font-bold uppercase text-slate-500">
                    Salidas / Disponible
                  </p>
                  <p className="text-xl font-black text-[#000814] mt-1 cifra-tabular">
                    {cierre.inventario.salidas_hoy.total_unidades} /{" "}
                    {cierre.inventario.disponible_cierre.total_unidades}
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {cierre.inventario.disponible_cierre.total_equipos} eq ·{" "}
                    {cierre.inventario.disponible_cierre.total_componentes} comp
                  </p>
                </div>

                <div className="bg-white p-4 rounded-2xl border border-slate-200 border-t-2 border-t-amber-500">
                  <p className="text-[11px] font-bold uppercase text-slate-500">
                    Garantías y Casos
                  </p>
                  <p className="text-xl font-black text-[#000814] mt-1 cifra-tabular">
                    {cierre.garantias_casos.recibidas_hoy.length} /{" "}
                    {cierre.garantias_casos.resueltas_hoy.length} /{" "}
                    {cierre.garantias_casos.pendientes.total}
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    Recib. / Resuel. / Pend.
                  </p>
                </div>
              </div>

              {/* Bloque 1: Recibido por Instrumento de Pago */}
              <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
                <div className="px-5 py-3.5 border-b border-slate-200 flex items-center justify-between">
                  <h3 className="font-bold text-sm text-[#000814] flex items-center gap-2">
                    <CreditCard className="w-4 h-4 text-[#003566]" />
                    1. Recibido por Instrumento de Pago (sin egresos ni
                    comisiones)
                  </h3>
                  {cierre.ventas_dia.cashea_cantidad > 0 && (
                    <span className="text-xs font-bold text-[#003566] bg-[#EDF3FA] px-2.5 py-0.5 rounded-full">
                      Cashea: {cierre.ventas_dia.cashea_cantidad} · Inicial{" "}
                      {formatearUsd(cierre.ventas_dia.cashea_inicial_usd)} |
                      Financ.{" "}
                      {formatearUsd(cierre.ventas_dia.cashea_financiado_usd)}
                    </span>
                  )}
                </div>
                {cierre.recibido_por_instrumento.items.length === 0 ? (
                  <p className="p-6 text-center text-xs text-slate-500">
                    Sin cobros registrados en esta fecha.
                  </p>
                ) : (
                  <table className="w-full text-sm text-left">
                    <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                      <tr>
                        <th className="px-4 py-2.5">Instrumento / Cuenta</th>
                        <th className="px-4 py-2.5 text-right">Operaciones</th>
                        <th className="px-4 py-2.5 text-right">
                          Monto Moneda Nativa
                        </th>
                        <th className="px-4 py-2.5 text-right">Equiv. USD</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {cierre.recibido_por_instrumento.items.map((i) => (
                        <tr key={i.instrumento_id}>
                          <td className="px-4 py-2.5 font-bold text-[#000814]">
                            {i.instrumento}
                          </td>
                          <td className="px-4 py-2.5 text-right text-slate-600">
                            {i.cantidad_pagos}
                          </td>
                          <td className="px-4 py-2.5 text-right font-semibold">
                            {i.moneda === "BS"
                              ? formatearBs(i.total_moneda_origen)
                              : `${formatearUsd(i.total_moneda_origen)} ${i.moneda}`}
                          </td>
                          <td className="px-4 py-2.5 text-right font-black text-emerald-700">
                            {formatearUsd(i.total_usd)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              {/* Bloque 2: Inventario del Día (Recepciones, Salidas, Disponible) */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="bg-white rounded-2xl border border-slate-200 p-4 space-y-2.5">
                  <h3 className="font-bold text-xs uppercase tracking-wide text-[#003566] flex items-center gap-1.5">
                    <PackageCheck className="w-4 h-4" />
                    Recepciones de Almacén (
                    {cierre.recepciones_almacen.total_unidades})
                  </h3>
                  {cierre.recepciones_almacen.items.length === 0 ? (
                    <p className="text-xs text-slate-500">
                      Sin recepciones hoy.
                    </p>
                  ) : (
                    <ul className="space-y-1.5 max-h-56 overflow-y-auto text-xs">
                      {cierre.recepciones_almacen.items.map((item, idx) => (
                        <li
                          key={idx}
                          className="p-2 rounded-lg bg-slate-50 border border-slate-100"
                        >
                          <p className="font-bold text-[#000814]">
                            {item.cantidad}x {item.descripcion}
                          </p>
                          <p className="text-[11px] text-slate-500">
                            {item.serial ? `Serial: ${item.serial} · ` : ""}
                            {item.origen} ({item.documento})
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="bg-white rounded-2xl border border-slate-200 p-4 space-y-2.5">
                  <h3 className="font-bold text-xs uppercase tracking-wide text-amber-700 flex items-center gap-1.5">
                    <Boxes className="w-4 h-4" />
                    Salieron Hoy ({cierre.inventario.salidas_hoy.total_unidades}
                    )
                  </h3>
                  {cierre.inventario.salidas_hoy.items.length === 0 ? (
                    <p className="text-xs text-slate-500">Sin salidas hoy.</p>
                  ) : (
                    <ul className="space-y-1.5 max-h-56 overflow-y-auto text-xs">
                      {cierre.inventario.salidas_hoy.items.map((s, idx) => (
                        <li
                          key={idx}
                          className="p-2 rounded-lg bg-amber-50/40 border border-amber-100"
                        >
                          <p className="font-bold text-[#000814]">
                            {s.cantidad}x {s.descripcion}
                          </p>
                          <p className="text-[11px] text-slate-500">
                            {s.serial ? `Serial: ${s.serial} · ` : ""}
                            {s.motivo} ({s.documento})
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="bg-white rounded-2xl border border-slate-200 p-4 space-y-2.5">
                  <h3 className="font-bold text-xs uppercase tracking-wide text-emerald-700 flex items-center gap-1.5">
                    <Boxes className="w-4 h-4" />
                    Disponible al Cierre (
                    {cierre.inventario.disponible_cierre.total_unidades})
                  </h3>
                  <div className="space-y-1.5 max-h-56 overflow-y-auto text-xs">
                    {cierre.inventario.disponible_cierre.equipos_por_modelo.map(
                      (m) => (
                        <div
                          key={`${m.modelo}-${m.categoria}`}
                          className="flex items-center justify-between p-2 rounded-lg bg-slate-50"
                        >
                          <span className="font-semibold text-[#000814] truncate pr-2">
                            {m.modelo}
                          </span>
                          <span className="px-2 py-0.5 rounded-md bg-[#EDF3FA] text-[#003566] font-bold shrink-0">
                            {m.cantidad}
                          </span>
                        </div>
                      )
                    )}
                    {cierre.inventario.disponible_cierre.componentes_stock.map(
                      (c) => (
                        <div
                          key={c.sku}
                          className="flex items-center justify-between p-2 rounded-lg bg-emerald-50/50"
                        >
                          <span className="text-slate-700 truncate pr-2">
                            {c.descripcion}
                          </span>
                          <span className="px-2 py-0.5 rounded-md bg-emerald-100 text-emerald-800 font-bold shrink-0">
                            {c.cantidad}
                          </span>
                        </div>
                      )
                    )}
                  </div>
                </div>
              </div>

              {/* Bloque 3: Garantías y Casos */}
              <div className="bg-white rounded-2xl border border-slate-200 p-5 space-y-3">
                <h3 className="font-bold text-sm text-[#000814] flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-[#003566]" />
                  3. Garantías y Casos Postventa
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                  <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 space-y-1.5">
                    <p className="font-bold text-[#003566]">
                      Recibidas hoy ({cierre.garantias_casos.recibidas_hoy.length})
                    </p>
                    {cierre.garantias_casos.recibidas_hoy.length === 0 ? (
                      <p className="text-slate-400">Ninguna hoy.</p>
                    ) : (
                      cierre.garantias_casos.recibidas_hoy.map((c) => (
                        <div key={c.numero_caso} className="border-t pt-1">
                          <p className="font-bold">
                            {c.numero_caso} · {c.equipo}
                          </p>
                          <p className="text-slate-500">
                            {c.cliente} — {c.motivo}
                          </p>
                        </div>
                      ))
                    )}
                  </div>

                  <div className="p-3 rounded-xl bg-emerald-50/50 border border-emerald-200 space-y-1.5">
                    <p className="font-bold text-emerald-800">
                      Resueltas hoy ({cierre.garantias_casos.resueltas_hoy.length})
                    </p>
                    {cierre.garantias_casos.resueltas_hoy.length === 0 ? (
                      <p className="text-slate-400">Ninguna hoy.</p>
                    ) : (
                      cierre.garantias_casos.resueltas_hoy.map((r, i) => (
                        <div key={i} className="border-t border-emerald-100 pt-1">
                          <p className="font-bold">
                            {r.numero} · {r.equipo}
                          </p>
                          <p className="text-slate-600">
                            {r.cliente} — {r.resolucion}
                          </p>
                        </div>
                      ))
                    )}
                  </div>

                  <div className="p-3 rounded-xl bg-amber-50/50 border border-amber-200 space-y-1.5">
                    <p className="font-bold text-amber-900">
                      Pendientes abiertas (
                      {cierre.garantias_casos.pendientes.total})
                    </p>
                    {cierre.garantias_casos.pendientes.items.length === 0 ? (
                      <p className="text-slate-400">Sin casos pendientes.</p>
                    ) : (
                      cierre.garantias_casos.pendientes.items
                        .slice(0, 6)
                        .map((p) => (
                          <div
                            key={p.numero_caso}
                            className="border-t border-amber-100 pt-1"
                          >
                            <p className="font-bold">
                              {p.numero_caso} · {p.equipo} ({p.estado})
                            </p>
                            <p className="text-slate-600">{p.cliente}</p>
                          </div>
                        ))
                    )}
                  </div>
                </div>
              </div>

              {/* Bloque 4 (Sección Aparte): Resumen de Ventas por Asesor (SIN comisiones) */}
              <div className="bg-white rounded-2xl border-2 border-[#003566]/20 overflow-hidden">
                <div className="px-5 py-3.5 bg-[#EDF3FA]/60 border-b border-[#003566]/15 flex items-center justify-between">
                  <h3 className="font-black text-sm text-[#003566] flex items-center gap-2">
                    <Users className="w-4 h-4" />
                    Sección Aparte — Resumen de Ventas por Asesor (solo ventas,
                    sin comisiones)
                  </h3>
                  <span className="text-xs font-bold text-[#003566]">
                    {cierre.ventas_por_asesor.length} asesor(es)
                  </span>
                </div>
                {cierre.ventas_por_asesor.length === 0 &&
                cierre.ventas_tienda_sin_asesor.cantidad === 0 ? (
                  <p className="p-6 text-center text-xs text-slate-500">
                    Sin ventas registradas en esta jornada.
                  </p>
                ) : (
                  <table className="w-full text-sm text-left">
                    <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                      <tr>
                        <th className="px-4 py-2.5">Asesor / Encargado</th>
                        <th className="px-4 py-2.5 text-right">Pasillo</th>
                        <th className="px-4 py-2.5 text-right">Lead</th>
                        <th className="px-4 py-2.5 text-right">Total Ventas</th>
                        <th className="px-4 py-2.5 text-right">
                          Monto Vendido USD
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {cierre.ventas_por_asesor.map((a) => (
                        <tr key={a.personal_id}>
                          <td className="px-4 py-2.5 font-bold text-[#000814]">
                            {a.nombre}{" "}
                            {a.modalidad === "ONLINE" && (
                              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md bg-sky-50 text-sky-700 text-[10px] font-semibold">
                                <Globe className="w-2.5 h-2.5" /> Online
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            {a.cantidad_pasillo}
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            {a.cantidad_lead}
                          </td>
                          <td className="px-4 py-2.5 text-right font-bold">
                            {a.total_ventas}
                          </td>
                          <td className="px-4 py-2.5 text-right font-black text-[#003566]">
                            {formatearUsd(a.total_usd)}
                          </td>
                        </tr>
                      ))}
                      {cierre.ventas_tienda_sin_asesor.cantidad > 0 && (
                        <tr className="bg-slate-50/70">
                          <td className="px-4 py-2.5 font-semibold text-slate-600">
                            Tienda (Sin asesor)
                          </td>
                          <td className="px-4 py-2.5 text-right">—</td>
                          <td className="px-4 py-2.5 text-right">—</td>
                          <td className="px-4 py-2.5 text-right font-bold">
                            {cierre.ventas_tienda_sin_asesor.cantidad}
                          </td>
                          <td className="px-4 py-2.5 text-right font-bold text-slate-700">
                            {formatearUsd(
                              cierre.ventas_tienda_sin_asesor.total_usd
                            )}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                )}
              </div>

              {/* Observaciones + Guardar Cierre */}
              <form
                onSubmit={manejarGuardarCierre}
                className="bg-white rounded-2xl border border-slate-200 p-5 space-y-3"
              >
                <label className="block text-xs font-bold uppercase text-slate-600">
                  Observaciones / Novedades del Arqueo del Día
                </label>
                <textarea
                  rows={3}
                  value={observaciones}
                  onChange={(e) => setObservaciones(e.target.value)}
                  placeholder="Ej. Caja cuadrada sin diferencias. Quedó pendiente envío MRW para mañana."
                  className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 text-sm"
                />
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      abrirWhatsApp(cierre, encargadoActualNombre, observaciones)
                    }
                    className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold cursor-pointer"
                  >
                    <MessageCircle className="w-4 h-4" />
                    Enviar Cierre por WhatsApp
                  </button>
                  {!esSoloLectura && (
                    <button
                      type="submit"
                      disabled={guardando || !encargadoId}
                      className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#003566] hover:bg-[#001D3D] disabled:opacity-60 text-white text-xs font-bold cursor-pointer"
                    >
                      {guardando ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Save className="w-4 h-4" />
                      )}
                      Guardar Cierre del Día
                    </button>
                  )}
                </div>
              </form>
            </>
          )}
        </>
      )}

      {/* PESTAÑA HISTORIAL DE CIERRES */}
      {pestana === "historial" && (
        <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
          <div className="px-5 py-3.5 border-b border-slate-200 flex items-center justify-between">
            <span className="font-bold text-sm text-[#000814]">
              Historial de Cierres Diarios Guardados
            </span>
            <span className="text-xs text-slate-500">
              {historial.length} cierre(s)
            </span>
          </div>

          {cargandoHistorial ? (
            <div className="p-6 h-24 bg-slate-100 animate-pulse" />
          ) : historial.length === 0 ? (
            <p className="p-10 text-center text-sm text-slate-500">
              Todavía no hay cierres diarios guardados.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Fecha / Sede</th>
                    <th className="px-4 py-3">Encargado de Tienda</th>
                    <th className="px-4 py-3">Tasas</th>
                    <th className="px-4 py-3 text-right">Ventas USD</th>
                    <th className="px-4 py-3 text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {historial.map((h) => (
                    <tr key={h.id} className="hover:bg-[#EDF3FA]/40">
                      <td className="px-4 py-3 text-xs">
                        <p className="font-bold text-[#000814]">{h.fecha}</p>
                        <p className="text-slate-500">{h.sucursal_nombre}</p>
                      </td>
                      <td className="px-4 py-3 font-semibold text-xs text-[#000814]">
                        {h.encargado_tienda_nombre}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-600 cifra-tabular">
                        BCV {h.tasa_bcv} · Rec. {h.porcentaje_recargo}%
                      </td>
                      <td className="px-4 py-3 text-right font-black text-emerald-700">
                        {formatearUsd(h.resumen?.ventas_dia?.total_promo_usd ?? 0)}
                      </td>
                      <td className="px-4 py-3 text-right space-x-1.5 whitespace-nowrap">
                        <button
                          type="button"
                          onClick={() => setHistDetalle(h)}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-slate-200 bg-white text-[#003566] text-xs font-bold cursor-pointer"
                        >
                          <Eye className="w-3.5 h-3.5" />
                          Ver
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            abrirWhatsApp(
                              h.resumen,
                              h.encargado_tienda_nombre,
                              h.observaciones
                            )
                          }
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-600 text-white text-xs font-bold cursor-pointer"
                        >
                          <MessageCircle className="w-3.5 h-3.5" />
                          WhatsApp
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Modal Ver Snapshot Histórico */}
      {histDetalle && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-xl w-full p-6 shadow-2xl space-y-4 max-h-[88vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-black text-[#000814]">
                Cierre {histDetalle.fecha} — {histDetalle.encargado_tienda_nombre}
              </h3>
              <button
                type="button"
                onClick={() => setHistDetalle(null)}
                className="p-1 text-slate-400 hover:text-[#000814] cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <pre className="whitespace-pre-wrap text-xs bg-slate-50 border border-slate-200 rounded-xl p-4 font-sans text-slate-800">
              {formatearWhatsAppCierreDiario(
                histDetalle.resumen,
                histDetalle.encargado_tienda_nombre,
                histDetalle.observaciones
              )}
            </pre>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() =>
                  abrirWhatsApp(
                    histDetalle.resumen,
                    histDetalle.encargado_tienda_nombre,
                    histDetalle.observaciones
                  )
                }
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-600 text-white text-xs font-bold cursor-pointer"
              >
                <MessageCircle className="w-4 h-4" />
                Reenviar por WhatsApp
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
