"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Copy,
  CreditCard,
  Plus,
  Search,
  Trash2,
  Wallet,
  X,
} from "lucide-react";
import { copiarTextoPortapapeles } from "@/lib/whatsapp";
import { ErrorApi, formatearUsd, solicitarApi } from "@/servicios/api";
import type { CuentaPorCobrarResumen, InstrumentoFinanciero } from "@/tipos/finanzas";

interface TasaHoyResp {
  tasa_bcv: number;
  tasa_usdt: number;
  fecha: string;
}

interface LineaMultipago {
  id: string;
  instrumento_id: string;
  monto: string;
  referencia: string;
}

interface RespuestaAbonoMultipago {
  id: number;
  venta_id: number | null;
  saldo_pendiente_usd: number;
  total_abonado_usd: number;
  estado: string;
  liquidada: boolean;
  pagos_registrados: Array<{
    instrumento_id: number;
    instrumento: string;
    moneda: string;
    monto_moneda_origen: number;
    usd_nominal: number;
    referencia: string;
  }>;
}

interface Props {
  alActualizarConteo?: (pendientes: number) => void;
  alRegistrarCobro?: () => void;
}

export default function PanelApartadosCobros({
  alActualizarConteo,
  alRegistrarCobro,
}: Props) {
  const [cuentas, setCuentas] = useState<CuentaPorCobrarResumen[]>([]);
  const [instrumentos, setInstrumentos] = useState<InstrumentoFinanciero[]>([]);
  const [tasaBcv, setTasaBcv] = useState<number>(0);
  const [busqueda, setBusqueda] = useState("");
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);
  const [reciboWhatsapp, setReciboWhatsapp] = useState<string | null>(null);

  // Estado modal multipagos
  const [cxcActiva, setCxcActiva] = useState<CuentaPorCobrarResumen | null>(null);
  const [lineas, setLineas] = useState<LineaMultipago[]>([]);
  const [guardando, setGuardando] = useState(false);

  const instrumentosValidos = useMemo(
    () =>
      instrumentos.filter((i) => {
        const nom = (i.nombre || "").toLowerCase();
        return !nom.includes("cuenta por cobrar") && !nom.includes("cashea");
      }),
    [instrumentos]
  );

  const cargarDatos = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const [respCxc, respInst, respTasa] = await Promise.all([
        solicitarApi<CuentaPorCobrarResumen[]>(
          "/api/finanzas/cuentas-por-cobrar?tipo=CLIENTE&estado=PENDIENTE"
        ),
        solicitarApi<InstrumentoFinanciero[]>("/api/finanzas/instrumentos"),
        solicitarApi<TasaHoyResp | null>("/api/tasas/hoy").catch(() => null),
      ]);
      setCuentas(respCxc);
      setInstrumentos(respInst);
      setTasaBcv(respTasa?.tasa_bcv || 0);
      alActualizarConteo?.(respCxc.length);
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudieron cargar los apartados y cuentas por cobrar."
      );
    } finally {
      setCargando(false);
    }
  }, [alActualizarConteo]);

  useEffect(() => {
    void cargarDatos();
  }, [cargarDatos]);

  const abrirModalAbono = (c: CuentaPorCobrarResumen) => {
    setError(null);
    setExito(null);
    setReciboWhatsapp(null);
    setCxcActiva(c);
    const defaultInst = instrumentosValidos[0]?.id
      ? String(instrumentosValidos[0].id)
      : "";
    setLineas([
      {
        id: `p-${Date.now()}-1`,
        instrumento_id: defaultInst,
        monto: "",
        referencia: "",
      },
    ]);
  };

  const agregarMetodoPago = () => {
    const defaultInst = instrumentosValidos[0]?.id
      ? String(instrumentosValidos[0].id)
      : "";
    setLineas((prev) => [
      ...prev,
      {
        id: `p-${Date.now()}-${prev.length + 1}`,
        instrumento_id: defaultInst,
        monto: "",
        referencia: "",
      },
    ]);
  };

  const eliminarLinea = (id: string) => {
    setLineas((prev) => (prev.length > 1 ? prev.filter((l) => l.id !== id) : prev));
  };

  const actualizarLinea = (
    id: string,
    campo: keyof Omit<LineaMultipago, "id">,
    valor: string
  ) => {
    setLineas((prev) =>
      prev.map((l) => (l.id === id ? { ...l, [campo]: valor } : l))
    );
  };

  const calcularUsdLinea = useCallback(
    (l: LineaMultipago): number => {
      const m = parseFloat(l.monto);
      if (!Number.isFinite(m) || m <= 0) return 0;
      const inst = instrumentosValidos.find((i) => String(i.id) === l.instrumento_id);
      if (!inst) return 0;
      if (inst.moneda === "BS") {
        return tasaBcv > 0 ? Math.round((m / tasaBcv) * 100) / 100 : 0;
      }
      return Math.round(m * 100) / 100;
    },
    [instrumentosValidos, tasaBcv]
  );

  const totalAbonoUsd = useMemo(
    () =>
      Math.round(
        lineas.reduce((acc, l) => acc + calcularUsdLinea(l), 0) * 100
      ) / 100,
    [lineas, calcularUsdLinea]
  );

  const saldoRestantePreview = useMemo(() => {
    if (!cxcActiva) return 0;
    return Math.max(
      0,
      Math.round((cxcActiva.saldo_pendiente_usd - totalAbonoUsd) * 100) / 100
    );
  }, [cxcActiva, totalAbonoUsd]);

  const completarRestanteEnLinea = (id: string) => {
    if (!cxcActiva) return;
    const otrosUsd = lineas
      .filter((l) => l.id !== id)
      .reduce((acc, l) => acc + calcularUsdLinea(l), 0);
    const faltaUsd = Math.max(
      0,
      Math.round((cxcActiva.saldo_pendiente_usd - otrosUsd) * 100) / 100
    );
    const linea = lineas.find((l) => l.id === id);
    if (!linea) return;
    const inst = instrumentosValidos.find(
      (i) => String(i.id) === linea.instrumento_id
    );
    if (!inst) return;
    if (inst.moneda === "BS") {
      if (tasaBcv <= 0) return;
      const montoBs = Math.round(faltaUsd * tasaBcv * 100) / 100;
      actualizarLinea(id, "monto", montoBs.toFixed(2));
    } else {
      actualizarLinea(id, "monto", faltaUsd.toFixed(2));
    }
  };

  const enviarAbono = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!cxcActiva) return;
    setError(null);
    setExito(null);

    const pagosPayload = lineas
      .map((l) => ({
        instrumento_id: Number(l.instrumento_id),
        monto_moneda_origen: parseFloat(l.monto),
        referencia: l.referencia.trim(),
      }))
      .filter((p) => p.instrumento_id > 0 && Number.isFinite(p.monto_moneda_origen) && p.monto_moneda_origen > 0);

    if (pagosPayload.length === 0) {
      setError("Ingresa al menos un método de pago con monto mayor a cero.");
      return;
    }

    setGuardando(true);
    try {
      const resp = await solicitarApi<RespuestaAbonoMultipago>(
        `/api/finanzas/cuentas-por-cobrar/${cxcActiva.id}/abono`,
        {
          method: "POST",
          body: JSON.stringify({ pagos: pagosPayload }),
        }
      );

      const detalleMetodos = resp.pagos_registrados
        .map(
          (p) =>
            `• ${p.instrumento}: ${
              p.moneda === "BS"
                ? `Bs ${p.monto_moneda_origen.toFixed(2)} (≈ $${p.usd_nominal.toFixed(2)})`
                : `$${p.monto_moneda_origen.toFixed(2)}`
            }${p.referencia ? ` · Ref: ${p.referencia}` : ""}`
        )
        .join("\n");

      const estadoTxt = resp.liquidada
        ? "✅ *NOTA CANCELADA EN SU TOTALIDAD (Saldo $0.00)*"
        : `⏳ *Saldo restante por cobrar:* $${resp.saldo_pendiente_usd.toFixed(2)}`;

      const textoWa = [
        "🧾 *RECIBO DE ABONO / CANCELACIÓN — ALFA IMPORTACIONES*",
        `📄 *Nota:* ${cxcActiva.numero_venta || `#${cxcActiva.id}`}`,
        `👤 *Cliente:* ${cxcActiva.cliente}`,
        `🏪 *Sucursal:* ${cxcActiva.sucursal || "Tienda"}`,
        "",
        "💳 *Detalle del pago recibido:*",
        detalleMetodos,
        "",
        `💵 *Total abonado hoy:* $${resp.total_abonado_usd.toFixed(2)}`,
        estadoTxt,
      ].join("\n");

      setReciboWhatsapp(textoWa);
      setExito(
        resp.liquidada
          ? `¡Nota ${cxcActiva.numero_venta || `#${cxcActiva.id}`} cancelada al 100%! El cobro quedó registrado en caja.`
          : `Abono de ${formatearUsd(resp.total_abonado_usd)} registrado. Saldo restante: ${formatearUsd(resp.saldo_pendiente_usd)}.`
      );
      setCxcActiva(null);
      setLineas([]);
      await cargarDatos();
      alRegistrarCobro?.();
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo registrar el abono."
      );
    } finally {
      setGuardando(false);
    }
  };

  const cuentasFiltradas = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    if (!q) return cuentas;
    return cuentas.filter((c) =>
      [c.numero_venta || "", c.cliente || "", c.sucursal || "", c.fecha_venta || ""]
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  }, [cuentas, busqueda]);

  const totalPorCobrar = useMemo(
    () => cuentas.reduce((acc, c) => acc + Number(c.saldo_pendiente_usd || 0), 0),
    [cuentas]
  );

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="bg-white rounded-2xl border border-slate-200 p-4 flex items-center gap-3.5">
          <div className="w-11 h-11 rounded-xl bg-amber-50 border border-amber-200 flex items-center justify-center text-amber-700">
            <Wallet className="w-5 h-5" />
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-slate-500">
              Notas Apartadas / Pendientes
            </p>
            <p className="text-2xl font-black text-slate-900">{cuentas.length}</p>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-4 flex items-center gap-3.5">
          <div className="w-11 h-11 rounded-xl bg-blue-50 border border-blue-200 flex items-center justify-center text-[#003566]">
            <CreditCard className="w-5 h-5" />
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-slate-500">
              Total Pendiente por Cobrar
            </p>
            <p className="text-2xl font-black text-[#003566]">
              {formatearUsd(totalPorCobrar)}
            </p>
          </div>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2.5 p-4 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {exito && (
        <div className="flex flex-wrap items-center justify-between gap-3 p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-sm text-emerald-800">
          <div className="flex items-center gap-2.5">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span className="font-semibold">{exito}</span>
          </div>
          {reciboWhatsapp && (
            <button
              type="button"
              onClick={async () => {
                await copiarTextoPortapapeles(reciboWhatsapp);
                setExito("Recibo de abono copiado al portapapeles para WhatsApp.");
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold"
            >
              <Copy className="w-3.5 h-3.5" />
              Copiar Recibo WhatsApp
            </button>
          )}
        </div>
      )}

      <div className="bg-white rounded-2xl border border-slate-200 p-4">
        <div className="relative">
          <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar apartado por N° de nota, cliente o sucursal..."
            className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#003566]/30 focus:border-[#003566]"
          />
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
        {cargando ? (
          <div className="p-6 space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-12 rounded-xl bg-slate-100 animate-pulse" />
            ))}
          </div>
        ) : cuentasFiltradas.length === 0 ? (
          <div className="p-10 text-center space-y-2">
            <Wallet className="w-10 h-10 text-slate-300 mx-auto" />
            <p className="text-sm font-semibold text-slate-600">
              {busqueda
                ? "No hay apartados pendientes que coincidan con tu búsqueda."
                : "No hay equipos apartados ni cuentas por cobrar pendientes."}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-slate-50 border-b border-slate-200 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3">Nota</th>
                  <th className="px-4 py-3">Fecha / Sucursal</th>
                  <th className="px-4 py-3">Cliente</th>
                  <th className="px-4 py-3 text-right">Monto CxC Inicial</th>
                  <th className="px-4 py-3 text-right">Saldo Pendiente</th>
                  <th className="px-4 py-3 text-right">Acción</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {cuentasFiltradas.map((c) => (
                  <tr key={c.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-mono font-bold text-slate-900">
                      {c.numero_venta || `CXC-${c.id}`}
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-medium text-slate-800">{c.fecha_venta || "—"}</p>
                      <p className="text-xs text-slate-500">{c.sucursal || "—"}</p>
                    </td>
                    <td className="px-4 py-3 font-semibold text-slate-800">
                      {c.cliente}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-slate-600">
                      {formatearUsd(c.monto_original_usd)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono font-black text-[#003566]">
                      {formatearUsd(c.saldo_pendiente_usd)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => abrirModalAbono(c)}
                        className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-[#003566] hover:bg-[#001D3D] text-white text-xs font-bold transition"
                      >
                        <CreditCard className="w-3.5 h-3.5" />
                        Registrar Abono / Cancelar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal de Abono / Liquidación con Multipagos */}
      {cxcActiva && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
              <div>
                <h3 className="text-lg font-black text-slate-900">
                  Registrar Abono / Cancelación (Multipagos)
                </h3>
                <p className="text-xs text-slate-500">
                  Nota {cxcActiva.numero_venta || `#${cxcActiva.id}`} · {cxcActiva.cliente}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setCxcActiva(null)}
                className="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={enviarAbono} className="p-6 space-y-5">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 bg-[#F6F6F6] rounded-xl p-4 border border-slate-200">
                <div>
                  <p className="text-[11px] font-bold uppercase text-slate-500">
                    Saldo Pendiente Actual
                  </p>
                  <p className="text-xl font-black text-slate-900">
                    {formatearUsd(cxcActiva.saldo_pendiente_usd)}
                  </p>
                  {tasaBcv > 0 && (
                    <p className="text-[11px] text-slate-500">
                      ≈ Bs {(cxcActiva.saldo_pendiente_usd * tasaBcv).toFixed(2)} (BCV {tasaBcv})
                    </p>
                  )}
                </div>
                <div>
                  <p className="text-[11px] font-bold uppercase text-slate-500">
                    Total Abono Hoy
                  </p>
                  <p className="text-xl font-black text-[#003566]">
                    {formatearUsd(totalAbonoUsd)}
                  </p>
                </div>
                <div>
                  <p className="text-[11px] font-bold uppercase text-slate-500">
                    Nuevo Saldo Restante
                  </p>
                  <p
                    className={`text-xl font-black ${
                      saldoRestantePreview <= 0.5 ? "text-emerald-600" : "text-slate-800"
                    }`}
                  >
                    {formatearUsd(saldoRestantePreview <= 0.5 ? 0 : saldoRestantePreview)}
                  </p>
                  {totalAbonoUsd > 0 && saldoRestantePreview <= 0.5 && (
                    <span className="inline-block mt-0.5 text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">
                      100% CANCELADA
                    </span>
                  )}
                </div>
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-bold uppercase tracking-wide text-slate-600">
                    Métodos de pago ({lineas.length})
                  </p>
                  <button
                    type="button"
                    onClick={agregarMetodoPago}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-[#003566] text-[#003566] hover:bg-blue-50 text-xs font-bold"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Agregar otro método de pago
                  </button>
                </div>

                {lineas.map((l, idx) => {
                  const inst = instrumentosValidos.find(
                    (i) => String(i.id) === l.instrumento_id
                  );
                  const usdEq = calcularUsdLinea(l);
                  return (
                    <div
                      key={l.id}
                      className="p-3.5 rounded-xl border border-slate-200 bg-white space-y-3"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-slate-600">
                          Pago #{idx + 1}
                        </span>
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => completarRestanteEnLinea(l.id)}
                            className="text-[11px] font-bold text-[#003566] hover:underline"
                          >
                            Completar saldo restante
                          </button>
                          {lineas.length > 1 && (
                            <button
                              type="button"
                              onClick={() => eliminarLinea(l.id)}
                              className="p-1 rounded text-slate-400 hover:text-red-600"
                              title="Eliminar método"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div>
                          <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                            Instrumento
                          </label>
                          <select
                            value={l.instrumento_id}
                            onChange={(e) =>
                              actualizarLinea(l.id, "instrumento_id", e.target.value)
                            }
                            required
                            className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm bg-white"
                          >
                            {instrumentosValidos.map((i) => (
                              <option key={i.id} value={String(i.id)}>
                                {i.nombre} ({i.moneda})
                              </option>
                            ))}
                          </select>
                        </div>

                        <div>
                          <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                            Monto ({inst?.moneda || "USD"})
                          </label>
                          <input
                            type="number"
                            step="0.01"
                            min="0.01"
                            required
                            value={l.monto}
                            onChange={(e) => actualizarLinea(l.id, "monto", e.target.value)}
                            placeholder="0.00"
                            className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm font-mono"
                          />
                          {inst?.moneda === "BS" && usdEq > 0 && (
                            <p className="text-[11px] text-emerald-700 font-semibold mt-0.5">
                              Equivale a {formatearUsd(usdEq)}
                            </p>
                          )}
                        </div>

                        <div>
                          <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                            Referencia
                          </label>
                          <input
                            type="text"
                            value={l.referencia}
                            onChange={(e) =>
                              actualizarLinea(l.id, "referencia", e.target.value)
                            }
                            placeholder="Últimos 4-6 dígitos o Efectivo"
                            className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm"
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="flex items-center justify-end gap-3 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setCxcActiva(null)}
                  className="px-4 py-2.5 rounded-xl border border-slate-200 text-sm font-semibold text-slate-600 hover:bg-slate-50"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={guardando || totalAbonoUsd <= 0}
                  className="px-5 py-2.5 rounded-xl bg-[#003566] hover:bg-[#001D3D] disabled:opacity-50 text-white text-sm font-bold"
                >
                  {guardando
                    ? "Registrando cobro..."
                    : saldoRestantePreview <= 0.5 && totalAbonoUsd > 0
                      ? "Confirmar Cancelación Total"
                      : "Confirmar Abono"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
