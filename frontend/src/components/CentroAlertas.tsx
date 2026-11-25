"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Boxes,
  CalendarClock,
  CheckCircle2,
  Loader2,
  MessageCircle,
  Settings,
  ShoppingBag,
  Truck,
  Wallet,
} from "lucide-react";
import type { ResumenAlertas } from "@/components/CampanaAlertas";
import { usarSesion } from "@/contexto/SesionContexto";
import {
  ErrorApi,
  esRolAdministrativo,
  formatearUsd,
  solicitarApi,
} from "@/servicios/api";

export default function CentroAlertas() {
  const { usuario } = usarSesion();
  const esAdmin = usuario ? esRolAdministrativo(usuario.rol) : false;
  const esDirector = usuario?.rol === "DIRECTOR";

  const [resumen, setResumen] = useState<ResumenAlertas | null>(null);
  const [cargando, setCargando] = useState(true);
  const [pestana, setPestana] = useState<"inventario" | "cxp">("inventario");
  const [filtroStock, setFiltroStock] = useState<"TODOS" | "AGOTADO" | "BAJO">(
    "TODOS"
  );
  const [mostrarConfig, setMostrarConfig] = useState(false);
  const [minGlobal, setMinGlobal] = useState("2");
  const [diasCxp, setDiasCxp] = useState("5");
  const [guardandoCfg, setGuardandoCfg] = useState(false);
  const [mensaje, setMensaje] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    if (!esAdmin && !esDirector) return;
    setCargando(true);
    try {
      const data = await solicitarApi<ResumenAlertas>("/api/alertas/resumen");
      setResumen(data);
      setMinGlobal(String(data.configuracion.stock_minimo_global));
      setDiasCxp(String(data.configuracion.dias_alerta_cxp));
    } catch {
      // Manejado silenciosamente si no aplica
    } finally {
      setCargando(false);
    }
  }, [esAdmin, esDirector]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  const inventarioFiltrado = useMemo(() => {
    if (!resumen) return [];
    if (filtroStock === "TODOS") return resumen.inventario;
    return resumen.inventario.filter((i) => i.severidad === filtroStock);
  }, [resumen, filtroStock]);

  if (!esAdmin && !esDirector) return null;

  const guardarConfiguracion = async (e: React.FormEvent) => {
    e.preventDefault();
    setGuardandoCfg(true);
    setMensaje(null);
    try {
      await solicitarApi("/api/alertas/configuracion", {
        method: "PATCH",
        body: JSON.stringify({
          stock_minimo_global: Number(minGlobal),
          dias_alerta_cxp: Number(diasCxp),
        }),
      });
      setMensaje("Umbrales de alerta actualizados correctamente.");
      setMostrarConfig(false);
      await cargar();
    } catch (err) {
      setMensaje(
        err instanceof ErrorApi ? err.message : "No se pudo actualizar la configuración."
      );
    } finally {
      setGuardandoCfg(false);
    }
  };

  const editarMinimoSku = async (sku: string, actual: number) => {
    const nuevoStr = window.prompt(
      `Nuevo stock mínimo para ${sku} (0 desactiva alertas para este SKU):`,
      String(actual)
    );
    if (nuevoStr === null) return;
    const nuevo = parseInt(nuevoStr, 10);
    if (Number.isNaN(nuevo) || nuevo < 0) return;
    try {
      await solicitarApi("/api/alertas/configuracion", {
        method: "PATCH",
        body: JSON.stringify({ sku, stock_minimo_sku: nuevo }),
      });
      setMensaje(`Stock mínimo de ${sku} actualizado a ${nuevo}.`);
      await cargar();
    } catch {
      // Ignorar
    }
  };

  const construirWhatsAppAlertas = (): string => {
    if (!resumen) return "";
    const sinTransito = resumen.inventario.filter(
      (i) => i.cantidad_en_transito === 0
    );
    const lineas: string[] = [
      `🚨 *RESUMEN DE ALERTAS · ALFA DIGITAL STORE*`,
      `📅 Fecha: ${resumen.fecha_evaluacion}`,
      `🔴 Críticas: ${resumen.contadores.total_criticas} | 🟡 Preventivas: ${resumen.contadores.total_preventivas}`,
      ``,
    ];

    if (sinTransito.length > 0) {
      lineas.push(`📦 *STOCK AGOTADO / BAJO (SIN TRÁNSITO):*`);
      sinTransito.slice(0, 15).forEach((i) => {
        const ico = i.severidad === "AGOTADO" ? "🔴" : "🟡";
        lineas.push(
          `${ico} ${i.nombre} (${i.sku}) · ${i.almacen}: Disp ${i.stock_disponible} (Mín ${i.stock_minimo})`
        );
      });
      lineas.push(``);
    }

    if (resumen.cuentas_por_pagar.length > 0) {
      lineas.push(
        `💳 *CUENTAS POR PAGAR (${formatearUsd(resumen.contadores.monto_total_cxp_alerta_usd)}):*`
      );
      resumen.cuentas_por_pagar.slice(0, 12).forEach((c) => {
        const tag =
          c.urgencia === "VENCIDA"
            ? `🔴 VENCIDA (${c.dias_diferencia}d)`
            : c.urgencia === "VENCE_HOY"
              ? `🔴 VENCE HOY`
              : `🟡 En ${c.dias_diferencia}d`;
        lineas.push(
          `${tag} · ${c.proveedor} — ${c.concepto_o_referencia}: ${formatearUsd(c.monto_pendiente_usd)}`
        );
      });
    }

    return lineas.join("\n");
  };

  return (
    <section
      id="centro-alertas"
      className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-xs"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-5 py-4">
        <div className="flex items-center gap-2.5">
          <AlertTriangle className="h-5 w-5 text-amber-600" />
          <div>
            <h2 className="text-base font-bold text-[#001D3D]">
              Centro de Alertas Inteligentes
            </h2>
            <p className="text-xs text-slate-500">
              {resumen
                ? `${resumen.contadores.total_criticas} críticas · ${resumen.contadores.total_preventivas} preventivas · CxP en alerta: ${formatearUsd(resumen.contadores.monto_total_cxp_alerta_usd)}`
                : "Evaluando stock disponible y vencimientos CxP..."}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {resumen && (
            <a
              href={`https://wa.me/?text=${encodeURIComponent(
                construirWhatsAppAlertas()
              )}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-3.5 py-2 text-xs font-bold text-white hover:bg-emerald-700"
            >
              <MessageCircle className="h-4 w-4" />
              Enviar resumen por WhatsApp
            </a>
          )}
          {esAdmin && (
            <button
              type="button"
              onClick={() => setMostrarConfig((v) => !v)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 cursor-pointer"
            >
              <Settings className="h-4 w-4 text-[#003566]" />
              Umbrales
            </button>
          )}
        </div>
      </div>

      {mensaje && (
        <div className="flex items-center gap-2 bg-emerald-50 border-b border-emerald-200 px-5 py-2.5 text-xs font-medium text-emerald-800">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{mensaje}</span>
        </div>
      )}

      {esAdmin && mostrarConfig && (
        <form
          onSubmit={guardarConfiguracion}
          className="flex flex-wrap items-end gap-4 border-b border-slate-200 bg-sky-50/60 px-5 py-4 text-xs"
        >
          <div>
            <label className="mb-1 block font-bold text-[#001D3D]">
              Stock mínimo global
            </label>
            <input
              type="number"
              min="0"
              max="500"
              value={minGlobal}
              onChange={(e) => setMinGlobal(e.target.value)}
              className="w-28 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block font-bold text-[#001D3D]">
              Días de anticipación CxP
            </label>
            <input
              type="number"
              min="1"
              max="90"
              value={diasCxp}
              onChange={(e) => setDiasCxp(e.target.value)}
              className="w-28 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={guardandoCfg}
            className="rounded-xl bg-[#003566] px-4 py-2 text-xs font-bold text-white hover:bg-[#001D3D] disabled:opacity-50"
          >
            {guardandoCfg ? "Guardando..." : "Guardar umbrales"}
          </button>
        </form>
      )}

      {/* Pestañas */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-5 py-3">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setPestana("inventario")}
            className={`inline-flex items-center gap-1.5 rounded-xl px-3.5 py-1.5 text-xs font-bold cursor-pointer ${
              pestana === "inventario"
                ? "bg-[#003566] text-white"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            <Boxes className="h-3.5 w-3.5" />
            Stock Bajo y Agotado ({resumen?.inventario.length ?? 0})
          </button>
          <button
            type="button"
            onClick={() => setPestana("cxp")}
            className={`inline-flex items-center gap-1.5 rounded-xl px-3.5 py-1.5 text-xs font-bold cursor-pointer ${
              pestana === "cxp"
                ? "bg-[#003566] text-white"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            <CalendarClock className="h-3.5 w-3.5" />
            Cuentas por Pagar ({resumen?.cuentas_por_pagar.length ?? 0})
          </button>
        </div>

        {pestana === "inventario" && (
          <div className="flex gap-1.5">
            {(["TODOS", "AGOTADO", "BAJO"] as const).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFiltroStock(f)}
                className={`rounded-lg px-2.5 py-1 text-[11px] font-bold cursor-pointer ${
                  filtroStock === f
                    ? "bg-slate-900 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {f === "TODOS" ? "Todos" : f === "AGOTADO" ? "Agotados" : "Stock Bajo"}
              </button>
            ))}
          </div>
        )}
      </div>

      {cargando ? (
        <div className="flex items-center justify-center gap-2 py-10 text-xs text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Analizando alertas...
        </div>
      ) : pestana === "inventario" ? (
        inventarioFiltrado.length === 0 ? (
          <p className="py-10 text-center text-xs text-slate-500">
            No hay productos agotados ni con stock bajo en este filtro.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="bg-slate-50 text-slate-500 uppercase">
                <tr>
                  <th className="px-4 py-2.5">SKU / Producto</th>
                  <th className="px-4 py-2.5">Almacén</th>
                  <th className="px-4 py-2.5 text-center">Disp. / Mín.</th>
                  <th className="px-4 py-2.5 text-center">Tránsito</th>
                  <th className="px-4 py-2.5">Estado</th>
                  {esAdmin && <th className="px-4 py-2.5 text-right">Acciones</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {inventarioFiltrado.slice(0, 30).map((it) => (
                  <tr key={`${it.articulo_id}-${it.sucursal_id}`} className="hover:bg-slate-50/70">
                    <td className="px-4 py-2.5">
                      <p className="font-semibold text-slate-800">{it.nombre}</p>
                      <p className="font-mono text-[10px] text-slate-500">
                        {it.sku} · {it.categoria}
                      </p>
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">{it.almacen}</td>
                    <td className="px-4 py-2.5 text-center cifra-tabular">
                      <strong
                        className={
                          it.stock_disponible === 0 ? "text-red-600" : "text-amber-700"
                        }
                      >
                        {it.stock_disponible}
                      </strong>{" "}
                      / {it.stock_minimo}
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      {it.cantidad_en_transito > 0 ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2 py-0.5 text-[10px] font-bold text-sky-800">
                          <Truck className="h-3 w-3" />
                          En tránsito ({it.cantidad_en_transito})
                        </span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                          it.severidad === "AGOTADO"
                            ? "bg-red-100 text-red-700"
                            : "bg-amber-100 text-amber-800"
                        }`}
                      >
                        {it.severidad === "AGOTADO" ? "AGOTADO" : "STOCK BAJO"}
                      </span>
                    </td>
                    {esAdmin && (
                      <td className="px-4 py-2.5 text-right space-x-1.5 whitespace-nowrap">
                        <button
                          type="button"
                          onClick={() => void editarMinimoSku(it.sku, it.stock_minimo)}
                          className="rounded-lg border border-slate-200 px-2 py-1 text-[11px] font-semibold text-slate-600 hover:bg-slate-100 cursor-pointer"
                        >
                          Mín.
                        </button>
                        <Link
                          href="/dashboard/logistica/compras"
                          className="inline-flex items-center gap-1 rounded-lg bg-[#EDF3FA] px-2 py-1 text-[11px] font-bold text-[#003566] hover:bg-sky-100"
                        >
                          <ShoppingBag className="h-3 w-3" />
                          Comprar
                        </Link>
                        <Link
                          href="/dashboard/logistica/traslados"
                          className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2 py-1 text-[11px] font-bold text-slate-700 hover:bg-slate-200"
                        >
                          <Truck className="h-3 w-3" />
                          Trasladar
                        </Link>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : resumen && resumen.cuentas_por_pagar.length === 0 ? (
        <p className="py-10 text-center text-xs text-slate-500">
          No hay cuentas por pagar vencidas ni próximas a vencer en los siguientes{" "}
          {resumen.configuracion.dias_alerta_cxp} días.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead className="bg-slate-50 text-slate-500 uppercase">
              <tr>
                <th className="px-4 py-2.5">Urgencia</th>
                <th className="px-4 py-2.5">Proveedor / Referencia</th>
                <th className="px-4 py-2.5">Vencimiento</th>
                <th className="px-4 py-2.5 text-right">Pendiente USD</th>
                {esAdmin && <th className="px-4 py-2.5 text-right">Acción</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(resumen?.cuentas_por_pagar || []).map((c) => (
                <tr key={`${c.fuente}-${c.id}`} className="hover:bg-slate-50/70">
                  <td className="px-4 py-2.5">
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold ${
                        c.urgencia === "PROXIMA"
                          ? "bg-amber-100 text-amber-800"
                          : "bg-red-100 text-red-700"
                      }`}
                    >
                      {c.urgencia === "VENCIDA"
                        ? `VENCIDA (${c.dias_diferencia}d)`
                        : c.urgencia === "VENCE_HOY"
                          ? "VENCE HOY"
                          : `EN ${c.dias_diferencia} DÍA(S)`}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <p className="font-semibold text-slate-800">{c.proveedor}</p>
                    <p className="text-[11px] text-slate-500">{c.concepto_o_referencia}</p>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-slate-700">
                    {c.fecha_vencimiento}
                  </td>
                  <td className="px-4 py-2.5 text-right font-bold text-red-700 cifra-tabular">
                    {formatearUsd(c.monto_pendiente_usd)}
                  </td>
                  {esAdmin && (
                    <td className="px-4 py-2.5 text-right">
                      <Link
                        href="/dashboard/finanzas/tesoreria"
                        className="inline-flex items-center gap-1 rounded-lg bg-[#003566] px-2.5 py-1 text-[11px] font-bold text-white hover:bg-[#001D3D]"
                      >
                        <Wallet className="h-3 w-3" />
                        Pagar
                      </Link>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
