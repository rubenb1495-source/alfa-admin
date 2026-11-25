"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Building2,
  Check,
  Copy,
  Globe,
  KeyRound,
  Lock,
  MessageCircle,
  Pencil,
  Phone,
  Plus,
  Share2,
  ShieldAlert,
  UserCheck,
  UserX,
  Users,
  X,
} from "lucide-react";
import BuscadorTabla from "@/componentes/BuscadorTabla";
import { usarSesion } from "@/contexto/SesionContexto";
import { ErrorApi, esRolAdministrativo, solicitarApi } from "@/servicios/api";
import type {
  ModalidadPersonal,
  RolUsuario,
  Sucursal,
  Usuario,
} from "@/tipos/dominio";

const ROLES_DISPONIBLES: RolUsuario[] = [
  "DIRECTOR",
  "ASESORA",
  "ENCARGADO_TIENDA",
  "TECNICO",
  "ADMINISTRACION",
  "LOGISTICA",
  "DIRECCION",
  "OTRO",
];

const ETIQUETAS_ROL: Record<string, string> = {
  DIRECCION: "Dirección (Admin Total)",
  ADMINISTRACION: "Administración (Admin Total)",
  DIRECTOR: "Director (Solo Lectura Ejecutiva)",
  LOGISTICA: "Logística",
  ENCARGADO_TIENDA: "Encargado de Tienda (5% Pasillo / 8% Lead)",
  LIDER: "Encargado de Tienda (5% Pasillo / 8% Lead)",
  ASESORA: "Asesor (1% Pasillo / 8% Lead)",
  TECNICO: "Técnico",
  OTRO: "Otro colaborador",
};

const ETIQUETA_CORTA_ROL: Record<string, string> = {
  DIRECCION: "Dirección",
  ADMINISTRACION: "Administración",
  DIRECTOR: "Director (Solo Lectura)",
  LOGISTICA: "Logística",
  ENCARGADO_TIENDA: "Encargado (5%/8%)",
  LIDER: "Encargado (5%/8%)",
  ASESORA: "Asesor (1%/8%)",
  TECNICO: "Técnico",
  OTRO: "Otro",
};

