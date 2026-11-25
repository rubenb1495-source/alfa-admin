"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Bell, Boxes, CalendarClock, ExternalLink, ShieldAlert } from "lucide-react";
import { usarSesion } from "@/contexto/SesionContexto";
import { esRolAdministrativo, formatearUsd, solicitarApi } from "@/servicios/api";

export interface AlertaSeguridadItem {
  usuario_id: number;
  nombre: string;
  usuario: string;
  rol: string;
  intentos_fallidos: number;
  fecha_bloqueo: string | null;
  mensaje: string;
}

export interface AlertaInventarioItem {
  articulo_id: number;
  sku: string;
  nombre: string;
  categoria: string;
  tipo: string;
  sucursal_id: number;
  almacen: string;
  stock_disponible: number;
  stock_minimo: number;
  cantidad_en_transito: number;
  severidad: "AGOTADO" | "BAJO";
}

export interface AlertaCxpItem {
  id: number;
  fuente: string;
  proveedor: string;
  concepto_o_referencia: string;
  fecha_vencimiento: string;
  monto_pendiente_usd: number;
  dias_diferencia: number;
  urgencia: "VENCIDA" | "VENCE_HOY" | "PROXIMA";
}

export interface ResumenAlertas {
  fecha_evaluacion: string;
  configuracion: {
    stock_minimo_global: number;
    dias_alerta_cxp: number;
    actualizado_por: string;
  };
  contadores: {
    total_criticas: number;
    total_preventivas: number;
    total_alertas: number;
    agotados: number;
    stock_bajo: number;
    cxp_criticas: number;
    cxp_proximas: number;
    seguridad_bloqueos?: number;
    monto_total_cxp_alerta_usd: number;
  };
  inventario: AlertaInventarioItem[];
  cuentas_por_pagar: AlertaCxpItem[];
  seguridad?: AlertaSeguridadItem[];
}

