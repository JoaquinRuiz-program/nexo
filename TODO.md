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

- [x] **Regla estricta del envío** (16 sept 2026, PROGRESS.md #44): sin costo de envío de
      Mercado Libre, Nexo dice "Faltan datos" en vez de "Conviene"/"No conviene".
      Consecuencia a revisar: el **envío manual de Configuración ya no decide** nada en
      Mercado Libre. Si quieres que vuelva a contar como dato válido, es un cambio de una
      línea; si no, conviene sacar ese campo de Configuración para no ofrecer algo que no se usa.
- [x] **Obtención automática del envío al importar, con progreso en vivo** (16 sept 2026,
      PROGRESS.md #45) — al subir el Excel, Nexo intenta solo el costo de envío real/estimado
      de cada producto, sin pedir peso ni medidas, con pantalla de progreso. Verificado en vivo
      contra la cuenta real (201/201 productos resueltos). De paso corregido: el botón manual
      no pasaba `user_id`, así que nunca estimaba el envío.
      **Límite real de la API, no una falta de Nexo**: un producto sin publicación Y sin
      categoría que Mercado Libre pueda predecir (`domain_discovery`) no tiene ningún camino
      para obtener un costo de envío sin dimensiones — Mercado Libre no ofrece una cotización
      por texto/SKU sola. Ese caso queda en "Faltan datos"; no hay nada más que automatizar ahí
      sin pedirle una medida al dueño (que es justo lo que se pidió evitar).

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
      La revisión de Google Sheets ya se recalcula al corregir columnas (PROGRESS.md #33).
- [x] Importantes 9–18 — corregidos 15 sept 2026 (PROGRESS.md #31). El precio recomendado ya
      se redondea hacia arriba a un precio "de vitrina" terminado en 990 (PROGRESS.md #34).
- [x] Menores 19–28 del mismo documento — corregidos 15 sept 2026 (PROGRESS.md #32).
- [x] Cuentas de prueba `*@revision.nexo.local` borradas de `nexo.db` de desarrollo (15 sept 2026).

## QA integral (15 sept 2026) — ver `QA_INTEGRAL.md`
- [x] 6 bugs corregidos (PROGRESS.md #35).
- [x] **P1 — Ventas en modo real** — hecho 15 sept 2026 (PROGRESS.md #36). Falta verlo con
      ventas reales importadas de Mercado Libre.
- [x] Productos sin costo de compra (costo considerado $0) — hecho 15 sept 2026 (PROGRESS.md #37).

## Revisión del sistema (16 sept 2026) — ver `REVISION_SISTEMA.md`
- [x] Webhook de Mercado Pago idempotente + el período se suma al que quedaba (PROGRESS.md #43).
- [x] Importación de ventas paginada (antes se perdían los pedidos después del 50).
- [ ] **Cobro mensual del mes 2 en adelante** (`subscription_authorized_payment`): hoy no se
      procesa, así que un cliente mensual cuyo cobro falla sigue con acceso completo. Decidir
      y construir (REVISION_SISTEMA.md §2.1).
- [ ] Publicación que deja de convenir con el envío real: decidir si Nexo pausa solo, ajusta
      el precio o solo avisa (REVISION_SISTEMA.md §2.3).
- [ ] Comisión real cacheada sin vencimiento (el envío estimado ya vence a los 30 días).
- [ ] Antes de escalar a más de un worker: mover a algo compartido el estado de OAuth y el
      límite de intentos de login (hoy viven en memoria del proceso).

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
