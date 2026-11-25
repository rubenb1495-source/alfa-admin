"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  FileText,
  MessageCircle,
  Printer,
  Search,
  Send,
  Shield,
  Wrench,
} from "lucide-react";
import { usarSesion } from "@/contexto/SesionContexto";
import { descargarPdfApi, solicitarApi } from "@/servicios/api";
import { MARCA_ALFA } from "@/config/brand";

interface TecnicoItem {
  id: number;
  nombre: string;
  telefono: string;
  sucursal_id: number | null;
}

interface VentaBusquedaItem {
  venta_id: number;
  numero_nota_venta: string;
  fecha_venta: string | null;
  dias_transcurridos_garantia: number;
  garantia_vigente: boolean;
  sucursal_id: number;
  sucursal_nombre: string;
  cliente_id: number | null;
  cliente_nombre: string;
  cliente_documento: string;
  cliente_telefono: string;
  equipos: {
    equipo_id: number | null;
    modelo: string;
    serial: string;
    especificaciones: string;
    categoria: string;
  }[];
}

interface OrdenRecepcion {
  id: number;
  codigo: string;
  tipo_orden: "GARANTIA" | "SERVICIO_TECNICO";
  estado: string;
  sucursal_id: number;
  sucursal_nombre: string;
  recibido_por_nombre: string;
  tecnico_asignado_id: number | null;
  tecnico_asignado_nombre: string;
  tecnico_asignado_telefono: string;
  cliente_id: number | null;
  cliente_nombre: string;
  cliente_documento: string;
  cliente_telefono: string;
  venta_id: number | null;
  numero_nota_venta: string | null;
  fecha_venta: string | null;
  dias_transcurridos_garantia: number | null;
  garantia_vigente: boolean | null;
  equipo_id: number | null;
  marca: string;
  modelo: string;
  serial: string;
  especificaciones: string;
  clave_acceso: string;
  falla_declarada_cliente: string;
  accesorios_entregados: string[];
  accesorios_otros: string;
  detalles_esteticos: string;
  detalles_sistema_recepcion: string;
  equipo_llega_apagado: boolean;
  condiciones_aceptadas: boolean;
  costo_revision_usd: number;
  costo_revision_efectivo_usd: number;
  reparacion_aprobada: boolean;
  fecha_recepcion: string | null;
  diagnostico_tecnico: string;
  solucion_aplicada: string;
}

const ACCESORIOS_OPCIONES = [
  "Cargador",
  "Cable de poder",
  "Bolso / Funda",
  "Batería",
  "Mouse",
  "RAM / SSD adicional",
];

const CHECKLIST_ESTETICO = [
  "Sin rayones visibles",
  "Rayones leves en tapa/carcasa",
  "Golpes o abolladuras",
  "Pantalla en buen estado",
  "Bisagras flojas",
  "Tornillos faltantes",
];

const CHECKLIST_SISTEMA = [
  "Da video correctamente",
  "Carga batería",
  "Entra al sistema operativo",
  "Teclado y touchpad funcionales",
  "No da señal de video",
];

const ESTADOS_ORDEN = [
  { valor: "RECIBIDO_EN_TIENDA", etiqueta: "Recibido en Tienda" },
  { valor: "ENVIADO_A_TECNICO", etiqueta: "Enviado a Técnico" },
  { valor: "EN_REVISION", etiqueta: "En Revisión" },
  { valor: "PRESUPUESTADO", etiqueta: "Presupuestado" },
  { valor: "EN_REPARACION", etiqueta: "En Reparación" },
  { valor: "LISTO_PARA_ENTREGA", etiqueta: "Listo para Entrega" },
  { valor: "RESUELTO_ENTREGADO", etiqueta: "Resuelto y Entregado" },
  { valor: "NO_REPARADO_ENTREGADO", etiqueta: "No Reparado / Entregado" },
];

const ESTADOS_TECNICO = [
  "EN_REVISION",
  "PRESUPUESTADO",
  "EN_REPARACION",
  "LISTO_PARA_ENTREGA",
];

function limpiarTelefonoWa(tel: string): string {
  const dig = (tel || "").replace(/\D/g, "");
  if (!dig) return "";
  if (dig.startsWith("0")) return `58${dig.slice(1)}`;
  if (dig.startsWith("58")) return dig;
  return `58${dig}`;
}

