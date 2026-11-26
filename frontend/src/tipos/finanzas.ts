export interface InstrumentoFinanciero {
  id: number;
  nombre: string;
  moneda: "USD" | "USDT" | "BS";
  tipo_precio: "PROMO" | "REGULAR";
  requiere_verificacion: boolean;
  liquida_en_bs: boolean;
  saldo_actual?: number;
  activo?: boolean;
}

export interface DesgloseCashea {
  total_precio_regular_usd: number;
  total_precio_regular_bs: number;
  total_precio_regular_usdt: number;
  inicial_cobrada_usd: number;
  monto_financiado_usd: number;
  cashea_comision_venta_usd: number;
  cashea_comision_financiado_usd: number;
  cashea_iva_usd: number;
  cashea_islr_usd: number;
  cashea_total_cargos_usd: number;
  cashea_neto_por_cobrar_usd: number;
  cashea_neto_bs: number;
  cashea_neto_usdt: number;
  tasa_bcv_aplicada: number;
  tasa_usdt_aplicada: number;
}

export interface SimulacionVenta {
  total_promo_usd: number;
  total_regular_usd: number;
  cubierto_promo_usd: number;
  cubierto_regular_usd?: number;
  falta_usd_promo: number;
  sobra_usd_promo: number;
  falta_usd_regular: number;
  falta_bs: number | null;
  cashea_financiado_sugerido_usd?: number;
  cashea_financiado_sugerido_bs?: number | null;
  usa_cashea: boolean;
  desglose_cashea?: DesgloseCashea | null;
  tasa_bcv: number;
  tasa_usdt?: number;
  recargo_porcentaje: number;
  estado: "CUADRADA" | "CON_SALDO";
}

export type OrigenVenta = "PASILLO" | "LEAD";

export interface UsuarioOperativo {
  id: number;
  nombre: string;
  rol: string;
  modalidad?: string;
  telefono?: string;
  tiene_acceso?: boolean;
  es_lider?: boolean;
  es_encargado?: boolean;
  sucursal_id: number | null;
}

export interface VentaResumen {
  id: number;
  numero_venta: string;
  sucursal_id: number;
  sucursal: string | null;
  fecha: string;
  cliente_id: number | null;
  cliente: string;
  cliente_rif?: string;
  cliente_telefono?: string;
  cliente_direccion?: string;
  cliente_tipo_persona?: "NATURAL" | "JURIDICO" | string;
  asesor_id: number | null;
  asesor: string;
  tecnico_id?: number | null;
  tecnico?: string | null;
  canal_visita: string;
  origen_venta?: OrigenVenta;
  tipo_entrega: string;
  datos_entrega?: Record<string, string> | null;
  tasa_bcv_snapshot: number;
  tasa_usdt_snapshot: number;
  recargo_porcentaje_snapshot: number;
  total_promo_usd: number;
  total_regular_usd: number;
  vuelto_caja_chica_usd?: number;
  creado_en?: string | null;
  estado: "CUADRADA" | "CON_SALDO" | "ANULADA" | "DEVUELTA";
  motivo_anulacion: string;
  nota: string;
  detalles: {
    id: number;
    equipo_id: number | null;
    serial: string | null;
    articulo_id: number | null;
    descripcion: string;
    descripcion_servicio?: string;
    es_servicio_tecnico?: boolean;
    cantidad: number;
    precio_promo_usd: number;
    precio_regular_usd: number;
  }[];
  pagos: {
    id: number;
    instrumento: string | null;
    monto_moneda_origen: number;
    moneda: string;
    usd_nominal: number;
    usd_real: number;
    cubre_promo_usd: number;
    referencia: string;
    estado_verificacion: "CONFIRMADO" | "PENDIENTE";
    anulado: boolean;
  }[];
}

