"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  BarChart3,
  Building2,
  Calendar,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Globe,
  Lock,
  MessageCircle,
  Phone,
  Search,
} from "lucide-react";
import { usarSesion } from "@/contexto/SesionContexto";
import {
  construirUrlWhatsApp,
  copiarTextoPortapapeles,
  formatearWhatsAppComisionPersona,
} from "@/lib/whatsapp";
import { ErrorApi, formatearUsd, solicitarApi } from "@/servicios/api";
import type {
  ComisionPorPersonaReporte,
  DetalleVentaComision,
  ReporteComisionesAvanzado,
  UsuarioOperativo,
} from "@/tipos/finanzas";

function formatearFechaISO(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function obtenerRangoQuincenaActual(): { inicio: string; fin: string } {
  const hoy = new Date();
  const inicio = new Date(
    hoy.getFullYear(),
    hoy.getMonth(),
    hoy.getDate() <= 15 ? 1 : 16
  );
  return { inicio: formatearFechaISO(inicio), fin: formatearFechaISO(hoy) };
}

export default function PaginaComisionesYCierre() {
  const { usuario, tasaHoy } = usarSesion();
  const esDireccion = usuario?.rol === "DIRECCION";

  const rangoInicial = useMemo(() => obtenerRangoQuincenaActual(), []);
  const [fechaInicio, setFechaInicio] = useState(rangoInicial.inicio);
  const [fechaFin, setFechaFin] = useState(rangoInicial.fin);
  const [atajoActivo, setAtajoActivo] = useState<string>("quincena");
  const [personalId, setPersonalId] = useState<string>("");
  const [busquedaPersonal, setBusquedaPersonal] = useState<string>("");
  const [origenFiltro, setOrigenFiltro] = useState<string>("");

  const [personalLista, setPersonalLista] = useState<UsuarioOperativo[]>([]);
  const [reporte, setReporte] = useState<ReporteComisionesAvanzado | null>(
    null
  );
  const [expandidos, setExpandidos] = useState<Record<number, boolean>>({});
  const [copiadoId, setCopiadoId] = useState<number | null>(null);

  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);
  const [modalCierre, setModalCierre] = useState(false);

  const hoyObj = new Date();
  const [mesCierre, setMesCierre] = useState(hoyObj.getMonth() + 1);
  const [anioCierre, setAnioCierre] = useState(hoyObj.getFullYear());

  useEffect(() => {
    solicitarApi<UsuarioOperativo[]>("/api/usuarios/operativos")
      .then((res) => setPersonalLista(res))
      .catch(() => {});
  }, []);

  const cargarReporte = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (fechaInicio) params.set("fecha_inicio", fechaInicio);
      if (fechaFin) params.set("fecha_fin", fechaFin);
      if (personalId) params.set("personal_id", personalId);
      if (origenFiltro) params.set("origen", origenFiltro);

      const resp = await solicitarApi<ReporteComisionesAvanzado>(
        `/api/comisiones/reporte?${params.toString()}`
      );
      setReporte(resp);
      // Si se filtra por una persona específica, expandir automáticamente su detalle
      if (personalId && resp.por_persona.length === 1) {
        setExpandidos({ [resp.por_persona[0].personal_id]: true });
      }
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo cargar el reporte de comisiones."
      );
    } finally {
      setCargando(false);
    }
  }, [fechaInicio, fechaFin, personalId, origenFiltro]);

  useEffect(() => {
    void cargarReporte();
  }, [cargarReporte]);

  const aplicarAtajo = (tipo: "hoy" | "semana" | "quincena" | "mes") => {
    const hoy = new Date();
    let ini = new Date(hoy);
    if (tipo === "hoy") {
      ini = new Date(hoy);
    } else if (tipo === "semana") {
      const diaSemana = hoy.getDay(); // 0=Dom, 1=Lun
      const diffLunes = diaSemana === 0 ? 6 : diaSemana - 1;
      ini.setDate(hoy.getDate() - diffLunes);
    } else if (tipo === "quincena") {
      ini = new Date(
        hoy.getFullYear(),
        hoy.getMonth(),
        hoy.getDate() <= 15 ? 1 : 16
      );
    } else if (tipo === "mes") {
      ini = new Date(hoy.getFullYear(), hoy.getMonth(), 1);
    }
    setFechaInicio(formatearFechaISO(ini));
    setFechaFin(formatearFechaISO(hoy));
    setAtajoActivo(tipo);
  };

  const personalFiltradoSelector = useMemo(() => {
    const q = busquedaPersonal.trim().toLowerCase();
    if (!q) return personalLista;
    return personalLista.filter((p) =>
      `${p.nombre} ${p.rol} ${p.modalidad || ""} ${p.telefono || ""}`
        .toLowerCase()
        .includes(q)
    );
  }, [personalLista, busquedaPersonal]);

  const detallesPorPersona = useMemo(() => {
    const mapa: Record<number, DetalleVentaComision[]> = {};
    for (const d of reporte?.detalle_ventas ?? []) {
      if (!mapa[d.personal_id]) mapa[d.personal_id] = [];
      mapa[d.personal_id].push(d);
    }
    return mapa;
  }, [reporte]);

  const tasaBcvEfectiva =
    tasaHoy?.tasa_bcv ?? reporte?.tasa_bcv_referencia ?? null;

  const abrirWhatsAppPersona = (persona: ComisionPorPersonaReporte) => {
    const detalles = detallesPorPersona[persona.personal_id] ?? [];
    const mensaje = formatearWhatsAppComisionPersona(
      persona,
      detalles,
      reporte?.fecha_inicio || fechaInicio,
      reporte?.fecha_fin || fechaFin,
      tasaBcvEfectiva
    );
    const url = construirUrlWhatsApp(mensaje, persona.telefono);
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const copiarResumenPersona = async (persona: ComisionPorPersonaReporte) => {
    const detalles = detallesPorPersona[persona.personal_id] ?? [];
    const mensaje = formatearWhatsAppComisionPersona(
      persona,
      detalles,
      reporte?.fecha_inicio || fechaInicio,
      reporte?.fecha_fin || fechaFin,
      tasaBcvEfectiva
    );
    const ok = await copiarTextoPortapapeles(mensaje);
    if (ok) {
      setCopiadoId(persona.personal_id);
      setTimeout(() => setCopiadoId(null), 2200);
    }
  };

  const confirmarCierreMes = async () => {
    setError(null);
    setExito(null);
    try {
      await solicitarApi("/api/finanzas/cierres-mensuales", {
        method: "POST",
        body: JSON.stringify({ anio: anioCierre, mes: mesCierre }),
      });
      setModalCierre(false);
      setExito(
        `Período ${String(mesCierre).padStart(2, "0")}/${anioCierre} cerrado y bloqueado correctamente.`
      );
    } catch (err) {
      setError(
        err instanceof ErrorApi ? err.message : "No se pudo cerrar el mes."
      );
    }
  };

  const personaSeleccionadaUnica =
    personalId && reporte?.por_persona.length === 1
      ? reporte.por_persona[0]
      : null;

  return (
    <div className="space-y-6">
      {/* Cabecera */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black text-[#000814] flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-[#003566]" />
            Reporte de Comisiones y Liquidación
          </h2>
          <p className="text-sm text-slate-500">
            Cálculo SIEMPRE sobre Precio Promo USD (Asesor: 1% Pasillo / 8% Lead
            · Encargado de Tienda: 5% Pasillo / 8% Lead · Tienda: 0%).
          </p>
        </div>

        {esDireccion && (
          <button
            type="button"
            onClick={() => setModalCierre(true)}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[#000814] hover:bg-[#001D3D] text-white text-xs font-bold cursor-pointer"
          >
            <Lock className="w-3.5 h-3.5" />
            Cerrar mes
          </button>
        )}
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

      {/* Barra de filtros avanzados */}
      <div className="bg-white rounded-2xl border border-slate-200 p-4 space-y-3.5">
        {/* Atajos de rango rápido */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-bold text-slate-500 mr-1 inline-flex items-center gap-1">
              <Calendar className="w-3.5 h-3.5 text-[#003566]" />
              Rango rápido:
            </span>
            {(
              [
                ["hoy", "Hoy"],
                ["semana", "Esta semana"],
                ["quincena", "Quincena actual"],
                ["mes", "Mes actual"],
              ] as const
            ).map(([clave, etiqueta]) => (
              <button
                key={clave}
                type="button"
                onClick={() => aplicarAtajo(clave)}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors cursor-pointer ${
                  atajoActivo === clave
                    ? "bg-[#003566] text-white shadow-xs"
                    : "bg-slate-100 text-slate-700 hover:bg-[#EDF3FA] hover:text-[#003566]"
                }`}
              >
                {etiqueta}
              </button>
            ))}
          </div>

          <span className="text-xs text-slate-500 font-medium">
            Período activo: <strong className="text-[#000814]">{fechaInicio}</strong> al{" "}
            <strong className="text-[#000814]">{fechaFin}</strong>
          </span>
        </div>

        {/* Inputs de Fecha, Asesor (con buscador) y Origen */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <div>
            <label className="block text-[11px] font-bold uppercase text-slate-500 mb-1">
              Fecha inicio
            </label>
            <input
              type="date"
              value={fechaInicio}
              onChange={(e) => {
                setFechaInicio(e.target.value);
                setAtajoActivo("personalizado");
              }}
              className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs font-semibold bg-white"
            />
          </div>

          <div>
            <label className="block text-[11px] font-bold uppercase text-slate-500 mb-1">
              Fecha fin
            </label>
            <input
              type="date"
              value={fechaFin}
              onChange={(e) => {
                setFechaFin(e.target.value);
                setAtajoActivo("personalizado");
              }}
              className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs font-semibold bg-white"
            />
          </div>

          <div className="lg:col-span-2 space-y-1">
            <label className="block text-[11px] font-bold uppercase text-slate-500">
              Asesor / Encargado (Presencial y Online)
            </label>
            <div className="flex gap-2">
              <div className="relative w-36 shrink-0 hidden sm:block">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={busquedaPersonal}
                  onChange={(e) => setBusquedaPersonal(e.target.value)}
                  placeholder="Filtrar..."
                  className="w-full pl-8 pr-2 py-2 rounded-xl border border-slate-300 text-xs bg-white"
                />
              </div>
              <select
                value={personalId}
                onChange={(e) => setPersonalId(e.target.value)}
                className="flex-1 min-w-0 px-3 py-2 rounded-xl border border-slate-300 text-xs font-semibold bg-white text-[#000814]"
              >
                <option value="">Todos los asesores y encargados</option>
                {personalFiltradoSelector.map((p) => (
                  <option key={p.id} value={String(p.id)}>
                    {p.nombre}
                    {p.modalidad === "ONLINE" ? " [Online]" : ""} (
                    {p.es_encargado
                      ? "Encargado"
                      : p.rol === "ASESORA"
                      ? "Asesor"
                      : p.rol}
                    )
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-bold uppercase text-slate-500 mb-1">
              Origen de venta
            </label>
            <select
              value={origenFiltro}
              onChange={(e) => setOrigenFiltro(e.target.value)}
              className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs font-semibold bg-white text-[#000814]"
            >
              <option value="">Todos los orígenes</option>
              <option value="PASILLO">Solo Pasillo (Tienda)</option>
              <option value="LEAD">Solo Lead (Redes / WhatsApp)</option>
            </select>
          </div>
        </div>
      </div>

      {/* 5 Tarjetas KPI */}
      {reporte && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          <div className="bg-white p-4 rounded-2xl border border-slate-200 border-t-2 border-t-[#000814]">
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
              Total Ventas
            </p>
            <p className="text-xl font-black text-[#000814] mt-1 cifra-tabular">
              {reporte.resumen_general.total_ventas}
            </p>
          </div>
          <div className="bg-white p-4 rounded-2xl border border-slate-200 border-t-2 border-t-[#003566]">
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
              Base Comisionable (Promo)
            </p>
            <p className="text-xl font-black text-[#000814] mt-1 cifra-tabular">
              {formatearUsd(reporte.resumen_general.volumen_promo_usd)}
            </p>
          </div>
          <div className="bg-white p-4 rounded-2xl border border-slate-200 border-t-2 border-t-slate-500">
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
              Comisiones Pasillo
            </p>
            <p className="text-xl font-black text-slate-800 mt-1 cifra-tabular">
              {formatearUsd(reporte.resumen_general.pasillo_usd)}
            </p>
          </div>
          <div className="bg-white p-4 rounded-2xl border border-slate-200 border-t-2 border-t-sky-600">
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
              Comisiones Lead
            </p>
            <p className="text-xl font-black text-[#003566] mt-1 cifra-tabular">
              {formatearUsd(reporte.resumen_general.lead_usd)}
            </p>
          </div>
          <div className="bg-gradient-to-br from-[#EDF3FA] to-white p-4 rounded-2xl border border-[#003566]/30 shadow-xs">
            <p className="text-[11px] font-bold uppercase tracking-wider text-[#003566]">
              Total a Pagar (USD)
            </p>
            <p className="text-xl font-black text-emerald-700 mt-1 cifra-tabular">
              {formatearUsd(reporte.resumen_general.total_comisiones_usd)}
            </p>
          </div>
        </div>
      )}

      {/* Acción rápida WhatsApp cuando hay un asesor específico seleccionado */}
      {personaSeleccionadaUnica && (
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5 rounded-2xl bg-[#EDF3FA]/80 border border-[#003566]/25">
          <div>
            <p className="text-sm font-black text-[#000814]">
              Liquidación lista para {personaSeleccionadaUnica.nombre}
            </p>
            <p className="text-xs text-slate-600">
              {personaSeleccionadaUnica.total_ventas} venta(s) · Total a pagar:{" "}
              <strong className="text-emerald-700">
                {formatearUsd(personaSeleccionadaUnica.total_comision_usd)}
              </strong>
              {personaSeleccionadaUnica.telefono
                ? ` · Tel: ${personaSeleccionadaUnica.telefono}`
                : " · Sin teléfono registrado (elegir contacto en WhatsApp)"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => abrirWhatsAppPersona(personaSeleccionadaUnica)}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold shadow-xs cursor-pointer"
            >
              <MessageCircle className="w-4 h-4" />
              Enviar por WhatsApp
            </button>
            <button
              type="button"
              onClick={() => void copiarResumenPersona(personaSeleccionadaUnica)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-white border border-slate-300 hover:border-[#003566] text-[#003566] text-xs font-bold cursor-pointer"
            >
              {copiadoId === personaSeleccionadaUnica.personal_id ? (
                <Check className="w-3.5 h-3.5 text-emerald-600" />
              ) : (
                <Copy className="w-3.5 h-3.5" />
              )}
              {copiadoId === personaSeleccionadaUnica.personal_id
                ? "¡Copiado!"
                : "Copiar resumen"}
            </button>
          </div>
        </div>
      )}

      {/* Tabla agrupada por Asesor / Encargado con detalle desplegable */}
      <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-200 flex items-center justify-between gap-3">
          <span className="font-bold text-sm text-[#000814]">
            Desglose por Asesor / Encargado (haz clic en una fila para ver las
            ventas)
          </span>
          <span className="text-xs text-slate-500">
            {reporte?.por_persona.length ?? 0} colaborador(es)
          </span>
        </div>

        {cargando ? (
          <div className="p-6 space-y-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-12 rounded-xl bg-slate-100 animate-pulse"
              />
            ))}
          </div>
        ) : !reporte || reporte.por_persona.length === 0 ? (
          <p className="p-10 text-center text-sm text-slate-500">
            No hay ventas comisionables en el rango y filtros seleccionados.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-slate-50 border-b border-slate-200 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-3 py-3 w-8" />
                  <th className="px-4 py-3">Colaborador</th>
                  <th className="px-4 py-3">Rol / Modalidad</th>
                  <th className="px-4 py-3 text-right">Ventas Pasillo</th>
                  <th className="px-4 py-3 text-right">Ventas Lead</th>
                  <th className="px-4 py-3 text-right">Total a Pagar</th>
                  <th className="px-4 py-3 text-right">WhatsApp / Resumen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {reporte.por_persona.map((p) => {
                  const abierto = Boolean(expandidos[p.personal_id]);
                  const detalles = detallesPorPersona[p.personal_id] ?? [];
                  return (
                    <React.Fragment key={p.personal_id}>
                      <tr
                        onClick={() =>
                          setExpandidos((prev) => ({
                            ...prev,
                            [p.personal_id]: !prev[p.personal_id],
                          }))
                        }
                        className="hover:bg-[#EDF3FA]/50 cursor-pointer"
                      >
                        <td className="px-3 py-3 text-slate-400">
                          {abierto ? (
                            <ChevronDown className="w-4 h-4 text-[#003566]" />
                          ) : (
                            <ChevronRight className="w-4 h-4" />
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <p className="font-bold text-[#000814]">{p.nombre}</p>
                          <p className="text-[11px] text-slate-500 flex items-center gap-1.5">
                            <span>{p.total_ventas} venta(s)</span>
                            {p.telefono && (
                              <span className="inline-flex items-center gap-0.5">
                                · <Phone className="w-2.5 h-2.5" /> {p.telefono}
                              </span>
                            )}
                          </p>
                        </td>
                        <td className="px-4 py-3 text-xs space-y-1">
                          <div>
                            <span
                              className={`inline-block px-2 py-0.5 rounded-md font-bold text-[11px] ${
                                p.es_encargado
                                  ? "bg-[#EDF3FA] text-[#003566]"
                                  : "bg-slate-100 text-slate-700"
                              }`}
                            >
                              {p.es_encargado
                                ? "Encargado (5% / 8%)"
                                : p.rol === "ASESORA"
                                ? "Asesor (1% / 8%)"
                                : p.rol}
                            </span>
                          </div>
                          <span className="inline-flex items-center gap-1 text-[11px] text-slate-500">
                            {p.modalidad === "ONLINE" ? (
                              <>
                                <Globe className="w-3 h-3 text-sky-600" /> Online
                              </>
                            ) : (
                              <>
                                <Building2 className="w-3 h-3 text-slate-400" />{" "}
                                Presencial
                              </>
                            )}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <p className="font-semibold text-slate-800">
                            {p.cantidad_pasillo} ·{" "}
                            {formatearUsd(p.base_pasillo_usd)}
                          </p>
                          <p className="text-[11px] text-[#003566] font-bold">
                            {p.porcentaje_pasillo}% →{" "}
                            {formatearUsd(p.comision_pasillo_usd)}
                          </p>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <p className="font-semibold text-slate-800">
                            {p.cantidad_lead} · {formatearUsd(p.base_lead_usd)}
                          </p>
                          <p className="text-[11px] text-[#003566] font-bold">
                            {p.porcentaje_lead}% →{" "}
                            {formatearUsd(p.comision_lead_usd)}
                          </p>
                        </td>
                        <td className="px-4 py-3 text-right font-black text-emerald-700 text-base">
                          {formatearUsd(p.total_comision_usd)}
                        </td>
                        <td
                          className="px-4 py-3 text-right whitespace-nowrap space-x-1.5"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            type="button"
                            onClick={() => abrirWhatsAppPersona(p)}
                            title={
                              p.telefono
                                ? `Enviar resumen a ${p.telefono}`
                                : "Abrir WhatsApp para elegir contacto"
                            }
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold cursor-pointer"
                          >
                            <MessageCircle className="w-3.5 h-3.5" />
                            WhatsApp
                          </button>
                          <button
                            type="button"
                            onClick={() => void copiarResumenPersona(p)}
                            title="Copiar resumen al portapapeles"
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white hover:border-[#003566] text-[#003566] text-xs font-bold cursor-pointer"
                          >
                            {copiadoId === p.personal_id ? (
                              <Check className="w-3.5 h-3.5 text-emerald-600" />
                            ) : (
                              <Copy className="w-3.5 h-3.5" />
                            )}
                            {copiadoId === p.personal_id ? "Copiado" : "Copiar"}
                          </button>
                        </td>
                      </tr>

                      {/* Detalle desplegable de ventas */}
                      {abierto && (
                        <tr className="bg-slate-50/80">
                          <td colSpan={7} className="px-6 py-4">
                            {detalles.length === 0 ? (
                              <p className="text-xs text-slate-500">
                                Sin notas individuales (ajustes por cambios de
                                garantía/upgrade).
                              </p>
                            ) : (
                              <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
                                <table className="w-full text-xs text-left">
                                  <thead className="bg-[#EDF3FA]/70 text-[11px] uppercase text-[#001D3D]">
                                    <tr>
                                      <th className="px-3 py-2">Fecha</th>
                                      <th className="px-3 py-2">Nota</th>
                                      <th className="px-3 py-2">Cliente</th>
                                      <th className="px-3 py-2">
                                        Equipo / Producto
                                      </th>
                                      <th className="px-3 py-2">Origen</th>
                                      <th className="px-3 py-2 text-right">
                                        Base Promo
                                      </th>
                                      <th className="px-3 py-2 text-right">
                                        %
                                      </th>
                                      <th className="px-3 py-2 text-right">
                                        Comisión
                                      </th>
                                    </tr>
                                  </thead>
                                  <tbody className="divide-y divide-slate-100">
                                    {detalles.map((d) => (
                                      <tr key={`${d.venta_id}-${d.numero_venta}`}>
                                        <td className="px-3 py-2 font-medium text-slate-600 whitespace-nowrap">
                                          {d.fecha}
                                        </td>
                                        <td className="px-3 py-2 font-mono font-bold text-[#000814]">
                                          {d.numero_venta}
                                        </td>
                                        <td className="px-3 py-2 text-slate-700">
                                          {d.cliente}
                                        </td>
                                        <td className="px-3 py-2 text-slate-700 max-w-xs truncate">
                                          {d.producto}
                                        </td>
                                        <td className="px-3 py-2">
                                          <span
                                            className={`px-1.5 py-0.5 rounded-md font-bold text-[10px] ${
                                              d.origen === "LEAD"
                                                ? "bg-[#EDF3FA] text-[#003566]"
                                                : "bg-slate-100 text-slate-600"
                                            }`}
                                          >
                                            {d.origen === "LEAD"
                                              ? "Lead"
                                              : "Pasillo"}
                                          </span>
                                        </td>
                                        <td className="px-3 py-2 text-right font-semibold text-slate-700">
                                          {formatearUsd(d.base_promo_usd)}
                                        </td>
                                        <td className="px-3 py-2 text-right font-bold text-[#003566]">
                                          {d.porcentaje_aplicado}%
                                        </td>
                                        <td className="px-3 py-2 text-right font-black text-emerald-700">
                                          {formatearUsd(d.comision_usd)}
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal de Cierre Mensual (Solo DIRECCION) */}
      {modalCierre && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <h3 className="text-lg font-black text-[#000814]">
              Cerrar período mensual
            </h3>
            <p className="text-xs text-slate-600">
              Al cerrar el mes, se bloquean las ventas, anulaciones y pagos de
              ese período para proteger la contabilidad.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Mes
                </label>
                <input
                  type="number"
                  min={1}
                  max={12}
                  value={mesCierre}
                  onChange={(e) => setMesCierre(Number(e.target.value))}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Año
                </label>
                <input
                  type="number"
                  min={2024}
                  max={2100}
                  value={anioCierre}
                  onChange={(e) => setAnioCierre(Number(e.target.value))}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setModalCierre(false)}
                className="px-4 py-2 rounded-xl border border-slate-300 text-xs font-bold text-slate-700 cursor-pointer"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => void confirmarCierreMes()}
                className="px-4 py-2 rounded-xl bg-[#003566] hover:bg-[#001D3D] text-white text-xs font-bold cursor-pointer"
              >
                Confirmar cierre
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
