# TODO — Nexo

Prioridad de arriba hacia abajo. Ver `PROGRESS.md` para lo ya hecho.

## Inmediato
- [ ] **Commitear las 5 features de esta sesión** (están sin commitear). Sugerencia de
      commits separados: (1) importador encabezados, (2) eliminar producto, (3) margen
      neto + recomendación de tipo de publicación, (4) rentabilidad en paso 1 +
      auto-relleno de atributos, (5) Admin BI dashboard. Luego `git push`.
      Recordar: no commitear sin confirmación del usuario.

## Mercado Libre / rentabilidad
- [x] **Costo de envío real por publicación** — hecho 14 sept 2026 (ver PROGRESS.md),
      sin peso ni medidas. Pendiente: verlo en pantalla logueado.
- [ ] **Autor y Editorial** al publicar libros: no están en el catálogo. Definir si se
      importan como columnas del Excel o se dejan manuales en la revisión.
- [ ] Dato del usuario: corregir "repiza de habitacion" → "repisa" para que ML le
      encuentre categoría al recalcular comisiones.

## Admin BI — extensiones opcionales (el spec original quedó cortado en la sección 8)
- [ ] Gráfico dedicado de **evolución del margen** en el tiempo (hoy hay serie de ventas
      + KPIs de margen, no una serie temporal de margen).
- [x] Sección **"Clientes que necesitan atención"** — hecha 14 sept 2026 (ver PROGRESS.md).
      Falta solo verla logueado como admin en el navegador.
- [ ] Devoluciones/errores de sincronización por empresa: hoy no hay modelo de errores
      por tienda (solo logs de servidor). No inventar; construir el modelo si se necesita.

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
