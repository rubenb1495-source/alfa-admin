"use client";

import React, { useEffect, useState } from "react";
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import { ErrorApi, solicitarApi } from "@/servicios/api";
import type { TasaHoy } from "@/tipos/dominio";

interface ModalAperturaDiariaProps {
  tasaHoy: TasaHoy;
  bloqueante: boolean;
  alCerrar?: () => void;
  alConfirmar: (tasaActualizada: TasaHoy) => void;
}

export default function ModalAperturaDiaria({
  tasaHoy,
  bloqueante,
  alCerrar,
  alConfirmar,
}: ModalAperturaDiariaProps) {
  const [tasaBcv, setTasaBcv] = useState(
    tasaHoy.tasa_bcv !== null ? String(tasaHoy.tasa_bcv) : ""
  );
  const [tasaUsdt, setTasaUsdt] = useState(
    tasaHoy.tasa_usdt !== null ? String(tasaHoy.tasa_usdt) : ""
  );
  const [porcentajeRecargo, setPorcentajeRecargo] = useState(
    !bloqueante && tasaHoy.recargo_porcentaje !== null
      ? String(tasaHoy.recargo_porcentaje)
      : ""
  );
  const [fuenteActual, setFuenteActual] = useState(
    tasaHoy.fuente_tasa || "RESPALDO_MANUAL"
  );
  const [sincronizando, setSincronizando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [infoSync, setInfoSync] = useState<string | null>(null);

  useEffect(() => {
    const manejarTecla = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (bloqueante) {
          e.preventDefault();
          e.stopPropagation();
        } else if (alCerrar) {
          alCerrar();
        }
      }
    };
    window.addEventListener("keydown", manejarTecla, true);
    return () => window.removeEventListener("keydown", manejarTecla, true);
  }, [bloqueante, alCerrar]);

  const refrescarTasas = async () => {
    setSincronizando(true);
    setError(null);
    setInfoSync(null);
    try {
      const resp = await solicitarApi<TasaHoy>("/api/tasas/sincronizar", {
        method: "POST",
      });
      if (resp.tasa_bcv !== null) setTasaBcv(String(resp.tasa_bcv));
      if (resp.tasa_usdt !== null) setTasaUsdt(String(resp.tasa_usdt));
      setFuenteActual(resp.fuente_tasa || "RESPALDO_MANUAL");
      if (resp.fuente_tasa === "API_VIVO") {
        setInfoSync("Tasas actualizadas en vivo correctamente.");
      } else {
        setInfoSync(
          resp.alerta ||
            "No se pudo conectar con la API externa; se mantienen los valores de respaldo."
        );
      }
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudieron refrescar las tasas automáticas."
      );
    } finally {
      setSincronizando(false);
    }
  };

  const manejarConfirmar = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    setInfoSync(null);

    const bcvNum = Number(tasaBcv);
    const usdtNum = tasaUsdt.trim() === "" ? bcvNum : Number(tasaUsdt);
    const recargoNum = Number(porcentajeRecargo);

    if (!Number.isFinite(bcvNum) || bcvNum <= 0) {
      setError("Ingresa una tasa BCV válida mayor a 0.");
      return;
    }
    if (!Number.isFinite(usdtNum) || usdtNum <= 0) {
      setError("Ingresa una tasa USDT válida mayor a 0.");
      return;
    }
    if (
      porcentajeRecargo.trim() === "" ||
      !Number.isFinite(recargoNum) ||
      recargoNum < 0 ||
      recargoNum > 500
    ) {
      setError(
        "El porcentaje de recargo es obligatorio y debe ser un número mayor o igual a 0."
      );
      return;
    }

    setGuardando(true);
    try {
      const confirmada = await solicitarApi<TasaHoy>(
        "/api/tasas/hoy/confirmar",
        {
          method: "POST",
          body: JSON.stringify({
            porcentaje_recargo: recargoNum,
            tasa_bcv: bcvNum,
            tasa_usdt: usdtNum,
          }),
        }
      );
      alConfirmar(confirmada);
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo confirmar la apertura del día."
      );
    } finally {
      setGuardando(false);
    }
  };

  const esEnVivo = fuenteActual === "API_VIVO";

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center p-4 bg-[#000814]/55 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="titulo-apertura-diaria"
      onClick={(e) => {
        if (!bloqueante && alCerrar && e.target === e.currentTarget) {
          alCerrar();
        }
      }}
    >
      <div className="w-full max-w-lg rounded-3xl bg-white border border-slate-200 shadow-2xl overflow-hidden">
        {/* Franja superior Azul Alfa */}
        <div className="h-1.5 w-full bg-[#003566]" />

        <div className="p-6 sm:p-7 space-y-5">
          {/* Encabezado */}
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-[#EDF3FA] text-[#003566] text-[11px] font-bold uppercase tracking-wider">
                <Calendar className="w-3 h-3" />
                Jornada {tasaHoy.fecha} (Venezuela)
              </div>
              <h2
                id="titulo-apertura-diaria"
                className="text-lg sm:text-xl font-black text-[#000814] leading-tight"
              >
                Apertura del día — Tasas y Porcentaje de Recargo
              </h2>
              <p className="text-xs text-slate-500">
                {bloqueante
                  ? "Confirma las tasas vigentes y el porcentaje de recargo para habilitar la jornada de hoy."
                  : "Actualiza las tasas BCV/USDT o el porcentaje de recargo activo de la jornada."}
              </p>
            </div>
            {!bloqueante && alCerrar && (
              <button
                type="button"
                onClick={alCerrar}
                aria-label="Cerrar"
                className="p-1.5 rounded-lg text-slate-400 hover:text-[#000814] hover:bg-slate-100 cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            )}
          </div>

          {/* Indicador de fuente + botón Refrescar tasas */}
          <div className="flex flex-wrap items-center justify-between gap-2 px-3.5 py-2.5 rounded-xl bg-slate-50 border border-slate-200">
            <div className="flex items-center gap-2 text-xs font-semibold">
              {esEnVivo ? (
                <>
                  <Wifi className="w-4 h-4 text-emerald-600 shrink-0" />
                  <span className="text-emerald-700">
                    Tasas obtenidas en vivo
                  </span>
                </>
              ) : (
                <>
                  <WifiOff className="w-4 h-4 text-amber-600 shrink-0" />
                  <span className="text-amber-700">
                    {fuenteActual === "MANUAL"
                      ? "Tasas ajustadas manualmente"
                      : "Tasas de respaldo (verifica o edita)"}
                  </span>
                </>
              )}
            </div>
            <button
              type="button"
              onClick={() => void refrescarTasas()}
              disabled={sincronizando || guardando}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white border border-slate-200 hover:border-[#003566] text-[#003566] text-xs font-bold transition-colors disabled:opacity-60 cursor-pointer"
            >
              {sincronizando ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <RefreshCw className="w-3.5 h-3.5" />
              )}
              Refrescar tasas
            </button>
          </div>

          {error && (
            <div className="flex items-start gap-2 p-3 rounded-xl bg-red-50 border border-red-200 text-xs text-red-700 font-medium">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {infoSync && (
            <div className="flex items-start gap-2 p-3 rounded-xl bg-[#EDF3FA] border border-[#003566]/20 text-xs text-[#003566] font-medium">
              <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
              <span>{infoSync}</span>
            </div>
          )}

          <form onSubmit={manejarConfirmar} className="space-y-4">
            {/* Tasas BCV y USDT editables */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-bold text-[#000814] mb-1">
                  Tasa BCV (Bs / USD) *
                </label>
                <input
                  type="number"
                  step="0.0001"
                  min="0.0001"
                  required
                  value={tasaBcv}
                  onChange={(e) => setTasaBcv(e.target.value)}
                  placeholder="Ej. 52.4500"
                  className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 bg-white text-sm font-semibold cifra-tabular text-[#000814]"
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-[#000814] mb-1">
                  Tasa USDT / Paralelo (Bs)
                </label>
                <input
                  type="number"
                  step="0.0001"
                  min="0.0001"
                  value={tasaUsdt}
                  onChange={(e) => setTasaUsdt(e.target.value)}
                  placeholder="Ej. 64.0000"
                  className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 bg-white text-sm font-semibold cifra-tabular text-[#000814]"
                />
              </div>
            </div>

            {/* Campo obligatorio de Porcentaje de Recargo */}
            <div className="p-4 rounded-2xl bg-[#EDF3FA]/65 border border-[#003566]/25 space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label
                  htmlFor="input-porcentaje-recargo"
                  className="text-xs font-black text-[#003566] uppercase tracking-wide"
                >
                  Porcentaje de Recargo del día (%) *
                </label>
                {tasaHoy.ultimo_recargo_usado !== null &&
                  tasaHoy.ultimo_recargo_usado !== undefined && (
                    <button
                      type="button"
                      onClick={() =>
                        setPorcentajeRecargo(
                          String(tasaHoy.ultimo_recargo_usado)
                        )
                      }
                      className="text-[11px] font-bold text-[#003566] hover:underline cursor-pointer"
                    >
                      Usar anterior ({tasaHoy.ultimo_recargo_usado}%)
                    </button>
                  )}
              </div>
              <input
                id="input-porcentaje-recargo"
                type="number"
                step="0.01"
                min="0"
                max="500"
                required
                autoFocus
                value={porcentajeRecargo}
                onChange={(e) => setPorcentajeRecargo(e.target.value)}
                placeholder="Ej. 15"
                className="w-full px-3.5 py-2.5 rounded-xl border border-[#003566]/35 bg-white text-base font-black cifra-tabular text-[#000814]"
              />
              <p className="text-[11px] text-slate-600">
                {tasaHoy.ultimo_recargo_usado !== null &&
                tasaHoy.ultimo_recargo_usado !== undefined
                  ? `Referencia: el día anterior se utilizó ${tasaHoy.ultimo_recargo_usado}%. Debes ingresarlo o confirmarlo explícitamente para hoy.`
                  : "Ingresa el porcentaje de recargo que se aplicará hoy sobre los precios regulares y pagos en Bs/Cashea (puede ser 0)."}
              </p>
            </div>

            <div className="flex items-center justify-end gap-2 pt-1">
              {!bloqueante && alCerrar && (
                <button
                  type="button"
                  onClick={alCerrar}
                  className="px-4 py-2.5 rounded-xl border border-slate-200 text-xs font-bold text-slate-600 hover:bg-slate-50 cursor-pointer"
                >
                  Cancelar
                </button>
              )}
              <button
                type="submit"
                disabled={guardando}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-[#003566] hover:bg-[#001D3D] disabled:opacity-60 text-white text-sm font-bold shadow-sm transition-colors cursor-pointer"
              >
                {guardando ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <ShieldCheck className="w-4 h-4" />
                )}
                {bloqueante
                  ? "Confirmar y abrir jornada"
                  : "Guardar cambios del día"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
