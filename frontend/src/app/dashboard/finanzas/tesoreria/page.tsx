"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ArrowLeftRight,
  Ban,
  CheckCircle2,
  Loader2,
  Plus,
  TrendingDown,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { usarSesion } from "@/contexto/SesionContexto";
import {
  ErrorApi,
  esRolAdministrativo,
  formatearBs,
  formatearUsd,
  solicitarApi,
} from "@/servicios/api";

interface InstrumentoSaldo {
  id: number;
  nombre: string;
  moneda: "USD" | "USDT" | "BS";
  saldo_actual?: number;
}

type TipoTesoreria = "CAMBIO_DIVISA" | "TRASLADO" | "INGRESO_ADMIN" | "EGRESO_ADMIN";

interface MovimientoTesoreria {
  id: number;
  codigo: string;
  tipo: TipoTesoreria;
  fecha: string;
  estado: "CONFIRMADO" | "ANULADO";
  cuenta_origen_id: number | null;
  cuenta_origen_nombre: string | null;
  moneda_origen: string;
  monto_salida: number;
  cuenta_destino_id: number | null;
  cuenta_destino_nombre: string | null;
  moneda_destino: string;
  monto_entrada: number;
  comision_usd: number;
  tasa_referencia_tipo: "BCV" | "USDT";
  tasa_bcv_dia: number;
  tasa_usdt_dia: number;
  tasa_referencia_aplicada: number;
  tasa_operacion: number | null;
  equivalente_salida_usd: number;
  equivalente_entrada_usd: number;
  diferencial_usd: number;
  diferencial_porcentaje: number;
  resultado_tipo: "GANANCIA" | "PERDIDA" | "NEUTRO";
  concepto: string;
  referencia: string;
  observaciones: string;
  registrado_por: string;
  anulado_por: string | null;
  motivo_anulacion: string;
}

interface RespuestaTesoreria {
  resumen: {
    total_ganancia_usd: number;
    total_perdida_usd: number;
    resultado_neto_usd: number;
    cantidad_movimientos: number;
  };
  movimientos: MovimientoTesoreria[];
}

