"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  Landmark,
  Loader2,
  Percent,
  Plus,
  Scale,
  TrendingUp,
} from "lucide-react";
import { usarSesion } from "@/contexto/SesionContexto";
import {
  ErrorApi,
  esRolAdministrativo,
  formatearUsd,
  solicitarApi,
} from "@/servicios/api";

type TabContab = "balance" | "pnl" | "rentabilidad" | "prestamos" | "diario";

interface BalanceGeneral {
  fecha_corte: string;
  activos: { total_usd: number; detalle: { codigo: string; nombre: string; saldo_usd: number }[] };
  pasivos: { total_usd: number; detalle: { codigo: string; nombre: string; saldo_usd: number }[] };
  patrimonio: { total_usd: number; detalle: { codigo: string; nombre: string; saldo_usd: number }[] };
  ecuacion_cuadrada: boolean;
}

interface EstadoResultadosContable {
  periodo: { fecha_inicio: string; fecha_fin: string };
  ingresos_usd: number;
  costo_ventas_usd: number;
  utilidad_bruta_usd: number;
  gastos_variables_usd: number;
  gastos_fijos_usd: number;
  gastos_financieros_usd: number;
  impuestos_usd: number;
  utilidad_neta_usd: number;
  cuentas: { codigo: string; nombre: string; tipo: string; monto_usd: number }[];
}

interface RentabilidadVentas {
  resumen: {
    total_ventas_usd: number;
    total_costos_reales_usd: number;
    total_comisiones_usd: number;
    utilidad_neta_total_usd: number;
    margen_neto_promedio_pct: number;
  };
  ventas: {
    venta_id: number;
    numero_venta: string;
    fecha: string;
    sucursal: string;
    asesor: string;
    origen_venta: string;
    precio_venta_usd: number;
    costo_base_usd: number;
    costo_flete_usd: number;
    costo_preparacion_usd: number;
    costo_total_real_usd: number;
    comision_usd: number;
    utilidad_neta_usd: number;
    margen_neto_pct: number;
  }[];
}

interface PrestamoItem {
  id: number;
  codigo: string;
  acreedor: string;
  concepto: string;
  fecha_desembolso: string;
  capital_original_usd: number;
  saldo_capital_usd: number;
  tasa_interes_mensual_pct: number;
  total_intereses_pagados_usd: number;
  estado: string;
}

interface PlanCuentaItem {
  id: number;
  codigo: string;
  nombre: string;
  tipo: string;
  naturaleza: string;
}

interface AsientoItem {
  id: number;
  fecha: string;
  descripcion: string;
  origen_tipo: string;
  estado: string;
  total_debe_usd: number;
  total_haber_usd: number;
  detalles: {
    id: number;
    cuenta_codigo: string;
    cuenta_nombre: string;
    debe_usd: number;
    haber_usd: number;
  }[];
}

interface InstrumentoSimple {
  id: number;
  nombre: string;
  moneda: string;
}

