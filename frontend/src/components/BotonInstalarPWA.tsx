"use client";

import React, { useEffect, useState } from "react";
import { Download, Share, Smartphone, X } from "lucide-react";

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export default function BotonInstalarPWA({ compacto = false }: { compacto?: boolean }) {
  const [eventoInstalacion, setEventoInstalacion] =
    useState<BeforeInstallPromptEvent | null>(null);
  const [esIOS, setEsIOS] = useState(false);
  const [yaInstalada, setYaInstalada] = useState(false);
  const [modalIOSAbierto, setModalIOSAbierto] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;

    // Registrar Service Worker ligero
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // Ignorar si el navegador restringe SW en modo incógnito
      });
    }

    const modoStandalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      (window.navigator as Navigator & { standalone?: boolean }).standalone === true;
    if (modoStandalone) {
      setYaInstalada(true);
      return;
    }

    const ua = window.navigator.userAgent.toLowerCase();
    const iosDetectado = /iphone|ipad|ipod/.test(ua);
    setEsIOS(iosDetectado);

    const onBeforeInstall = (e: Event) => {
      e.preventDefault();
      setEventoInstalacion(e as BeforeInstallPromptEvent);
    };
    const onAppInstalled = () => {
      setYaInstalada(true);
      setEventoInstalacion(null);
    };

    window.addEventListener("beforeinstallprompt", onBeforeInstall);
    window.addEventListener("appinstalled", onAppInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstall);
      window.removeEventListener("appinstalled", onAppInstalled);
    };
  }, []);

  if (yaInstalada) return null;

  const manejarClick = async () => {
    if (eventoInstalacion) {
      await eventoInstalacion.prompt();
      const { outcome } = await eventoInstalacion.userChoice;
      if (outcome === "accepted") {
        setYaInstalada(true);
        setEventoInstalacion(null);
      }
      return;
    }
    setModalIOSAbierto(true);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => void manejarClick()}
        title="Instalar Alfa Admin como aplicación"
        className={`inline-flex items-center justify-center gap-1.5 rounded-xl border border-[#003566]/25 bg-[#EDF3FA] text-[#003566] hover:bg-[#003566] hover:text-white transition text-xs font-semibold cursor-pointer ${
          compacto ? "px-2.5 py-1.5" : "w-full px-3 py-2"
        }`}
      >
        <Download className="h-3.5 w-3.5 shrink-0" />
        <span>Instalar App</span>
      </button>

      {modalIOSAbierto && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-xs">
          <div className="w-full max-w-sm overflow-hidden rounded-2xl bg-white shadow-2xl border border-slate-200">
            <div className="flex items-center justify-between bg-[#003566] px-5 py-3.5 text-white">
              <div className="flex items-center gap-2">
                <Smartphone className="h-4 w-4 text-sky-300" />
                <h3 className="text-sm font-bold">Instalar Alfa Admin</h3>
              </div>
              <button
                type="button"
                onClick={() => setModalIOSAbierto(false)}
                className="rounded-lg p-1 hover:bg-white/10"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 p-5 text-sm text-slate-700">
              {esIOS ? (
                <>
                  <p className="text-xs text-slate-600">
                    Para instalar <strong>Alfa Admin</strong> en tu iPhone o iPad desde Safari:
                  </p>
                  <ol className="space-y-2.5 text-xs">
                    <li className="flex items-start gap-2.5 rounded-xl bg-slate-50 p-3 border border-slate-200">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#003566] text-[11px] font-bold text-white">
                        1
                      </span>
                      <span>
                        Toca el botón{" "}
                        <strong className="inline-flex items-center gap-1 text-[#003566]">
                          <Share className="h-3.5 w-3.5" /> Compartir
                        </strong>{" "}
                        en la barra inferior de Safari.
                      </span>
                    </li>
                    <li className="flex items-start gap-2.5 rounded-xl bg-slate-50 p-3 border border-slate-200">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#003566] text-[11px] font-bold text-white">
                        2
                      </span>
                      <span>
                        Desliza y selecciona{" "}
                        <strong className="text-[#001D3D]">
                          Agregar a pantalla de inicio
                        </strong>{" "}
                        y confirma con <strong>Agregar</strong>.
                      </span>
                    </li>
                  </ol>
                </>
              ) : (
                <div className="space-y-2 text-xs text-slate-600">
                  <p>
                    En <strong>Windows, Mac o Android</strong> (Chrome / Edge):
                  </p>
                  <p className="rounded-xl bg-slate-50 p-3 border border-slate-200">
                    Haz clic en el ícono de <strong>Instalar</strong> en la barra de
                    direcciones o abre el menú del navegador y selecciona{" "}
                    <strong>Instalar Alfa Admin / Agregar a pantalla principal</strong>.
                  </p>
                </div>
              )}
              <button
                type="button"
                onClick={() => setModalIOSAbierto(false)}
                className="w-full rounded-xl bg-[#003566] py-2 text-xs font-bold text-white hover:bg-[#001D3D]"
              >
                Entendido
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