export interface NotaCreditoResumen {
  id: number;
  numero_nc: string;
  venta_original_id: number;
  numero_venta: string | null;
  serial: string | null;
  sku: string | null;
  cantidad: number;
  monto_reconocido_promo_usd: number;
  motivo: string;
  estado_reingreso: "POR_PREPARAR" | "GARANTIA" | "LISTO";
  autorizado_por: string | null;
  fecha: string;
}

export interface PagoBandeja {
  id: number;
  venta_id: number | null;
  numero_venta: string | null;
  instrumento_id: number;
  instrumento: string | null;
  fecha: string;
  tipo_movimiento?: "INGRESO" | "EGRESO" | "TRASLADO" | string;
  tipo_documento: string;
  categoria?: string;
  origen_tipo?: string;
  origen_id?: number | null;
  monto_moneda_origen: number;
  moneda: string;
  usd_nominal: number;
  usd_real: number;
  referencia: string;
  estado_verificacion: "CONFIRMADO" | "PENDIENTE";
  verificado_por: string | null;
  conciliado: boolean;
  nota: string;
}

export interface CuentaPorCobrarResumen {
  id: number;
  venta_id: number;
  numero_venta: string | null;
  sucursal: string | null;
  fecha_venta: string | null;
  tipo: "CLIENTE" | "CASHEA";
  cliente: string;
  monto_original_usd: number;
  saldo_pendiente_usd: number;
  cashea_comision_venta_usd?: number;
  cashea_comision_financiado_usd?: number;
  cashea_iva_usd?: number;
  cashea_islr_usd?: number;
  cashea_total_cargos_usd?: number;
  cashea_neto_por_cobrar_usd?: number;
  estado: "PENDIENTE" | "PAGADA" | "ANULADA";
}

export interface ResultadoConciliacion {
  cuadrados: {
    pago_id: number;
    extracto_id: number;
    referencia: string;
    monto: number;
  }[];
  registrados_sin_banco: {
    pago_id: number;
    fecha: string;
    referencia: string;
    monto: number;
  }[];
  en_banco_sin_registrar: {
    extracto_id: number;
    fecha: string;
    referencia: string;
    descripcion: string;
    monto: number;
  }[];
}

export interface ComisionPersona {
  usuario_id: number;
  nombre: string;
  rol: string;
  ventas_pasillo_usd: number;
  porcentaje_pasillo: number;
  comision_pasillo_usd: number;
  ventas_leads_usd: number;
  porcentaje_leads: number;
  comision_leads_usd: number;
  ventas_promo_usd: number;
  comision_ventas_1_usd: number;
  comision_lider_05_usd: number;
  comision_servicios_50_usd: number;
  pago_preparaciones_usd: number;
  total_comision_usd: number;
}

export interface ReporteComisiones {
  mes: number;
  anio: number;
  mes_cerrado: boolean;
  comisiones: ComisionPersona[];
}

export type EstadoComision = "PENDIENTE" | "PAGADA" | "ANULADA";

export interface ResumenGeneralComisiones {
  total_ventas: number;
  volumen_promo_usd: number;
  pasillo_usd: number;
  lead_usd: number;
  pendiente_usd: number;
  pagado_usd: number;
  total_comisiones_usd: number;
}

export interface ComisionPorPersonaReporte {
  personal_id: number;
  nombre: string;
  rol: string;
  es_encargado: boolean;
  modalidad: string;
  telefono: string;
  porcentaje_pasillo: number;
  porcentaje_lead: number;
  cantidad_pasillo: number;
  base_pasillo_usd: number;
  comision_pasillo_usd: number;
  cantidad_lead: number;
  base_lead_usd: number;
  comision_lead_usd: number;
  pendiente_usd: number;
  pagado_usd: number;
  total_ventas: number;
  total_comision_usd: number;
}

export interface DetalleVentaComision {
  venta_id: number;
  personal_id: number;
  asesor: string;
  fecha: string;
  numero_venta: string;
  cliente: string;
  producto: string;
  origen: "PASILLO" | "LEAD" | string;
  estado_comision: EstadoComision | string;
  liquidacion_id: number | null;
  base_promo_usd: number;
  porcentaje_aplicado: number;
  comision_usd: number;
}

