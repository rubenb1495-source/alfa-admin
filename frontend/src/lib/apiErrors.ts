export interface ErrorApiEstructurado {
  message: string;
  fieldErrors: Record<string, string>;
}

const ETIQUETAS_CAMPOS: Record<string, string> = {
  almacen_destino_id: "Almacén de destino",
  almacen_origen_id: "Almacén de origen",
  sucursal_id: "Tienda / Sucursal",
  ubicacion_id: "Ubicación / Almacén",
  proveedor_nombre: "Proveedor / Consignante",
  tipo_ingreso: "Tipo de ingreso",
  referencia_factura: "Referencia / Factura",
  costo_unitario_usd: "Costo unitario (USD)",
  costo_compra_usd: "Costo de compra (USD)",
  costo_flete_usd: "Costo de flete (USD)",
  costo_aduana_otros_usd: "Aduana y otros gastos (USD)",
  precio_venta_usd: "Precio de venta (USD)",
  precio_promo_usd: "Precio Promo (USD)",
  estado_inicial: "Estado inicial",
  sku: "SKU / Producto",
  serial: "Serial",
  cantidad: "Cantidad",
  fecha: "Fecha",
  fecha_emision: "Fecha de emisión",
  fecha_vencimiento: "Fecha de vencimiento",
  fecha_inicio: "Fecha de inicio",
  fecha_fin: "Fecha de fin",
  cuenta_origen_id: "Cuenta de origen",
  cuenta_destino_id: "Cuenta de destino",
  instrumento_id: "Instrumento de pago",
  instrumento_pago_id: "Cuenta / Instrumento de pago",
  instrumento_ingreso_id: "Cuenta de ingreso",
  monto_salida: "Monto de salida",
  monto_entrada: "Monto de entrada",
  monto_moneda_origen: "Monto del pago",
  monto_usd: "Monto (USD)",
  capital_usd: "Capital (USD)",
  monto_capital_usd: "Abono a capital (USD)",
  monto_interes_usd: "Intereses (USD)",
  comision_usd: "Comisión (USD)",
  tasa_operacion: "Tasa de operación",
  tasa_bcv: "Tasa BCV",
  tasa_usdt: "Tasa USDT",
  porcentaje_recargo: "Porcentaje de recargo",
  personal_id: "Asesor / Personal",
  asesor_id: "Asesor",
  tecnico_id: "Técnico",
  cliente_id: "Cliente",
  nombre: "Nombre",
  correo: "Correo electrónico",
  email: "Correo electrónico",
  clave: "Contraseña",
  rol: "Rol",
  telefono: "Teléfono",
  cedula: "Cédula / RIF",
  razon_social: "Razón social",
  rif_proveedor: "RIF del proveedor",
  base_imponible_bs: "Base imponible (Bs)",
  alicuota_iva: "Alícuota IVA (%)",
  observaciones: "Observaciones",
  motivo: "Motivo",
  items: "Artículos / Ítems",
  detalles: "Detalles",
  pagos: "Pagos",
  lineas: "Líneas del asiento",
};

function formatearRutaCampo(loc: unknown[]): { clave: string; etiqueta: string } {
  const partes = loc
    .map((p) => String(p))
    .filter((p) => p !== "body" && p !== "query" && p !== "path");

  if (partes.length === 0) {
    return { clave: "_general", etiqueta: "" };
  }

  const clave = partes.join(".");
  const etiquetas: string[] = [];

  for (let i = 0; i < partes.length; i++) {
    const seg = partes[i];
    if (/^\d+$/.test(seg)) {
      const indiceHumano = Number(seg) + 1;
      if (etiquetas.length > 0) {
        etiquetas[etiquetas.length - 1] = `${etiquetas[etiquetas.length - 1]} #${indiceHumano}`;
      } else {
        etiquetas.push(`Ítem #${indiceHumano}`);
      }
    } else {
      etiquetas.push(ETIQUETAS_CAMPOS[seg] || seg.replace(/_/g, " "));
    }
  }

  return { clave, etiqueta: etiquetas.join(" → ") };
}

