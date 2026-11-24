import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import SplashTekio from "@/components/SplashTekio";
import { ProveedorSesion } from "@/contexto/SesionContexto";
import "./globals.css";

const plusJakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "700"],
  variable: "--font-plus-jakarta",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Sistema Administrativo · Alfa Importaciones",
  description:
    "Sistema administrativo centralizado de Alfa Importaciones.",
};

export default function DisenoRaiz({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className={plusJakarta.variable}>
      <body className="font-sans antialiased min-h-screen text-[#191818]">
        <SplashTekio />
        <ProveedorSesion>{children}</ProveedorSesion>
      </body>
    </html>
  );
}