export default function PaginaContabilidad() {
  const { usuario } = usarSesion();
  const esAdmin = usuario ? esRolAdministrativo(usuario.rol) : false;

  const [tab, setTab] = useState<TabContab>("balance");
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);

  const [balance, setBalance] = useState<BalanceGeneral | null>(null);
  const [pnl, setPnl] = useState<EstadoResultadosContable | null>(null);
  const [rentab, setRentab] = useState<RentabilidadVentas | null>(null);
  const [prestamos, setPrestamos] = useState<PrestamoItem[]>([]);
  const [plan, setPlan] = useState<PlanCuentaItem[]>([]);
  const [asientos, setAsientos] = useState<AsientoItem[]>([]);
  const [instrumentos, setInstrumentos] = useState<InstrumentoSimple[]>([]);

  // Form nuevo préstamo
  const [acreedor, setAcreedor] = useState("");
  const [conceptoPrest, setConceptoPrest] = useState("");
  const [capitalUsd, setCapitalUsd] = useState("");
  const [tasaInteres, setTasaInteres] = useState("0");
  const [instPrestId, setInstPrestId] = useState("");
  const [guardando, setGuardando] = useState(false);

  const cargarTodo = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const [rBal, rPnl, rRen, rPre, rPlan, rAsi, rInst] = await Promise.all([
        solicitarApi<BalanceGeneral>("/api/contabilidad/balance-general"),
        solicitarApi<EstadoResultadosContable>("/api/contabilidad/estado-resultados"),
        solicitarApi<RentabilidadVentas>("/api/contabilidad/rentabilidad-ventas"),
        solicitarApi<PrestamoItem[]>("/api/contabilidad/prestamos"),
        solicitarApi<PlanCuentaItem[]>("/api/contabilidad/plan-cuentas"),
        solicitarApi<AsientoItem[]>("/api/contabilidad/asientos"),
        solicitarApi<InstrumentoSimple[]>("/api/finanzas/instrumentos"),
      ]);
      setBalance(rBal);
      setPnl(rPnl);
      setRentab(rRen);
      setPrestamos(rPre);
      setPlan(rPlan);
      setAsientos(rAsi);
      setInstrumentos(rInst);
      if (!instPrestId && rInst.length > 0) setInstPrestId(String(rInst[0].id));
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo cargar el módulo contable."
      );
    } finally {
      setCargando(false);
    }
  }, [instPrestId]);

  useEffect(() => {
    void cargarTodo();
  }, [cargarTodo]);

  const registrarPrestamo = async (e: React.FormEvent) => {
    e.preventDefault();
    setGuardando(true);
    setError(null);
    setExito(null);
    try {
      const res = await solicitarApi<{ codigo: string }>("/api/contabilidad/prestamos", {
        method: "POST",
        body: JSON.stringify({
          acreedor: acreedor.trim(),
          concepto: conceptoPrest.trim(),
          capital_usd: parseFloat(capitalUsd || "0"),
          tasa_interes_mensual_pct: parseFloat(tasaInteres || "0"),
          instrumento_ingreso_id: Number(instPrestId),
        }),
      });
      setExito(`Préstamo ${res.codigo} registrado con ingreso a caja y asiento contable.`);
      setAcreedor("");
      setConceptoPrest("");
      setCapitalUsd("");
      await cargarTodo();
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "Error al registrar préstamo.");
    } finally {
      setGuardando(false);
    }
  };

  const pagarCuotaPrestamo = async (p: PrestamoItem) => {
    if (!instrumentos.length) return;
    const capStr = window.prompt(
      `Monto a CAPITAL USD para ${p.codigo} (Saldo: $${p.saldo_capital_usd}):`,
      String(Math.min(100, p.saldo_capital_usd))
    );
    if (capStr === null) return;
    const intStr = window.prompt(`Monto de INTERESES USD para ${p.codigo}:`, "0");
    if (intStr === null) return;
    try {
      await solicitarApi(`/api/contabilidad/prestamos/${p.id}/pagar`, {
        method: "POST",
        body: JSON.stringify({
          monto_capital_usd: parseFloat(capStr || "0") || 0,
          monto_interes_usd: parseFloat(intStr || "0") || 0,
          instrumento_pago_id: instrumentos[0].id,
          referencia: `PAGO-${p.codigo}`,
        }),
      });
      setExito(`Pago de préstamo ${p.codigo} contabilizado (Capital 2.2.01 + Intereses 8.1.02).`);
      await cargarTodo();
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "Error al registrar pago.");
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-[#EDF3FA] px-3 py-1 text-[11px] font-bold uppercase tracking-wider text-[#003566]">
          <Scale className="h-3.5 w-3.5" />
          Motor Contable Integrado · Partida Doble
        </span>
        <h1 className="mt-1 text-2xl font-bold tracking-tight text-[#001D3D]">
          Contabilidad, Balance General y Rentabilidad Real
        </h1>
        <p className="text-xs text-slate-600">
          Plan de cuentas oficial Alfa, asientos automáticos, costeo real en preparación, préstamos y margen neto post-comisión.
        </p>
      </div>

      {/* Pestañas */}
      <div className="flex flex-wrap gap-1.5 border-b border-slate-200 pb-3">
        {(
          [
            { id: "balance", label: "Balance General", icono: <Scale className="h-4 w-4" /> },
            { id: "pnl", label: "Estado de Resultados", icono: <TrendingUp className="h-4 w-4" /> },
            { id: "rentabilidad", label: "Rentabilidad Real por Venta", icono: <Percent className="h-4 w-4" /> },
            { id: "prestamos", label: "Préstamos y Financiamientos", icono: <Landmark className="h-4 w-4" /> },
            { id: "diario", label: "Plan de Cuentas y Libro Diario", icono: <BookOpen className="h-4 w-4" /> },
          ] as const
        ).map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-bold transition cursor-pointer ${
              tab === t.id
                ? "bg-[#003566] text-white shadow-xs"
                : "bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
            }`}
          >
            {t.icono}
            {t.label}
          </button>
        ))}
      </div>

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

      {cargando ? (
        <div className="flex items-center justify-center gap-2 py-20 text-sm text-slate-500">
          <Loader2 className="h-5 w-5 animate-spin text-[#003566]" />
          Calculando estados financieros...
        </div>
      ) : (
        <>
          {/* 1. BALANCE GENERAL */}
          {tab === "balance" && balance && (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-xs">
                <div className="flex items-center justify-between bg-[#003566] px-5 py-3.5 text-white">
                  <span className="text-sm font-bold">ACTIVOS (Al {balance.fecha_corte})</span>
                  <span className="text-base font-black cifra-tabular">
                    {formatearUsd(balance.activos.total_usd)}
                  </span>
                </div>
                <div className="divide-y divide-slate-100 text-xs">
                  {balance.activos.detalle.map((a) => (
                    <div key={a.codigo} className="flex items-center justify-between px-5 py-3">
                      <span>
                        <strong className="font-mono text-[#003566]">{a.codigo}</strong> · {a.nombre}
                      </span>
                      <span className="font-bold text-[#001D3D] cifra-tabular">
                        {formatearUsd(a.saldo_usd)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="space-y-4">
                <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-xs">
                  <div className="flex items-center justify-between bg-red-700 px-5 py-3.5 text-white">
                    <span className="text-sm font-bold">PASIVOS</span>
                    <span className="text-base font-black cifra-tabular">
                      {formatearUsd(balance.pasivos.total_usd)}
                    </span>
                  </div>
                  <div className="divide-y divide-slate-100 text-xs">
                    {balance.pasivos.detalle.map((p) => (
                      <div key={p.codigo} className="flex items-center justify-between px-5 py-3">
                        <span>
                          <strong className="font-mono text-red-700">{p.codigo}</strong> · {p.nombre}
                        </span>
                        <span className="font-bold text-red-700 cifra-tabular">
                          {formatearUsd(p.saldo_usd)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-2xl border border-emerald-200 bg-emerald-50/70 p-5 flex items-center justify-between">
                  <div>
                    <p className="text-xs font-bold uppercase text-emerald-800">
                      PATRIMONIO NETO (Activo - Pasivo)
                    </p>
                    <p className="text-[11px] text-emerald-700">
                      Ecuación patrimonial cuadrada al día
                    </p>
                  </div>
                  <p className="text-2xl font-black text-emerald-800 cifra-tabular">
                    {formatearUsd(balance.patrimonio.total_usd)}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* 2. ESTADO DE RESULTADOS CONTABLE */}
          {tab === "pnl" && pnl && (
            <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-xs divide-y divide-slate-100 text-sm">
              {[
                { label: "4. Ingresos Operativos", val: pnl.ingresos_usd, bold: false },
                { label: "5. (-) Costo de Ventas (COGS)", val: -pnl.costo_ventas_usd, bold: false },
                { label: "= UTILIDAD BRUTA", val: pnl.utilidad_bruta_usd, bold: true },
                { label: "6. (-) Gastos Variables (Comisiones, Envíos, Garantías)", val: -pnl.gastos_variables_usd, bold: false },
                { label: "7. (-) Gastos Fijos (Sueldos, Alquiler, Condominio, Servicios)", val: -pnl.gastos_fijos_usd, bold: false },
                { label: "8. (-) Gastos Financieros / Intereses / Cambiario", val: -pnl.gastos_financieros_usd, bold: false },
                { label: "9. (-) Impuestos (SENIAT / Alcaldía)", val: -pnl.impuestos_usd, bold: false },
                { label: "= UTILIDAD NETA CONTABLE", val: pnl.utilidad_neta_usd, bold: true },
              ].map((r) => (
                <div
                  key={r.label}
                  className={`flex items-center justify-between px-5 py-3.5 ${
                    r.bold ? "bg-[#EDF3FA]/70 font-black text-[#001D3D]" : "text-slate-700"
                  }`}
                >
                  <span>{r.label}</span>
                  <span className={`cifra-tabular ${r.val < 0 ? "text-red-700" : "text-emerald-700"}`}>
                    {formatearUsd(r.val)}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* 3. RENTABILIDAD REAL POR VENTA */}
          {tab === "rentabilidad" && rentab && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div className="rounded-2xl border border-slate-200 bg-white p-4">
                  <p className="text-[11px] text-slate-500">Ventas Promo</p>
                  <p className="text-lg font-black text-[#001D3D]">{formatearUsd(rentab.resumen.total_ventas_usd)}</p>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white p-4">
                  <p className="text-[11px] text-slate-500">Costo Real (Base+Flete+Prep)</p>
                  <p className="text-lg font-black text-slate-700">{formatearUsd(rentab.resumen.total_costos_reales_usd)}</p>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white p-4">
                  <p className="text-[11px] text-slate-500">Comisiones</p>
                  <p className="text-lg font-black text-amber-700">-{formatearUsd(rentab.resumen.total_comisiones_usd)}</p>
                </div>
                <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
                  <p className="text-[11px] text-emerald-800">Utilidad Neta ({rentab.resumen.margen_neto_promedio_pct}%)</p>
                  <p className="text-lg font-black text-emerald-700">{formatearUsd(rentab.resumen.utilidad_neta_total_usd)}</p>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-50 text-slate-500 uppercase">
                    <tr>
                      <th className="px-4 py-3">Nota / Fecha</th>
                      <th className="px-4 py-3">Asesor / Origen</th>
                      <th className="px-4 py-3 text-right">Venta</th>
                      <th className="px-4 py-3 text-right">Base+Flete</th>
                      <th className="px-4 py-3 text-right">Prep.</th>
                      <th className="px-4 py-3 text-right">Comisión</th>
                      <th className="px-4 py-3 text-right">Utilidad Neta</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {rentab.ventas.map((v) => (
                      <tr key={v.venta_id}>
                        <td className="px-4 py-2.5 font-mono font-bold text-[#003566]">
                          {v.numero_venta} <span className="font-sans font-normal text-slate-500">· {v.fecha}</span>
                        </td>
                        <td className="px-4 py-2.5">{v.asesor} ({v.origen_venta})</td>
                        <td className="px-4 py-2.5 text-right font-bold">{formatearUsd(v.precio_venta_usd)}</td>
                        <td className="px-4 py-2.5 text-right text-slate-600">{formatearUsd(v.costo_base_usd + v.costo_flete_usd)}</td>
                        <td className="px-4 py-2.5 text-right text-sky-700">{formatearUsd(v.costo_preparacion_usd)}</td>
                        <td className="px-4 py-2.5 text-right text-amber-700">-{formatearUsd(v.comision_usd)}</td>
                        <td className="px-4 py-2.5 text-right font-black text-emerald-700">
                          {formatearUsd(v.utilidad_neta_usd)} ({v.margen_neto_pct}%)
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 4. PRÉSTAMOS Y FINANCIAMIENTOS */}
          {tab === "prestamos" && (
            <div className="space-y-5">
              {esAdmin && (
                <form
                  onSubmit={registrarPrestamo}
                  className="grid grid-cols-1 gap-3 rounded-2xl border border-slate-200 bg-white p-5 sm:grid-cols-5"
                >
                  <input
                    required
                    value={acreedor}
                    onChange={(e) => setAcreedor(e.target.value)}
                    placeholder="Acreedor / Banco / Socio *"
                    className="rounded-xl border border-slate-300 px-3 py-2 text-xs"
                  />
                  <input
                    value={conceptoPrest}
                    onChange={(e) => setConceptoPrest(e.target.value)}
                    placeholder="Concepto"
                    className="rounded-xl border border-slate-300 px-3 py-2 text-xs"
                  />
                  <input
                    required
                    type="number"
                    step="0.01"
                    min="1"
                    value={capitalUsd}
                    onChange={(e) => setCapitalUsd(e.target.value)}
                    placeholder="Capital USD *"
                    className="rounded-xl border border-slate-300 px-3 py-2 text-xs"
                  />
                  <select
                    value={instPrestId}
                    onChange={(e) => setInstPrestId(e.target.value)}
                    className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs"
                  >
                    {instrumentos.map((i) => (
                      <option key={i.id} value={i.id}>
                        Entra en: {i.nombre}
                      </option>
                    ))}
                  </select>
                  <button
                    type="submit"
                    disabled={guardando}
                    className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-[#003566] px-4 py-2 text-xs font-bold text-white hover:bg-[#001D3D] cursor-pointer"
                  >
                    <Plus className="h-4 w-4" />
                    Registrar Préstamo
                  </button>
                </form>
              )}

              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-50 text-slate-500 uppercase">
                    <tr>
                      <th className="px-4 py-3">Código / Acreedor</th>
                      <th className="px-4 py-3 text-right">Capital Orig.</th>
                      <th className="px-4 py-3 text-right">Saldo Capital</th>
                      <th className="px-4 py-3 text-right">Intereses Pag.</th>
                      <th className="px-4 py-3">Estado</th>
                      {esAdmin && <th className="px-4 py-3 text-right">Acción</th>}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {prestamos.map((p) => (
                      <tr key={p.id}>
                        <td className="px-4 py-3">
                          <span className="font-mono font-bold text-[#003566]">{p.codigo}</span> · {p.acreedor}
                        </td>
                        <td className="px-4 py-3 text-right">{formatearUsd(p.capital_original_usd)}</td>
                        <td className="px-4 py-3 text-right font-bold text-red-700">{formatearUsd(p.saldo_capital_usd)}</td>
                        <td className="px-4 py-3 text-right text-amber-700">{formatearUsd(p.total_intereses_pagados_usd)}</td>
                        <td className="px-4 py-3">
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${p.estado === "PAGADO" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>
                            {p.estado}
                          </span>
                        </td>
                        {esAdmin && (
                          <td className="px-4 py-3 text-right">
                            {p.estado === "ACTIVO" && (
                              <button
                                type="button"
                                onClick={() => void pagarCuotaPrestamo(p)}
                                className="rounded-lg bg-[#003566] px-2.5 py-1 text-[11px] font-bold text-white cursor-pointer"
                              >
                                Pagar Cuota
                              </button>
                            )}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 5. PLAN DE CUENTAS Y LIBRO DIARIO */}
          {tab === "diario" && (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
                <div className="bg-slate-50 px-5 py-3 border-b border-slate-200 text-sm font-bold text-[#001D3D]">
                  Plan de Cuentas Oficial Alfa ({plan.length})
                </div>
                <div className="max-h-[520px] overflow-y-auto divide-y divide-slate-100 text-xs">
                  {plan.map((c) => (
                    <div key={c.id} className="flex items-center justify-between px-4 py-2.5">
                      <div>
                        <span className="font-mono font-bold text-[#003566]">{c.codigo}</span>{" "}
                        <span className="text-slate-800">{c.nombre}</span>
                      </div>
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-600">
                        {c.tipo}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
                <div className="bg-slate-50 px-5 py-3 border-b border-slate-200 text-sm font-bold text-[#001D3D]">
                  Libro Diario · Últimos Asientos ({asientos.length})
                </div>
                <div className="max-h-[520px] overflow-y-auto divide-y divide-slate-100 text-xs">
                  {asientos.map((a) => (
                    <div key={a.id} className="p-4 space-y-1.5">
                      <div className="flex items-center justify-between font-bold text-[#001D3D]">
                        <span>#{a.id} · {a.descripcion}</span>
                        <span className="font-mono text-[11px] text-slate-500">{a.fecha}</span>
                      </div>
                      {a.detalles.map((d) => (
                        <div key={d.id} className="flex items-center justify-between text-[11px] text-slate-600 pl-2">
                          <span>{d.cuenta_codigo} {d.cuenta_nombre}</span>
                          <span className="font-mono">
                            {d.debe_usd > 0 ? `D: ${formatearUsd(d.debe_usd)}` : `H: ${formatearUsd(d.haber_usd)}`}
                          </span>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
