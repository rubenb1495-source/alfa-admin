import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import SplashAlfa from "@/components/SplashAlfa";
import { MARCA_ALFA } from "@/config/brand";
import { ProveedorSesion } from "@/contexto/SesionContexto";
import "./globals.css";

const plusJakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "700"],
  variable: "--font-plus-jakarta",
  display: "swap",
});

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#003566",
};

export const metadata: Metadata = {
  title: MARCA_ALFA.tituloApp,
  description: `Sistema administrativo centralizado de ${MARCA_ALFA.razonSocial} (${MARCA_ALFA.nombreComercial}).`,
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Alfa",
  },
  icons: {
    icon: [
      { url: "/alfa-favicon.png?v=alfa1", type: "image/png" },
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
    ],
    shortcut: "/alfa-favicon.png?v=alfa1",
    apple: [{ url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
  },
};

export default function DisenoRaiz({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className={plusJakarta.variable}>
      <body className="font-sans antialiased min-h-screen text-[#000814]">
        <SplashAlfa />
        <ProveedorSesion>{children}</ProveedorSesion>
      </body>
    </html>
  );
}
