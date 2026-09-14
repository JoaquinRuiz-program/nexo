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
- [ ] Devoluciones por empresa — investigado 14 sept 2026 contra la API real:
      `GET /post-purchase/v1/claims/search` (tipos mediations, cancel_purchase, return,
      cancel_sale; vínculo con la orden por `resource_id`) y
      `GET /post-purchase/v2/claims/{claim_id}/returns` (status, status_money, refund_at,
      envío de vuelta, revisión del producto). La app YA tiene permiso (HTTP 200). Exige al
      menos un filtro real (`type`/`status`/`stage`…); `players.role`+`players.user_id` solos
      dan 400. Hoy: 0 reclamos y 0 órdenes en Nexo. Pendiente decidir construirlo (sincronizar
      reclamos al importar ventas y mostrarlos por empresa) cuando haya ventas reales.

## Deploy (día del despliegue, ver backend/DEPLOY.md)
- [ ] **Servicio de mail** (Resend/SendGrid) + `noreply` para los recordatorios de
      vencimiento de suscripción (hoy van al log).
- [ ] **Cron diario** que dispare `python -m app.services.lifecycle` (recordatorios +
      pausa por vencimiento). Requiere `--workers 1`.
- [ ] Despliegue real: Render (backend) + Supabase (Postgres) + dominio. Reemplaza el
      túnel ngrok por el dominio HTTPS propio en el redirect de OAuth de ML.
- [ ] **Términos y Condiciones + Privacidad**. Redactar con cuidado: el claim "los
      admins solo ven números agregados" NO es literal por "ver como empresa" — decirlo
      con verdad. Considerar Ley 21.719 (diciembre 2026).
