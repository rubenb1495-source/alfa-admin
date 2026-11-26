"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  LogOut,
  ShieldAlert,
} from "lucide-react";
import LogoAlfa from "@/components/LogoAlfa";
import { usarSesion } from "@/contexto/SesionContexto";
import { ErrorApi, solicitarApi } from "@/servicios/api";
import type { RolUsuario } from "@/tipos/dominio";

function rutaInicioPorRol(rol: RolUsuario | string): string {
  switch (rol) {
    case "DIRECCION":
    case "ADMINISTRACION":
    case "DIRECTOR":
      return "/dashboard/direccion";
    case "TECNICO":
      return "/dashboard/taller/preparaciones";
    case "LOGISTICA":
      return "/dashboard/logistica/inventario";
    default:
      return "/dashboard/ventas/nueva";
  }
}

export default function PantallaCambioClaveObligatorio() {
  const { usuario, cerrarSesion, marcarClaveCambiada } = usarSesion();
  const router = useRouter();

  const [claveActual, setClaveActual] = useState("");
  const [nuevaClave, setNuevaClave] = useState("");
  const [confirmarClave, setConfirmarClave] = useState("");

  const [verActual, setVerActual] = useState(false);
  const [verNueva, setVerNueva] = useState(false);
  const [verConfirmar, setVerConfirmar] = useState(false);

  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);

  const cumpleMinimo = nuevaClave.length >= 6;
  const cumpleDistinta =
    nuevaClave.length > 0 && claveActual.length > 0 && nuevaClave !== claveActual;
  const cumpleCoincide =
    confirmarClave.length > 0 && nuevaClave === confirmarClave;

  const formularioValido =
    claveActual.length >= 4 && cumpleMinimo && cumpleDistinta && cumpleCoincide;

  const manejarEnvio = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    if (!cumpleMinimo) {
      setError("La nueva contraseña debe tener al menos 6 caracteres.");
      return;
    }
    if (!cumpleDistinta) {
      setError("La nueva contraseña debe ser distinta a la clave temporal actual.");
      return;
    }
    if (!cumpleCoincide) {
      setError("La nueva contraseña y su confirmación no coinciden.");
      return;
    }

    setGuardando(true);
    try {
      await solicitarApi("/api/auth/cambiar-clave", {
        method: "POST",
        body: JSON.stringify({
          clave_actual: claveActual,
          nueva_clave: nuevaClave,
          confirmar_clave: confirmarClave,
        }),
      });
      setExito("Contraseña actualizada correctamente. Redirigiendo a tu panel...");
      const destino = rutaInicioPorRol(usuario?.rol || "");
      window.setTimeout(async () => {
        await marcarClaveCambiada();
        router.replace(destino);
      }, 900);
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo actualizar tu contraseña. Verifica la clave temporal actual."
      );
    } finally {
      setGuardando(false);
    }
  };

  const manejarSalir = () => {
    cerrarSesion();
    router.replace("/login");
  };

  return (
    <div className="min-h-screen bg-slate-100 flex items-center justify-center p-4">
      <div className="w-full max-w-md rounded-3xl border border-slate-200 bg-white shadow-xl overflow-hidden">
        {/* Encabezado corporativo */}
        <div className="bg-gradient-to-br from-[#001D3D] to-[#003566] px-6 py-6 text-white space-y-3">
          <div className="flex items-center justify-between">
            <LogoAlfa variante="isotipo" tema="oscuro" tamano="sm" />
            <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-400/20 border border-amber-300/40 px-3 py-1 text-[11px] font-bold text-amber-200">
              <ShieldAlert className="w-3.5 h-3.5" />
              Paso obligatorio
            </span>
          </div>
          <div>
            <h1 className="text-xl font-black tracking-tight">
              Cambio Obligatorio de Contraseña
            </h1>
            <p className="mt-1 text-xs text-sky-100/90 leading-relaxed">
              Por seguridad, debes cambiar tu contraseña temporal antes de comenzar a
              usar Alfa Admin.
            </p>
          </div>
          {usuario && (
            <div className="rounded-xl bg-white/10 px-3 py-2 text-[11px] text-sky-100 flex items-center justify-between">
              <span className="font-semibold truncate">{usuario.nombre}</span>
              <span className="font-mono text-sky-200">{usuario.rol}</span>
            </div>
          )}
        </div>

        {/* Formulario bloqueante (sin X ni Escape) */}
        <form onSubmit={manejarEnvio} className="p-6 space-y-4">
          {error && (
            <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-2.5 text-xs text-red-700">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {exito && (
            <div className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-2.5 text-xs font-medium text-emerald-800">
              <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{exito}</span>
            </div>
          )}

          {/* Campo 1: Contraseña temporal actual */}
          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">
              Contraseña temporal actual *
            </label>
            <div className="relative">
              <input
                type={verActual ? "text" : "password"}
                required
                autoComplete="current-password"
                value={claveActual}
                onChange={(e) => setClaveActual(e.target.value)}
                placeholder="Ingresa tu clave temporal"
                className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 pr-10 text-sm focus:border-[#003566] focus:outline-none"
              />
              <button
                type="button"
                onClick={() => setVerActual((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700 cursor-pointer"
                aria-label="Mostrar u ocultar contraseña temporal"
              >
                {verActual ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* Campo 2: Nueva contraseña */}
          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">
              Nueva contraseña *
            </label>
            <div className="relative">
              <input
                type={verNueva ? "text" : "password"}
                required
                autoComplete="new-password"
                value={nuevaClave}
                onChange={(e) => setNuevaClave(e.target.value)}
                placeholder="Mínimo 6 caracteres"
                className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 pr-10 text-sm focus:border-[#003566] focus:outline-none"
              />
              <button
                type="button"
                onClick={() => setVerNueva((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700 cursor-pointer"
                aria-label="Mostrar u ocultar nueva contraseña"
              >
                {verNueva ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* Campo 3: Confirmar nueva contraseña */}
          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">
              Confirmar nueva contraseña *
            </label>
            <div className="relative">
              <input
                type={verConfirmar ? "text" : "password"}
                required
                autoComplete="new-password"
                value={confirmarClave}
                onChange={(e) => setConfirmarClave(e.target.value)}
                placeholder="Repite tu nueva contraseña"
                className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 pr-10 text-sm focus:border-[#003566] focus:outline-none"
              />
              <button
                type="button"
                onClick={() => setVerConfirmar((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700 cursor-pointer"
                aria-label="Mostrar u ocultar confirmación"
              >
                {verConfirmar ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* Validación visual de requisitos */}
          <div className="rounded-xl bg-slate-50 border border-slate-200 p-3 space-y-1.5 text-xs">
            <p className="font-bold text-slate-600 text-[11px] uppercase">
              Requisitos de seguridad
            </p>
            <div className={`flex items-center gap-2 ${cumpleMinimo ? "text-emerald-700 font-semibold" : "text-slate-500"}`}>
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
              <span>Al menos 6 caracteres</span>
            </div>
            <div className={`flex items-center gap-2 ${cumpleDistinta ? "text-emerald-700 font-semibold" : "text-slate-500"}`}>
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
              <span>Distinta a tu contraseña temporal actual</span>
            </div>
            <div className={`flex items-center gap-2 ${cumpleCoincide ? "text-emerald-700 font-semibold" : "text-slate-500"}`}>
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
              <span>La confirmación coincide exactamente</span>
            </div>
          </div>

          {/* Botones */}
          <div className="pt-1 space-y-2.5">
            <button
              type="submit"
              disabled={guardando || !formularioValido || Boolean(exito)}
              className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-[#003566] hover:bg-[#001D3D] disabled:opacity-50 px-4 py-3 text-sm font-bold text-white shadow-xs transition cursor-pointer"
            >
              {guardando ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Actualizando contraseña...
                </>
              ) : (
                <>
                  <KeyRound className="w-4 h-4" />
                  Guardar nueva contraseña y continuar
                </>
              )}
            </button>

            <button
              type="button"
              onClick={manejarSalir}
              disabled={guardando}
              className="w-full inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 px-4 py-2.5 text-xs font-semibold text-slate-600 transition cursor-pointer"
            >
              <LogOut className="w-3.5 h-3.5" />
              Cerrar sesión
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
