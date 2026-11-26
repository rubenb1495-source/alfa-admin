"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { guardarToken, obtenerToken, solicitarApi } from "@/servicios/api";
import type { RespuestaLogin, TasaHoy, Usuario } from "@/tipos/dominio";

interface ValorContextoSesion {
  usuario: Usuario | null;
  cargandoSesion: boolean;
  tasaHoy: TasaHoy | null;
  cargandoTasa: boolean;
  iniciarSesion: (correo: string, clave: string) => Promise<void>;
  cerrarSesion: () => void;
  recargarTasaHoy: () => Promise<void>;
  actualizarTasaHoyLocal: (tasa: TasaHoy) => void;
  marcarClaveCambiada: () => Promise<void>;
}

const ContextoSesion = createContext<ValorContextoSesion | undefined>(undefined);

export function ProveedorSesion({ children }: { children: React.ReactNode }) {
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [cargandoSesion, setCargandoSesion] = useState(true);
  const [tasaHoy, setTasaHoy] = useState<TasaHoy | null>(null);
  const [cargandoTasa, setCargandoTasa] = useState(false);

  const recargarTasaHoy = useCallback(async () => {
    if (!obtenerToken()) return;
    setCargandoTasa(true);
    try {
      const datos = await solicitarApi<TasaHoy>("/api/tasas/hoy");
      setTasaHoy(datos);
    } catch {
      setTasaHoy(null);
    } finally {
      setCargandoTasa(false);
    }
  }, []);

  useEffect(() => {
    const inicializar = async () => {
      const token = obtenerToken();
      if (!token) {
        setCargandoSesion(false);
        return;
      }
      try {
        const perfil = await solicitarApi<Usuario>("/api/auth/me");
        setUsuario(perfil);
        if (!perfil.debe_cambiar_clave) {
          await recargarTasaHoy();
        }
      } catch {
        guardarToken(null);
        setUsuario(null);
      } finally {
        setCargandoSesion(false);
      }
    };
    void inicializar();
  }, [recargarTasaHoy]);

  const iniciarSesion = useCallback(
    async (usuarioNombre: string, clave: string) => {
      const respuesta = await solicitarApi<RespuestaLogin>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ usuario: usuarioNombre, clave }),
      });
      guardarToken(respuesta.token);
      const usr = {
        ...respuesta.usuario,
        debe_cambiar_clave: Boolean(
          respuesta.debe_cambiar_clave ?? respuesta.usuario.debe_cambiar_clave
        ),
      };
      setUsuario(usr);
      if (!usr.debe_cambiar_clave) {
        await recargarTasaHoy();
      }
    },
    [recargarTasaHoy]
  );

  const cerrarSesion = useCallback(() => {
    if (obtenerToken()) {
      void solicitarApi("/api/auth/logout", { method: "POST" }).catch(() => {});
    }
    guardarToken(null);
    setUsuario(null);
    setTasaHoy(null);
  }, []);

  const marcarClaveCambiada = useCallback(async () => {
    setUsuario((prev) => (prev ? { ...prev, debe_cambiar_clave: false } : prev));
    await recargarTasaHoy();
  }, [recargarTasaHoy]);

  const actualizarTasaHoyLocal = useCallback((tasa: TasaHoy) => {
    setTasaHoy(tasa);
  }, []);

  return (
    <ContextoSesion.Provider
      value={{
        usuario,
        cargandoSesion,
        tasaHoy,
        cargandoTasa,
        iniciarSesion,
        cerrarSesion,
        recargarTasaHoy,
        actualizarTasaHoyLocal,
        marcarClaveCambiada,
      }}
    >
      {children}
    </ContextoSesion.Provider>
  );
}

export function usarSesion(): ValorContextoSesion {
  const contexto = useContext(ContextoSesion);
  if (!contexto) {
    throw new Error("usarSesion debe utilizarse dentro de ProveedorSesion.");
  }
  return contexto;
}
