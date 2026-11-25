"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, ArrowRight, Eye, EyeOff, Lock, ShieldAlert, User } from "lucide-react";
import LogoAlfa from "@/components/LogoAlfa";
import { usarSesion } from "@/contexto/SesionContexto";
import { ErrorApi } from "@/servicios/api";

export default function PaginaLogin() {
  const { usuario, cargandoSesion, iniciarSesion } = usarSesion();
  const router = useRouter();

  const [nombreUsuario, setNombreUsuario] = useState("");
  const [clave, setClave] = useState("");
  const [mostrarClave, setMostrarClave] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bloqueado, setBloqueado] = useState(false);

  useEffect(() => {
    if (!cargandoSesion && usuario) {
      router.replace(
        usuario.rol === "DIRECTOR" ? "/dashboard/direccion" : "/dashboard/tasas"
      );
    }
  }, [usuario, cargandoSesion, router]);

  const manejarEnvio = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    setBloqueado(false);

    if (!nombreUsuario.trim() || !clave) {
      setError("Ingresa tu nombre de usuario y tu clave de acceso.");
      return;
    }

    setEnviando(true);
    try {
      await iniciarSesion(nombreUsuario.trim(), clave);
      router.replace("/dashboard/tasas");
    } catch (err) {
      if (err instanceof ErrorApi) {
        if (err.estado === 423) {
          setBloqueado(true);
        }
        setError(err.message);
      } else {
        setError("Ocurrió un error inesperado al iniciar sesión.");
      }
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className="min-h-screen relative flex items-center justify-center p-4 sm:p-8 overflow-hidden">
      <div
        aria-hidden="true"
        className="pointer-events-none select-none fixed inset-0 flex items-center justify-center opacity-[0.04]"
      >
        <img
          src="/brand/alfa-isotipo.png"
          alt=""
          className="w-[460px] h-[460px] object-contain"
        />
      </div>

      <div className="relative z-10 w-full max-w-md rounded-3xl bg-white/90 backdrop-blur-xl border border-slate-200/80 shadow-xl overflow-hidden">
        <div className="h-1.5 w-full bg-[#003566]" />

        <div className="p-7 sm:p-9 space-y-6">
          <div className="text-center space-y-3">
            <div className="flex justify-center">
              <LogoAlfa variante="horizontal" tema="claro" tamano="lg" />
            </div>
            <div className="space-y-1">
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#EDF3FA] text-[#003566] text-[11px] font-bold uppercase tracking-wider">
                Sistema Administrativo
              </span>
              <p className="text-xs font-medium text-neutral-500">
                ALFA IMPORTACIONES, C.A. · RIF J-50793794-1
              </p>
            </div>
          </div>

          <form onSubmit={manejarEnvio} className="space-y-4">
            {bloqueado ? (
              <div className="rounded-xl bg-red-600 text-white p-4 space-y-1.5 shadow-sm">
                <div className="flex items-center gap-2 font-bold text-sm">
                  <ShieldAlert className="w-5 h-5 shrink-0" />
                  <span>Acceso Bloqueado por Seguridad</span>
                </div>
                <p className="text-xs text-red-50 leading-relaxed">
                  {error ||
                    "Acceso bloqueado tras 5 intentos fallidos. Se ha notificado al Administrador para su desbloqueo."}
                </p>
              </div>
            ) : error ? (
              <div className="flex items-start gap-2.5 rounded-xl bg-red-50/90 border border-red-200 p-3.5 text-sm text-red-700">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            ) : null}

            <div className="space-y-1.5">
              <label
                htmlFor="usuario"
                className="block text-xs font-bold text-[#000814] uppercase tracking-wider"
              >
                Usuario (Nombre)
              </label>
              <div className="relative">
                <User className="w-4 h-4 text-neutral-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  id="usuario"
                  type="text"
                  required
                  autoComplete="username"
                  value={nombreUsuario}
                  onChange={(e) => setNombreUsuario(e.target.value)}
                  placeholder="Ej. Carlos Mendoza o Dirección General Alfa"
                  className="w-full pl-10 pr-3.5 py-2.5 rounded-xl border border-neutral-200 bg-white/95 text-sm text-[#000814] placeholder:text-neutral-400"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label
                htmlFor="clave"
                className="block text-xs font-bold text-[#000814] uppercase tracking-wider"
              >
                Clave de acceso
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 text-neutral-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  id="clave"
                  type={mostrarClave ? "text" : "password"}
                  required
                  autoComplete="current-password"
                  value={clave}
                  onChange={(e) => setClave(e.target.value)}
                  placeholder="••••••••"
                  className="w-full pl-10 pr-10 py-2.5 rounded-xl border border-neutral-200 bg-white/95 text-sm text-[#000814] placeholder:text-neutral-400"
                />
                <button
                  type="button"
                  onClick={() => setMostrarClave((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-neutral-700"
                  aria-label="Mostrar u ocultar clave"
                >
                  {mostrarClave ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={enviando}
              className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl bg-[#003566] hover:bg-[#001D3D] text-white font-bold text-sm transition-colors shadow-sm disabled:opacity-60 cursor-pointer"
            >
              <span>{enviando ? "Verificando acceso..." : "Ingresar al sistema"}</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