export interface ReporteComisionesAvanzado {
  fecha_inicio: string;
  fecha_fin: string;
  estado_comision: string;
  tasa_bcv_referencia: number | null;
  resumen_general: ResumenGeneralComisiones;
  por_persona: ComisionPorPersonaReporte[];
  detalle_ventas: DetalleVentaComision[];
}

export interface LiquidacionVentaItem {
  venta_id: number;
  fecha: string;
  numero_venta: string;
  cliente: string;
  producto: string;
  origen: string;
  base_promo_usd: number;
  porcentaje_aplicado: number;
  comision_usd: number;
}

export interface LiquidacionComisionResumen {
  id: number;
  codigo: string;
  personal_id: number;
  personal_nombre: string;
  personal_rol: string;
  personal_telefono: string;
  personal_modalidad: string;
  fecha_inicio: string;
  fecha_fin: string;
  cantidad_ventas: number;
  cantidad_pasillo: number;
  cantidad_lead: number;
  monto_pasillo_usd: number;
  monto_lead_usd: number;
  monto_total_usd: number;
  metodo_pago: string;
  instrumento_pago_id?: number | null;
  instrumento_pago_nombre?: string;
  instrumento_pago_moneda?: string;
  movimiento_financiero_id?: number | null;
  egreso_registrado?: boolean;
  tasa_bcv_aplicada: number | null;
  monto_bs: number | null;
  referencia: string;
  observaciones: string;
  estado: "PAGADA" | "ANULADA";
  motivo_anulacion: string;
  pagado_por: string | null;
  created_at: string | null;
  ventas?: LiquidacionVentaItem[];
}

export interface SaldoCajaCierre {
  instrumento_id: number;
  nombre: string;
  moneda: string;
  es_liquidez: boolean;
  saldo_inicial: number;
  entradas: number;
  salidas: number;
  saldo_final: number;
  saldo_inicial_usd: number;
  entradas_usd: number;
  salidas_usd: number;
  saldo_final_usd: number;
}

export interface ComparativaTiendaCierre {
  sucursal_id: number | null;
  nombre: string;
  cantidad_ventas: number;
  ventas_promo_usd: number;
  ingresos_usd: number;
  egresos_usd: number;
  flujo_neto_usd: number;
}

export interface MovimientoDiaCierre {
  id: number;
  hora: string;
  sede_id: number | null;
  sede_nombre: string;
  instrumento_id: number;
  instrumento_nombre: string;
  moneda: string;
  tipo_movimiento: "INGRESO" | "EGRESO" | string;
  tipo_documento: string;
  categoria: string;
  concepto: string;
  referencia: string;
  monto_moneda_origen: number;
  monto_usd: number;
}

export interface EgresosDiaCierre {
  total_usd: number;
  gastos_operativos_usd: number;
  envios_delivery_usd: number;
  nomina_usd: number;
  comisiones_usd: number;
  proveedores_prestamos_usd: number;
  impuestos_usd: number;
  otros_egresos_usd: number;
  items: {
    id: number;
    categoria_resumen: string;
    tipo_documento: string;
    categoria: string;
    concepto: string;
    instrumento: string;
    moneda: string;
    monto_moneda_origen: number;
    monto_usd: number;
    referencia: string;
  }[];
}