export default function PaginaRecepcionTecnica() {
  const { usuario } = usarSesion();
  const esTecnico = usuario?.rol === "TECNICO";
  const esDirector = usuario?.rol === "DIRECTOR";
  const puedeCrear = !esTecnico && !esDirector;

  const [pestana, setPestana] = useState<"nueva" | "bandeja">(
    puedeCrear ? "nueva" : "bandeja"
  );
  const [tecnicos, setTecnicos] = useState<TecnicoItem[]>([]);
  const [ordenes, setOrdenes] = useState<OrdenRecepcion[]>([]);
  const [cargando, setCargando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [mensaje, setMensaje] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Filtros bandeja
  const [filtroTipo, setFiltroTipo] = useState("");
  const [filtroEstado, setFiltroEstado] = useState("");
  const [filtroTecnico, setFiltroTecnico] = useState("");
  const [filtroTexto, setFiltroTexto] = useState("");

  // Modal / panel edición rápida de estado/diagnóstico
  const [ordenEditando, setOrdenEditando] = useState<OrdenRecepcion | null>(null);
  const [editEstado, setEditEstado] = useState("");
  const [editTecnicoId, setEditTecnicoId] = useState("");
  const [editDiagnostico, setEditDiagnostico] = useState("");
  const [editSolucion, setEditSolucion] = useState("");
  const [editRepAprobada, setEditRepAprobada] = useState(false);

  // Formulario Nueva Recepción
  const [tipoOrden, setTipoOrden] = useState<"GARANTIA" | "SERVICIO_TECNICO">("GARANTIA");
  const [busquedaVenta, setBusquedaVenta] = useState("");
  const [resultadosVentas, setResultadosVentas] = useState<VentaBusquedaItem[]>([]);
  const [buscandoVentas, setBuscandoVentas] = useState(false);
  const [ventaSeleccionada, setVentaSeleccionada] = useState<VentaBusquedaItem | null>(null);

  const [clienteId, setClienteId] = useState<number | null>(null);
  const [clienteNombre, setClienteNombre] = useState("");
  const [clienteDocumento, setClienteDocumento] = useState("");
  const [clienteTelefono, setClienteTelefono] = useState("");

  const [equipoId, setEquipoId] = useState<number | null>(null);
  const [marca, setMarca] = useState("");
  const [modelo, setModelo] = useState("");
  const [serial, setSerial] = useState("");
  const [especificaciones, setEspecificaciones] = useState("");
  const [claveAcceso, setClaveAcceso] = useState("");

  const [fallaDeclarada, setFallaDeclarada] = useState("");
  const [accesoriosSel, setAccesoriosSel] = useState<string[]>([]);
  const [accesoriosOtros, setAccesoriosOtros] = useState("");
  const [equipoLlegaApagado, setEquipoLlegaApagado] = useState(false);
  const [esteticosSel, setEsteticosSel] = useState<string[]>([]);
  const [esteticosObs, setEsteticosObs] = useState("");
  const [sistemaSel, setSistemaSel] = useState<string[]>([]);
  const [sistemaObs, setSistemaObs] = useState("");
  const [tecnicoAsignadoId, setTecnicoAsignadoId] = useState("");
  const [condicionesAceptadas, setCondicionesAceptadas] = useState(true);

  const cargarDatos = useCallback(async () => {
    setCargando(true);
    try {
      const params = new URLSearchParams();
      if (filtroTipo) params.set("tipo_orden", filtroTipo);
      if (filtroEstado) params.set("estado", filtroEstado);
      if (filtroTecnico) params.set("tecnico_asignado_id", filtroTecnico);
      if (filtroTexto.trim()) params.set("q", filtroTexto.trim());

      const [tecs, ords] = await Promise.all([
        solicitarApi<TecnicoItem[]>("/api/recepcion-tecnica/tecnicos"),
        solicitarApi<OrdenRecepcion[]>(
          `/api/recepcion-tecnica${params.toString() ? `?${params.toString()}` : ""}`
        ),
      ]);
      setTecnicos(tecs);
      setOrdenes(ords);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error cargando órdenes.");
    } finally {
      setCargando(false);
    }
  }, [filtroTipo, filtroEstado, filtroTecnico, filtroTexto]);

  useEffect(() => {
    void cargarDatos();
  }, [cargarDatos]);

  const buscarVentas = async () => {
    setBuscandoVentas(true);
    setError(null);
    try {
      const res = await solicitarApi<VentaBusquedaItem[]>(
        `/api/recepcion-tecnica/buscar-ventas?q=${encodeURIComponent(busquedaVenta.trim())}`
      );
      setResultadosVentas(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error buscando notas de venta.");
    } finally {
      setBuscandoVentas(false);
    }
  };

  const seleccionarVenta = (v: VentaBusquedaItem, eqIdx = 0) => {
    setVentaSeleccionada(v);
    setClienteId(v.cliente_id);
    setClienteNombre(v.cliente_nombre || "");
    setClienteDocumento(v.cliente_documento || "");
    setClienteTelefono(v.cliente_telefono || "");
    const eq = v.equipos[eqIdx] || v.equipos[0];
    if (eq) {
      setEquipoId(eq.equipo_id);
      setModelo(eq.modelo || "");
      setSerial(eq.serial || "");
      setEspecificaciones(eq.especificaciones || "");
    }
    setResultadosVentas([]);
  };

  const cambiarTipoOrden = (nuevo: "GARANTIA" | "SERVICIO_TECNICO") => {
    setTipoOrden(nuevo);
    setError(null);
    if (nuevo === "SERVICIO_TECNICO") {
      setVentaSeleccionada(null);
      setResultadosVentas([]);
      setBusquedaVenta("");
      setEquipoId(null);
      setCondicionesAceptadas(false);
    } else {
      setCondicionesAceptadas(true);
    }
  };

  const toggleItem = (lista: string[], setLista: (v: string[]) => void, valor: string) => {
    setLista(lista.includes(valor) ? lista.filter((x) => x !== valor) : [...lista, valor]);
  };

  const abrirPdf = async (ordenId: number, codigo: string) => {
    try {
      await descargarPdfApi(
        `/api/recepcion-tecnica/${ordenId}/pdf`,
        `comprobante_${codigo}.pdf`
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "No se pudo abrir el comprobante PDF.");
    }
  };

  const enviarWhatsappCliente = (o: OrdenRecepcion) => {
    const tipoTxt = o.tipo_orden === "GARANTIA" ? "Garantía" : "Servicio Técnico";
    const encTxt = o.equipo_llega_apagado ? "APAGADO" : "ENCENDIDO";
    const condSt =
      o.tipo_orden === "SERVICIO_TECNICO"
        ? "\n📌 Condiciones: Revisión $10 USD (exonerado si repara con nosotros). Si llega apagado, no nos hacemos responsables por fallas previas u ocultas."
        : "";
    const msg =
      `Hola ${o.cliente_nombre}, confirmamos la recepción de su equipo en *${MARCA_ALFA.nombreComercial}*:\n` +
      `• Orden: *${o.codigo}* (${tipoTxt})\n` +
      `• Equipo: ${o.marca} ${o.modelo} ${o.serial ? `(S/N: ${o.serial})` : ""}\n` +
      `• Falla declarada: ${o.falla_declarada_cliente}\n` +
      `• Estado de recepción: ${encTxt}\n` +
      `• Estado actual: ${o.estado.replaceAll("_", " ")}${condSt}`;
    const tel = limpiarTelefonoWa(o.cliente_telefono);
    window.open(
      `https://wa.me/${tel}?text=${encodeURIComponent(msg)}`,
      "_blank",
      "noopener,noreferrer"
    );
  };

  const enviarWhatsappTecnico = (o: OrdenRecepcion) => {
    const tipoTxt = o.tipo_orden === "GARANTIA" ? "GARANTÍA" : "SERVICIO TÉCNICO";
    const msg =
      `🔧 *Nueva Orden Asignada · ${o.codigo}* (${tipoTxt})\n` +
      `• Sede: ${o.sucursal_nombre}\n` +
      `• Cliente: ${o.cliente_nombre} (${o.cliente_telefono || "N/D"})\n` +
      `• Equipo: ${o.marca} ${o.modelo} ${o.serial ? `| S/N: ${o.serial}` : ""}\n` +
      `• Specs: ${o.especificaciones || "N/D"} ${o.clave_acceso ? `| Clave: ${o.clave_acceso}` : ""}\n` +
      `• Encendido al recibir: ${o.equipo_llega_apagado ? "APAGADO ⚠️" : "ENCENDIDO"}\n` +
      `• Falla: ${o.falla_declarada_cliente}\n` +
      `• Accesorios: ${(o.accesorios_entregados || []).join(", ") || "Ninguno"} ${o.accesorios_otros ? `(${o.accesorios_otros})` : ""}\n` +
      `• Estética: ${o.detalles_esteticos || "Sin observaciones"}`;
    const tel = limpiarTelefonoWa(o.tecnico_asignado_telefono);
    window.open(
      `https://wa.me/${tel}?text=${encodeURIComponent(msg)}`,
      "_blank",
      "noopener,noreferrer"
    );
  };

  const guardarRecepcion = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setMensaje(null);

    if (tipoOrden === "SERVICIO_TECNICO" && !condicionesAceptadas) {
      setError("El cliente debe confirmar las condiciones del Servicio Técnico antes de guardar.");
      return;
    }

    const detallesEsteticos = [...esteticosSel, esteticosObs.trim()]
      .filter(Boolean)
      .join(" · ");
    const detallesSistema = [
      equipoLlegaApagado ? "EQUIPO LLEGA APAGADO" : "EQUIPO ENCIENDE",
      ...sistemaSel,
      sistemaObs.trim(),
    ]
      .filter(Boolean)
      .join(" · ");

    setGuardando(true);
    try {
      const creada = await solicitarApi<OrdenRecepcion>("/api/recepcion-tecnica", {
        method: "POST",
        body: JSON.stringify({
          tipo_orden: tipoOrden,
          tecnico_asignado_id: tecnicoAsignadoId ? Number(tecnicoAsignadoId) : null,
          enviar_a_tecnico: Boolean(tecnicoAsignadoId),
          cliente_id: clienteId,
          cliente_nombre: clienteNombre,
          cliente_documento: clienteDocumento,
          cliente_telefono: clienteTelefono,
          venta_id: tipoOrden === "GARANTIA" ? ventaSeleccionada?.venta_id ?? null : null,
          numero_nota_venta:
            tipoOrden === "GARANTIA" ? ventaSeleccionada?.numero_nota_venta ?? null : null,
          equipo_id: tipoOrden === "GARANTIA" ? equipoId : null,
          marca,
          modelo,
          serial,
          especificaciones,
          clave_acceso: claveAcceso,
          falla_declarada_cliente: fallaDeclarada,
          accesorios_entregados: accesoriosSel,
          accesorios_otros: accesoriosOtros,
          detalles_esteticos: detallesEsteticos,
          detalles_sistema_recepcion: detallesSistema,
          equipo_llega_apagado: equipoLlegaApagado,
          condiciones_aceptadas: condicionesAceptadas,
        }),
      });

      setMensaje(`Orden ${creada.codigo} guardada correctamente. Abriendo comprobante PDF...`);
      await abrirPdf(creada.id, creada.codigo);

      // Limpiar formulario
      setVentaSeleccionada(null);
      setClienteId(null);
      setClienteNombre("");
      setClienteDocumento("");
      setClienteTelefono("");
      setEquipoId(null);
      setMarca("");
      setModelo("");
      setSerial("");
      setEspecificaciones("");
      setClaveAcceso("");
      setFallaDeclarada("");
      setAccesoriosSel([]);
      setAccesoriosOtros("");
      setEquipoLlegaApagado(false);
      setEsteticosSel([]);
      setEsteticosObs("");
      setSistemaSel([]);
      setSistemaObs("");
      setTecnicoAsignadoId("");
      setPestana("bandeja");
      await cargarDatos();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Error al registrar la recepción.");
    } finally {
      setGuardando(false);
    }
  };

  const abrirEdicion = (o: OrdenRecepcion) => {
    setOrdenEditando(o);
    setEditEstado(o.estado);
    setEditTecnicoId(o.tecnico_asignado_id ? String(o.tecnico_asignado_id) : "");
    setEditDiagnostico(o.diagnostico_tecnico || "");
    setEditSolucion(o.solucion_aplicada || "");
    setEditRepAprobada(Boolean(o.reparacion_aprobada));
  };

  const guardarActualizacion = async () => {
    if (!ordenEditando) return;
    setError(null);
    setMensaje(null);
    try {
      await solicitarApi(`/api/recepcion-tecnica/${ordenEditando.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          estado: editEstado,
          tecnico_asignado_id: !esTecnico && editTecnicoId ? Number(editTecnicoId) : undefined,
          diagnostico_tecnico: editDiagnostico,
          solucion_aplicada: editSolucion,
          reparacion_aprobada: !esTecnico ? editRepAprobada : undefined,
        }),
      });
      setMensaje(`Orden ${ordenEditando.codigo} actualizada.`);
      setOrdenEditando(null);
      await cargarDatos();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo actualizar la orden.");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">
            Recepción de Garantías y Servicios Técnicos
          </h1>
          <p className="text-sm text-slate-500">
            Formato oficial de recepción de tienda, asignación al técnico, comprobante PDF con
            cláusulas legales y seguimiento en Cierre Diario.
          </p>
        </div>
        <div className="flex gap-2">
          {puedeCrear && (
            <button
              type="button"
              onClick={() => setPestana("nueva")}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition ${
                pestana === "nueva"
                  ? "bg-blue-700 text-white shadow-sm"
                  : "bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
              }`}
            >
              + Nueva Recepción
            </button>
          )}
          <button
            type="button"
            onClick={() => setPestana("bandeja")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition ${
              pestana === "bandeja"
                ? "bg-blue-700 text-white shadow-sm"
                : "bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
            }`}
          >
            Bandeja y Seguimiento ({ordenes.length})
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {mensaje && (
        <div className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{mensaje}</span>
        </div>
      )}

      {pestana === "nueva" && puedeCrear && (
        <form onSubmit={guardarRecepcion} className="space-y-5">
          {/* Selector superior destacado: Garantía vs Servicio Técnico */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => cambiarTipoOrden("GARANTIA")}
              className={`p-4 rounded-xl border-2 text-left transition flex items-start gap-3 ${
                tipoOrden === "GARANTIA"
                  ? "border-blue-600 bg-blue-50/70 shadow-sm"
                  : "border-slate-200 bg-white hover:border-slate-300"
              }`}
            >
              <Shield
                className={`w-6 h-6 shrink-0 mt-0.5 ${
                  tipoOrden === "GARANTIA" ? "text-blue-700" : "text-slate-400"
                }`}
              />
              <div>
                <div className="font-semibold text-slate-900">Garantía de Equipo</div>
                <p className="text-xs text-slate-600 mt-0.5">
                  Vinculada a Nota de Venta de Alfa · Precarga automática de cliente, equipo y
                  vigencia · Sin costo de revisión.
                </p>
              </div>
            </button>

            <button
              type="button"
              onClick={() => cambiarTipoOrden("SERVICIO_TECNICO")}
              className={`p-4 rounded-xl border-2 text-left transition flex items-start gap-3 ${
                tipoOrden === "SERVICIO_TECNICO"
                  ? "border-amber-600 bg-amber-50/70 shadow-sm"
                  : "border-slate-200 bg-white hover:border-slate-300"
              }`}
            >
              <Wrench
                className={`w-6 h-6 shrink-0 mt-0.5 ${
                  tipoOrden === "SERVICIO_TECNICO" ? "text-amber-700" : "text-slate-400"
                }`}
              />
              <div>
                <div className="font-semibold text-slate-900">Servicio Técnico</div>
                <p className="text-xs text-slate-600 mt-0.5">
                  Equipo externo o fuera de garantía · Revisión $10 USD (exonerado si repara con
                  nosotros) · Sin Nota de Venta.
                </p>
              </div>
            </button>
          </div>

          {/* Bloque Nota de Venta: SOLO cuando tipoOrden === GARANTIA */}
          {tipoOrden === "GARANTIA" && (
            <div className="bg-white rounded-xl border border-blue-200 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-blue-900 flex items-center gap-2">
                  <FileText className="w-4 h-4" /> Buscar Nota de Venta (Respaldo de Garantía)
                </h2>
                {ventaSeleccionada && (
                  <span
                    className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${
                      ventaSeleccionada.garantia_vigente
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-red-100 text-red-700"
                    }`}
                  >
                    {ventaSeleccionada.garantia_vigente
                      ? `Vigente (${ventaSeleccionada.dias_transcurridos_garantia} días)`
                      : `Fuera de plazo (${ventaSeleccionada.dias_transcurridos_garantia} días)`}
                  </span>
                )}
              </div>

              <div className="flex gap-2">
                <input
                  type="text"
                  value={busquedaVenta}
                  onChange={(e) => setBusquedaVenta(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void buscarVentas();
                    }
                  }}
                  placeholder="Buscar por N° Nota (ej. VTA-0001), serial del equipo o cédula/nombre del cliente..."
                  className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
                <button
                  type="button"
                  onClick={() => void buscarVentas()}
                  disabled={buscandoVentas}
                  className="px-4 py-2 rounded-lg bg-blue-700 text-white text-sm font-medium hover:bg-blue-800 flex items-center gap-1.5"
                >
                  <Search className="w-4 h-4" />
                  {buscandoVentas ? "Buscando..." : "Buscar"}
                </button>
              </div>

              {resultadosVentas.length > 0 && (
                <div className="divide-y divide-slate-100 border border-slate-200 rounded-lg max-h-56 overflow-y-auto">
                  {resultadosVentas.map((v) => (
                    <div
                      key={v.venta_id}
                      className="p-2.5 hover:bg-blue-50/60 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs"
                    >
                      <div>
                        <span className="font-bold text-slate-900">{v.numero_nota_venta}</span> ·{" "}
                        <span className="text-slate-600">{v.fecha_venta}</span> ·{" "}
                        <span className="font-medium">{v.cliente_nombre}</span> (
                        {v.cliente_documento || "S/D"})
                        <div className="text-slate-500 mt-0.5">
                          {v.equipos.map((e, i) => (
                            <span key={i} className="mr-2">
                              {e.modelo} {e.serial ? `[${e.serial}]` : ""}
                            </span>
                          ))}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => seleccionarVenta(v)}
                        className="px-3 py-1.5 rounded-md bg-blue-600 text-white font-medium hover:bg-blue-700 shrink-0"
                      >
                        Cargar Nota
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {ventaSeleccionada && (
                <div className="p-3 rounded-lg bg-blue-50 border border-blue-200 text-xs flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <strong>Nota vinculada:</strong> {ventaSeleccionada.numero_nota_venta} ·{" "}
                    <strong>Fecha:</strong> {ventaSeleccionada.fecha_venta} ·{" "}
                    <strong>Sucursal:</strong> {ventaSeleccionada.sucursal_nombre}
                  </div>
                  <button
                    type="button"
                    onClick={() => setVentaSeleccionada(null)}
                    className="text-red-600 hover:underline font-medium"
                  >
                    Quitar vínculo
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Aviso legal obligatorio: SOLO cuando tipoOrden === SERVICIO_TECNICO */}
          {tipoOrden === "SERVICIO_TECNICO" && (
            <div className="bg-amber-50 border border-amber-300 rounded-xl p-4 space-y-2.5">
              <div className="font-semibold text-amber-900 text-sm flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-700" />
                Condiciones del Servicio Técnico (Informar al cliente)
              </div>
              <ul className="text-xs text-amber-900 space-y-1 list-disc pl-5">
                <li>
                  Costo de revisión técnica: <strong>$10 USD</strong> (dicho monto{" "}
                  <strong>no se cancela</strong> si decide realizar la reparación con nosotros).
                </li>
                <li>
                  Si el equipo llega <strong>apagado</strong>, no nos hacemos responsables por
                  fallas adicionales, previas u ocultas que presente el equipo al momento de la
                  revisión o encendido.
                </li>
              </ul>
              <label className="flex items-center gap-2 text-xs font-medium text-amber-950 pt-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={condicionesAceptadas}
                  onChange={(e) => setCondicionesAceptadas(e.target.checked)}
                  className="rounded border-amber-400"
                />
                Confirmo que el cliente fue informado y acepta las condiciones del Servicio Técnico.
              </label>
            </div>
          )}

          {/* Datos del Cliente y Detalles del Equipo */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="bg-white rounded-xl border border-slate-200 p-4 space-y-3">
              <h3 className="text-sm font-semibold text-slate-800">Datos del Cliente</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="sm:col-span-2">
                  <label className="block text-xs font-medium text-slate-600 mb-1">
                    Nombre / Razón Social *
                  </label>
                  <input
                    required
                    value={clienteNombre}
                    onChange={(e) => setClienteNombre(e.target.value)}
                    placeholder="Nombre completo del cliente"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">
                    Cédula / RIF
                  </label>
                  <input
                    value={clienteDocumento}
                    onChange={(e) => setClienteDocumento(e.target.value)}
                    placeholder="V-12345678 / J-..."
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">
                    Teléfono / WhatsApp
                  </label>
                  <input
                    value={clienteTelefono}
                    onChange={(e) => setClienteTelefono(e.target.value)}
                    placeholder="0414-0000000"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-slate-200 p-4 space-y-3">
              <h3 className="text-sm font-semibold text-slate-800">1. Detalles del Equipo</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">Marca</label>
                  <input
                    value={marca}
                    onChange={(e) => setMarca(e.target.value)}
                    placeholder="HP, Dell, Lenovo, Apple..."
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">Modelo *</label>
                  <input
                    required
                    value={modelo}
                    onChange={(e) => setModelo(e.target.value)}
                    placeholder="Ej. Latitude 5420 / Pavilion 15"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">Serial</label>
                  <input
                    value={serial}
                    onChange={(e) => setSerial(e.target.value)}
                    placeholder="Número de serie"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm uppercase"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">
                    Clave de acceso (opcional)
                  </label>
                  <input
                    value={claveAcceso}
                    onChange={(e) => setClaveAcceso(e.target.value)}
                    placeholder="PIN o contraseña"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="block text-xs font-medium text-slate-600 mb-1">
                    Especificaciones (Procesador / RAM / SSD)
                  </label>
                  <input
                    value={especificaciones}
                    onChange={(e) => setEspecificaciones(e.target.value)}
                    placeholder="Ej. Core i5 11va · 16GB RAM · 512GB SSD"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Falla declarada + Accesorios */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="bg-white rounded-xl border border-slate-200 p-4 space-y-2">
              <h3 className="text-sm font-semibold text-slate-800">
                2. Falla Declarada por el Cliente *
              </h3>
              <textarea
                required
                rows={4}
                value={fallaDeclarada}
                onChange={(e) => setFallaDeclarada(e.target.value)}
                placeholder="Describe exactamente el problema que reporta el cliente..."
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>

            <div className="bg-white rounded-xl border border-slate-200 p-4 space-y-3">
              <h3 className="text-sm font-semibold text-slate-800">
                3. Accesorios y Componentes Entregados
              </h3>
              <div className="flex flex-wrap gap-2">
                {ACCESORIOS_OPCIONES.map((acc) => {
                  const activo = accesoriosSel.includes(acc);
                  return (
                    <button
                      type="button"
                      key={acc}
                      onClick={() => toggleItem(accesoriosSel, setAccesoriosSel, acc)}
                      className={`px-3 py-1.5 rounded-full text-xs font-medium border transition ${
                        activo
                          ? "bg-blue-700 text-white border-blue-700"
                          : "bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100"
                      }`}
                    >
                      {acc}
                    </button>
                  );
                })}
              </div>
              <input
                value={accesoriosOtros}
                onChange={(e) => setAccesoriosOtros(e.target.value)}
                placeholder="Otros accesorios (adaptadores, pendrive, caja, etc.)"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
          </div>

          {/* Detalles estéticos y de sistema */}
          <div className="bg-white rounded-xl border border-slate-200 p-4 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-800">
                4. Detalles Estéticos y de Sistema al Recibir
              </h3>
              <label
                className={`flex items-center gap-2.5 px-3 py-1.5 rounded-lg border text-xs font-semibold cursor-pointer ${
                  equipoLlegaApagado
                    ? "bg-red-50 border-red-300 text-red-700"
                    : "bg-emerald-50 border-emerald-300 text-emerald-800"
                }`}
              >
                <input
                  type="checkbox"
                  checked={equipoLlegaApagado}
                  onChange={(e) => setEquipoLlegaApagado(e.target.checked)}
                />
                ¿El equipo llega APAGADO? ({equipoLlegaApagado ? "SÍ · APAGADO" : "NO · ENCIENDE"})
              </label>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="space-y-2">
                <div className="text-xs font-medium text-slate-600">Estado estético</div>
                <div className="flex flex-wrap gap-1.5">
                  {CHECKLIST_ESTETICO.map((item) => (
                    <button
                      type="button"
                      key={item}
                      onClick={() => toggleItem(esteticosSel, setEsteticosSel, item)}
                      className={`px-2.5 py-1 rounded-md text-xs border ${
                        esteticosSel.includes(item)
                          ? "bg-slate-800 text-white border-slate-800"
                          : "bg-slate-50 text-slate-700 border-slate-200"
                      }`}
                    >
                      {item}
                    </button>
                  ))}
                </div>
                <textarea
                  rows={2}
                  value={esteticosObs}
                  onChange={(e) => setEsteticosObs(e.target.value)}
                  placeholder="Observaciones estéticas detalladas..."
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </div>

              <div className="space-y-2">
                <div className="text-xs font-medium text-slate-600">
                  Estado de sistema / funcionamiento
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {CHECKLIST_SISTEMA.map((item) => (
                    <button
                      type="button"
                      key={item}
                      onClick={() => toggleItem(sistemaSel, setSistemaSel, item)}
                      className={`px-2.5 py-1 rounded-md text-xs border ${
                        sistemaSel.includes(item)
                          ? "bg-blue-700 text-white border-blue-700"
                          : "bg-slate-50 text-slate-700 border-slate-200"
                      }`}
                    >
                      {item}
                    </button>
                  ))}
                </div>
                <textarea
                  rows={2}
                  value={sistemaObs}
                  onChange={(e) => setSistemaObs(e.target.value)}
                  placeholder="Observaciones de encendido, video, batería, teclado..."
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </div>
            </div>
          </div>

          {/* Asignación al Técnico y Botón de Guardado */}
          <div className="bg-white rounded-xl border border-slate-200 p-4 flex flex-col sm:flex-row sm:items-end justify-between gap-4">
            <div className="flex-1 max-w-md">
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                5. Técnico Responsable Asignado
              </label>
              <select
                value={tecnicoAsignadoId}
                onChange={(e) => setTecnicoAsignadoId(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="">— Dejar en tienda (sin asignar aún) —</option>
                {tecnicos.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.nombre}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              disabled={guardando}
              className="px-5 py-2.5 rounded-lg bg-blue-700 hover:bg-blue-800 text-white text-sm font-semibold shadow-sm flex items-center justify-center gap-2 disabled:opacity-60"
            >
              <Printer className="w-4 h-4" />
              {guardando
                ? "Guardando..."
                : "Guardar, Enviar al Técnico e Imprimir Comprobante"}
            </button>
          </div>
        </form>
      )}

      {pestana === "bandeja" && (
        <div className="space-y-4">
          {/* Filtros */}
          <div className="bg-white rounded-xl border border-slate-200 p-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
            <input
              value={filtroTexto}
              onChange={(e) => setFiltroTexto(e.target.value)}
              placeholder="Buscar código, cliente, serial o nota..."
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
            <select
              value={filtroTipo}
              onChange={(e) => setFiltroTipo(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">Todos los tipos</option>
              <option value="GARANTIA">Solo Garantías</option>
              <option value="SERVICIO_TECNICO">Solo Servicios Técnicos</option>
            </select>
            <select
              value={filtroEstado}
              onChange={(e) => setFiltroEstado(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">Todos los estados</option>
              {ESTADOS_ORDEN.map((e) => (
                <option key={e.valor} value={e.valor}>
                  {e.etiqueta}
                </option>
              ))}
            </select>
            {!esTecnico && (
              <select
                value={filtroTecnico}
                onChange={(e) => setFiltroTecnico(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="">Todos los técnicos</option>
                {tecnicos.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.nombre}
                  </option>
                ))}
              </select>
            )}
          </div>

          {cargando ? (
            <div className="p-8 text-center text-sm text-slate-500">Cargando órdenes...</div>
          ) : ordenes.length === 0 ? (
            <div className="p-8 text-center text-sm text-slate-500 bg-white rounded-xl border border-slate-200">
              No hay órdenes de recepción con los filtros actuales.
            </div>
          ) : (
            <div className="space-y-3">
              {ordenes.map((o) => (
                <div
                  key={o.id}
                  className="bg-white rounded-xl border border-slate-200 p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4"
                >
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-bold text-slate-900">{o.codigo}</span>
                      <span
                        className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                          o.tipo_orden === "GARANTIA"
                            ? "bg-blue-100 text-blue-800"
                            : "bg-amber-100 text-amber-800"
                        }`}
                      >
                        {o.tipo_orden === "GARANTIA" ? "GARANTÍA" : "SERVICIO TÉCNICO"}
                      </span>
                      <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-700">
                        {o.estado.replaceAll("_", " ")}
                      </span>
                      {o.equipo_llega_apagado && (
                        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-red-100 text-red-700">
                          LLEGÓ APAGADO
                        </span>
                      )}
                      {o.tipo_orden === "SERVICIO_TECNICO" && (
                        <span className="text-xs font-medium text-slate-600">
                          Revisión:{" "}
                          {o.reparacion_aprobada
                            ? "Exonerada ($0)"
                            : `$${o.costo_revision_efectivo_usd.toFixed(2)}`}
                        </span>
                      )}
                    </div>
                    <div className="text-sm font-medium text-slate-800">
                      {o.cliente_nombre} {o.cliente_documento ? `(${o.cliente_documento})` : ""} ·{" "}
                      <span className="text-slate-600">
                        {o.marca} {o.modelo} {o.serial ? `[${o.serial}]` : ""}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500">
                      Falla: {o.falla_declarada_cliente}
                      {o.numero_nota_venta ? ` · Nota: ${o.numero_nota_venta}` : ""} · Técnico:{" "}
                      <strong>{o.tecnico_asignado_nombre || "Sin asignar"}</strong>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={() => void abrirPdf(o.id, o.codigo)}
                      className="px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-medium hover:bg-slate-800 flex items-center gap-1.5"
                    >
                      <Printer className="w-3.5 h-3.5" /> PDF
                    </button>
                    <button
                      type="button"
                      onClick={() => enviarWhatsappCliente(o)}
                      className="px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-700 flex items-center gap-1.5"
                    >
                      <MessageCircle className="w-3.5 h-3.5" /> Cliente WA
                    </button>
                    <button
                      type="button"
                      onClick={() => enviarWhatsappTecnico(o)}
                      className="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-medium hover:bg-blue-700 flex items-center gap-1.5"
                    >
                      <Send className="w-3.5 h-3.5" /> Técnico WA
                    </button>
                    {!esDirector && (
                      <button
                        type="button"
                        onClick={() => abrirEdicion(o)}
                        className="px-3 py-1.5 rounded-lg border border-slate-300 bg-white text-slate-700 text-xs font-medium hover:bg-slate-50 flex items-center gap-1.5"
                      >
                        <ClipboardCheck className="w-3.5 h-3.5" /> Actualizar
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Modal de actualización de estado y diagnóstico */}
      {ordenEditando && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl max-w-lg w-full p-5 space-y-4 shadow-xl">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-slate-900">
                Actualizar Orden {ordenEditando.codigo}
              </h3>
              <button
                type="button"
                onClick={() => setOrdenEditando(null)}
                className="text-sm text-slate-500 hover:text-slate-800"
              >
                Cerrar
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Estado</label>
                <select
                  value={editEstado}
                  onChange={(e) => setEditEstado(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                >
                  {ESTADOS_ORDEN.filter(
                    (e) => !esTecnico || ESTADOS_TECNICO.includes(e.valor)
                  ).map((e) => (
                    <option key={e.valor} value={e.valor}>
                      {e.etiqueta}
                    </option>
                  ))}
                </select>
              </div>

              {!esTecnico && (
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">
                    Técnico Asignado
                  </label>
                  <select
                    value={editTecnicoId}
                    onChange={(e) => setEditTecnicoId(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  >
                    <option value="">Sin asignar</option>
                    {tecnicos.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.nombre}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {!esTecnico && ordenEditando.tipo_orden === "SERVICIO_TECNICO" && (
                <label className="flex items-center gap-2 text-xs font-medium text-emerald-800 bg-emerald-50 border border-emerald-200 p-2.5 rounded-lg cursor-pointer">
                  <input
                    type="checkbox"
                    checked={editRepAprobada}
                    onChange={(e) => setEditRepAprobada(e.target.checked)}
                  />
                  Reparación aprobada por el cliente (exonera automáticamente los $10 de revisión)
                </label>
              )}

              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  Diagnóstico Técnico
                </label>
                <textarea
                  rows={3}
                  value={editDiagnostico}
                  onChange={(e) => setEditDiagnostico(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  Solución Aplicada
                </label>
                <textarea
                  rows={2}
                  value={editSolucion}
                  onChange={(e) => setEditSolucion(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setOrdenEditando(null)}
                className="px-4 py-2 rounded-lg border border-slate-200 text-sm text-slate-700"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => void guardarActualizacion()}
                className="px-4 py-2 rounded-lg bg-blue-700 text-white text-sm font-semibold hover:bg-blue-800"
              >
                Guardar Cambios
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
