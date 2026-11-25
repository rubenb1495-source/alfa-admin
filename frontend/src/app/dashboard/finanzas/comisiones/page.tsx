"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Ban,
  BarChart3,
  Building2,
  Calendar,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Eye,
  FileDown,
  Globe,
  History,
  Lock,
  MessageCircle,
  Phone,
  Search,
  Wallet,
  X,
} from "lucide-react";
import ModalLiquidacionComision from "@/components/ModalLiquidacionComision";
import { usarSesion } from "@/contexto/SesionContexto";
import {
  construirUrlWhatsApp,
  copiarTextoPortapapeles,
  formatearWhatsAppComisionPersona,
  formatearWhatsAppLiquidacion,
} from "@/lib/whatsapp";
import {
  descargarPdfApi,
  ErrorApi,
  formatearBs,
  formatearUsd,
  solicitarApi,
} from "@/servicios/api";
import type {
  ComisionPorPersonaReporte,
  DetalleVentaComision,
  LiquidacionComisionResumen,
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

  const [pestana, setPestana] = useState<"reporte" | "historial">("reporte");

  const rangoInicial = useMemo(() => obtenerRangoQuincenaActual(), []);
  const [fechaInicio, setFechaInicio] = useState(rangoInicial.inicio);
  const [fechaFin, setFechaFin] = useState(rangoInicial.fin);
  const [atajoActivo, setAtajoActivo] = useState<string>("quincena");
  const [personalId, setPersonalId] = useState<string>("");
  const [busquedaPersonal, setBusquedaPersonal] = useState<string>("");
  const [origenFiltro, setOrigenFiltro] = useState<string>("");
  const [estadoComisionFiltro, setEstadoComisionFiltro] = useState<
    "PENDIENTE" | "PAGADA" | "TODOS"
  >("PENDIENTE");

  const [personalLista, setPersonalLista] = useState<UsuarioOperativo[]>([]);
  const [reporte, setReporte] = useState<ReporteComisionesAvanzado | null>(
    null
  );
  const [expandidos, setExpandidos] = useState<Record<number, boolean>>({});
  const [copiadoId, setCopiadoId] = useState<number | null>(null);

  // Modal Liquidar Comisiones
  const [personaALiquidar, setPersonaALiquidar] =
    useState<ComisionPorPersonaReporte | null>(null);

  // Historial de Liquidaciones
  const [liquidaciones, setLiquidaciones] = useState<
    LiquidacionComisionResumen[]
  >([]);
  const [cargandoHistorial, setCargandoHistorial] = useState(false);
  const [busquedaLiq, setBusquedaLiq] = useState("");
  const [liqDetalle, setLiqDetalle] =
    useState<LiquidacionComisionResumen | null>(null);
  const [liqAnular, setLiqAnular] = useState<LiquidacionComisionResumen | null>(
    null
  );
  const [motivoAnulacion, setMotivoAnulacion] = useState("");
  const [anulando, setAnulando] = useState(false);

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
      params.set("estado_comision", estadoComisionFiltro);

      const resp = await solicitarApi<ReporteComisionesAvanzado>(
        `/api/comisiones/reporte?${params.toString()}`
      );
      setReporte(resp);
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
  }, [fechaInicio, fechaFin, personalId, origenFiltro, estadoComisionFiltro]);

  const cargarHistorialLiquidaciones = useCallback(async () => {
    setCargandoHistorial(true);
    try {
      const params = new URLSearchParams();
      if (fechaInicio) params.set("fecha_inicio", fechaInicio);
      if (fechaFin) params.set("fecha_fin", fechaFin);
      if (personalId) params.set("personal_id", personalId);
      const qs = params.toString() ? `?${params.toString()}` : "";
      const res = await solicitarApi<LiquidacionComisionResumen[]>(
        `/api/comisiones/liquidaciones${qs}`
      );
      setLiquidaciones(res);
    } catch {
      setLiquidaciones([]);
    } finally {
      setCargandoHistorial(false);
    }
  }, [fechaInicio, fechaFin, personalId]);

  useEffect(() => {
    void cargarReporte();
  }, [cargarReporte]);

  useEffect(() => {
    if (pestana === "historial") {
      void cargarHistorialLiquidaciones();
    }
  }, [pestana, cargarHistorialLiquidaciones]);

  const aplicarAtajo = (tipo: "hoy" | "semana" | "quincena" | "mes") => {
    const hoy = new Date();
    let ini = new Date(hoy);
    if (tipo === "hoy") {
      ini = new Date(hoy);
    } else if (tipo === "semana") {
      const diaSemana = hoy.getDay();
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

  const liquidacionesFiltradas = useMemo(() => {
    const q = busquedaLiq.trim().toLowerCase();
    if (!q) return liquidaciones;
    return liquidaciones.filter((l) =>
      `${l.codigo} ${l.personal_nombre} ${l.metodo_pago} ${l.referencia}`
        .toLowerCase()
        .includes(q)
    );
  }, [liquidaciones, busquedaLiq]);

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
    window.open(
      construirUrlWhatsApp(mensaje, persona.telefono),
      "_blank",
      "noopener,noreferrer"
    );
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

  const verDetalleLiquidacion = async (liqId: number) => {
    try {
      const det = await solicitarApi<LiquidacionComisionResumen>(
        `/api/comisiones/liquidaciones/${liqId}`
      );
      setLiqDetalle(det);
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo cargar el detalle de la liquidación."
      );
    }
  };

  const manejarAnularLiquidacion = async (
    e: React.FormEvent<HTMLFormElement>
  ) => {
    e.preventDefault();
    if (!liqAnular) return;
    setAnulando(true);
    setError(null);
    setExito(null);
    try {
      await solicitarApi(
        `/api/comisiones/liquidaciones/${liqAnular.id}/anular`,
        {
          method: "POST",
          body: JSON.stringify({ motivo: motivoAnulacion.trim() }),
        }
      );
      setExito(
        `Liquidación ${liqAnular.codigo} anulada. Todas sus ventas volvieron a estado PENDIENTE.`
      );
      setLiqAnular(null);
      setMotivoAnulacion("");
      await Promise.all([cargarHistorialLiquidaciones(), cargarReporte()]);
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo anular la liquidación."
      );
    } finally {
      setAnulando(false);
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

  const ventasPendientesModal = useMemo(() => {
    if (!personaALiquidar) return [];
    return (detallesPorPersona[personaALiquidar.personal_id] ?? []).filter(
      (v) => v.estado_comision === "PENDIENTE"
    );
  }, [personaALiquidar, detallesPorPersona]);

  return (
    <div className="space-y-6">
      {/* Cabecera */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black text-[#000814] flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-[#003566]" />
            Comisiones y Liquidaciones Quincenales
          </h2>
          <p className="text-sm text-slate-500">
            Cálculo SIEMPRE sobre Precio Promo USD (Asesor: 1% Pasillo / 8% Lead
            · Encargado de Tienda: 5% Pasillo / 8% Lead · Tienda: 0%).
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-xl bg-slate-100 p-1 border border-slate-200">
            <button
              type="button"
              onClick={() => setPestana("reporte")}
              className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold transition-colors cursor-pointer ${
                pestana === "reporte"
                  ? "bg-[#003566] text-white shadow-xs"
                  : "text-slate-600 hover:text-[#000814]"
              }`}
            >
              <Wallet className="w-3.5 h-3.5" />
              Reporte de Comisiones
            </button>
            <button
              type="button"
              onClick={() => setPestana("historial")}
              className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold transition-colors cursor-pointer ${
                pestana === "historial"
                  ? "bg-[#003566] text-white shadow-xs"
                  : "text-slate-600 hover:text-[#000814]"
              }`}
            >
              <History className="w-3.5 h-3.5" />
              Historial de Liquidaciones
            </button>
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

      {/* Barra de filtros compartida */}
      <div className="bg-white rounded-2xl border border-slate-200 p-4 space-y-3.5">
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

          {pestana === "reporte" && (
            <div className="inline-flex items-center gap-1 rounded-xl bg-slate-100 p-1 border border-slate-200">
              {(
                [
                  ["PENDIENTE", "Pendientes"],
                  ["PAGADA", "Pagadas"],
                  ["TODOS", "Todas"],
                ] as const
              ).map(([est, lbl]) => (
                <button
                  key={est}
                  type="button"
                  onClick={() => setEstadoComisionFiltro(est)}
                  className={`px-3 py-1 rounded-lg text-xs font-bold transition-colors cursor-pointer ${
                    estadoComisionFiltro === est
                      ? est === "PENDIENTE"
                        ? "bg-amber-500 text-white"
                        : est === "PAGADA"
                        ? "bg-emerald-600 text-white"
                        : "bg-[#003566] text-white"
                      : "text-slate-600 hover:text-[#000814]"
                  }`}
                >
                  {lbl}
                </button>
              ))}
            </div>
          )}
        </div>

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
              <div className="relative w-32 shrink-0 hidden sm:block">
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

          {pestana === "reporte" ? (
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
          ) : (
            <div>
              <label className="block text-[11px] font-bold uppercase text-slate-500 mb-1">
                Buscar liquidación
              </label>
              <input
                type="text"
                value={busquedaLiq}
                onChange={(e) => setBusquedaLiq(e.target.value)}
                placeholder="LIQ-..., asesor o ref..."
                className="w-full px-3 py-2 rounded-xl border border-slate-300 text-xs bg-white"
              />
            </div>
          )}
        </div>
      </div>

      {/* PESTAÑA 1: REPORTE DE COMISIONES */}
      {pestana === "reporte" && (
        <>
          {reporte && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
              <div className="bg-white p-4 rounded-2xl border border-slate-200 border-t-2 border-t-[#000814]">
                <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
                  Ventas ({estadoComisionFiltro})
                </p>
                <p className="text-xl font-black text-[#000814] mt-1 cifra-tabular">
                  {reporte.resumen_general.total_ventas}
                </p>
              </div>
              <div className="bg-white p-4 rounded-2xl border border-slate-200 border-t-2 border-t-[#003566]">
                <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
                  Base Promo USD
                </p>
                <p className="text-xl font-black text-[#000814] mt-1 cifra-tabular">
                  {formatearUsd(reporte.resumen_general.volumen_promo_usd)}
                </p>
              </div>
              <div className="bg-white p-4 rounded-2xl border border-slate-200 border-t-2 border-t-amber-500">
                <p className="text-[11px] font-bold uppercase tracking-wider text-amber-700">
                  Pendiente por Pagar
                </p>
                <p className="text-xl font-black text-amber-700 mt-1 cifra-tabular">
                  {formatearUsd(reporte.resumen_general.pendiente_usd)}
                </p>
              </div>
              <div className="bg-white p-4 rounded-2xl border border-slate-200 border-t-2 border-t-emerald-600">
                <p className="text-[11px] font-bold uppercase tracking-wider text-emerald-700">
                  Ya Pagado
                </p>
                <p className="text-xl font-black text-emerald-700 mt-1 cifra-tabular">
                  {formatearUsd(reporte.resumen_general.pagado_usd)}
                </p>
              </div>
              <div className="bg-gradient-to-br from-[#EDF3FA] to-white p-4 rounded-2xl border border-[#003566]/30 shadow-xs">
                <p className="text-[11px] font-bold uppercase tracking-wider text-[#003566]">
                  Total Período (USD)
                </p>
                <p className="text-xl font-black text-[#000814] mt-1 cifra-tabular">
                  {formatearUsd(reporte.resumen_general.total_comisiones_usd)}
                </p>
              </div>
            </div>
          )}

          <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
            <div className="px-5 py-3.5 border-b border-slate-200 flex items-center justify-between gap-3">
              <span className="font-bold text-sm text-[#000814]">
                Desglose por Asesor / Encargado (clic en una fila para ver las
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
                No hay comisiones{" "}
                {estadoComisionFiltro === "PENDIENTE"
                  ? "pendientes"
                  : estadoComisionFiltro === "PAGADA"
                  ? "pagadas"
                  : ""}{" "}
                en el rango seleccionado.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                  <thead className="bg-slate-50 border-b border-slate-200 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-3 py-3 w-8" />
                      <th className="px-4 py-3">Colaborador</th>
                      <th className="px-4 py-3 text-right">Pasillo / Lead</th>
                      <th className="px-4 py-3 text-right">Pendiente USD</th>
                      <th className="px-4 py-3 text-right">Pagado USD</th>
                      <th className="px-4 py-3 text-right">Acciones</th>
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
                              <div className="flex flex-wrap items-center gap-1.5">
                                <p className="font-bold text-[#000814]">
                                  {p.nombre}
                                </p>
                                <span
                                  className={`px-1.5 py-0.5 rounded-md font-bold text-[10px] ${
                                    p.es_encargado
                                      ? "bg-[#EDF3FA] text-[#003566]"
                                      : "bg-slate-100 text-slate-600"
                                  }`}
                                >
                                  {p.es_encargado
                                    ? "Encargado 5%/8%"
                                    : "Asesor 1%/8%"}
                                </span>
                                {p.modalidad === "ONLINE" && (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md bg-sky-50 text-sky-700 text-[10px] font-semibold">
                                    <Globe className="w-2.5 h-2.5" /> Online
                                  </span>
                                )}
                              </div>
                              <p className="text-[11px] text-slate-500 mt-0.5">
                                {p.total_ventas} venta(s)
                                {p.telefono ? ` · ${p.telefono}` : ""}
                              </p>
                            </td>
                            <td className="px-4 py-3 text-right text-xs">
                              <p className="text-slate-700 font-semibold">
                                P: {p.cantidad_pasillo} (
                                {formatearUsd(p.comision_pasillo_usd)})
                              </p>
                              <p className="text-[#003566] font-semibold">
                                L: {p.cantidad_lead} (
                                {formatearUsd(p.comision_lead_usd)})
                              </p>
                            </td>
                            <td className="px-4 py-3 text-right font-black text-amber-700 cifra-tabular">
                              {formatearUsd(p.pendiente_usd)}
                            </td>
                            <td className="px-4 py-3 text-right font-bold text-emerald-700 cifra-tabular">
                              {formatearUsd(p.pagado_usd)}
                            </td>
                            <td
                              className="px-4 py-3 text-right whitespace-nowrap space-x-1.5"
                              onClick={(e) => e.stopPropagation()}
                            >
                              {p.pendiente_usd > 0 && (
                                <button
                                  type="button"
                                  onClick={() => setPersonaALiquidar(p)}
                                  className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-[#003566] hover:bg-[#001D3D] text-white text-xs font-bold cursor-pointer"
                                >
                                  <Wallet className="w-3.5 h-3.5" />
                                  Liquidar
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => abrirWhatsAppPersona(p)}
                                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold cursor-pointer"
                              >
                                <MessageCircle className="w-3.5 h-3.5" />
                                WhatsApp
                              </button>
                              <button
                                type="button"
                                onClick={() => void copiarResumenPersona(p)}
                                className="inline-flex items-center gap-1 px-2 py-1.5 rounded-lg border border-slate-200 bg-white hover:border-[#003566] text-[#003566] text-xs font-bold cursor-pointer"
                              >
                                {copiadoId === p.personal_id ? (
                                  <Check className="w-3.5 h-3.5 text-emerald-600" />
                                ) : (
                                  <Copy className="w-3.5 h-3.5" />
                                )}
                              </button>
                            </td>
                          </tr>

                          {abierto && (
                            <tr className="bg-slate-50/80">
                              <td colSpan={6} className="px-6 py-4">
                                <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
                                  <table className="w-full text-xs text-left">
                                    <thead className="bg-[#EDF3FA]/70 text-[11px] uppercase text-[#001D3D]">
                                      <tr>
                                        <th className="px-3 py-2">Fecha</th>
                                        <th className="px-3 py-2">Nota</th>
                                        <th className="px-3 py-2">Producto</th>
                                        <th className="px-3 py-2">Origen</th>
                                        <th className="px-3 py-2">Estado</th>
                                        <th className="px-3 py-2 text-right">
                                          Promo USD
                                        </th>
                                        <th className="px-3 py-2 text-right">
                                          Comisión
                                        </th>
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-100">
                                      {detalles.map((d) => (
                                        <tr key={d.venta_id}>
                                          <td className="px-3 py-2 text-slate-600 whitespace-nowrap">
                                            {d.fecha}
                                          </td>
                                          <td className="px-3 py-2 font-mono font-bold text-[#000814]">
                                            {d.numero_venta}
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
                                                ? `Lead ${d.porcentaje_aplicado}%`
                                                : `Pasillo ${d.porcentaje_aplicado}%`}
                                            </span>
                                          </td>
                                          <td className="px-3 py-2">
                                            <span
                                              className={`px-2 py-0.5 rounded-full font-bold text-[10px] ${
                                                d.estado_comision === "PAGADA"
                                                  ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                                  : "bg-amber-50 text-amber-800 border border-amber-200"
                                              }`}
                                            >
                                              {d.estado_comision === "PAGADA"
                                                ? "Pagada"
                                                : "Pendiente"}
                                            </span>
                                          </td>
                                          <td className="px-3 py-2 text-right font-semibold text-slate-700">
                                            {formatearUsd(d.base_promo_usd)}
                                          </td>
                                          <td className="px-3 py-2 text-right font-black text-emerald-700">
                                            {formatearUsd(d.comision_usd)}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
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
        </>
      )}

      {/* PESTAÑA 2: HISTORIAL DE LIQUIDACIONES */}
      {pestana === "historial" && (
        <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
          <div className="px-5 py-3.5 border-b border-slate-200 flex items-center justify-between">
            <span className="font-bold text-sm text-[#000814]">
              Historial de Liquidaciones Pagadas y Anuladas
            </span>
            <span className="text-xs text-slate-500">
              {liquidacionesFiltradas.length} registro(s)
            </span>
          </div>

          {cargandoHistorial ? (
            <div className="p-6 space-y-3">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-12 rounded-xl bg-slate-100 animate-pulse"
                />
              ))}
            </div>
          ) : liquidacionesFiltradas.length === 0 ? (
            <p className="p-10 text-center text-sm text-slate-500">
              No hay liquidaciones registradas para este rango o filtro.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-50 border-b border-slate-200 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Código</th>
                    <th className="px-4 py-3">Colaborador / Período</th>
                    <th className="px-4 py-3">Método / Ref.</th>
                    <th className="px-4 py-3 text-right">Total Pagado</th>
                    <th className="px-4 py-3">Estado</th>
                    <th className="px-4 py-3 text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {liquidacionesFiltradas.map((l) => (
                    <tr key={l.id} className="hover:bg-[#EDF3FA]/40">
                      <td className="px-4 py-3 font-mono font-black text-[#003566] text-xs">
                        {l.codigo}
                      </td>
                      <td className="px-4 py-3 text-xs">
                        <p className="font-bold text-[#000814]">
                          {l.personal_nombre}
                        </p>
                        <p className="text-slate-500">
                          {l.fecha_inicio} al {l.fecha_fin} · {l.cantidad_ventas}{" "}
                          venta(s)
                        </p>
                      </td>
                      <td className="px-4 py-3 text-xs">
                        <p className="font-semibold text-slate-700">
                          {l.instrumento_pago_nombre || l.metodo_pago}
                        </p>
                        <p className="text-slate-500">
                          {l.referencia || "Sin referencia"}
                        </p>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <p className="font-black text-emerald-700 cifra-tabular">
                          {formatearUsd(l.monto_total_usd)}
                        </p>
                        {l.monto_bs && (
                          <p className="text-[11px] text-slate-500">
                            {formatearBs(l.monto_bs)}
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs space-y-1">
                        <div>
                          <span
                            className={`px-2 py-0.5 rounded-full font-bold text-[11px] ${
                              l.estado === "PAGADA"
                                ? "bg-emerald-50 text-emerald-700"
                                : "bg-red-50 text-red-700"
                            }`}
                          >
                            {l.estado}
                          </span>
                        </div>
                        <span
                          className={`inline-block px-1.5 py-0.5 rounded-md font-semibold text-[10px] ${
                            l.estado === "ANULADA"
                              ? "bg-slate-100 text-slate-500"
                              : l.egreso_registrado
                              ? "bg-[#EDF3FA] text-[#003566]"
                              : "bg-slate-100 text-slate-500"
                          }`}
                        >
                          {l.estado === "ANULADA"
                            ? "Egreso revertido"
                            : l.egreso_registrado
                            ? "Egreso registrado"
                            : "Sin egreso"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right whitespace-nowrap space-x-1">
                        <button
                          type="button"
                          onClick={() => void verDetalleLiquidacion(l.id)}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded-lg border border-slate-200 bg-white hover:border-[#003566] text-[#003566] text-xs font-bold cursor-pointer"
                          title="Ver ventas incluidas"
                        >
                          <Eye className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            void descargarPdfApi(
                              `/api/comisiones/liquidaciones/${l.id}/pdf`,
                              `${l.codigo}.pdf`
                            )
                          }
                          className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-[#003566] text-white text-xs font-bold cursor-pointer"
                          title="Descargar PDF"
                        >
                          <FileDown className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            const msg = formatearWhatsAppLiquidacion(l);
                            window.open(
                              construirUrlWhatsApp(msg, l.personal_telefono),
                              "_blank",
                              "noopener,noreferrer"
                            );
                          }}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-emerald-600 text-white text-xs font-bold cursor-pointer"
                          title="Reenviar comprobante por WhatsApp"
                        >
                          <MessageCircle className="w-3.5 h-3.5" />
                        </button>
                        {l.estado === "PAGADA" && (
                          <button
                            type="button"
                            onClick={() => {
                              setLiqAnular(l);
                              setMotivoAnulacion("");
                            }}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-lg border border-red-200 text-red-700 hover:bg-red-50 text-xs font-bold cursor-pointer"
                            title="Anular liquidación"
                          >
                            <Ban className="w-3.5 h-3.5" />
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
      )}

      {/* Modal de Liquidación Quincenal */}
      {personaALiquidar && (
        <ModalLiquidacionComision
          persona={personaALiquidar}
          ventasPendientes={ventasPendientesModal}
          fechaInicio={reporte?.fecha_inicio || fechaInicio}
          fechaFin={reporte?.fecha_fin || fechaFin}
          tasaBcvInicial={tasaBcvEfectiva}
          alCerrar={() => setPersonaALiquidar(null)}
          alLiquidarExito={() => {
            void cargarReporte();
            void cargarHistorialLiquidaciones();
          }}
        />
      )}

      {/* Modal Detalle de Liquidación */}
      {liqDetalle && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-2xl w-full p-6 shadow-2xl space-y-4 max-h-[88vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-black text-[#000814]">
                  {liqDetalle.codigo} — {liqDetalle.personal_nombre}
                </h3>
                <p className="text-xs text-slate-500">
                  Período {liqDetalle.fecha_inicio} al {liqDetalle.fecha_fin} ·{" "}
                  {liqDetalle.metodo_pago}
                  {liqDetalle.referencia ? ` · Ref: ${liqDetalle.referencia}` : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setLiqDetalle(null)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-[#000814] cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="rounded-xl border border-slate-200 overflow-hidden">
              <table className="w-full text-xs text-left">
                <thead className="bg-[#EDF3FA] text-[#001D3D] uppercase text-[11px]">
                  <tr>
                    <th className="px-3 py-2">Fecha</th>
                    <th className="px-3 py-2">Nota</th>
                    <th className="px-3 py-2">Producto</th>
                    <th className="px-3 py-2">Origen</th>
                    <th className="px-3 py-2 text-right">Comisión</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {(liqDetalle.ventas ?? []).map((v) => (
                    <tr key={v.venta_id}>
                      <td className="px-3 py-2">{v.fecha}</td>
                      <td className="px-3 py-2 font-mono font-bold">
                        {v.numero_venta}
                      </td>
                      <td className="px-3 py-2 max-w-xs truncate">
                        {v.producto}
                      </td>
                      <td className="px-3 py-2">
                        {v.origen} ({v.porcentaje_aplicado}%)
                      </td>
                      <td className="px-3 py-2 text-right font-bold text-emerald-700">
                        {formatearUsd(v.comision_usd)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Modal Anular Liquidación */}
      {liqAnular && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <h3 className="text-lg font-black text-red-700">
              Anular liquidación {liqAnular.codigo}
            </h3>
            <p className="text-xs text-slate-600">
              Al anular esta liquidación de{" "}
              <strong>{liqAnular.personal_nombre}</strong> (
              {formatearUsd(liqAnular.monto_total_usd)}), todas sus ventas
              asociadas volverán a estado <strong>PENDIENTE</strong> para poder
              liquidarlas nuevamente.
            </p>
            <form onSubmit={manejarAnularLiquidacion} className="space-y-3">
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Motivo de anulación *
                </label>
                <input
                  type="text"
                  required
                  minLength={3}
                  value={motivoAnulacion}
                  onChange={(e) => setMotivoAnulacion(e.target.value)}
                  placeholder="Ej. Error en referencia / monto"
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                />
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setLiqAnular(null)}
                  className="px-4 py-2 rounded-xl border border-slate-300 text-xs font-bold cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={anulando}
                  className="px-4 py-2 rounded-xl bg-red-600 hover:bg-red-700 text-white text-xs font-bold cursor-pointer"
                >
                  {anulando ? "Anulando..." : "Confirmar anulación"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal de Cierre Mensual (Solo DIRECCION) */}
      {modalCierre && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <h3 className="text-lg font-black text-[#000814]">
              Cerrar período mensual
            </h3>
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
                className="px-4 py-2 rounded-xl border border-slate-300 text-xs font-bold cursor-pointer"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => void confirmarCierreMes()}
                className="px-4 py-2 rounded-xl bg-[#003566] text-white text-xs font-bold cursor-pointer"
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