export interface CierreDiarioSnapshot {
  alcance?: "TIENDA" | "GENERAL";
  mensaje_whatsapp?: string;
  resumen_financiero?: {
    ingresos_totales_usd: number;
    egresos_totales_usd: number;
    flujo_neto_usd: number;
    liquidez_total_usd: number;
  } | null;
  egresos_dia?: EgresosDiaCierre | null;
  saldos_cajas?: SaldoCajaCierre[] | null;
  comparativa_tiendas?: ComparativaTiendaCierre[] | null;
  movimientos_dia?: MovimientoDiaCierre[] | null;
  operacion_general?: {
    traslados_despachados_hoy: number;
    traslados_recibidos_hoy: number;
    preparaciones_hoy: number;
    cashea_dia: {
      cantidad: number;
      total_regular_usd: number;
      inicial_usd: number;
      financiado_usd: number;
      cargos_usd: number;
      neto_por_cobrar_usd: number;
      cobrado_hoy_usd: number;
    };
  } | null;
  jornada: {
    fecha: string;
    sucursal_id: number | null;
    sucursal_nombre: string;
    encargado_sugerido_id: number | null;
    encargado_sugerido_nombre: string;
    encargados_disponibles: { id: number; nombre: string; rol: string }[];
    tasa_bcv: number;
    tasa_usdt: number;
    porcentaje_recargo: number;
    ya_cerrado: boolean;
    cierre_existente_id: number | null;
    observaciones_guardadas: string;
  };
  ventas_dia: {
    cantidad_total: number;
    total_promo_usd: number;
    total_regular_usd: number;
    pasillo_cantidad: number;
    pasillo_usd: number;
    lead_cantidad: number;
    lead_usd: number;
    cashea_cantidad: number;
    cashea_inicial_usd: number;
    cashea_financiado_usd: number;
  };
  recibido_por_instrumento: {
    total_usd: number;
    items: {
      instrumento_id: number;
      instrumento: string;
      moneda: string;
      cantidad_pagos: number;
      total_moneda_origen: number;
      total_usd: number;
    }[];
  };
  recepciones_almacen: {
    total_unidades: number;
    items: {
      origen: string;
      documento: string;
      tipo: string;
      descripcion: string;
      serial: string | null;
      cantidad: number;
    }[];
  };
  inventario: {
    salidas_hoy: {
      total_unidades: number;
      items: {
        motivo: string;
        documento: string;
        descripcion: string;
        serial: string | null;
        cantidad: number;
      }[];
    };
    disponible_cierre: {
      total_equipos: number;
      total_componentes: number;
      total_unidades: number;
      equipos_por_modelo: { modelo: string; categoria: string; cantidad: number }[];
      componentes_stock: { sku: string; descripcion: string; cantidad: number }[];
    };
  };
  garantias_casos: {
    recibidas_hoy: {
      numero_caso: string;
      tipo: string;
      cliente: string;
      equipo: string;
      serial: string;
      motivo: string;
    }[];
    resueltas_hoy: {
      numero: string;
      tipo: string;
      cliente: string;
      equipo: string;
      resolucion: string;
    }[];
    pendientes: {
      total: number;
      items: {
        numero_caso: string;
        tipo: string;
        cliente: string;
        equipo: string;
        serial: string;
        estado: string;
        fecha_ingreso: string;
      }[];
    };
  };
  ventas_por_asesor: {
    personal_id: number;
    nombre: string;
    rol: string;
    modalidad: string;
    cantidad_pasillo: number;
    cantidad_lead: number;
    total_ventas: number;
    total_usd: number;
  }[];
  ventas_tienda_sin_asesor: {
    cantidad: number;
    total_usd: number;
  };
}

export interface CierreDiarioHistorialItem {
  id: number;
  fecha: string;
  sucursal_id: number | null;
  sucursal_nombre: string;
  encargado_tienda_id: number;
  encargado_tienda_nombre: string;
  tasa_bcv: number;
  tasa_usdt: number;
  porcentaje_recargo: number;
  observaciones: string;
  cerrado_por: string | null;
  created_at: string | null;
  resumen: CierreDiarioSnapshot;
}

export interface TableroFinanciero {
  desde: string;
  hasta: string;
  cantidad_ventas: number;
  venta_promo_usd: number;
  usd_nominal: number;
  usd_real: number;
  diferencial_cambiario_usd: number;
  cashea_por_cobrar_usd: number;
  costo_total_usd: number;
  utilidad_real_neta_usd: number;
}
