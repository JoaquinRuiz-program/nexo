# Estado del proyecto — Nexo

_Actualizado: 14 de septiembre de 2026._ Etapa: Production Release Candidate.

## Terminado y verificado esta sesión (SIN COMMITEAR todavía)
Cinco features completas, con tests dedicados y verificadas en vivo. Están en el
working tree sin commitear (ver `git status`); el usuario commitea con confirmación.

1. **Importador: detección de la fila de encabezados** (`backend/app/domain/spreadsheet_io.py`)
   — encuentra la fila de encabezados real (salta título/instrucciones/blancos de
   arriba) y corta la tabla en la primera fila en blanco tras los datos (ignora notas
   al pie). Antes, una planilla con título arriba "no reconocía nada".
2. **Eliminar producto** (`backend/app/api/routes/productos_db.py` `DELETE /api/productos/{variant_id}`
   + menú de fila en `frontend/js/app.js`) — borra el producto completo; **bloquea (409)
   si está publicado en ML** (hay que despublicar primero); desvincula ventas
   (`OrderItem.variant_id → None`, conserva el historial); borra movimientos de stock;
   IDOR → 404.
3. **Margen neto + recomendación automática de tipo de publicación**
   (`backend/app/domain/ml_fees.py::recomendar_tipo_publicacion`, enchufado en
   `rentabilidad.py::_fila`) — el sistema elige solo **Clásica vs Premium** por producto
   con la comisión **exacta** de cada uno: Clásica por defecto (más utilidad), sube a
   Premium solo si el margen supera el objetivo del canal. Oportunidades del importador
   (`frontend/js/importFlow.js`) ahora muestra margen NETO de ML + columna "Publicar como".
4. **Rentabilidad antes + auto-relleno de atributos**
   (`backend/app/api/routes/publicaciones.py`) — `/decision` (paso "¿Conviene?") aplica
   el mismo gate de margen mínimo que la publicación → dice "no conviene" al inicio, no
   recién en Revisar. `_datos_conocidos_ml` auto-completa **Título del libro** (del nombre)
   e **ISBN/GTIN** (del código de barras) al publicar.
5. **Admin BI Dashboard** — `GET /api/admin/overview` (`backend/app/api/routes/admin.py`
   + módulo puro `backend/app/domain/admin_overview.py`, ARCHIVO NUEVO sin commitear):
   KPIs (GMV, margen, ventas, unidades, empresas/productos/publicaciones/usuarios
   activos), ventas por empresa, serie temporal, top empresas, analytics de ML,
   crecimiento SaaS. Filtros período/empresa/canal. **Solo `is_nexo_admin`**, global,
   datos reales, ceros/`Sin datos suficientes` honestos, nunca cuenta la tienda del
   admin. Frontend: nueva pestaña **Overview** premium (`frontend/js/adminPanel.js`) con
   tarjetas KPI, gráfico de línea + dona SVG (`frontend/js/chart.js`, sin librería),
   ranking sortable, sección ML y crecimiento. CSS en `frontend/css/styles.css`.

**Tests**: **798 pasando** (suite completa, exit 0). Áreas nuevas verificadas:
publicaciones (193), admin overview (5), ml_fees+rentabilidad (38), productos_db (63),
catálogo (52).

## Estado del entorno / datos reales
- **Mercado Libre conectado** en la cuenta de prueba (`demo@nexo.local`, seller MLC
  JOACORUIZDUENAS). Comisiones reales cacheadas para 6/7 productos importados.
- **Ventas: 0 órdenes** en la base → todo KPI de ventas/GMV/margen muestra `0` /
  `Sin datos suficientes` (correcto: aún no se importaron ventas de ML).
- El túnel **ngrok** debe estar corriendo para el OAuth de ML (ver CLAUDE.md).
- Único admin de plataforma: `joacoruizduenas@gmail.com`. `demo@nexo.local` es cliente.

6. **Admin Overview: "Clientes que necesitan atención"** (sin commitear) —
   `admin_overview.py::motivos_de_atencion` (pura, reusa `subscription_lifecycle`) +
   `admin.py::_clientes_que_necesitan_atencion` → campo `atencion` de `/api/admin/overview`.
   Motivos reales: sin suscripción, plan vencido / en gracia, pago pendiente, cancelada,
   prueba que vence en ≤7 días, ML con token vencido, sin ML, sin productos, soporte sin
   resolver. Omite suspendidos; respeta el filtro de empresa; ordena por severidad.
   Frontend: panel bajo los KPIs (`adminPanel.js?v=16`, `styles.css?v=7`). 3 tests nuevos.
7. **Costo de envío REAL de Mercado Libre por publicación** (sin commitear) — sin pedir
   peso ni medidas. `GET /items/{id}` (shipping) + `GET /users/{id}/shipping_options/free?item_id=`
   (`coverage.all_country.list_cost`, doc oficial "Management of shipping fees": solo ítems
   activos con Mercado Envíos). Interpretación pura en `domain/ml_shipping.py`, orquestación
   best effort en `services/ml_shipping_sync.py`, columnas `shipping_*` en
   `marketplace_listings` (migración `b8d2f4a6c1e3`, ya aplicada a `nexo.db`). Se sincroniza
   al conectar ML, al importar ventas, al actualizar comisiones y al publicar; un error de
   red no pisa el último costo real. Rentabilidad (`rentabilidad.py::aplicar_envio_real_ml`,
   también en /precio-recomendado, /decision y /decision-lote): usa el envío real; sin él,
   `envioMlFuente = "no_disponible"` + motivo + `rentabilidadMlProvisional`. Nunca estima.
   Frontend: columna "Costo de envío" en Oportunidades, línea de envío en Revisar publicación,
   "Provisional" en el importador (`app.js?v=44`, `mercadolibrePublicar.js?v=14`, `importFlow.js?v=7`).
   **Validado contra la API real (14 sept 2026)**, con `importar_ventas` de la tienda 2: el
   token vencido se renovó bien; ML devolvió `list_cost` 3400 CLP para MLC2219784709
   (descuento "mandatory" 50%) y quedó guardado en `nexo.db`. Dos hallazgos corregidos:
   la API informa el costo también de ítems no activos (se quitó ese filtro), y el estado
   local estaba viejo (Nexo "active", ML "closed"): la sincronización ahora lo actualiza.
   Como la publicación está CERRADA en ML, Rentabilidad no la cuenta (muestra "No
   disponible", provisional). No hay publicaciones activas para ver el costo en pantalla.

## En progreso
- Nada a medias. El Admin BI cubre lo pedido (secciones 1–8); ver `TODO.md` para las
  extensiones opcionales que quedaron fuera de alcance a propósito.

## Pendiente
Ver `TODO.md`.