export default function PaginaPersonalYUsuarios() {
  const { usuario } = usarSesion();
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [sucursales, setSucursales] = useState<Sucursal[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal compartir acceso / restablecer clave
  const [credencialesCompartir, setCredencialesCompartir] = useState<{
    nombre: string;
    correo: string;
    rol: string;
    telefono: string;
    clave_temporal: string;
    url_app: string;
  } | null>(null);
  const [copiadoCreds, setCopiadoCreds] = useState(false);
  const [restableciendoId, setRestableciendoId] = useState<number | null>(null);

  const manejarCompartirAcceso = async (u: Usuario) => {
    setRestableciendoId(u.id);
    setError(null);
    try {
      const resp = await solicitarApi<{
        nombre: string;
        correo: string;
        rol: string;
        telefono: string;
        clave_temporal: string;
        url_app: string;
      }>(`/api/usuarios/${u.id}/restablecer-clave`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setCredencialesCompartir(resp);
      setCopiadoCreds(false);
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo generar la clave temporal."
      );
    } finally {
      setRestableciendoId(null);
    }
  };

  const construirMensajeAcceso = (c: {
    nombre: string;
    correo: string;
    rol: string;
    clave_temporal: string;
    url_app: string;
  }) => {
    return [
      `Hola ${c.nombre}, aquí tienes tu acceso a *Alfa Admin*:`,
      ``,
      `🔗 *Enlace:* ${c.url_app}`,
      `📧 *Correo:* ${c.correo}`,
      `🔑 *Clave temporal:* ${c.clave_temporal}`,
      `🛡️ *Rol asignado:* ${ETIQUETA_CORTA_ROL[c.rol] || c.rol}`,
      ``,
      `ℹ️ Tus permisos en la plataforma dependen de tu rol asignado.`,
      `📲 *Instalar como App:* Al abrir el enlace, pulsa "Instalar App" (en Windows/Mac/Android) o Compartir → "Agregar a pantalla de inicio" (en iPhone Safari).`,
    ].join("\n");
  };

  const [filtroRol, setFiltroRol] = useState<string>("");
  const [filtroAcceso, setFiltroAcceso] = useState<string>("");
  const [filtroActivo, setFiltroActivo] = useState<string>("");
  const [busqueda, setBusqueda] = useState<string>("");

  // Modal crear / editar colaborador
  const [modalAbierto, setModalAbierto] = useState(false);
  const [editandoUsuario, setEditandoUsuario] = useState<Usuario | null>(null);
  const [nombre, setNombre] = useState("");
  const [rolForm, setRolForm] = useState<RolUsuario>("ASESORA");
  const [modalidad, setModalidad] = useState<ModalidadPersonal>("PRESENCIAL");
  const [telefono, setTelefono] = useState("");
  const [cedula, setCedula] = useState("");
  const [sucursalId, setSucursalId] = useState<string>("");
  const [tieneAcceso, setTieneAcceso] = useState(false);
  const [usuarioAcceso, setUsuarioAcceso] = useState("");
  const [correo, setCorreo] = useState("");
  const [clave, setClave] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [desbloqueandoId, setDesbloqueandoId] = useState<number | null>(null);
  const [errorModal, setErrorModal] = useState<string | null>(null);

  // Modal cambio de estado (borrado lógico)
  const [usuarioEstado, setUsuarioEstado] = useState<Usuario | null>(null);
  const [motivoEstado, setMotivoEstado] = useState("");

  const permitido = usuario ? esRolAdministrativo(usuario.rol) : false;

  const cargarDatos = useCallback(async () => {
    if (!permitido) {
      setCargando(false);
      return;
    }
    setCargando(true);
    setError(null);
    try {
      const parametros = new URLSearchParams();
      if (filtroRol) parametros.set("rol", filtroRol);
      if (filtroActivo) parametros.set("activo", filtroActivo);
      if (filtroAcceso) parametros.set("tiene_acceso", filtroAcceso);
      const qs = parametros.toString() ? `?${parametros.toString()}` : "";

      const [listaUsuarios, listaSucursales] = await Promise.all([
        solicitarApi<Usuario[]>(`/api/usuarios${qs}`),
        solicitarApi<Sucursal[]>("/api/sucursales"),
      ]);
      setUsuarios(listaUsuarios);
      setSucursales(listaSucursales);
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo cargar el listado de personal y usuarios."
      );
    } finally {
      setCargando(false);
    }
  }, [permitido, filtroRol, filtroActivo, filtroAcceso]);

  useEffect(() => {
    void cargarDatos();
  }, [cargarDatos]);

  const usuariosFiltrados = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    if (!q) return usuarios;
    return usuarios.filter((u) =>
      [
        u.nombre,
        u.correo || "",
        u.telefono || "",
        u.cedula || "",
        u.rol,
        u.modalidad || "",
        u.sucursal?.nombre || "",
      ]
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  }, [usuarios, busqueda]);

  const abrirModalCrear = () => {
    setEditandoUsuario(null);
    setNombre("");
    setUsuarioAcceso("");
    setRolForm("ASESORA");
    setModalidad("PRESENCIAL");
    setTelefono("");
    setCedula("");
    setSucursalId("");
    setTieneAcceso(false);
    setCorreo("");
    setClave("");
    setErrorModal(null);
    setModalAbierto(true);
  };

  const abrirModalEditar = (u: Usuario) => {
    setEditandoUsuario(u);
    setNombre(u.nombre);
    setUsuarioAcceso(u.usuario || u.nombre);
    setRolForm(u.rol);
    setModalidad(u.modalidad === "ONLINE" ? "ONLINE" : "PRESENCIAL");
    setTelefono(u.telefono || "");
    setCedula(u.cedula || "");
    setSucursalId(u.sucursal ? String(u.sucursal.id) : "");
    setTieneAcceso(u.tiene_acceso !== false);
    setCorreo(u.correo || "");
    setClave("");
    setErrorModal(null);
    setModalAbierto(true);
  };

  const manejarDesbloquearAcceso = async (u: Usuario) => {
    setDesbloqueandoId(u.id);
    setError(null);
    try {
      await solicitarApi(`/api/personal/${u.id}/desbloquear`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      await cargarDatos();
    } catch (err) {
      setError(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo desbloquear el acceso del usuario."
      );
    } finally {
      setDesbloqueandoId(null);
    }
  };

  const manejarGuardarPersonal = async (
    e: React.FormEvent<HTMLFormElement>
  ) => {
    e.preventDefault();
    setErrorModal(null);

    if (tieneAcceso) {
      const usrFinal = (usuarioAcceso || nombre).trim();
      if (!usrFinal) {
        setErrorModal(
          "El usuario de acceso (nombre) es obligatorio al dar acceso al sistema."
        );
        return;
      }
      const necesitaClave =
        !editandoUsuario || editandoUsuario.tiene_acceso === false;
      if (necesitaClave && clave.length < 6) {
        setErrorModal(
          "La contraseña inicial (mínimo 6 caracteres) es obligatoria al habilitar acceso."
        );
        return;
      }
      if (clave.length > 0 && clave.length < 6) {
        setErrorModal("La contraseña debe tener al menos 6 caracteres.");
        return;
      }
    }

    setGuardando(true);
    try {
      const payload = {
        nombre: nombre.trim(),
        usuario: tieneAcceso ? (usuarioAcceso.trim() || nombre.trim()) : null,
        rol: rolForm,
        modalidad,
        telefono: telefono.trim(),
        cedula: cedula.trim(),
        sucursal_id: sucursalId ? Number(sucursalId) : null,
        tiene_acceso: tieneAcceso,
        correo: tieneAcceso && correo.trim() ? correo.trim() : null,
        clave: tieneAcceso && clave ? clave : null,
      };

      if (editandoUsuario) {
        await solicitarApi<Usuario>(`/api/usuarios/${editandoUsuario.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
      } else {
        await solicitarApi<Usuario>("/api/usuarios", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      setModalAbierto(false);
      await cargarDatos();
    } catch (err) {
      setErrorModal(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo guardar el registro del colaborador."
      );
    } finally {
      setGuardando(false);
    }
  };

  const manejarCambiarEstado = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!usuarioEstado) return;
    setErrorModal(null);
    setGuardando(true);
    try {
      await solicitarApi<Usuario>(`/api/usuarios/${usuarioEstado.id}/estado`, {
        method: "PATCH",
        body: JSON.stringify({
          activo: !usuarioEstado.activo,
          motivo: motivoEstado.trim(),
        }),
      });
      setUsuarioEstado(null);
      setMotivoEstado("");
      await cargarDatos();
    } catch (err) {
      setErrorModal(
        err instanceof ErrorApi
          ? err.message
          : "No se pudo cambiar el estado del colaborador."
      );
    } finally {
      setGuardando(false);
    }
  };

  if (!permitido) {
    return (
      <div className="bg-white rounded-2xl border border-red-200 p-8 text-center max-w-lg mx-auto mt-10">
        <ShieldAlert className="w-10 h-10 text-red-500 mx-auto mb-3" />
        <h2 className="text-lg font-bold text-slate-900">Acceso restringido</h2>
        <p className="text-sm text-slate-600 mt-1">
          Solo Dirección y Administración pueden gestionar el personal y los
          usuarios del sistema.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Cabecera */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black text-[#000814] flex items-center gap-2">
            <Users className="w-6 h-6 text-[#003566]" />
            Personal y Usuarios
          </h2>
          <p className="text-sm text-slate-500">
            Registra asesores online, encargados, técnicos y personal
            administrativo (con o sin acceso al sistema) para el POS y cálculo
            de comisiones.
          </p>
        </div>

        <button
          type="button"
          onClick={abrirModalCrear}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[#003566] hover:bg-[#001D3D] text-white text-sm font-bold shadow-sm transition-colors cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          Nuevo colaborador
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2.5 p-4 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Filtros y buscador */}
      <div className="bg-white rounded-2xl border border-slate-200 p-4 flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[240px]">
          <BuscadorTabla
            valor={busqueda}
            alCambiar={setBusqueda}
            placeholder="Buscar por nombre, teléfono, cédula o correo..."
            totalRegistros={usuarios.length}
            totalFiltrados={usuariosFiltrados.length}
          />
        </div>

        <select
          value={filtroRol}
          onChange={(e) => setFiltroRol(e.target.value)}
          className="px-3 py-2 rounded-xl border border-slate-300 text-xs font-semibold bg-white text-slate-700"
        >
          <option value="">Todos los roles</option>
          {ROLES_DISPONIBLES.map((r) => (
            <option key={r} value={r}>
              {ETIQUETA_CORTA_ROL[r] || r}
            </option>
          ))}
        </select>

        <select
          value={filtroAcceso}
          onChange={(e) => setFiltroAcceso(e.target.value)}
          className="px-3 py-2 rounded-xl border border-slate-300 text-xs font-semibold bg-white text-slate-700"
        >
          <option value="">Acceso: Todos</option>
          <option value="true">Con acceso</option>
          <option value="false">Sin acceso</option>
        </select>

        <select
          value={filtroActivo}
          onChange={(e) => setFiltroActivo(e.target.value)}
          className="px-3 py-2 rounded-xl border border-slate-300 text-xs font-semibold bg-white text-slate-700"
        >
          <option value="">Estado: Todos</option>
          <option value="true">Activos</option>
          <option value="false">Inactivos</option>
        </select>
      </div>

      {/* Tabla de personal */}
      <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
        {cargando ? (
          <div className="p-6 space-y-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-12 rounded-xl bg-slate-100 animate-pulse"
              />
            ))}
          </div>
        ) : usuariosFiltrados.length === 0 ? (
          <p className="p-10 text-center text-sm text-slate-500">
            No se encontraron colaboradores con los filtros aplicados.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-slate-50 border-b border-slate-200 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3">Nombre</th>
                  <th className="px-4 py-3">Rol</th>
                  <th className="px-4 py-3">Modalidad</th>
                  <th className="px-4 py-3">Teléfono</th>
                  <th className="px-4 py-3">Acceso</th>
                  <th className="px-4 py-3">Estado</th>
                  <th className="px-4 py-3 text-right">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {usuariosFiltrados.map((u) => {
                  const conAcceso = u.tiene_acceso !== false;
                  const esOnline = u.modalidad === "ONLINE";
                  return (
                    <tr key={u.id} className="hover:bg-[#EDF3FA]/40">
                      <td className="px-4 py-3">
                        <p className="font-bold text-[#000814]">{u.nombre}</p>
                        <p className="text-xs text-slate-500">
                          {u.correo ? u.correo : "Sin correo"}
                          {u.cedula ? ` · CI: ${u.cedula}` : ""}
                          {u.sucursal ? ` · ${u.sucursal.nombre}` : ""}
                        </p>
                      </td>
                      <td className="px-4 py-3 text-xs">
                        <span
                          title={ETIQUETAS_ROL[u.rol] || u.rol}
                          className={`inline-block px-2 py-0.5 rounded-md font-bold text-[11px] ${
                            u.rol === "ENCARGADO_TIENDA" || u.rol === "LIDER"
                              ? "bg-[#EDF3FA] text-[#003566]"
                              : "bg-slate-100 text-slate-700"
                          }`}
                        >
                          {ETIQUETA_CORTA_ROL[u.rol] || u.rol}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-semibold ${
                            esOnline
                              ? "bg-sky-50 text-sky-700 border border-sky-200"
                              : "bg-slate-100 text-slate-600"
                          }`}
                        >
                          {esOnline ? (
                            <Globe className="w-3 h-3" />
                          ) : (
                            <Building2 className="w-3 h-3" />
                          )}
                          {esOnline ? "Online" : "Presencial"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-700">
                        {u.telefono ? (
                          <span className="inline-flex items-center gap-1">
                            <Phone className="w-3 h-3 text-slate-400" />
                            {u.telefono}
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs">
                        {conAcceso ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 font-bold border border-emerald-200">
                            <KeyRound className="w-3 h-3" />
                            Con acceso
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 font-semibold">
                            <Lock className="w-3 h-3" />
                            Sin acceso
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs space-x-1">
                        <span
                          className={`px-2 py-0.5 rounded-full font-bold ${
                            u.activo
                              ? "bg-emerald-50 text-emerald-700"
                              : "bg-red-50 text-red-700"
                          }`}
                        >
                          {u.activo ? "Activo" : "Inactivo"}
                        </span>
                        {u.cuenta_bloqueada && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-600 text-white font-bold">
                            <ShieldAlert className="w-3 h-3" />
                            Bloqueado
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right space-x-1.5 whitespace-nowrap">
                        {u.cuenta_bloqueada && (
                          <button
                            type="button"
                            disabled={desbloqueandoId === u.id}
                            onClick={() => void manejarDesbloquearAcceso(u)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-bold cursor-pointer disabled:opacity-50"
                          >
                            <KeyRound className="w-3.5 h-3.5" />
                            {desbloqueandoId === u.id ? "..." : "Desbloquear acceso"}
                          </button>
                        )}
                        {conAcceso && (
                          <button
                            type="button"
                            disabled={restableciendoId === u.id}
                            onClick={() => void manejarCompartirAcceso(u)}
                            title="Generar clave temporal y compartir por WhatsApp"
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-emerald-200 bg-emerald-50 hover:bg-emerald-100 text-emerald-800 text-xs font-bold cursor-pointer disabled:opacity-50"
                          >
                            <Share2 className="w-3.5 h-3.5" />
                            {restableciendoId === u.id ? "..." : "Compartir acceso"}
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => abrirModalEditar(u)}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-slate-200 bg-white hover:border-[#003566] text-[#003566] text-xs font-bold cursor-pointer"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                          Editar
                        </button>
                        {u.id !== usuario?.id && (
                          <button
                            type="button"
                            onClick={() => {
                              setUsuarioEstado(u);
                              setMotivoEstado("");
                              setErrorModal(null);
                            }}
                            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border text-xs font-bold cursor-pointer ${
                              u.activo
                                ? "border-red-200 text-red-700 hover:bg-red-50"
                                : "border-emerald-200 text-emerald-700 hover:bg-emerald-50"
                            }`}
                          >
                            {u.activo ? (
                              <>
                                <UserX className="w-3.5 h-3.5" />
                                Desactivar
                              </>
                            ) : (
                              <>
                                <UserCheck className="w-3.5 h-3.5" />
                                Activar
                              </>
                            )}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Sedes activas de referencia */}
      <div className="bg-white rounded-2xl border border-slate-200 p-5 space-y-3">
        <h3 className="text-sm font-black text-[#000814] uppercase tracking-wide flex items-center gap-2">
          <Building2 className="w-4 h-4 text-[#003566]" />
          Sucursales y Almacenes ({sucursales.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {sucursales.map((s) => (
            <div
              key={s.id}
              className="p-3.5 rounded-xl border border-slate-200 bg-slate-50/70"
            >
              <div className="flex items-center justify-between gap-2">
                <p className="font-bold text-sm text-[#000814]">{s.nombre}</p>
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                    s.estado === "ACTIVA"
                      ? "bg-emerald-50 text-emerald-700"
                      : "bg-slate-200 text-slate-600"
                  }`}
                >
                  {s.estado}
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-1">{s.direccion}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Modal Crear / Editar Personal */}
      {modalAbierto && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4 max-h-[92vh] overflow-y-auto">
            <h3 className="text-lg font-black text-[#000814]">
              {editandoUsuario
                ? `Editar colaborador: ${editandoUsuario.nombre}`
                : "Registrar nuevo colaborador"}
            </h3>

            {errorModal && (
              <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-xs text-red-700 font-medium">
                {errorModal}
              </div>
            )}

            <form onSubmit={manejarGuardarPersonal} className="space-y-3.5">
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Nombre completo *
                </label>
                <input
                  type="text"
                  required
                  minLength={2}
                  value={nombre}
                  onChange={(e) => setNombre(e.target.value)}
                  placeholder="Ej. Andrea Pérez"
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Rol *
                  </label>
                  <select
                    value={rolForm}
                    onChange={(e) => setRolForm(e.target.value as RolUsuario)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm bg-white"
                  >
                    {ROLES_DISPONIBLES.map((r) => (
                      <option key={r} value={r}>
                        {ETIQUETAS_ROL[r] || r}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Modalidad
                  </label>
                  <select
                    value={modalidad}
                    onChange={(e) =>
                      setModalidad(e.target.value as ModalidadPersonal)
                    }
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm bg-white"
                  >
                    <option value="PRESENCIAL">Presencial (Tienda)</option>
                    <option value="ONLINE">Online (Remoto / Redes)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Teléfono (opcional)
                  </label>
                  <input
                    type="text"
                    value={telefono}
                    onChange={(e) => setTelefono(e.target.value)}
                    placeholder="Ej. 0424-1234567"
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">
                    Cédula (opcional)
                  </label>
                  <input
                    type="text"
                    value={cedula}
                    onChange={(e) => setCedula(e.target.value)}
                    placeholder="Ej. V-25123456"
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Sucursal asignada (opcional)
                </label>
                <select
                  value={sucursalId}
                  onChange={(e) => setSucursalId(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm bg-white"
                >
                  <option value="">Sin asignar / Multi-sede</option>
                  {sucursales.map((s) => (
                    <option key={s.id} value={String(s.id)}>
                      {s.nombre}
                    </option>
                  ))}
                </select>
              </div>

              {/* Switch Dar acceso al sistema */}
              <div className="p-3.5 rounded-xl bg-[#EDF3FA]/65 border border-[#003566]/20 space-y-3">
                <label className="flex items-center justify-between gap-3 cursor-pointer select-none">
                  <div>
                    <p className="text-xs font-black text-[#003566] uppercase tracking-wide">
                      Dar acceso al sistema
                    </p>
                    <p className="text-[11px] text-slate-600">
                      Desactívalo para asesores online o técnicos que solo se
                      seleccionan en el POS para comisiones.
                    </p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={tieneAcceso}
                    disabled={editandoUsuario?.id === usuario?.id}
                    onClick={() => {
                      setTieneAcceso((prev) => {
                        const next = !prev;
                        if (next && !usuarioAcceso.trim() && nombre.trim()) {
                          setUsuarioAcceso(nombre.trim());
                        }
                        return next;
                      });
                    }}
                    className={`relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent transition-colors cursor-pointer disabled:opacity-50 ${
                      tieneAcceso ? "bg-[#003566]" : "bg-slate-300"
                    }`}
                  >
                    <span
                      className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
                        tieneAcceso ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                </label>

                {tieneAcceso && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-[#003566]/15">
                    <div className="sm:col-span-2">
                      <label className="block text-xs font-bold text-slate-700 mb-1">
                        Usuario de acceso (Nombre para iniciar sesión) *
                      </label>
                      <input
                        type="text"
                        required
                        value={usuarioAcceso}
                        onChange={(e) => setUsuarioAcceso(e.target.value)}
                        placeholder={nombre.trim() || "Ej. Carlos Mendoza"}
                        className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm bg-white"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-bold text-slate-700 mb-1">
                        Correo electrónico (opcional)
                      </label>
                      <input
                        type="email"
                        value={correo}
                        onChange={(e) => setCorreo(e.target.value)}
                        placeholder="opcional@alfadigitalstore.com"
                        className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm bg-white"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-bold text-slate-700 mb-1">
                        {editandoUsuario && editandoUsuario.tiene_acceso !== false
                          ? "Nueva clave (opcional)"
                          : "Contraseña inicial *"}
                      </label>
                      <input
                        type="password"
                        required={
                          !editandoUsuario ||
                          editandoUsuario.tiene_acceso === false
                        }
                        minLength={6}
                        value={clave}
                        onChange={(e) => setClave(e.target.value)}
                        placeholder="Mín. 6 caracteres"
                        className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm bg-white"
                      />
                    </div>
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setModalAbierto(false)}
                  className="px-4 py-2 rounded-xl border border-slate-300 text-xs font-bold text-slate-700 cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={guardando}
                  className="px-4 py-2 rounded-xl bg-[#003566] hover:bg-[#001D3D] disabled:opacity-60 text-white text-xs font-bold cursor-pointer"
                >
                  {guardando
                    ? "Guardando..."
                    : editandoUsuario
                    ? "Guardar cambios"
                    : "Registrar colaborador"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Activar / Desactivar */}
      {usuarioEstado && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <h3 className="text-lg font-black text-[#000814]">
              {usuarioEstado.activo ? "Desactivar" : "Reactivar"} a{" "}
              {usuarioEstado.nombre}
            </h3>
            <p className="text-xs text-slate-500">
              Esta acción conserva intacto todo el historial de ventas y
              comisiones del colaborador.
            </p>
            {errorModal && (
              <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-xs text-red-700">
                {errorModal}
              </div>
            )}
            <form onSubmit={manejarCambiarEstado} className="space-y-3">
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Motivo obligatorio
                </label>
                <input
                  type="text"
                  required
                  minLength={3}
                  value={motivoEstado}
                  onChange={(e) => setMotivoEstado(e.target.value)}
                  placeholder="Ej. Egreso / Reincorporación"
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 text-sm"
                />
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setUsuarioEstado(null)}
                  className="px-4 py-2 rounded-xl border border-slate-300 text-xs font-bold text-slate-700 cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={guardando}
                  className="px-4 py-2 rounded-xl bg-[#003566] text-white text-xs font-bold cursor-pointer"
                >
                  {guardando ? "Aplicando..." : "Confirmar"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Compartir Acceso / Credenciales */}
      {credencialesCompartir && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-xs">
          <div className="w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-2xl border border-slate-200">
            <div className="flex items-center justify-between bg-[#003566] px-5 py-3.5 text-white">
              <div className="flex items-center gap-2">
                <KeyRound className="h-4 w-4 text-sky-300" />
                <h3 className="text-sm font-bold">
                  Acceso listo para compartir
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setCredencialesCompartir(null)}
                className="rounded-lg p-1 hover:bg-white/10"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="p-5 space-y-4 text-xs">
              <div className="rounded-xl bg-slate-50 border border-slate-200 p-3.5 space-y-1.5">
                <p>
                  <span className="text-slate-500">Usuario:</span>{" "}
                  <strong className="text-[#001D3D]">{credencialesCompartir.nombre}</strong>
                </p>
                <p>
                  <span className="text-slate-500">Enlace:</span>{" "}
                  <strong className="text-[#003566]">{credencialesCompartir.url_app}</strong>
                </p>
                <p>
                  <span className="text-slate-500">Correo:</span>{" "}
                  <strong className="font-mono">{credencialesCompartir.correo}</strong>
                </p>
                <p>
                  <span className="text-slate-500">Clave temporal:</span>{" "}
                  <strong className="font-mono text-sm text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">
                    {credencialesCompartir.clave_temporal}
                  </strong>
                </p>
                <p>
                  <span className="text-slate-500">Rol:</span>{" "}
                  <strong>
                    {ETIQUETA_CORTA_ROL[credencialesCompartir.rol] ||
                      credencialesCompartir.rol}
                  </strong>
                </p>
              </div>
              <div className="flex flex-col sm:flex-row gap-2">
                <button
                  type="button"
                  onClick={() => {
                    void navigator.clipboard.writeText(
                      construirMensajeAcceso(credencialesCompartir)
                    );
                    setCopiadoCreds(true);
                  }}
                  className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-xs font-bold text-slate-700 hover:bg-slate-50 cursor-pointer"
                >
                  {copiadoCreds ? (
                    <>
                      <Check className="h-4 w-4 text-emerald-600" />
                      Copiado
                    </>
                  ) : (
                    <>
                      <Copy className="h-4 w-4" />
                      Copiar credenciales
                    </>
                  )}
                </button>
                <a
                  href={`https://wa.me/${(credencialesCompartir.telefono || "").replace(/\D/g, "")}?text=${encodeURIComponent(
                    construirMensajeAcceso(credencialesCompartir)
                  )}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2.5 text-xs font-bold text-white hover:bg-emerald-700"
                >
                  <MessageCircle className="h-4 w-4" />
                  Enviar por WhatsApp
                </a>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
