"use client";

import React from "react";

interface LogoAlfaProps {
  variante?: "horizontal" | "vertical" | "isotipo";
  tema?: "oscuro" | "claro" | "mono-blanco";
  tamano?: "sm" | "md" | "lg";
  className?: string;
}

/**
 * Componente oficial del imagotipo de Alfa Digital Store (ALFA IMPORTACIONES, C.A.).
 * Usa los PNG oficiales en /public/brand/ respetando proporción y zona de respeto.
 */
export default function LogoAlfa({
  variante = "horizontal",
  tema = "claro",
  tamano = "md",
  className = "",
}: LogoAlfaProps) {
  if (variante === "isotipo") {
    const dim = tamano === "sm" ? 28 : tamano === "lg" ? 56 : 36;
    return (
      <div
        className={`inline-flex items-center justify-center p-1 select-none ${className}`}
      >
        <img
          src="/brand/alfa-isotipo.png"
          alt="Alfa Digital Store"
          width={dim}
          height={dim}
          className="object-contain shrink-0"
          style={{ width: dim, height: dim }}
        />
      </div>
    );
  }

  const rutaHorizontal =
    tema === "claro"
      ? "/brand/alfa-logo-horizontal.png"
      : "/brand/alfa-logo-horizontal-blanco.png";

  const altura =
    variante === "vertical"
      ? tamano === "lg"
        ? 56
        : tamano === "sm"
        ? 30
        : 42
      : tamano === "lg"
      ? 54
      : tamano === "sm"
      ? 30
      : 38;

  return (
    <div
      className={`inline-flex items-center py-1 px-0.5 select-none ${className}`}
    >
      <img
        src={rutaHorizontal}
        alt="Alfa Digital Store"
        className="object-contain w-auto max-w-full"
        style={{ height: altura }}
      />
    </div>
  );
}
