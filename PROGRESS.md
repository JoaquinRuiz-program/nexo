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

8. **Atributos sugeridos desde el catálogo real de ML** (14 sept 2026) — `/validar` busca el
   producto en el catálogo (misma búsqueda que /competencia) y devuelve `valorSugerido` para
   los atributos faltantes (ej. Autor, Editorial de un libro; verificado en vivo: "Cien años
   de soledad" -> Autor "Gabriel García Márquez"). Quedan precargados y marcados "Por
   confirmar". El ISBN solo se sugiere si la búsqueda fue por código de barras (por nombre
   podría ser otra edición). Best effort: sin catálogo, se completa a mano como antes.
9. **Oportunidades coherente con "¿Conviene?"** (14 sept 2026) — Oportunidades ahora usa el
   margen NETO de ML y el mismo margen mínimo de Configuración (`/api/seleccion` lo toma por
   defecto con canal ML; `/decision-lote` aplica el mismo gate que `/decision`). "Margen bajo"
   pasa al grupo "No conviene todavía". Nunca más "Alta oportunidad" y después "no conviene".
   Ojo datos: en Empresa Demo hay productos "Ej: ..." (LIB-001, ESC-014) que parecen filas de
   ejemplo de la plantilla importadas como productos.

10. **Imágenes: subida directa a Mercado Libre** (14 sept 2026, sin commitear) — caso real
    MLC2244564341: Nexo mandaba `source: http://localhost:8000/uploads/...`, ML no pudo
    descargarla y pausó la publicación (`sub_status: picture_download_pending`). Ahora, al
    confirmar, una imagen guardada en Nexo se sube con sus bytes (`POST /pictures/items/upload`,
    doc oficial "Pictures") y se publica por `id`; una URL externa se manda igual. Archivo
    perdido -> 400 sin publicar. Validado en vivo: ML rechazó la foto del volante por medir
    290 × 290 px (pide al menos 500 px en un lado, sin bordes blancos). Ahora Nexo lo avisa
    antes de llamar a ML, con las medidas, y traduce ese rechazo de ML (nunca "probá JPG/PNG").
    MLC2244564341 quedó `inactive` en ML: la API no permite cerrarla
    (`item.status.not_modifiable`). Con fotos nuevas (500 × 499 y 399 × 501 px) el volante se
    republicó en vivo: MLC4479906612 `active`, sin sub_status, 2 fotos subidas por `id`
    (mlstatic), 4 unidades, envío real $7.200. Minutos después llegó desde la UI un segundo
    "Eliminar publicación" y la cerró (`closed`, terminal en ML): Nexo guarda UNA fila de
    publicación por producto, así que el botón ya apuntaba a la nueva. El dueño confirmó que
    la eliminó a propósito (era de prueba): no se republica.
12. **Oportunidades separa lo ya publicado** (14 sept 2026, sin commitear) — los productos con
    publicación activa/pausada van a "Publicados en Mercado Libre" (con su estado y aviso si el
    margen con envío real quedó bajo el mínimo), no a los grupos de oportunidad; los contadores
    solo cuentan lo que falta publicar. Campo nuevo `publicacionMlEstado` en la fila de
    rentabilidad. Productos: sin stock de tienda pero con unidades para ML muestra
    "N para Mercado Libre" en vez de "Sin stock".
13. **Importador: "Precio de Compra" / "Precio de Venta Recomendado"** (14 sept 2026, sin
    commitear) — caso real (Inventario_200_Productos_V2.xlsx): el matching parcial de
    "precio" tomaba el precio de COMPRA como precio de venta y el costo quedaba vacío (sin
    margen posible). `catalog_import.py`: sinónimos "preciodecompra"/"compra" y
    "precioventa"/"venta" + regla de intención (un encabezado de compra/costo nunca es precio,
    uno de venta nunca es costo). En Empresa Demo ya estaban 199 de los 200 productos del
    Excel (10 categorías: DEP, ROP, AUT, TEC, LIB, HOG, HER, ASE, CUI, ALI), todos con el
    precio de compra como precio de venta y sin costo; con el volante sumaban 200 = tope del
    plan, así que ALI-200 no había entrado. Tras subir el límite se reimportó el Excel: 199
    actualizados + 1 creado, los 200 con compra/venta correctas (tienda: 201 productos, 0 sin
    costo).
14. **Límites de productos por plan** (14 sept 2026, decisión del dueño) — Nexo Básico
    200 -> 1.000 productos, Nexo Pro 1.000 -> 5.000 (publicaciones sin cambios: 150 / 800).
    `plans.py` + migración de datos `c9e1a3b5d7f2` (ensure_default_plans solo crea, nunca
    actualiza; la migración solo toca planes que siguen con el valor viejo).
15. **Admin Overview: evolución del margen** (14 sept 2026, sin commitear) — serie
    `margenEnElTiempo` (venta − comisión − costo conocido por orden, mismo cálculo que el
    KPI `margenGenerado`) + `margenEnElTiempoParcial` si algún ítem vendido no tiene costo.
    Panel "Evolución del margen" en el Overview. `chart.js::lineChartSVG` ahora soporta
    valores negativos (escala desde min(0, valores), línea de cero); con valores >= 0 el
    gráfico de ventas queda idéntico.
16. **Deploy preparado en el repo (Render + Supabase + Resend)** (14 sept 2026, sin
    commitear) — `render.yaml` (Blueprint: `nexo-api` con preDeploy `alembic upgrade head`,
    `--workers 1`, `/api/health` y disco `/var/data`; cron `nexo-ciclo-de-vida` diario;
    frontend estático `nexo-app` que genera `js/env.js` con `API_BASE_URL`), secretos todos
    `sync: false`. `psycopg[binary]` activo. Correo real: `EnviadorResend`
    (`RESEND_API_KEY` + `EMAIL_FROM`; sin ellas, al log) — si Resend rechaza, el recordatorio
    no se marca como enviado y se reintenta al día siguiente. DEPLOY.md con los pasos de
    cuentas (dominio, Supabase pooler en modo sesión, Resend, Blueprint, DNS, ML).
11. **Stock de Mercado Libre sincronizado** (14 sept 2026, sin commitear) — antes el stock
    reservado solo se usaba al crear la publicación. Ahora `PUT /{id}/stock-mercadolibre` y
    `/stock-mercadolibre/lote` también mandan `available_quantity` a las publicaciones vivas
    (`services/ml_stock_sync.py`, best effort, doc oficial "Distributed Stock": sin
    multi-origen). Detalle de producto: nuevo campo "Unidades para Mercado Libre".

## En progreso
- Nada a medias. El Admin BI cubre lo pedido (secciones 1–8); ver `TODO.md` para las
  extensiones opcionales que quedaron fuera de alcance a propósito.

## Pendiente
Ver `TODO.md`.