export default function PaginaTesoreria() {
  const { usuario, tasaHoy } = usarSesion();
  const esAdmin = usuario ? esRolAdministrativo(usuario.rol) : false;

  const [instrumentos, setInstrumentos] = useState<InstrumentoSaldo[]>([]);
  const [datos, setDatos] = useState<RespuestaTesoreria | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);

  // Filtros historial
  const [filtroTipo, setFiltroTipo] = useState("");
  const [filtroCuenta, setFiltroCuenta] = useState("");
  const [filtroInicio, setFiltroInicio] = useState("");
  const [filtroFin, setFiltroFin] = useState("");

  // Formulario nuevo movimiento
  const [mostrarForm, setMostrarForm] = useState(true);
  const [tipo, setTipo] = useState<TipoTesoreria>("CAMBIO_DIVISA");
  const [cuentaOrigenId, setCuentaOrigenId] = useState("");
  const [cuentaDestinoId, setCuentaDestinoId] = useState("");
  const [montoSalida, setMontoSalida] = useState("");
  const [montoEntrada, setMontoEntrada] = useState("");
  const [tasaOperacion, setTasaOperacion] = useState("");
  const [tasaRefTipo, setTasaRefTipo] = useState<"BCV" | "USDT">("BCV");
  const [comisionUsd, setComisionUsd] = useState("0");
  const [concepto, setConcepto] = useState("");
  const [referencia, setReferencia] = useState("");
  const [observaciones, setObservaciones] = useState("");
  const [guardando, setGuardando] = useState(false);

  const cargarTodo = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const qs = new URLSearchParams();
      if (filtroTipo) qs.set("tipo", filtroTipo);
      if (filtroCuenta) qs.set("cuenta_id", filtroCuenta);
      if (filtroInicio) qs.set("fecha_inicio", filtroInicio);
      if (filtroFin) qs.set("fecha_fin", filtroFin);
      const sufijo = qs.toString() ? `?${qs.toString()}` : "";

      const [respInst, respMovs] = await Promise.all([
        solicitarApi<InstrumentoSaldo[]>("/api/finanzas/instrumentos"),
        solicitarApi<RespuestaTesoreria>(`/api/tesoreria/movimientos${sufijo}`),
      ]);
      setInstrumentos(respInst);
      setDatos(respMovs);
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo cargar Tesorería."
      );
    } finally {
      setCargando(false);
    }
  }, [filtroTipo, filtroCuenta, filtroInicio, filtroFin]);

  useEffect(() => {
    void cargarTodo();
  }, [cargarTodo]);

  const cuentaOrigen = useMemo(
    () => instrumentos.find((i) => String(i.id) === cuentaOrigenId) || null,
    [instrumentos, cuentaOrigenId]
  );
  const cuentaDestino = useMemo(
    () => instrumentos.find((i) => String(i.id) === cuentaDestinoId) || null,
    [instrumentos, cuentaDestinoId]
  );

  const tasaRefDia = useMemo(() => {
    const bcv = Number(tasaHoy?.tasa_bcv || 0);
    const usdt = Number(tasaHoy?.tasa_usdt || 0);
    return tasaRefTipo === "USDT" ? (usdt > 0 ? usdt : bcv) : (bcv > 0 ? bcv : usdt);
  }, [tasaHoy, tasaRefTipo]);

  // Calculadora en vivo de diferencial cambiario
  const calculoVivo = useMemo(() => {
    if (tipo !== "CAMBIO_DIVISA" && tipo !== "TRASLADO") return null;
    if (!cuentaOrigen || !cuentaDestino) return null;

    const sal = parseFloat(montoSalida || "0") || 0;
    if (sal <= 0) return null;

    const tasaOpNum = parseFloat(tasaOperacion || "0") || 0;
    let ent = parseFloat(montoEntrada || "0") || 0;

    if (!montoEntrada.trim() && tasaOpNum > 0) {
      if (cuentaOrigen.moneda !== "BS" && cuentaDestino.moneda === "BS") {
        ent = sal * tasaOpNum;
      } else if (cuentaOrigen.moneda === "BS" && cuentaDestino.moneda !== "BS") {
        ent = sal / tasaOpNum;
      } else {
        ent = sal * tasaOpNum;
      }
    } else if (!montoEntrada.trim() && cuentaOrigen.moneda === cuentaDestino.moneda) {
      ent = sal;
    }

    if (ent <= 0) return null;

    const aUsd = (m: number, mon: string) =>
      mon === "BS" ? (tasaRefDia > 0 ? m / tasaRefDia : 0) : m;

    const eqSalida = aUsd(sal, cuentaOrigen.moneda);
    const eqEntrada = aUsd(ent, cuentaDestino.moneda);
    const comision = parseFloat(comisionUsd || "0") || 0;
    const diferencialUsd = eqEntrada - eqSalida - comision;
    const diferencialPct = eqSalida > 0 ? (diferencialUsd / eqSalida) * 100 : 0;

    let tasaEfectiva: number | null = null;
    if (cuentaOrigen.moneda !== "BS" && cuentaDestino.moneda === "BS") {
      tasaEfectiva = ent / sal;
    } else if (cuentaOrigen.moneda === "BS" && cuentaDestino.moneda !== "BS") {
      tasaEfectiva = sal / ent;
    }

    return {
      entCalculado: ent,
      eqSalida,
      eqEntrada,
      diferencialUsd,
      diferencialPct,
      tasaEfectiva,
      resultado:
        diferencialUsd > 0.004
          ? "GANANCIA"
          : diferencialUsd < -0.004
            ? "PERDIDA"
            : "NEUTRO",
    };
  }, [
    tipo,
    cuentaOrigen,
    cuentaDestino,
    montoSalida,
    montoEntrada,
    tasaOperacion,
    tasaRefDia,
    comisionUsd,
  ]);

  const manejarRegistrar = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setExito(null);
    setGuardando(true);
    try {
      const payload: Record<string, unknown> = {
        tipo,
        tasa_referencia_tipo: tasaRefTipo,
        comision_usd: parseFloat(comisionUsd || "0") || 0,
        concepto: concepto.trim(),
        referencia: referencia.trim(),
        observaciones: observaciones.trim(),
      };
      if (tipo === "CAMBIO_DIVISA" || tipo === "TRASLADO") {
        payload.cuenta_origen_id = Number(cuentaOrigenId);
        payload.cuenta_destino_id = Number(cuentaDestinoId);
        payload.monto_salida = parseFloat(montoSalida || "0") || 0;
        if (montoEntrada.trim()) {
          payload.monto_entrada = parseFloat(montoEntrada);
        }
        if (tasaOperacion.trim()) {
          payload.tasa_operacion = parseFloat(tasaOperacion);
        }
      } else if (tipo === "INGRESO_ADMIN") {
        payload.cuenta_destino_id = Number(cuentaDestinoId);
        payload.monto_entrada = parseFloat(montoEntrada || "0") || 0;
      } else if (tipo === "EGRESO_ADMIN") {
        payload.cuenta_origen_id = Number(cuentaOrigenId);
        payload.monto_salida = parseFloat(montoSalida || "0") || 0;
      }

      const creado = await solicitarApi<MovimientoTesoreria>("/api/tesoreria/movimientos", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setExito(
        `Movimiento ${creado.codigo} registrado. Saldos actualizados atómicamente.`
      );
      setMontoSalida("");
      setMontoEntrada("");
      setTasaOperacion("");
      setComisionUsd("0");
      setConcepto("");
      setReferencia("");
      setObservaciones("");
      await cargarTodo();
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo registrar el movimiento."
      );
    } finally {
      setGuardando(false);
    }
  };

  const manejarAnular = async (mov: MovimientoTesoreria) => {
    const motivo = window.prompt(
      `Motivo para anular el movimiento ${mov.codigo} (revertirá los saldos de las cuentas):`
    );
    if (!motivo || motivo.trim().length < 3) return;
    setError(null);
    setExito(null);
    try {
      await solicitarApi(`/api/tesoreria/movimientos/${mov.id}/anular`, {
        method: "POST",
        body: JSON.stringify({ motivo: motivo.trim() }),
      });
      setExito(`Movimiento ${mov.codigo} anulado y saldos revertidos.`);
      await cargarTodo();
    } catch (err) {
      setError(
        err instanceof ErrorApi ? err.message : "No se pudo anular el movimiento."
      );
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-[#001D3D]">
            <Wallet className="h-6 w-6 text-[#003566]" />
            Tesorería, Cambios y Diferencial Cambiario
          </h1>
          <p className="text-sm text-slate-600">
            Traslados entre cuentas, cambios de divisas con cálculo en vivo de ganancia/pérdida y movimientos administrativos.
          </p>
        </div>
        {esAdmin && (
          <button
            type="button"
            onClick={() => setMostrarForm((v) => !v)}
            className="inline-flex items-center gap-2 rounded-xl bg-[#003566] px-4 py-2 text-xs font-bold text-white hover:bg-[#001D3D]"
          >
            <Plus className="h-4 w-4" />
            {mostrarForm ? "Ocultar Formulario" : "Nuevo Movimiento"}
          </button>
        )}
      </div>

      {/* KPIs de Diferencial Cambiario */}
      {datos && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50/70 p-4">
            <div className="flex items-center justify-between text-xs font-semibold text-emerald-800">
              <span>Total Ganancia Cambiaria</span>
              <TrendingUp className="h-4 w-4" />
            </div>
            <p className="mt-1.5 text-2xl font-black text-emerald-700 cifra-tabular">
              +{formatearUsd(datos.resumen.total_ganancia_usd)}
            </p>
          </div>
          <div className="rounded-2xl border border-red-200 bg-red-50/70 p-4">
            <div className="flex items-center justify-between text-xs font-semibold text-red-800">
              <span>Total Pérdida Cambiaria</span>
              <TrendingDown className="h-4 w-4" />
            </div>
            <p className="mt-1.5 text-2xl font-black text-red-700 cifra-tabular">
              -{formatearUsd(datos.resumen.total_perdida_usd)}
            </p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-600">
              <span>Resultado Neto Cambiario</span>
              <ArrowLeftRight className="h-4 w-4 text-[#003566]" />
            </div>
            <p
              className={`mt-1.5 text-2xl font-black cifra-tabular ${
                datos.resumen.resultado_neto_usd > 0
                  ? "text-emerald-700"
                  : datos.resumen.resultado_neto_usd < 0
                    ? "text-red-700"
                    : "text-[#001D3D]"
              }`}
            >
              {datos.resumen.resultado_neto_usd >= 0 ? "+" : ""}
              {formatearUsd(datos.resumen.resultado_neto_usd)}
            </p>
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {exito && (
        <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{exito}</span>
        </div>
      )}

      {/* Formulario con Calculadora en Vivo (solo ADMIN) */}
      {esAdmin && mostrarForm && (
        <form
          onSubmit={manejarRegistrar}
          className="space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-xs"
        >
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
            <h2 className="text-base font-bold text-[#001D3D]">
              Registrar Movimiento de Tesorería
            </h2>
            <div className="flex flex-wrap gap-1.5">
              {(
                [
                  { id: "CAMBIO_DIVISA", label: "Cambio de Divisas" },
                  { id: "TRASLADO", label: "Traslado entre Cuentas" },
                  { id: "INGRESO_ADMIN", label: "Ingreso Admin" },
                  { id: "EGRESO_ADMIN", label: "Egreso Admin" },
                ] as const
              ).map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTipo(t.id)}
                  className={`rounded-xl px-3 py-1.5 text-xs font-bold transition cursor-pointer ${
                    tipo === t.id
                      ? "bg-[#003566] text-white"
                      : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {tipo !== "INGRESO_ADMIN" && (
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-700">
                  Cuenta de Origen *
                </label>
                <select
                  required
                  value={cuentaOrigenId}
                  onChange={(e) => setCuentaOrigenId(e.target.value)}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
                >
                  <option value="">Selecciona origen...</option>
                  {instrumentos.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.nombre} ({i.moneda}) — Saldo:{" "}
                      {i.moneda === "BS"
                        ? formatearBs(i.saldo_actual ?? 0)
                        : formatearUsd(i.saldo_actual ?? 0)}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {tipo !== "INGRESO_ADMIN" && (
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-700">
                  Monto de Salida ({cuentaOrigen?.moneda || "Moneda"}) *
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  required
                  value={montoSalida}
                  onChange={(e) => setMontoSalida(e.target.value)}
                  placeholder="0.00"
                  className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
                />
              </div>
            )}

            {tipo !== "EGRESO_ADMIN" && (
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-700">
                  Cuenta de Destino *
                </label>
                <select
                  required
                  value={cuentaDestinoId}
                  onChange={(e) => setCuentaDestinoId(e.target.value)}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
                >
                  <option value="">Selecciona destino...</option>
                  {instrumentos.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.nombre} ({i.moneda}) — Saldo:{" "}
                      {i.moneda === "BS"
                        ? formatearBs(i.saldo_actual ?? 0)
                        : formatearUsd(i.saldo_actual ?? 0)}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {(tipo === "CAMBIO_DIVISA" || tipo === "TRASLADO") && (
              <>
                <div>
                  <label className="mb-1 block text-xs font-semibold text-slate-700">
                    Tasa de Operación (opcional si escribes entrada)
                  </label>
                  <input
                    type="number"
                    step="0.0001"
                    min="0"
                    value={tasaOperacion}
                    onChange={(e) => setTasaOperacion(e.target.value)}
                    placeholder={tasaRefDia ? `Ref. hoy: ${tasaRefDia}` : "Ej. 52.50"}
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold text-slate-700">
                    Monto de Entrada ({cuentaDestino?.moneda || "Moneda"})
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={montoEntrada}
                    onChange={(e) => setMontoEntrada(e.target.value)}
                    placeholder={
                      calculoVivo
                        ? `Auto: ${calculoVivo.entCalculado.toFixed(2)}`
                        : "0.00"
                    }
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-700">
                      Tasa Ref. del Día
                    </label>
                    <select
                      value={tasaRefTipo}
                      onChange={(e) =>
                        setTasaRefTipo(e.target.value as "BCV" | "USDT")
                      }
                      className="w-full rounded-xl border border-slate-300 bg-white px-2.5 py-2 text-sm"
                    >
                      <option value="BCV">BCV ({tasaHoy?.tasa_bcv ?? "—"})</option>
                      <option value="USDT">USDT ({tasaHoy?.tasa_usdt ?? "—"})</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-700">
                      Comisión (USD)
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={comisionUsd}
                      onChange={(e) => setComisionUsd(e.target.value)}
                      className="w-full rounded-xl border border-slate-300 px-2.5 py-2 text-sm"
                    />
                  </div>
                </div>
              </>
            )}

            {tipo === "INGRESO_ADMIN" && (
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-700">
                  Monto de Entrada ({cuentaDestino?.moneda || "Moneda"}) *
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  required
                  value={montoEntrada}
                  onChange={(e) => setMontoEntrada(e.target.value)}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
                />
              </div>
            )}

            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-700">
                Concepto
              </label>
              <input
                type="text"
                value={concepto}
                onChange={(e) => setConcepto(e.target.value)}
                placeholder="Ej. Compra de efectivo USD / Traslado a Zelle"
                className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-700">
                Referencia
              </label>
              <input
                type="text"
                value={referencia}
                onChange={(e) => setReferencia(e.target.value)}
                placeholder="Nro. comprobante"
                className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-700">
                Observaciones
              </label>
              <input
                type="text"
                value={observaciones}
                onChange={(e) => setObservaciones(e.target.value)}
                placeholder="Notas internas..."
                className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
          </div>

          {/* Recuadro destacado en vivo del Diferencial Cambiario */}
          {calculoVivo && (
            <div
              className={`rounded-2xl border p-4 flex flex-wrap items-center justify-between gap-3 ${
                calculoVivo.resultado === "GANANCIA"
                  ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                  : calculoVivo.resultado === "PERDIDA"
                    ? "border-red-300 bg-red-50 text-red-900"
                    : "border-slate-200 bg-slate-50 text-slate-800"
              }`}
            >
              <div>
                <p className="text-sm font-black cifra-tabular">
                  {calculoVivo.resultado === "GANANCIA"
                    ? `Ganancia cambiaria: +${formatearUsd(calculoVivo.diferencialUsd)} (+${calculoVivo.diferencialPct.toFixed(2)}%)`
                    : calculoVivo.resultado === "PERDIDA"
                      ? `Pérdida cambiaria: -${formatearUsd(Math.abs(calculoVivo.diferencialUsd))} (${calculoVivo.diferencialPct.toFixed(2)}%)`
                      : "Operación neutra: $0.00 (0.00%)"}
                </p>
                <p className="text-xs opacity-80 mt-0.5">
                  Salida equiv.: {formatearUsd(calculoVivo.eqSalida)} · Entrada equiv.:{" "}
                  {formatearUsd(calculoVivo.eqEntrada)}
                </p>
              </div>
              <div className="text-right text-xs cifra-tabular">
                <p>
                  Tasa ref. {tasaRefTipo}: <strong>{tasaRefDia.toFixed(4)}</strong>
                </p>
                {calculoVivo.tasaEfectiva !== null && (
                  <p>
                    Tasa efectiva op.:{" "}
                    <strong>{calculoVivo.tasaEfectiva.toFixed(4)}</strong>
                  </p>
                )}
              </div>
            </div>
          )}

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={guardando}
              className="inline-flex items-center gap-2 rounded-xl bg-[#003566] px-6 py-2.5 text-sm font-bold text-white hover:bg-[#001D3D] disabled:opacity-50"
            >
              {guardando ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              Confirmar Movimiento
            </button>
          </div>
        </form>
      )}

      {/* Filtros + Historial */}
      <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-xs">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-5 py-3.5">
          <h2 className="text-sm font-bold text-[#001D3D]">
            Historial de Tesorería
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={filtroTipo}
              onChange={(e) => setFiltroTipo(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
            >
              <option value="">Todos los tipos</option>
              <option value="CAMBIO_DIVISA">Cambio de Divisa</option>
              <option value="TRASLADO">Traslado</option>
              <option value="INGRESO_ADMIN">Ingreso Admin</option>
              <option value="EGRESO_ADMIN">Egreso Admin</option>
            </select>
            <select
              value={filtroCuenta}
              onChange={(e) => setFiltroCuenta(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
            >
              <option value="">Todas las cuentas</option>
              {instrumentos.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.nombre}
                </option>
              ))}
            </select>
            <input
              type="date"
              value={filtroInicio}
              onChange={(e) => setFiltroInicio(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
            />
            <input
              type="date"
              value={filtroFin}
              onChange={(e) => setFiltroFin(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
            />
          </div>
        </div>

        {cargando ? (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Cargando movimientos...
          </div>
        ) : !datos || datos.movimientos.length === 0 ? (
          <div className="py-12 text-center text-sm text-slate-500">
            No hay movimientos de tesorería con los filtros seleccionados.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-xs">
              <thead className="bg-slate-50 text-left uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3">Código / Fecha</th>
                  <th className="px-4 py-3">Operación</th>
                  <th className="px-4 py-3">Salida → Entrada</th>
                  <th className="px-4 py-3 text-right">Diferencial USD</th>
                  <th className="px-4 py-3">Estado</th>
                  {esAdmin && <th className="px-4 py-3 text-right">Acción</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {datos.movimientos.map((m) => (
                  <tr
                    key={m.id}
                    className={m.estado === "ANULADO" ? "bg-slate-50 opacity-60" : ""}
                  >
                    <td className="px-4 py-3">
                      <div className="font-mono font-bold text-[#003566]">{m.codigo}</div>
                      <div className="text-[11px] text-slate-500">{m.fecha}</div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-semibold text-slate-800">{m.tipo}</div>
                      <div className="text-[11px] text-slate-500">{m.concepto}</div>
                    </td>
                    <td className="px-4 py-3 cifra-tabular">
                      {m.cuenta_origen_nombre && (
                        <div>
                          <span className="text-red-600 font-semibold">
                            -
                            {m.moneda_origen === "BS"
                              ? formatearBs(m.monto_salida)
                              : formatearUsd(m.monto_salida)}
                          </span>{" "}
                          <span className="text-slate-500">({m.cuenta_origen_nombre})</span>
                        </div>
                      )}
                      {m.cuenta_destino_nombre && (
                        <div>
                          <span className="text-emerald-700 font-semibold">
                            +
                            {m.moneda_destino === "BS"
                              ? formatearBs(m.monto_entrada)
                              : formatearUsd(m.monto_entrada)}
                          </span>{" "}
                          <span className="text-slate-500">({m.cuenta_destino_nombre})</span>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right cifra-tabular">
                      {m.resultado_tipo === "GANANCIA" ? (
                        <span className="inline-block rounded-full bg-emerald-100 px-2.5 py-0.5 font-bold text-emerald-800">
                          +{formatearUsd(m.diferencial_usd)} (+{m.diferencial_porcentaje.toFixed(2)}%)
                        </span>
                      ) : m.resultado_tipo === "PERDIDA" ? (
                        <span className="inline-block rounded-full bg-red-100 px-2.5 py-0.5 font-bold text-red-700">
                          -{formatearUsd(Math.abs(m.diferencial_usd))} ({m.diferencial_porcentaje.toFixed(2)}%)
                        </span>
                      ) : (
                        <span className="text-slate-500">$0.00</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                          m.estado === "ANULADO"
                            ? "bg-red-100 text-red-700"
                            : "bg-emerald-100 text-emerald-800"
                        }`}
                      >
                        {m.estado}
                      </span>
                    </td>
                    {esAdmin && (
                      <td className="px-4 py-3 text-right">
                        {m.estado === "CONFIRMADO" && (
                          <button
                            type="button"
                            onClick={() => void manejarAnular(m)}
                            className="inline-flex items-center gap-1 rounded-lg border border-red-200 px-2.5 py-1 text-[11px] font-semibold text-red-700 hover:bg-red-50"
                          >
                            <Ban className="h-3 w-3" />
                            Anular
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
