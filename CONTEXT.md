# CONTEXTO DEL PROYECTO: Sistema Administrativo Alfa Importaciones

## 1. Visión General
- **Empresa:** Alfa Importaciones
- **Origen:** Clon limpio e independiente del sistema administrativo base (FastAPI + SQLAlchemy + Next.js 15 + TypeScript + Tailwind CSS v4 + ReportLab).
- **Objetivo:** Personalizar identidad visual (paleta, tipografía, logos, marca de agua PDF, razón social, RIF, garantías, sucursales) y conectar su propia base de datos PostgreSQL (Neon) y despliegue independiente en Vercel.

## 2. Arquitectura y Convenciones
- **Backend (`/backend-python`):** FastAPI + SQLAlchemy 2.0 + Pydantic v2 + ReportLab (PDFs con marca de agua) + PyJWT.
- **Frontend (`/frontend`):** Next.js 15 (App Router) + React 19 + TypeScript estricto + Tailwind CSS v4 + Lucide Icons.
- **Idioma:** Todo el código, variables, rutas, base de datos, textos de UI, PDFs y commits estrictamente en **español**.
- **Seguridad y RBAC:** Roles `DIRECCION`, `ADMINISTRACION`, `LOGISTICA`, `TECNICO`, `LIDER`, `ASESORA`. Nunca exponer costos internos, márgenes ni proveedores a `ASESORA` o `TECNICO`.

## 3. Personalización Aplicada para Alfa Importaciones
1. **Identidad Visual (`/frontend` y PDFs) — COMPLETADO:**
   - **Tema claro corporativo** en `frontend/src/app/globals.css`: blanco `#FFFFFF`, fondo `#F7F9FC`, Azul Alfa primario `#003566`, hover `#001D3D`, texto marino `#000814` y acento suave `#EDF3FA`.
   - **Logos y marca de agua:** Generados desde el logo oficial **ALFA Digital Store** en `frontend/public/brand/` (`alfa-logo-horizontal.png`, `alfa-logo-horizontal-blanco.png`, `alfa-isotipo.png`) y `backend-python/assets/` (`alfa-logo-horizontal.png`, `alfa-isotipo.png`, `alfa-watermark.png` al 7% de opacidad).
   - **Componentes y textos:** Reemplazados por `LogoAlfa.tsx`, `SplashAlfa.tsx`, encabezados PDF (`pdf_nota.py`, `pdf_documentos.py`, `pdf_branding.py`) y plantillas WhatsApp (`whatsapp.ts`) con razón social `ALFA IMPORTACIONES, C.A.`, RIF `J-50793794-1` y dirección `CC Free Market, Local T38, Naguanagua, Valencia`.
2. **Semilla y Datos Iniciales — COMPLETADO:**
   - `backend-python/app/semilla.py` actualizado con las 3 sedes: **Almacén Guaparo Norte**, **Local T38** (sede central por defecto) y **Local V30-V31**, y usuario administrador inicial `direccion@alfaimportaciones.com` (clave inicial `Alfa2026!`).
3. **Pendientes de Infraestructura Independiente:**
   - Crear repositorio GitHub propio para Alfa Importaciones.
   - Crear base de datos Neon PostgreSQL propia.
   - Crear proyectos independientes en Vercel (`alfa-importaciones-api` y `alfa-importaciones-web`).

## 4. Última Actualización
- **Fecha:** 2026-11-24
- **Último cambio:** Personalización completa de identidad visual clara (blanco + azules `#003566` / `#001D3D` / `#000814`), logos de ALFA Digital Store, marca de agua PDF, datos fiscales (`ALFA IMPORTACIONES, C.A.` / `RIF J-50793794-1`) y sucursales iniciales en `semilla.py`.
