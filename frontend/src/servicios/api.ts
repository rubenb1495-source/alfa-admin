import type { RolUsuario } from "@/tipos/dominio";

const CLAVE_TOKEN = "Alfa_admin_token";
const URL_BASE_API =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ||
  process.env.NEXT_PUBLIC_URL_API_PYTHON?.replace(/\/+$/, "") ||
  "http://localhost:8000";

export function fechaHoyCaracas(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Caracas",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

export class ErrorApi extends Error {
  readonly estado: number;

  constructor(mensaje: string, estado: number) {
    super(mensaje);
    this.name = "ErrorApi";
    this.estado = estado;
  }
}

export function obtenerToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(CLAVE_TOKEN);
  } catch {
    return null;
  }
}

export function guardarToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) {
      window.localStorage.setItem(CLAVE_TOKEN, token);
    } else {
      window.localStorage.removeItem(CLAVE_TOKEN);
    }
  } catch {
    // Ignorar errores de almacenamiento privado
  }
}

export function esRolAdministrativo(rol: RolUsuario): boolean {
  return rol === "DIRECCION" || rol === "ADMINISTRACION";
}

export function puedeGestionarCatalogo(rol: RolUsuario): boolean {
  return (
    rol === "DIRECCION" ||
    rol === "ADMINISTRACION" ||
    rol === "LOGISTICA" ||
    rol === "LIDER"
  );
}

export function puedeVerCostos(rol: RolUsuario): boolean {
  return (
    rol === "DIRECCION" ||
    rol === "ADMINISTRACION" ||
    rol === "DIRECTOR" ||
    rol === "LOGISTICA"
  );
}

export function normalizarSkuCliente(valor: string): string {
  return valor.trim().replace(/\s+/g, "-").toUpperCase();
}

function extraerMensajeErrorFastApi(cuerpo: unknown, estado: number): string {
  if (cuerpo && typeof cuerpo === "object" && "detail" in cuerpo) {
    const det = (cuerpo as { detail: unknown }).detail;
    if (typeof det === "string" && det.trim()) {
      return det;
    }
    if (Array.isArray(det) && det.length > 0) {
      const mensajes = det.map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const obj = item as { loc?: unknown[]; msg?: string };
          const ruta = Array.isArray(obj.loc)
            ? obj.loc.filter((p) => p !== "body" && p !== "query").join(".")
            : "";
          let msg = obj.msg || "valor inválido";
          if (msg.toLowerCase().includes("field required")) msg = "campo requerido";
          else if (msg.toLowerCase().includes("valid number") || msg.toLowerCase().includes("valid decimal")) msg = "debe ser un número válido";
          else if (msg.toLowerCase().includes("valid integer")) msg = "debe ser un número entero válido";
          else if (msg.toLowerCase().includes("at least")) msg = msg.replace(/String should have at least (\d+) characters?/i, "debe tener al menos $1 caracteres");
          return ruta ? `Error en ${ruta}: ${msg}` : msg;
        }
        return "Error de validación";
      });
      return mensajes.join(" · ");
    }
    if (det && typeof det === "object" && "mensaje" in det) {
      const m = (det as { mensaje?: unknown }).mensaje;
      if (typeof m === "string" && m.trim()) return m;
    }
  }
  return `Error del servidor (HTTP ${estado}).`;
}

export async function solicitarApi<T>(
  ruta: string,
  opciones: RequestInit = {}
): Promise<T> {
  const token = obtenerToken();
  const cabeceras = new Headers(opciones.headers);
  cabeceras.set("Accept", "application/json");
  if (opciones.body && !cabeceras.has("Content-Type")) {
    cabeceras.set("Content-Type", "application/json");
  }
  if (token) {
    cabeceras.set("Authorization", `Bearer ${token}`);
  }

  let respuesta: Response;
  try {
    respuesta = await fetch(`${URL_BASE_API}${ruta}`, {
      ...opciones,
      headers: cabeceras,
    });
  } catch {
    throw new ErrorApi(
      "No se pudo conectar con el servidor. Verifica que la API de FastAPI esté activa.",
      0
    );
  }

  const cuerpo = await respuesta.json().catch(() => null);

  if (!respuesta.ok) {
    if (respuesta.status === 401) {
      guardarToken(null);
    }
    const detalle = extraerMensajeErrorFastApi(cuerpo, respuesta.status);
    throw new ErrorApi(detalle, respuesta.status);
  }

  return cuerpo as T;
}

export async function subirArchivoApi<T>(
  ruta: string,
  formulario: FormData
): Promise<T> {
  const token = obtenerToken();
  const cabeceras = new Headers();
  cabeceras.set("Accept", "application/json");
  if (token) {
    cabeceras.set("Authorization", `Bearer ${token}`);
  }

  let respuesta: Response;
  try {
    respuesta = await fetch(`${URL_BASE_API}${ruta}`, {
      method: "POST",
      headers: cabeceras,
      body: formulario,
    });
  } catch {
    throw new ErrorApi(
      "No se pudo conectar con el servidor para validar el archivo.",
      0
    );
  }

  const cuerpo = await respuesta.json().catch(() => null);
  if (!respuesta.ok) {
    const detalle = extraerMensajeErrorFastApi(cuerpo, respuesta.status);
    throw new ErrorApi(detalle, respuesta.status);
  }
  return cuerpo as T;
}

export async function descargarPdfApi(
  ruta: string,
  nombreArchivo: string
): Promise<void> {
  const token = obtenerToken();
  const cabeceras = new Headers();
  if (token) {
    cabeceras.set("Authorization", `Bearer ${token}`);
  }
  const respuesta = await fetch(`${URL_BASE_API}${ruta}`, {
    headers: cabeceras,
  });
  if (!respuesta.ok) {
    throw new ErrorApi("No se pudo descargar el PDF de la Nota de Entrega.", respuesta.status);
  }
  const blob = await respuesta.blob();
  const url = window.URL.createObjectURL(blob);
  const enlace = document.createElement("a");
  enlace.href = url;
  enlace.download = nombreArchivo;
  document.body.appendChild(enlace);
  enlace.click();
  enlace.remove();
  window.URL.revokeObjectURL(url);
}

export async function abrirPdfEnPestanaApi(ruta: string): Promise<void> {
  const token = obtenerToken();
  const cabeceras = new Headers();
  if (token) {
    cabeceras.set("Authorization", `Bearer ${token}`);
  }
  const respuesta = await fetch(`${URL_BASE_API}${ruta}`, {
    headers: cabeceras,
  });
  if (!respuesta.ok) {
    throw new ErrorApi(
      "No se pudo abrir el PDF de la Nota de Entrega.",
      respuesta.status
    );
  }
  const blob = await respuesta.blob();
  const url = window.URL.createObjectURL(blob);
  const ventana = window.open(url, "_blank", "noopener,noreferrer");
  if (!ventana) {
    const enlace = document.createElement("a");
    enlace.href = url;
    enlace.target = "_blank";
    enlace.rel = "noopener noreferrer";
    document.body.appendChild(enlace);
    enlace.click();
    enlace.remove();
  }
  setTimeout(() => window.URL.revokeObjectURL(url), 60000);
}

export function formatearUsd(valor: number | null | undefined): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return `$${valor.toLocaleString("es-VE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatearBs(valor: number | null | undefined): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return `Bs ${valor.toLocaleString("es-VE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatearPorcentaje(valor: number | null | undefined): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return `${valor.toLocaleString("es-VE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`;
}
