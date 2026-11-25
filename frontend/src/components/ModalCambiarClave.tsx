"use client";

import React, { useState } from "react";
import { CheckCircle2, Eye, EyeOff, KeyRound, Lock, X } from "lucide-react";
import { ErrorApi, solicitarApi } from "@/servicios/api";

interface Props {
  abierto: boolean;
  alCerrar: () => void;
}

export default function ModalCambiarClave({ abierto, alCerrar }: Props) {
  const [claveActual, setClaveActual] = useState("");
  const [nuevaClave, setNuevaClave] = useState("");
  const [confirmarClave, setConfirmarClave] = useState("");
  const [verActual, setVerActual] = useState(false);
  const [verNueva, setVerNueva] = useState(false);
  const [verConfirmar, setVerConfirmar] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);

  if (!abierto) return null;

  const limpiarYCerrar = () => {
    setClaveActual("");
    setNuevaClave("");
    setConfirmarClave("");
    setError(null);
    setExito(null);
    alCerrar();
  };

  const manejarEnvio = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setExito(null);

    if (nuevaClave.length < 6) {
      setError("La nueva clave debe tener al menos 6 caracteres.");
      return;
    }
    if (nuevaClave !== confirmarClave) {
      setError("La nueva clave y su confirmación no coinciden.");
      return;
    }
    if (nuevaClave === claveActual) {
      setError("La nueva clave debe ser distinta a tu clave actual.");
      return;
    }

    setGuardando(true);
    try {
      const resp = await solicitarApi<{ mensaje: string }>("/api/auth/cambiar-clave", {
        method: "POST",
        body: JSON.stringify({
          clave_actual: claveActual,
          nueva_clave: nuevaClave,
          confirmar_clave: confirmarClave,
        }),
      });
      setExito(resp.mensaje || "Contraseña actualizada correctamente.");
      setClaveActual("");
      setNuevaClave("");
      setConfirmarClave("");
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "No se pudo cambiar la clave.");
    } finally {
      setGuardando(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/45 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl max-w-md w-full shadow-2xl border border-slate-200 overflow-hidden">
        <div className="flex items-center justify-between bg-[#003566] px-5 py-3.5 text-white">
          <div className="flex items-center gap-2 font-bold text-sm">
            <KeyRound className="w-4 h-4" />
            <span>Cambiar mi clave de acceso</span>
          </div>
          <button
            type="button"
            onClick={limpiarYCerrar}
            className="text-white/80 hover:text-white cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={manejarEnvio} className="p-5 space-y-4">
          {error && (
            <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-xs font-medium text-red-700">
              {error}
            </div>
          )}
          {exito && (
            <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-xs font-medium text-emerald-800 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>{exito}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Clave actual
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type={verActual ? "text" : "password"}
                required
                value={claveActual}
                onChange={(e) => setClaveActual(e.target.value)}
                className="w-full pl-9 pr-9 py-2 rounded-xl border border-slate-300 text-sm"
                placeholder="Tu clave actual"
              />
              <button
                type="button"
                onClick={() => setVerActual((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
              >
                {verActual ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Nueva clave (mín. 6 caracteres)
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type={verNueva ? "text" : "password"}
                required
                minLength={6}
                value={nuevaClave}
                onChange={(e) => setNuevaClave(e.target.value)}
                className="w-full pl-9 pr-9 py-2 rounded-xl border border-slate-300 text-sm"
                placeholder="Nueva contraseña segura"
              />
              <button
                type="button"
                onClick={() => setVerNueva((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
              >
                {verNueva ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Confirmar nueva clave
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type={verConfirmar ? "text" : "password"}
                required
                minLength={6}
                value={confirmarClave}
                onChange={(e) => setConfirmarClave(e.target.value)}
                className="w-full pl-9 pr-9 py-2 rounded-xl border border-slate-300 text-sm"
                placeholder="Repite tu nueva contraseña"
              />
              <button
                type="button"
                onClick={() => setVerConfirmar((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
              >
                {verConfirmar ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={limpiarYCerrar}
              className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer"
            >
              Cerrar
            </button>
            <button
              type="submit"
              disabled={guardando}
              className="px-4 py-2 rounded-xl bg-[#003566] hover:bg-[#001D3D] text-white text-xs font-bold disabled:opacity-60 cursor-pointer"
            >
              {guardando ? "Guardando..." : "Actualizar clave"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