function traducirMensajePydantic(msg: string): string {
  const limpio = (msg || "").trim();
  const lower = limpio.toLowerCase();

  if (lower.includes("field required")) return "es obligatorio";
  if (lower.includes("valid number") || lower.includes("valid decimal")) {
    return "debe ser un número válido";
  }
  if (lower.includes("valid integer")) return "debe ser un número entero válido";
  if (lower.includes("valid date")) return "debe tener una fecha válida";
  if (lower.includes("not a valid email") || lower.includes("valid email address")) {
    return "no es un correo electrónico válido";
  }
  if (lower.includes("greater than or equal to 0")) return "no puede ser negativo";
  if (lower.includes("greater than 0")) return "debe ser mayor a 0";
  if (lower.includes("greater than or equal to 1")) return "debe ser al menos 1";

  const matchMin = limpio.match(/at least (\d+) character/i);
  if (matchMin) {
    return `es demasiado corto (mínimo ${matchMin[1]} caracteres)`;
  }
  const matchMinItems = limpio.match(/at least (\d+) item/i);
  if (matchMinItems) {
    return `debe incluir al menos ${matchMinItems[1]} elemento(s)`;
  }
  if (lower.startsWith("value error,")) {
    return limpio.slice("value error,".length).trim();
  }
  return limpio || "tiene un valor inválido";
}

/**
 * Parsea respuestas de error HTTP 422 / 400 / 409 de FastAPI/Pydantic
 * y devuelve un mensaje legible en español junto con el mapa de errores por campo.
 */
export function parsearErrorApi(
  cuerpo: unknown,
  estadoHttp: number
): ErrorApiEstructurado {
  const fieldErrors: Record<string, string> = {};

  if (cuerpo && typeof cuerpo === "object" && "detail" in cuerpo) {
    const det = (cuerpo as { detail: unknown }).detail;

    if (typeof det === "string" && det.trim()) {
      return { message: det.trim(), fieldErrors };
    }

    if (Array.isArray(det) && det.length > 0) {
      const partesMensaje: string[] = [];
      for (const item of det) {
        if (typeof item === "string") {
          partesMensaje.push(item);
          continue;
        }
        if (item && typeof item === "object") {
          const obj = item as { loc?: unknown[]; msg?: string };
          const { clave, etiqueta } = formatearRutaCampo(
            Array.isArray(obj.loc) ? obj.loc : []
          );
          const texto = traducirMensajePydantic(obj.msg || "");
          fieldErrors[clave] = texto;
          partesMensaje.push(etiqueta ? `${etiqueta}: ${texto}` : texto);
        }
      }
      if (partesMensaje.length > 0) {
        return { message: partesMensaje.join(" · "), fieldErrors };
      }
    }

    if (det && typeof det === "object" && "mensaje" in det) {
      const m = (det as { mensaje?: unknown }).mensaje;
      if (typeof m === "string" && m.trim()) {
        return { message: m.trim(), fieldErrors };
      }
    }
  }

  return {
    message: `Error del servidor (HTTP ${estadoHttp}).`,
    fieldErrors,
  };
}

/**
 * Sanitiza un payload antes de enviarlo al backend:
 * - Convierte "" a null en claves opcionales especificadas (o por defecto en campos opcionales comunes).
 * - Convierte NaN a 0 (o null si está en numericNullableKeys).
 */
export function cleanPayload<T extends Record<string, unknown>>(
  payload: T,
  opciones?: {
    emptyStringToNullKeys?: string[];
    numericNullableKeys?: string[];
  }
): Record<string, unknown> {
  const nullKeys = new Set(
    opciones?.emptyStringToNullKeys ?? [
      "serial",
      "correo",
      "email",
      "clave",
      "fecha",
      "fecha_emision",
      "fecha_vencimiento",
      "fecha_ingreso",
      "precio_venta_usd",
      "tasa_operacion",
      "sucursal_id",
      "asesor_id",
      "tecnico_id",
      "cliente_id",
    ]
  );
  const numNullKeys = new Set(
    opciones?.numericNullableKeys ?? ["precio_venta_usd", "tasa_operacion", "monto_entrada"]
  );

  const limpiarValor = (clave: string, valor: unknown): unknown => {
    if (valor === undefined) return undefined;
    if (typeof valor === "number" && Number.isNaN(valor)) {
      return numNullKeys.has(clave) ? null : 0;
    }
    if (typeof valor === "string") {
      const trimmed = valor.trim();
      if (trimmed === "" && nullKeys.has(clave)) {
        return null;
      }
      return trimmed;
    }
    if (Array.isArray(valor)) {
      return valor.map((el) =>
        el && typeof el === "object" && !Array.isArray(el)
          ? cleanPayload(el as Record<string, unknown>, opciones)
          : el
      );
    }
    if (valor && typeof valor === "object") {
      return cleanPayload(valor as Record<string, unknown>, opciones);
    }
    return valor;
  };

  const resultado: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(payload)) {
    const limpio = limpiarValor(k, v);
    if (limpio !== undefined) {
      resultado[k] = limpio;
    }
  }
  return resultado;
}
