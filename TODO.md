# TODO — Nexo

Prioridad de arriba hacia abajo. Ver `PROGRESS.md` para lo ya hecho.

## Inmediato
- [x] Commitear y pushear las features de la sesión — hecho 14 sept 2026 (commits
      9b3e066 … 8351227 en origin/master).

## Mercado Libre / rentabilidad
- [x] **Costo de envío real por publicación** — hecho 14 sept 2026 (ver PROGRESS.md),
      sin peso ni medidas. Pendiente: verlo en pantalla logueado.
- [x] **Autor y Editorial** al publicar libros — resuelto 14 sept 2026 sin columnas nuevas:
      `/validar` los sugiere desde el catálogo real de ML, precargados "Por confirmar".
- [x] Dato del usuario: "repiza de habitacion" — corregido por el dueño (14 sept 2026).

## Admin BI — extensiones opcionales (el spec original quedó cortado en la sección 8)
- [x] Gráfico dedicado de **evolución del margen** en el tiempo — hecho 14 sept 2026
      (`margenEnElTiempo` en /api/admin/overview + panel en el Overview). Falta verlo
      logueado como admin con ventas reales (hoy hay 0 órdenes).
- [x] Sección **"Clientes que necesitan atención"** — hecha 14 sept 2026 (ver PROGRESS.md).
      Falta solo verla logueado como admin en el navegador.
- [x] Errores de sincronización por empresa — hecho 14 sept 2026: se registran en
      `SyncJob`/`SyncLog` (ya existían, nadie escribía) y el admin los ve (atención + detalle).
- [x] Devoluciones por empresa — hecho 14 sept 2026: `order_returns` (migración
      `e5a7c9b1d3f4`), se sincronizan al importar ventas (reclamos `return` + mediaciones con
      devolución), `GET /api/mercadolibre/devoluciones`, panel en Mercado Libre y en el detalle
      admin. Sincronización real OK (HTTP 200, 0 reclamos hoy). Falta verlo con una devolución
      real. Una venta con devolución reembolsada ("refunded") ya no suma a las métricas del
      admin (excluye la orden completa; un reembolso parcial todavía no se distingue).
- [x] Conciliación de comisiones con la facturación de ML — hecha 14 sept 2026
      (`GET /billing/integration/group/ML/order/details`, verificado en vivo HTTP 200 con 0
      cargos). Falta verla con ventas reales facturadas.
- [x] Adjuntar la factura PDF/XML del vendedor a cada venta — hecho 15 sept 2026
      (`/api/mercadolibre/facturas`, `POST`/`DELETE /packs/{pack_id}/fiscal_documents`). Nexo
      NO emite boletas/facturas SII ni guarda el archivo. Falta probarlo con una venta real.

## Revisión de experiencia (15 sept 2026) — decidir qué corregir
- [x] Críticos 1–8 de `REVISION_EXPERIENCIA.md` — corregidos 15 sept 2026 (PROGRESS.md #30).
      La pantalla de revisión de Google Sheets todavía no se recalcula al corregir columnas.
- [ ] Importantes 9–18 y menores 19–28 del mismo documento.
- [ ] Cuentas de prueba `*@revision.nexo.local` en `nexo.db` de desarrollo: borrarlas cuando se
      termine de revisar (respaldo previo en el scratchpad de la sesión).

## Deploy (día del despliegue, ver backend/DEPLOY.md)
- [ ] **Servicio de mail** — código listo (`EnviadorResend`, `RESEND_API_KEY`/`EMAIL_FROM` en
      render.yaml). Falta del dueño: cuenta Resend, dominio verificado y la API key.
- [ ] **Cron diario** — definido en render.yaml (`python -m app.services.lifecycle`). Se activa
      solo al desplegar en Render.
- [x] Migraciones verificadas para el deploy (15 sept 2026): `upgrade head` desde una base
      vacía OK, downgrade/upgrade de las últimas OK, 0 diferencias entre el esquema migrado y
      los modelos, y SQL offline para Postgres generado sin errores (la migración de datos
      `c9e1a3b5d7f2` solo corre online, que es lo que hace el preDeploy de Render).
- [ ] Despliegue real: Render (backend) + Supabase (Postgres) + dominio. Reemplaza el
      túnel ngrok por el dominio HTTPS propio en el redirect de OAuth de ML.
- [ ] **Términos y Condiciones + Privacidad** — borradores hechos 15 sept 2026 en `legal/`
      (describen lo que el código guarda hoy, incluido el modo soporte "ver como empresa").
      Falta del dueño: revisión de un abogado (Ley 19.628 y 21.719), completar los
      `[CORCHETES]` (razón social, RUT, correos, plazos, IVA, reembolsos, responsabilidad) y
      recién ahí reemplazar `TEXTO_TERMINOS_INTERINO` en `frontend/js/app.js`.
