"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Download,
  Loader2,
  RefreshCw,
  Save,
  ShieldAlert,
  Wallet,
} from "lucide-react";
import {
  ErrorApi,
  fechaHoyCaracas,
  formatearUsd,
  obtenerToken,
  solicitarApi,
} from "@/servicios/api";

const URL_BASE_API =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ||
  process.env.NEXT_PUBLIC_URL_API_PYTHON?.replace(/\/+$/, "") ||
  "http://localhost:8000";

interface InstrumentoApertura {
  id: number;
  nombre: string;
  moneda: string;
  saldo_inicial: number;
  saldo_inicial_usd: number;
}

interface EstadoApertura {
  en_cero: boolean;
  conteos: Record<string, number>;
  frase_confirmacion_requerida: string;
  total_saldos_iniciales_usd: number;
  instrumentos: InstrumentoApertura[];
}

export default function PaginaAperturaAlfa() {
  const [estado, setEstado] = useState<EstadoApertura | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);

  // Saldos iniciales editables
  const [saldosForm, setSaldosForm] = useState<Record<number, string>>({});
  const [fechaApertura, setFechaApertura] = useState(fechaHoyCaracas());
  const [guardandoSaldos, setGuardandoSaldos] = useState(false);

  // Reset en cero protegido
  const [passwordAdmin, setPasswordAdmin] = useState("");
  const [fraseConfirmacion, setFraseConfirmacion] = useState("");
  const [ejecutandoReset, setEjecutandoReset] = useState(false);

  const cargarEstado = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const data = await solicitarApi<EstadoApertura>("/api/apertura/estado");
      setEstado(data);
      const mapa: Record<number, string> = {};
      for (const inst of data.instrumentos) {
        mapa[inst.id] = String(inst.saldo_inicial ?? 0);
      }
      setSaldosForm(mapa);
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo cargar el estado de apertura."
      );
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void cargarEstado();
  }, [cargarEstado]);

  const descargarPlantillasZip = async () => {
    setError(null);
    try {
      const token = obtenerToken();
      const res = await fetch(`${URL_BASE_API}/api/apertura/plantillas-zip`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error("No se pudieron descargar las plantillas.");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "plantillas_apertura_alfa_01_12.zip";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      setExito("Paquete de 6 planillas oficiales de apertura (.zip) descargado.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al descargar .zip.");
    }
  };

  const guardarSaldosIniciales = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!estado) return;
    setGuardandoSaldos(true);
    setError(null);
    setExito(null);
    try {
      const saldos = estado.instrumentos.map((i) => ({
        instrumento_id: i.id,
        saldo_inicial: Number(saldosForm[i.id] || 0),
      }));
      const res = await solicitarApi<{
        mensaje: string;
        total_usd: number;
      }>("/api/apertura/cargar-saldos-iniciales", {
        method: "POST",
        body: JSON.stringify({
          fecha_apertura: fechaApertura,
          saldos,
        }),
      });
      setExito(
        `${res.mensaje} Total apertura: ${formatearUsd(res.total_usd)} (asiento contable cuadrado).`
      );
      await cargarEstado();
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudieron guardar los saldos iniciales."
      );
    } finally {
      setGuardandoSaldos(false);
    }
  };

  const ejecutarReset = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setEjecutandoReset(true);
    setError(null);
    setExito(null);
    try {
      const res = await solicitarApi<{
        mensaje: string;
        total_registros_eliminados: number;
      }>("/api/apertura/reset-cero", {
        method: "POST",
        body: JSON.stringify({
          password: passwordAdmin,
          frase_confirmacion: fraseConfirmacion,
        }),
      });
      setPasswordAdmin("");
      setFraseConfirmacion("");
      setExito(
        `${res.mensaje} (${res.total_registros_eliminados} registros operativos eliminados).`
      );
      await cargarEstado();
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo ejecutar el reinicio en cero."
      );
    } finally {
      setEjecutandoReset(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-[#001D3D] flex items-center gap-2">
            <RefreshCw className="w-6 h-6 text-[#003566]" />
            Inicio en Cero y Carga Inicial de Apertura 01/12
          </h1>
          <p className="text-sm text-slate-500">
            Exclusivo ADMIN · Descarga las 6 planillas oficiales, reinicia la data de prueba
            y carga los saldos iniciales reales de cajas y bancos con asiento de apertura.
          </p>
        </div>

        <button
          type="button"
          onClick={() => void descargarPlantillasZip()}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[#003566] hover:bg-[#001D3D] text-white text-xs font-bold shadow-xs cursor-pointer"
        >
          <Download className="w-4 h-4" />
          Descargar 6 Planillas de Apertura (.zip)
        </button>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {exito && (
        <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-sm text-emerald-800 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{exito}</span>
        </div>
      )}

      {cargando || !estado ? (
        <div className="py-16 flex items-center justify-center gap-2 text-sm text-slate-500">
          <Loader2 className="w-5 h-5 animate-spin text-[#003566]" />
          Consultando estado actual del sistema...
        </div>
      ) : (
        <>
          {/* Estado de registros operativos */}
          <div className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-black text-[#001D3D]">
                Estado Operativo Actual de la Base de Datos
              </h2>
              <span
                className={`px-3 py-1 rounded-full text-xs font-bold ${
                  estado.en_cero
                    ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                    : "bg-amber-50 text-amber-800 border border-amber-200"
                }`}
              >
                {estado.en_cero ? "Sistema en Cero (Listo para Apertura)" : "Contiene registros operativos"}
              </span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 text-xs">
              {Object.entries(estado.conteos).map(([clave, val]) => (
                <div key={clave} className="p-3 rounded-xl bg-slate-50 border border-slate-200">
                  <p className="text-slate-500 uppercase text-[10px] font-bold">
                    {clave.replace(/_/g, " ")}
                  </p>
                  <p className="text-lg font-black text-[#001D3D] cifra-tabular">{val}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Carga de Saldos Iniciales de Cajas y Bancos */}
          <form
            onSubmit={guardarSaldosIniciales}
            className="rounded-2xl border border-slate-200 bg-white p-5 space-y-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-black text-[#001D3D] flex items-center gap-2">
                  <Wallet className="w-4 h-4 text-[#003566]" />
                  Carga de Saldos Iniciales de Cajas y Bancos
                </h2>
                <p className="text-xs text-slate-500">
                  Total actual en apertura:{" "}
                  <strong className="text-[#003566]">
                    {formatearUsd(estado.total_saldos_iniciales_usd)}
                  </strong>
                </p>
              </div>
              <div className="flex items-center gap-2">
                <label className="text-xs font-bold text-slate-600">Fecha de apertura:</label>
                <input
                  type="date"
                  value={fechaApertura}
                  onChange={(e) => setFechaApertura(e.target.value)}
                  className="px-3 py-1.5 rounded-xl border border-slate-300 text-xs font-bold"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {estado.instrumentos.map((inst) => (
                <div
                  key={inst.id}
                  className="p-3 rounded-xl border border-slate-200 bg-slate-50/70 space-y-1.5"
                >
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-bold text-slate-800">{inst.nombre}</span>
                    <span className="px-1.5 py-0.5 rounded bg-slate-200 text-[10px] font-bold">
                      {inst.moneda}
                    </span>
                  </div>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={saldosForm[inst.id] ?? "0"}
                    onChange={(e) =>
                      setSaldosForm((prev) => ({ ...prev, [inst.id]: e.target.value }))
                    }
                    className="w-full px-3 py-1.5 rounded-lg border border-slate-300 bg-white text-sm font-bold cifra-tabular"
                  />
                </div>
              ))}
            </div>

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={guardandoSaldos}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-700 hover:bg-emerald-800 disabled:opacity-60 text-white text-xs font-bold cursor-pointer"
              >
                <Save className="w-4 h-4" />
                {guardandoSaldos
                  ? "Guardando y contabilizando..."
                  : "Guardar Saldos Iniciales y Generar Asiento"}
              </button>
            </div>
          </form>

          {/* Zona Peligrosa: Reset en Cero */}
          <form
            onSubmit={ejecutarReset}
            className="rounded-2xl border border-rose-200 bg-rose-50/50 p-5 space-y-4"
          >
            <div className="flex items-start gap-3">
              <ShieldAlert className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <h2 className="text-sm font-black text-rose-900">
                  Zona Protegida · Reiniciar Data Operativa en Cero
                </h2>
                <p className="text-xs text-rose-800">
                  Elimina ventas, pagos, inventario, traslados, asientos contables y cierres de
                  prueba para iniciar limpio. <strong>Preserva usuarios, sucursales, plan de cuentas y catálogo.</strong>
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] font-bold uppercase text-rose-900 mb-1">
                  Tu contraseña de Administrador *
                </label>
                <input
                  type="password"
                  required
                  value={passwordAdmin}
                  onChange={(e) => setPasswordAdmin(e.target.value)}
                  placeholder="Ingresa tu contraseña actual"
                  className="w-full px-3 py-2 rounded-xl border border-rose-300 bg-white text-sm"
                />
              </div>
              <div>
                <label className="block text-[11px] font-bold uppercase text-rose-900 mb-1">
                  Escribe exactamente: {estado.frase_confirmacion_requerida}
                </label>
                <input
                  type="text"
                  required
                  value={fraseConfirmacion}
                  onChange={(e) => setFraseConfirmacion(e.target.value)}
                  placeholder={estado.frase_confirmacion_requerida}
                  className="w-full px-3 py-2 rounded-xl border border-rose-300 bg-white text-sm font-mono"
                />
              </div>
            </div>

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={
                  ejecutandoReset ||
                  fraseConfirmacion.trim().toUpperCase() !== estado.frase_confirmacion_requerida
                }
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white text-xs font-bold cursor-pointer"
              >
                <AlertTriangle className="w-4 h-4" />
                {ejecutandoReset ? "Reiniciando en cero..." : "Confirmar Reinicio en Cero"}
              </button>
            </div>
          </form>
        </>
      )}
    </div>
  );
}
