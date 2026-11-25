"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  CloudUpload,
  Database,
  Download,
  History,
  Loader2,
} from "lucide-react";
import { ErrorApi, obtenerToken, solicitarApi } from "@/servicios/api";

const URL_BASE_API =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ||
  process.env.NEXT_PUBLIC_URL_API_PYTHON?.replace(/\/+$/, "") ||
  "http://localhost:8000";

interface RegistroRespaldo {
  id: number;
  fecha_hora: string;
  usuario_nombre: string;
  rol: string;
  archivo: string;
  tamano_bytes: number;
  tamano_kb: number;
  total_tablas: number;
  total_registros: number;
}

interface RespuestaHistorialRespaldo {
  ultimo_respaldo: RegistroRespaldo | null;
  historial: RegistroRespaldo[];
}

function formatearFechaCaracas(iso: string): string {
  if (!iso) return "—";
  try {
    const fecha = new Date(iso);
    return new Intl.DateTimeFormat("es-VE", {
      timeZone: "America/Caracas",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
    }).format(fecha);
  } catch {
    return iso;
  }
}

function formatearTamano(kb: number, bytes: number): string {
  if (kb >= 1024) return `${(kb / 1024).toFixed(2)} MB`;
  if (kb > 0) return `${kb.toFixed(1)} KB`;
  if (bytes > 0) return `${bytes} B`;
  return "—";
}

function extraerNombreArchivo(res: Response): string {
  const headerCustom = res.headers.get("X-Backup-Filename");
  if (headerCustom) return headerCustom;

  const cd = res.headers.get("Content-Disposition") || "";
  const match = cd.match(/filename="?([^";]+)"?/i);
  if (match?.[1]) return match[1];

  const ahora = new Date();
  const yyyy = ahora.getFullYear();
  const mm = String(ahora.getMonth() + 1).padStart(2, "0");
  const dd = String(ahora.getDate()).padStart(2, "0");
  const hh = String(ahora.getHours()).padStart(2, "0");
  const mi = String(ahora.getMinutes()).padStart(2, "0");
  return `respaldo_alfa_${yyyy}-${mm}-${dd}_${hh}${mi}.zip`;
}

