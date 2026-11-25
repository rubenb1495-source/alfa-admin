export const MARCA_ALFA = {
  nombreComercial: "Alfa Digital Store",
  nombreCorto: "Alfa",
  tituloApp: "Alfa Admin — Sistema Administrativo",
  razonSocial: "ALFA IMPORTACIONES, C.A.",
  rif: "J-50793794-1",
  direccionPrincipal: "CC Free Market, Local T38, Naguanagua, Valencia",
  urlApp: "https://alfa-admin-web.vercel.app",
  sucursales: [
    "Almacén Guaparo Norte",
    "Local T38",
    "Local V30-V31",
  ] as const,
  colores: {
    primario: "#003566",
    secundario: "#001D3D",
    tinta: "#000814",
    superficie: "#EDF3FA",
    fondo: "#F7F9FC",
  },
  rutasBrand: {
    logo: "/brand/logo-alfa.png",
    logoBlanco: "/brand/alfa-logo-horizontal-blanco.png",
    isotipo: "/brand/isotipo-alfa.png",
  },
} as const;