export default function CampanaAlertas() {
  const { usuario } = usarSesion();
  const esAdmin = usuario ? esRolAdministrativo(usuario.rol) : false;
  const [resumen, setResumen] = useState<ResumenAlertas | null>(null);
  const [desbloqueandoId, setDesbloqueandoId] = useState<number | null>(null);
  const [abierto, setAbierto] = useState(false);
  const contenedorRef = useRef<HTMLDivElement>(null);

  const cargar = useCallback(async () => {
    try {
      const data = await solicitarApi<ResumenAlertas>("/api/alertas/resumen");
      setResumen(data);
    } catch {
      // Silencioso en el header para no interrumpir la navegación
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  useEffect(() => {
    const alClickAfuera = (e: MouseEvent) => {
      if (
        contenedorRef.current &&
        !contenedorRef.current.contains(e.target as Node)
      ) {
        setAbierto(false);
      }
    };
    document.addEventListener("mousedown", alClickAfuera);
    return () => document.removeEventListener("mousedown", alClickAfuera);
  }, []);

  const totalCriticas = resumen?.contadores.total_criticas ?? 0;
  const totalPreventivas = resumen?.contadores.total_preventivas ?? 0;
  const totalAlertas = resumen?.contadores.total_alertas ?? 0;

  return (
    <div ref={contenedorRef} className="relative">
      <button
        type="button"
        onClick={() => {
          setAbierto((v) => !v);
          if (!abierto) void cargar();
        }}
        title="Centro de Alertas Inteligentes"
        className="relative inline-flex items-center justify-center rounded-xl border border-gray-200/80 bg-white/80 p-2 text-[#003566] hover:bg-[#EDF3FA] transition cursor-pointer"
      >
        <Bell className="h-4 w-4" />
        {totalAlertas > 0 && (
          <span
            className={`absolute -right-1 -top-1 flex min-w-[18px] h-[18px] items-center justify-center rounded-full px-1 text-[10px] font-black text-white shadow-xs ${
              totalCriticas > 0 ? "bg-red-600" : "bg-amber-500"
            }`}
          >
            {totalAlertas > 99 ? "99+" : totalAlertas}
          </span>
        )}
      </button>

      {abierto && (
        <div className="absolute right-0 mt-2 w-80 sm:w-96 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl z-50">
          <div className="flex items-center justify-between bg-[#003566] px-4 py-3 text-white">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-300" />
              <span className="text-xs font-bold">Alertas Inteligentes</span>
            </div>
            <div className="flex items-center gap-1.5 text-[10px] font-bold">
              {totalCriticas > 0 && (
                <span className="rounded-full bg-red-500 px-2 py-0.5">
                  {totalCriticas} críticas
                </span>
              )}
              {totalPreventivas > 0 && (
                <span className="rounded-full bg-amber-500 px-2 py-0.5">
                  {totalPreventivas} prev.
                </span>
              )}
            </div>
          </div>

          <div className="max-h-80 overflow-y-auto divide-y divide-slate-100">
            {!resumen || totalAlertas === 0 ? (
              <p className="p-6 text-center text-xs text-slate-500">
                Sin alertas críticas ni preventivas en este momento.
              </p>
            ) : (
              <>
                {(resumen.seguridad || []).map((seg) => (
                  <div
                    key={`seg-${seg.usuario_id}`}
                    className="p-3 bg-red-50/80 flex items-start justify-between gap-2"
                  >
                    <div className="space-y-0.5">
                      <div className="flex items-center gap-1.5 text-xs font-bold text-red-700">
                        <ShieldAlert className="h-3.5 w-3.5 shrink-0" />
                        <span>Acceso Bloqueado · {seg.nombre}</span>
                      </div>
                      <p className="text-[11px] text-red-600">
                        {seg.intentos_fallidos} intentos fallidos
                        {seg.fecha_bloqueo
                          ? ` · ${new Date(seg.fecha_bloqueo).toLocaleString("es-VE")}`
                          : ""}
                      </p>
                    </div>
                    {esAdmin && (
                      <button
                        type="button"
                        disabled={desbloqueandoId === seg.usuario_id}
                        onClick={async () => {
                          setDesbloqueandoId(seg.usuario_id);
                          try {
                            await solicitarApi(
                              `/api/personal/${seg.usuario_id}/desbloquear`,
                              { method: "POST", body: JSON.stringify({}) }
                            );
                            await cargar();
                          } finally {
                            setDesbloqueandoId(null);
                          }
                        }}
                        className="px-2 py-1 rounded-md bg-red-600 hover:bg-red-700 text-white text-[10px] font-bold shrink-0 cursor-pointer disabled:opacity-50"
                      >
                        {desbloqueandoId === seg.usuario_id ? "..." : "Desbloquear"}
                      </button>
                    )}
                  </div>
                ))}
                {resumen.cuentas_por_pagar.slice(0, 3).map((cxp) => (
                  <div
                    key={`cxp-${cxp.fuente}-${cxp.id}`}
                    className="flex items-start gap-2.5 px-4 py-2.5 hover:bg-slate-50"
                  >
                    <CalendarClock
                      className={`mt-0.5 h-4 w-4 shrink-0 ${
                        cxp.urgencia === "PROXIMA"
                          ? "text-amber-500"
                          : "text-red-600"
                      }`}
                    />
                    <div className="min-w-0 flex-1 text-xs">
                      <p className="font-bold text-slate-800 truncate">
                        CxP · {cxp.proveedor}
                      </p>
                      <p className="text-[11px] text-slate-500 truncate">
                        {cxp.concepto_o_referencia}
                      </p>
                      <p className="mt-0.5 text-[10px] font-bold text-red-600">
                        {cxp.urgencia === "VENCIDA"
                          ? `Vencida hace ${cxp.dias_diferencia} día(s)`
                          : cxp.urgencia === "VENCE_HOY"
                            ? "Vence HOY"
                            : `Vence en ${cxp.dias_diferencia} día(s)`}{" "}
                        · {formatearUsd(cxp.monto_pendiente_usd)}
                      </p>
                    </div>
                  </div>
                ))}

                {resumen.inventario.slice(0, 4).map((inv) => (
                  <div
                    key={`inv-${inv.articulo_id}-${inv.sucursal_id}`}
                    className="flex items-start gap-2.5 px-4 py-2.5 hover:bg-slate-50"
                  >
                    <Boxes
                      className={`mt-0.5 h-4 w-4 shrink-0 ${
                        inv.severidad === "AGOTADO"
                          ? "text-red-600"
                          : "text-amber-500"
                      }`}
                    />
                    <div className="min-w-0 flex-1 text-xs">
                      <p className="font-bold text-slate-800 truncate">
                        {inv.nombre}
                      </p>
                      <p className="text-[11px] text-slate-500">
                        {inv.almacen} · Disp:{" "}
                        <strong>{inv.stock_disponible}</strong> / Mín:{" "}
                        {inv.stock_minimo}
                        {inv.cantidad_en_transito > 0 && (
                          <span className="ml-1.5 rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-bold text-sky-800">
                            En tránsito ({inv.cantidad_en_transito})
                          </span>
                        )}
                      </p>
                    </div>
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold ${
                        inv.severidad === "AGOTADO"
                          ? "bg-red-100 text-red-700"
                          : "bg-amber-100 text-amber-800"
                      }`}
                    >
                      {inv.severidad}
                    </span>
                  </div>
                ))}
              </>
            )}
          </div>

          <div className="border-t border-slate-100 bg-slate-50 px-4 py-2.5 text-center">
            <Link
              href="/dashboard/direccion#centro-alertas"
              onClick={() => setAbierto(false)}
              className="inline-flex items-center gap-1.5 text-xs font-bold text-[#003566] hover:underline"
            >
              Ver Centro de Alertas completo
              <ExternalLink className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
