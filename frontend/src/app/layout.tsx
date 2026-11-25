import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import SplashAlfa from "@/components/SplashAlfa";
import { ProveedorSesion } from "@/contexto/SesionContexto";
import "./globals.css";

const plusJakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "700"],
  variable: "--font-plus-jakarta",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Sistema Administrativo · Alfa Digital Store",
  description:
    "Sistema administrativo centralizado de Alfa Importaciones, C.A. (Alfa Digital Store).",
  icons: {
    icon: [{ url: "/alfa-favicon.png?v=alfa1", type: "image/png" }],
    shortcut: "/alfa-favicon.png?v=alfa1",
    apple: "/alfa-favicon.png?v=alfa1",
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
