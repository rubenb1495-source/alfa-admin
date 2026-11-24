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

## 3. Pendientes de Personalización para Alfa Importaciones
1. **Identidad Visual (`/frontend` y PDFs):**
   - Definir paleta de colores corporativos en `frontend/src/app/globals.css`.
   - Reemplazar logos en `frontend/public/brand/` y `backend-python/assets/` (y regenerar marca de agua `*-watermark.png`).
   - Actualizar razón social, RIF, teléfonos, políticas de garantía y encabezados en `backend-python/app/servicios/pdf_nota.py`, `pdf_documentos.py`, `frontend/src/lib/whatsapp.ts` y `frontend/src/components/LogoTekio.tsx`.
2. **Semilla y Datos Iniciales:**
   - Actualizar sucursales y usuario administrador inicial en `backend-python/app/semilla.py`.
3. **Infraestructura Independiente:**
   - Crear repositorio GitHub propio para Alfa Importaciones.
   - Crear base de datos Neon PostgreSQL propia.
   - Crear proyectos independientes en Vercel (`alfa-importaciones-api` y `alfa-importaciones-web`).

## 4. Última Actualización
- **Fecha:** 2026-11-24
- **Último cambio:** Creación del clon limpio e independiente `alfa-importaciones-admin` sin credenciales, historial Git ni base de datos del proyecto original. Listo para aplicar el nuevo diseño visual de Alfa Importaciones.
