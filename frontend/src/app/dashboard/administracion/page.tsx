"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  BarChart3,
  Briefcase,
  Building2,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  FileText,
  Landmark,
  Loader2,
  Receipt,
  ShieldCheck,
  Users,
  Wallet,
} from "lucide-react";
import ModalCargaMasiva, {
  descargarPlantillaLogistica,
  type TipoCargaMasiva,
} from "@/components/ModalCargaMasiva";
import TarjetaRespaldoBD from "@/components/TarjetaRespaldoBD";
import { usarSesion } from "@/contexto/SesionContexto";
import {
  ErrorApi,
  esRolAdministrativo,
  formatearBs,
  formatearUsd,
  obtenerToken,
  solicitarApi,
} from "@/servicios/api";

type TabAdmin =
  | "pnl"
  | "fiscal"
  | "gastos"
  | "nomina"
  | "conciliacion"
  | "activos"
  | "auditoria";

const URL_BASE_API =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ||
  process.env.NEXT_PUBLIC_URL_API_PYTHON?.replace(/\/+$/, "") ||
  "http://localhost:8000";

async function descargarArchivoAuth(ruta: string, nombreArchivo: string) {
  const token = obtenerToken();
  const res = await fetch(`${URL_BASE_API}${ruta}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("No se pudo descargar el documento.");
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nombreArchivo;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

interface EstadoResultados {
  periodo: { fecha_inicio: string; fecha_fin: string };
  ingresos_ventas_usd: number;
  costo_ventas_usd: number;
  utilidad_bruta_usd: number;
  gastos_operativos_usd: number;
  nomina_usd: number;
  comisiones_pagadas_usd: number;
  impuestos_parafiscales_usd: number;
  resultado_cambiario_usd: number;
  utilidad_neta_operativa_usd: number;
}

interface LibrosIva {
  resumen: {
    debito_fiscal_bs: number;
    credito_fiscal_bs: number;
    cuota_tributaria_bs: number;
    facturas_compras: number;
    facturas_ventas: number;
  };
}

interface RetencionItem {
  id: number;
  numero_comprobante: string;
  tipo: string;
  rif_sujeto: string;
  razon_social: string;
  fecha_emision: string;
  porcentaje_retencion: number;
  monto_retenido_bs: number;
  monto_retenido_usd: number;
}

interface ObligacionItem {
  id: number;
  organismo: string;
  tipo_obligacion: string;
  periodo: string;
  fecha_vencimiento: string;
  monto_estimado_usd: number;
  monto_pagado_usd: number;
  estado: string;
}

interface GastoItem {
  id: number;
  rif_proveedor: string;
  razon_social: string;
  numero_factura: string;
  fecha_emision: string;
  fecha_vencimiento: string | null;
  categoria: string;
  es_deducible: boolean;
  monto_total_bs: number;
  monto_total_usd: number;
  saldo_pendiente_usd: number;
  estado: string;
}

interface NominaItem {
  id: number;
  codigo: string;
  tipo_periodo: string;
  fecha_inicio: string;
  fecha_fin: string;
  total_neto_usd: number;
  estado: string;
  detalles: {
    id: number;
    nombre_trabajador: string;
    cargo: string;
    neto_pagar_usd: number;
    neto_pagar_bs: number;
  }[];
}

interface ActivoItem {
  id: number;
  codigo_activo: string;
  descripcion: string;
  categoria: string;
  sucursal: string;
  costo_usd: number;
  depreciacion_mensual_usd: number;
  depreciacion_acumulada_usd: number;
  valor_libros_usd: number;
  estado: string;
}

interface ContratoItem {
  id: number;
  tipo: string;
  proveedor_contraparte: string;
  descripcion: string;
  fecha_vencimiento: string;
  canon_mensual_usd: number;
  dias_para_vencer: number;
  alerta_vencimiento: boolean;
}

interface AuditItem {
  id: number;
  usuario_nombre: string;
  rol: string;
  fecha_hora: string | null;
  modulo: string;
  accion: string;
  entidad_id: string;
  datos_nuevos: Record<string, unknown>;
}

interface InstrumentoSimple {
  id: number;
  nombre: string;
  moneda: string;
}

export default function PaginaAdministracionFinanzas() {
  const { usuario } = usarSesion();
  const esAdmin = usuario ? esRolAdministrativo(usuario.rol) : false;

  const [tab, setTab] = useState<TabAdmin>("pnl");
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exito, setExito] = useState<string | null>(null);

  const [pnl, setPnl] = useState<EstadoResultados | null>(null);
  const [libros, setLibros] = useState<LibrosIva | null>(null);
  const [retenciones, setRetenciones] = useState<RetencionItem[]>([]);
  const [obligaciones, setObligaciones] = useState<ObligacionItem[]>([]);
  const [gastos, setGastos] = useState<GastoItem[]>([]);
  const [nominas, setNominas] = useState<NominaItem[]>([]);
  const [activos, setActivos] = useState<ActivoItem[]>([]);
  const [contratos, setContratos] = useState<ContratoItem[]>([]);
  const [auditoria, setAuditoria] = useState<AuditItem[]>([]);
  const [instrumentos, setInstrumentos] = useState<InstrumentoSimple[]>([]);

  // Modal carga masiva reutilizable
  const [modalMasivo, setModalMasivo] = useState<{
    tipo: TipoCargaMasiva;
    titulo: string;
  } | null>(null);

  const cargarTodo = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const [
        rPnl,
        rLib,
        rRet,
        rOb,
        rGas,
        rNom,
        rAct,
        rCon,
        rAud,
        rInst,
      ] = await Promise.all([
        solicitarApi<EstadoResultados>("/api/admin/estado-resultados"),
        solicitarApi<LibrosIva>("/api/admin/fiscal/libros"),
        solicitarApi<RetencionItem[]>("/api/admin/fiscal/retenciones"),
        solicitarApi<ObligacionItem[]>("/api/admin/fiscal/obligaciones"),
        solicitarApi<GastoItem[]>("/api/admin/gastos"),
        solicitarApi<NominaItem[]>("/api/admin/nominas"),
        solicitarApi<ActivoItem[]>("/api/admin/activos"),
        solicitarApi<ContratoItem[]>("/api/admin/contratos"),
        solicitarApi<AuditItem[]>("/api/admin/auditoria"),
        solicitarApi<InstrumentoSimple[]>("/api/finanzas/instrumentos"),
      ]);
      setPnl(rPnl);
      setLibros(rLib);
      setRetenciones(rRet);
      setObligaciones(rOb);
      setGastos(rGas);
      setNominas(rNom);
      setActivos(rAct);
      setContratos(rCon);
      setAuditoria(rAud);
      setInstrumentos(rInst);
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo cargar el Departamento de Administración y Finanzas."
      );
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void cargarTodo();
  }, [cargarTodo]);

  const pagarObligacionRapido = async (ob: ObligacionItem) => {
    if (!instrumentos.length) return;
    const ref = window.prompt(
      `Referencia de pago para ${ob.organismo} - ${ob.tipo_obligacion} ($${ob.monto_estimado_usd}):`,
      "TRF-SENIAT"
    );
    if (ref === null) return;
    try {
      await solicitarApi(`/api/admin/fiscal/obligaciones/${ob.id}/pagar`, {
        method: "POST",
        body: JSON.stringify({
          instrumento_pago_id: instrumentos[0].id,
          monto_pagado_usd: ob.monto_estimado_usd || 1,
          referencia_pago: ref,
        }),
      });
      setExito(`Obligación ${ob.tipo_obligacion} marcada como PAGADA y descontada de caja.`);
      await cargarTodo();
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "Error al pagar obligación.");
    }
  };

  const pagarGastoRapido = async (g: GastoItem) => {
    if (!instrumentos.length) return;
    const ref = window.prompt(
      `Referencia de pago para ${g.razon_social} (Saldo: $${g.saldo_pendiente_usd}):`,
      g.numero_factura || "PAGO-GASTO"
    );
    if (ref === null) return;
    try {
      await solicitarApi(`/api/admin/gastos/${g.id}/pagar`, {
        method: "POST",
        body: JSON.stringify({
          instrumento_pago_id: instrumentos[0].id,
          monto_usd: g.saldo_pendiente_usd,
          referencia: ref,
        }),
      });
      setExito(`Factura de ${g.razon_social} pagada y descontada de caja.`);
      await cargarTodo();
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "Error al pagar gasto.");
    }
  };

  const pagarNominaRapido = async (n: NominaItem) => {
    if (!instrumentos.length) return;
    const ref = window.prompt(
      `Referencia de pago para Nómina ${n.codigo} ($${n.total_neto_usd}):`,
      n.codigo
    );
    if (ref === null) return;
    try {
      await solicitarApi(`/api/admin/nominas/${n.id}/pagar`, {
        method: "POST",
        body: JSON.stringify({
          instrumento_pago_id: instrumentos[0].id,
          referencia_pago: ref,
        }),
      });
      setExito(`Nómina ${n.codigo} pagada y registrada en egresos.`);
      await cargarTodo();
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "Error al pagar nómina.");
    }
  };

  const tabs: { id: TabAdmin; label: string; icono: React.ReactNode }[] = [
    { id: "pnl", label: "Resumen Gerencial (P&L)", icono: <BarChart3 className="h-4 w-4" /> },
    { id: "fiscal", label: "Fiscal y Tributario", icono: <Landmark className="h-4 w-4" /> },
    { id: "gastos", label: "Gastos, Servicios y CxP", icono: <Receipt className="h-4 w-4" /> },
    { id: "nomina", label: "Nómina y Parafiscales", icono: <Users className="h-4 w-4" /> },
    { id: "conciliacion", label: "Tesorería y Conciliación", icono: <Wallet className="h-4 w-4" /> },
    { id: "activos", label: "Activos Fijos y Contratos", icono: <Building2 className="h-4 w-4" /> },
    { id: "auditoria", label: "Auditoría", icono: <ShieldCheck className="h-4 w-4" /> },
  ];

  const abrirMasivo = (tipo: TipoCargaMasiva, titulo: string) =>
    setModalMasivo({ tipo, titulo });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-[#EDF3FA] px-3 py-1 text-[11px] font-bold uppercase tracking-wider text-[#003566]">
            <Briefcase className="h-3.5 w-3.5" />
            Departamento de Administración y Finanzas · Venezuela
          </span>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-[#001D3D]">
            Gestión Fiscal, Laboral, Contable y Auditoría
          </h1>
          <p className="text-xs text-slate-600">
            SENIAT, Alcaldía, LOTTT, Conciliación Bancaria, Activos Fijos, P&amp;L y Bitácora Inmutable.
          </p>
        </div>
      </div>

      {/* Respaldo de Base de Datos (solo visible para ADMIN) */}
      {esAdmin && <TarjetaRespaldoBD />}

      {/* Pestañas */}
      <div className="flex flex-wrap gap-1.5 border-b border-slate-200 pb-3">
        {tabs.map((t) => (
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
          Cargando información administrativa y fiscal...
        </div>
      ) : (
        <>
          {/* TAB 1: P&L */}
          {tab === "pnl" && pnl && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-slate-600">
                  Periodo: <strong>{pnl.periodo.fecha_inicio}</strong> al{" "}
                  <strong>{pnl.periodo.fecha_fin}</strong>
                </p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      void descargarArchivoAuth(
                        "/api/admin/estado-resultados/excel",
                        "estado_resultados_alfa.xlsx"
                      )
                    }
                    className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 cursor-pointer"
                  >
                    <FileSpreadsheet className="h-4 w-4 text-emerald-700" />
                    Exportar Excel
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      void descargarArchivoAuth(
                        "/api/admin/estado-resultados/pdf",
                        "estado_resultados_alfa.pdf"
                      )
                    }
                    className="inline-flex items-center gap-1.5 rounded-xl bg-[#003566] px-3.5 py-2 text-xs font-bold text-white hover:bg-[#001D3D] cursor-pointer"
                  >
                    <FileText className="h-4 w-4" />
                    Exportar PDF
                  </button>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-xs divide-y divide-slate-100 text-sm">
                {[
                  { label: "Ingresos por Ventas", val: pnl.ingresos_ventas_usd, bold: false },
                  { label: "(-) Costo de Ventas (COGS)", val: -pnl.costo_ventas_usd, bold: false },
                  { label: "= Utilidad Bruta", val: pnl.utilidad_bruta_usd, bold: true },
                  { label: "(-) Gastos Operativos", val: -pnl.gastos_operativos_usd, bold: false },
                  { label: "(-) Nómina Pagada", val: -pnl.nomina_usd, bold: false },
                  { label: "(-) Comisiones Pagadas", val: -pnl.comisiones_pagadas_usd, bold: false },
                  { label: "(-) Impuestos y Parafiscales", val: -pnl.impuestos_parafiscales_usd, bold: false },
                  { label: "(+/-) Resultado Cambiario (Tesorería)", val: pnl.resultado_cambiario_usd, bold: false },
                  { label: "= UTILIDAD NETA OPERATIVA", val: pnl.utilidad_neta_operativa_usd, bold: true },
                ].map((r) => (
                  <div
                    key={r.label}
                    className={`flex items-center justify-between px-5 py-3.5 ${
                      r.bold ? "bg-[#EDF3FA]/60 font-black text-[#001D3D]" : "text-slate-700"
                    }`}
                  >
                    <span>{r.label}</span>
                    <span
                      className={`cifra-tabular ${
                        r.val < 0 ? "text-red-700" : "text-emerald-700"
                      }`}
                    >
                      {formatearUsd(r.val)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* TAB 2: FISCAL Y TRIBUTARIO */}
          {tab === "fiscal" && libros && (
            <div className="space-y-5">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div className="rounded-2xl border border-slate-200 bg-white p-4">
                  <p className="text-xs text-slate-500">Débito Fiscal (Ventas IVA)</p>
                  <p className="mt-1 text-xl font-black text-[#001D3D]">
                    {formatearBs(libros.resumen.debito_fiscal_bs)}
                  </p>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white p-4">
                  <p className="text-xs text-slate-500">Crédito Fiscal (Compras IVA)</p>
                  <p className="mt-1 text-xl font-black text-emerald-700">
                    {formatearBs(libros.resumen.credito_fiscal_bs)}
                  </p>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white p-4">
                  <p className="text-xs text-slate-500">Cuota Tributaria Neta</p>
                  <p className="mt-1 text-xl font-black text-[#003566]">
                    {formatearBs(libros.resumen.cuota_tributaria_bs)}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() =>
                    void descargarArchivoAuth(
                      "/api/admin/fiscal/libros/excel?tipo=COMPRAS",
                      "libro_compras_iva.xlsx"
                    )
                  }
                  className="inline-flex items-center gap-1.5 rounded-xl bg-[#003566] px-4 py-2 text-xs font-bold text-white cursor-pointer"
                >
                  <Download className="h-4 w-4" />
                  Libro de Compras (.xlsx)
                </button>
                <button
                  type="button"
                  onClick={() =>
                    void descargarArchivoAuth(
                      "/api/admin/fiscal/libros/excel?tipo=VENTAS",
                      "libro_ventas_iva.xlsx"
                    )
                  }
                  className="inline-flex items-center gap-1.5 rounded-xl bg-[#003566] px-4 py-2 text-xs font-bold text-white cursor-pointer"
                >
                  <Download className="h-4 w-4" />
                  Libro de Ventas (.xlsx)
                </button>
                {esAdmin && (
                  <>
                    <button
                      type="button"
                      onClick={() =>
                        void descargarPlantillaLogistica(
                          "OBLIGACIONES_FISCALES",
                          "/api/admin"
                        )
                      }
                      className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 cursor-pointer"
                    >
                      <Download className="h-4 w-4 text-[#003566]" />
                      Descargar Plantilla (.xlsx)
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        abrirMasivo(
                          "OBLIGACIONES_FISCALES",
                          "Carga Masiva — Calendario Fiscal y Municipal"
                        )
                      }
                      className="inline-flex items-center gap-1.5 rounded-xl bg-sky-50 border border-[#003566]/30 px-3.5 py-2 text-xs font-bold text-[#003566] cursor-pointer"
                    >
                      <FileSpreadsheet className="h-4 w-4" />
                      Carga Masiva Obligaciones
                    </button>
                  </>
                )}
              </div>

              {/* Calendario de Obligaciones */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
                <div className="bg-slate-50 px-5 py-3 border-b border-slate-200 text-sm font-bold text-[#001D3D]">
                  Calendario de Obligaciones (SENIAT · Alcaldía · Parafiscales · Permisología)
                </div>
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-50/70 text-slate-500 uppercase">
                    <tr>
                      <th className="px-4 py-2.5">Organismo</th>
                      <th className="px-4 py-2.5">Obligación</th>
                      <th className="px-4 py-2.5">Vencimiento</th>
                      <th className="px-4 py-2.5 text-right">Monto USD</th>
                      <th className="px-4 py-2.5">Estado</th>
                      {esAdmin && <th className="px-4 py-2.5 text-right">Acción</th>}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {obligaciones.map((o) => (
                      <tr key={o.id}>
                        <td className="px-4 py-2.5 font-bold text-[#003566]">{o.organismo}</td>
                        <td className="px-4 py-2.5">{o.tipo_obligacion} {o.periodo ? `(${o.periodo})` : ""}</td>
                        <td className="px-4 py-2.5 font-mono">{o.fecha_vencimiento}</td>
                        <td className="px-4 py-2.5 text-right font-bold">{formatearUsd(o.monto_estimado_usd)}</td>
                        <td className="px-4 py-2.5">
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${o.estado === "PAGADA" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>
                            {o.estado}
                          </span>
                        </td>
                        {esAdmin && (
                          <td className="px-4 py-2.5 text-right">
                            {o.estado !== "PAGADA" && (
                              <button
                                type="button"
                                onClick={() => void pagarObligacionRapido(o)}
                                className="rounded-lg bg-[#003566] px-2.5 py-1 text-[11px] font-bold text-white cursor-pointer"
                              >
                                Marcar Pagada
                              </button>
                            )}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Retenciones */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
                <div className="bg-slate-50 px-5 py-3 border-b border-slate-200 text-sm font-bold text-[#001D3D]">
                  Comprobantes de Retención (IVA / ISLR)
                </div>
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-50/70 text-slate-500 uppercase">
                    <tr>
                      <th className="px-4 py-2.5">Comprobante</th>
                      <th className="px-4 py-2.5">Tipo</th>
                      <th className="px-4 py-2.5">Sujeto Retenido</th>
                      <th className="px-4 py-2.5 text-right">Retenido Bs</th>
                      <th className="px-4 py-2.5 text-right">PDF</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {retenciones.map((r) => (
                      <tr key={r.id}>
                        <td className="px-4 py-2.5 font-mono font-bold text-[#003566]">{r.numero_comprobante}</td>
                        <td className="px-4 py-2.5 font-bold">{r.tipo} ({r.porcentaje_retencion}%)</td>
                        <td className="px-4 py-2.5">{r.razon_social} ({r.rif_sujeto})</td>
                        <td className="px-4 py-2.5 text-right font-bold">{formatearBs(r.monto_retenido_bs)}</td>
                        <td className="px-4 py-2.5 text-right">
                          <button
                            type="button"
                            onClick={() =>
                              void descargarArchivoAuth(
                                `/api/admin/fiscal/retenciones/${r.id}/pdf`,
                                `retencion_${r.numero_comprobante}.pdf`
                              )
                            }
                            className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-2.5 py-1 text-[11px] font-bold text-[#003566] cursor-pointer"
                          >
                            <FileText className="h-3.5 w-3.5" /> PDF
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 3: GASTOS Y CXP */}
          {tab === "gastos" && (
            <div className="space-y-4">
              {esAdmin && (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      void descargarPlantillaLogistica(
                        "FACTURAS_GASTOS_CXP",
                        "/api/admin"
                      )
                    }
                    className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 cursor-pointer"
                  >
                    <Download className="h-4 w-4 text-[#003566]" />
                    Descargar Plantilla (.xlsx)
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      abrirMasivo(
                        "FACTURAS_GASTOS_CXP",
                        "Carga Masiva — Facturas de Gastos y CxP"
                      )
                    }
                    className="inline-flex items-center gap-1.5 rounded-xl bg-sky-50 border border-[#003566]/30 px-3.5 py-2 text-xs font-bold text-[#003566] cursor-pointer"
                  >
                    <FileSpreadsheet className="h-4 w-4" />
                    Carga Masiva Facturas
                  </button>
                </div>
              )}

              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-50 text-slate-500 uppercase">
                    <tr>
                      <th className="px-4 py-3">Proveedor / Factura</th>
                      <th className="px-4 py-3">Categoría</th>
                      <th className="px-4 py-3">Emisión / Venc.</th>
                      <th className="px-4 py-3 text-right">Total USD</th>
                      <th className="px-4 py-3 text-right">Pendiente</th>
                      <th className="px-4 py-3">Estado</th>
                      {esAdmin && <th className="px-4 py-3 text-right">Acción</th>}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {gastos.map((g) => (
                      <tr key={g.id}>
                        <td className="px-4 py-2.5">
                          <div className="font-bold text-slate-800">{g.razon_social}</div>
                          <div className="text-[11px] text-slate-500">{g.rif_proveedor} · {g.numero_factura || "Sin factura"}</div>
                        </td>
                        <td className="px-4 py-2.5">{g.categoria}</td>
                        <td className="px-4 py-2.5 font-mono text-[11px]">{g.fecha_emision} / {g.fecha_vencimiento || "—"}</td>
                        <td className="px-4 py-2.5 text-right font-bold">{formatearUsd(g.monto_total_usd)}</td>
                        <td className="px-4 py-2.5 text-right font-bold text-red-700">{formatearUsd(g.saldo_pendiente_usd)}</td>
                        <td className="px-4 py-2.5">
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${g.estado === "PAGADA" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>
                            {g.estado}
                          </span>
                        </td>
                        {esAdmin && (
                          <td className="px-4 py-2.5 text-right">
                            {g.estado !== "PAGADA" && (
                              <button
                                type="button"
                                onClick={() => void pagarGastoRapido(g)}
                                className="rounded-lg bg-[#003566] px-2.5 py-1 text-[11px] font-bold text-white cursor-pointer"
                              >
                                Pagar
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

          {/* TAB 4: NÓMINA Y PARAFISCALES */}
          {tab === "nomina" && (
            <div className="space-y-4">
              {esAdmin && (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      void descargarPlantillaLogistica(
                        "NOMINA_PERSONAL",
                        "/api/admin"
                      )
                    }
                    className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 cursor-pointer"
                  >
                    <Download className="h-4 w-4 text-[#003566]" />
                    Descargar Plantilla (.xlsx)
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      abrirMasivo(
                        "NOMINA_PERSONAL",
                        "Carga Masiva — Datos Laborales y Salarios"
                      )
                    }
                    className="inline-flex items-center gap-1.5 rounded-xl bg-sky-50 border border-[#003566]/30 px-3.5 py-2 text-xs font-bold text-[#003566] cursor-pointer"
                  >
                    <FileSpreadsheet className="h-4 w-4" />
                    Carga Masiva Nómina
                  </button>
                </div>
              )}

              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-50 text-slate-500 uppercase">
                    <tr>
                      <th className="px-4 py-3">Código</th>
                      <th className="px-4 py-3">Periodo</th>
                      <th className="px-4 py-3 text-right">Neto USD</th>
                      <th className="px-4 py-3">Estado</th>
                      <th className="px-4 py-3 text-right">Recibos / Pago</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {nominas.map((n) => (
                      <tr key={n.id}>
                        <td className="px-4 py-3 font-mono font-bold text-[#003566]">{n.codigo}</td>
                        <td className="px-4 py-3">{n.tipo_periodo} · {n.fecha_inicio} al {n.fecha_fin}</td>
                        <td className="px-4 py-3 text-right font-bold">{formatearUsd(n.total_neto_usd)}</td>
                        <td className="px-4 py-3">
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${n.estado === "PAGADA" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>
                            {n.estado}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right space-x-1.5">
                          {n.detalles[0] && (
                            <button
                              type="button"
                              onClick={() =>
                                void descargarArchivoAuth(
                                  `/api/admin/nominas/${n.id}/recibo/${n.detalles[0].id}/pdf`,
                                  `recibo_${n.codigo}.pdf`
                                )
                              }
                              className="rounded-lg border border-slate-300 px-2.5 py-1 text-[11px] font-bold text-slate-700 cursor-pointer"
                            >
                              Recibo PDF
                            </button>
                          )}
                          {esAdmin && n.estado !== "PAGADA" && (
                            <button
                              type="button"
                              onClick={() => void pagarNominaRapido(n)}
                              className="rounded-lg bg-[#003566] px-2.5 py-1 text-[11px] font-bold text-white cursor-pointer"
                            >
                              Pagar Nómina
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 5: TESORERÍA Y CONCILIACIÓN */}
          {tab === "conciliacion" && (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <Link
                  href="/dashboard/finanzas/tesoreria"
                  className="inline-flex items-center gap-1.5 rounded-xl bg-[#003566] px-4 py-2 text-xs font-bold text-white"
                >
                  <Wallet className="h-4 w-4" />
                  Ir a Cambios y Traslados de Tesorería
                </Link>
                {esAdmin && (
                  <>
                    <button
                      type="button"
                      onClick={() =>
                        void descargarPlantillaLogistica(
                          "EXTRACTO_BANCARIO",
                          "/api/admin"
                        )
                      }
                      className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 cursor-pointer"
                    >
                      <Download className="h-4 w-4 text-[#003566]" />
                      Descargar Plantilla Extracto (.xlsx)
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        abrirMasivo(
                          "EXTRACTO_BANCARIO",
                          "Carga Masiva — Extracto Bancario para Conciliación"
                        )
                      }
                      className="inline-flex items-center gap-1.5 rounded-xl bg-sky-50 border border-[#003566]/30 px-3.5 py-2 text-xs font-bold text-[#003566] cursor-pointer"
                    >
                      <FileSpreadsheet className="h-4 w-4" />
                      Carga Masiva Extracto
                    </button>
                  </>
                )}
              </div>
              <div className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-600">
                Usa <strong>Carga Masiva Extracto</strong> para subir el estado de cuenta bancario (.xlsx/.csv) y cruzarlo automáticamente contra los movimientos registrados en libros.
              </div>
            </div>
          )}

          {/* TAB 6: ACTIVOS FIJOS Y CONTRATOS */}
          {tab === "activos" && (
            <div className="space-y-5">
              {esAdmin && (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      void descargarPlantillaLogistica("ACTIVOS_FIJOS", "/api/admin")
                    }
                    className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 cursor-pointer"
                  >
                    <Download className="h-4 w-4 text-[#003566]" />
                    Descargar Plantilla Activos (.xlsx)
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      abrirMasivo(
                        "ACTIVOS_FIJOS",
                        "Carga Masiva — Inventario de Activos Fijos"
                      )
                    }
                    className="inline-flex items-center gap-1.5 rounded-xl bg-sky-50 border border-[#003566]/30 px-3.5 py-2 text-xs font-bold text-[#003566] cursor-pointer"
                  >
                    <FileSpreadsheet className="h-4 w-4" />
                    Carga Masiva Activos
                  </button>
                </div>
              )}

              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
                <div className="bg-slate-50 px-5 py-3 border-b border-slate-200 text-sm font-bold text-[#001D3D]">
                  Activos Fijos y Depreciación
                </div>
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-50/70 text-slate-500 uppercase">
                    <tr>
                      <th className="px-4 py-2.5">Código / Descripción</th>
                      <th className="px-4 py-2.5">Categoría</th>
                      <th className="px-4 py-2.5 text-right">Costo USD</th>
                      <th className="px-4 py-2.5 text-right">Dep. Acum.</th>
                      <th className="px-4 py-2.5 text-right">Valor Libros</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {activos.map((a) => (
                      <tr key={a.id}>
                        <td className="px-4 py-2.5">
                          <span className="font-mono font-bold text-[#003566]">{a.codigo_activo}</span>{" "}
                          · {a.descripcion}
                        </td>
                        <td className="px-4 py-2.5">{a.categoria}</td>
                        <td className="px-4 py-2.5 text-right">{formatearUsd(a.costo_usd)}</td>
                        <td className="px-4 py-2.5 text-right text-amber-700">{formatearUsd(a.depreciacion_acumulada_usd)}</td>
                        <td className="px-4 py-2.5 text-right font-bold text-emerald-700">{formatearUsd(a.valor_libros_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
                <div className="bg-slate-50 px-5 py-3 border-b border-slate-200 text-sm font-bold text-[#001D3D]">
                  Contratos y Pólizas Vigentes
                </div>
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-50/70 text-slate-500 uppercase">
                    <tr>
                      <th className="px-4 py-2.5">Tipo / Contraparte</th>
                      <th className="px-4 py-2.5">Vencimiento</th>
                      <th className="px-4 py-2.5 text-right">Canon Mensual</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {contratos.map((c) => (
                      <tr key={c.id}>
                        <td className="px-4 py-2.5 font-semibold">{c.tipo} · {c.proveedor_contraparte}</td>
                        <td className="px-4 py-2.5 font-mono">
                          {c.fecha_vencimiento}
                          {c.alerta_vencimiento && (
                            <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-700">
                              Por vencer ({c.dias_para_vencer}d)
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-2.5 text-right font-bold">{formatearUsd(c.canon_mensual_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 7: AUDITORÍA INMUTABLE */}
          {tab === "auditoria" && (
            <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
              <div className="bg-slate-50 px-5 py-3 border-b border-slate-200 text-sm font-bold text-[#001D3D]">
                Bitácora de Auditoría Inmutable (Solo Lectura)
              </div>
              <table className="w-full text-xs text-left">
                <thead className="bg-slate-50/70 text-slate-500 uppercase">
                  <tr>
                    <th className="px-4 py-2.5">Fecha / Hora</th>
                    <th className="px-4 py-2.5">Usuario / Rol</th>
                    <th className="px-4 py-2.5">Módulo</th>
                    <th className="px-4 py-2.5">Acción</th>
                    <th className="px-4 py-2.5">Entidad</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {auditoria.map((a) => (
                    <tr key={a.id}>
                      <td className="px-4 py-2.5 font-mono text-[11px]">
                        {a.fecha_hora ? new Date(a.fecha_hora).toLocaleString("es-VE") : "—"}
                      </td>
                      <td className="px-4 py-2.5 font-semibold">
                        {a.usuario_nombre} <span className="text-slate-400">({a.rol})</span>
                      </td>
                      <td className="px-4 py-2.5 font-bold text-[#003566]">{a.modulo}</td>
                      <td className="px-4 py-2.5">
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-700">
                          {a.accion}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 font-mono">#{a.entidad_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {modalMasivo && (
        <ModalCargaMasiva
          abierto={true}
          alCerrar={() => setModalMasivo(null)}
          tipo={modalMasivo.tipo}
          titulo={modalMasivo.titulo}
          prefijoRuta="/api/admin"
          instrumentos={instrumentos}
          alCompletar={() => {
            void cargarTodo();
          }}
        />
      )}
    </div>
  );
}