export default function TarjetaRespaldoBD() {
  const [ultimo, setUltimo] = useState<RegistroRespaldo | null>(null);
  const [historial, setHistorial] = useState<RegistroRespaldo[]>([]);
  const [cargandoHistorial, setCargandoHistorial] = useState(true);
  const [descargando, setDescargando] = useState(false);
  const [mostrarHistorial, setMostrarHistorial] = useState(false);
  const [toast, setToast] = useState<{ tipo: "ok" | "error"; mensaje: string } | null>(null);

  const cargarHistorial = useCallback(async () => {
    setCargandoHistorial(true);
    try {
      const data = await solicitarApi<RespuestaHistorialRespaldo>(
        "/api/admin/respaldo/historial"
      );
      setUltimo(data.ultimo_respaldo);
      setHistorial(data.historial || []);
    } catch {
      // Silencioso si no hay permisos o fallo temporal
    } finally {
      setCargandoHistorial(false);
    }
  }, []);

  useEffect(() => {
    void cargarHistorial();
  }, [cargarHistorial]);

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 6000);
    return () => window.clearTimeout(t);
  }, [toast]);

  const descargarRespaldo = async () => {
    setDescargando(true);
    setToast(null);
    try {
      const token = obtenerToken();
      const res = await fetch(`${URL_BASE_API}/api/admin/respaldo/descargar`, {
        method: "GET",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        let detalle = "No se pudo generar el respaldo completo.";
        try {
          const errJson = (await res.json()) as { detail?: string };
          if (errJson.detail) detalle = errJson.detail;
        } catch {
          // ignore
        }
        throw new Error(detalle);
      }

      const nombreArchivo = extraerNombreArchivo(res);
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const enlace = document.createElement("a");
      enlace.href = url;
      enlace.download = nombreArchivo;
      document.body.appendChild(enlace);
      enlace.click();
      enlace.remove();
      window.URL.revokeObjectURL(url);

      setToast({
        tipo: "ok",
        mensaje: `Respaldo completo descargado correctamente (${nombreArchivo}).`,
      });
      await cargarHistorial();
    } catch (err) {
      setToast({
        tipo: "error",
        mensaje:
          err instanceof ErrorApi || err instanceof Error
            ? err.message
            : "Error al generar el respaldo de la base de datos.",
      });
    } finally {
      setDescargando(false);
    }
  };

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs space-y-4">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-xl bg-[#001D3D] text-white">
              <Database className="h-4 w-4" />
            </span>
            <h2 className="text-base font-bold text-[#001D3D]">
              Respaldo de Base de Datos
            </h2>
            <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-600">
              Solo ADMIN
            </span>
          </div>

          {cargandoHistorial ? (
            <p className="text-xs text-slate-500 flex items-center gap-1.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Consultando último respaldo registrado...
            </p>
          ) : ultimo ? (
            <p className="text-xs text-slate-600 flex flex-wrap items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
              <span>
                Último respaldo:{" "}
                <strong className="text-slate-900">
                  {formatearFechaCaracas(ultimo.fecha_hora)}
                </strong>{" "}
                por <strong className="text-slate-800">{ultimo.usuario_nombre}</strong>
                {ultimo.tamano_bytes > 0 && (
                  <>
                    {" "}
                    ·{" "}
                    <span className="text-slate-500">
                      {formatearTamano(ultimo.tamano_kb, ultimo.tamano_bytes)}
                    </span>
                  </>
                )}
              </span>
            </p>
          ) : (
            <p className="text-xs text-amber-700 font-medium flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              Aún no se ha descargado ningún respaldo completo de la base de datos.
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {historial.length > 0 && (
            <button
              type="button"
              onClick={() => setMostrarHistorial((v) => !v)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs font-bold text-slate-700 hover:bg-slate-100 cursor-pointer"
            >
              <History className="h-4 w-4" />
              {mostrarHistorial ? "Ocultar historial" : `Historial (${historial.length})`}
            </button>
          )}
          <button
            type="button"
            disabled={descargando}
            onClick={() => void descargarRespaldo()}
            className="inline-flex items-center gap-2 rounded-xl bg-[#003566] hover:bg-[#001D3D] disabled:opacity-60 px-4 py-2.5 text-xs font-bold text-white shadow-xs transition cursor-pointer"
          >
            {descargando ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Generando respaldo...
              </>
            ) : (
              <>
                <Download className="h-4 w-4" />
                Descargar Respaldo Completo (.zip)
              </>
            )}
          </button>
        </div>
      </div>

      <div className="flex items-start gap-2.5 rounded-xl border border-sky-200 bg-sky-50/70 px-3.5 py-2.5 text-xs text-sky-900">
        <CloudUpload className="h-4 w-4 shrink-0 mt-0.5 text-sky-700" />
        <p>
          El archivo <strong>.zip</strong> incluye{" "}
          <code className="font-mono text-[11px]">backup_completo.json</code> (todas las
          tablas para restauración técnica) y{" "}
          <code className="font-mono text-[11px]">resumen_legible_alfa.xlsx</code>{" "}
          (Cajas/Bancos, Inventario, Ventas, CxC/Cashea, CxP/Préstamos y Personal).{" "}
          <strong>Recuerda guardar una copia en Google Drive</strong> al completar la
          descarga.
        </p>
      </div>

      {toast && (
        <div
          className={`flex items-center gap-2 rounded-xl border px-3.5 py-2.5 text-xs font-medium ${
            toast.tipo === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-red-200 bg-red-50 text-red-700"
          }`}
        >
          {toast.tipo === "ok" ? (
            <CheckCircle2 className="h-4 w-4 shrink-0" />
          ) : (
            <AlertTriangle className="h-4 w-4 shrink-0" />
          )}
          <span>{toast.mensaje}</span>
        </div>
      )}

      {mostrarHistorial && historial.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-[11px] uppercase text-slate-600">
              <tr>
                <th className="px-3 py-2">Fecha y Hora (Caracas)</th>
                <th className="px-3 py-2">Usuario</th>
                <th className="px-3 py-2">Archivo</th>
                <th className="px-3 py-2 text-right">Tablas / Registros</th>
                <th className="px-3 py-2 text-right">Tamaño</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {historial.map((h) => (
                <tr key={h.id} className="hover:bg-slate-50/70">
                  <td className="px-3 py-2 font-medium text-slate-800">
                    {formatearFechaCaracas(h.fecha_hora)}
                  </td>
                  <td className="px-3 py-2 text-slate-700">{h.usuario_nombre}</td>
                  <td className="px-3 py-2 font-mono text-[11px] text-slate-600">
                    {h.archivo}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-600">
                    {h.total_tablas} tablas · {h.total_registros} reg.
                  </td>
                  <td className="px-3 py-2 text-right font-semibold text-slate-800">
                    {formatearTamano(h.tamano_kb, h.tamano_bytes)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
