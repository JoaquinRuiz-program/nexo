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
17. **Errores de sincronización visibles para el admin** (14 sept 2026, sin commitear) —
    `services/sync_registro.py` escribe en `SyncJob`/`SyncLog` (existían desde el esquema
    inicial, sin uso): importar ventas (fallos de ML + avisos de SKU fuera del catálogo y
    stock reservado insuficiente), costos de envío (errores temporales por publicación) y
    stock (rechazos de ML). "Clientes que necesitan atención" suma el motivo "N errores de
    sincronización (últimos 7 días)" y el detalle del cliente muestra las últimas 10.
18. **Margen venta − compra visible** (14 sept 2026, sin commitear) — el dueño no veía en
    ningún lado el margen simple de su Excel: `/api/productos` ahora trae `costo`,
    `margenClp`, `margenPct`; la lista de Productos muestra Costo y Margen; el detalle del
    producto, Oportunidades y el importador muestran "Venta − compra" junto a la ganancia
    neta de ML.
19. **Ganancia neta mínima por unidad** (14 sept 2026, sin commitear) — caso real: Notebook HP
    ($499.990, costo $350.000, comisión manual 19%) deja $54.992 (11,0%) y quedaba "no
    conviene" por el margen mínimo de 22,5%. Nuevo `ChannelCostSettings.min_profit_clp`
    (migración `d4f6a8c0e2b1`, aplicada a `nexo.db`) y campo en Configuración. Regla: un
    producto conviene si alcanza el margen mínimo (%) **o** la ganancia neta mínima ($); una
    pérdida nunca se rescata. Aplicada igual en `classify_product` (Oportunidades, /seleccion,
    gate de /decision y de publicar), `recomendar_precio` y `/decision-lote`.
    Nota de datos: resuelto en el punto 21 (los 201 productos ya tienen comisión real).
20. **Devoluciones de Mercado Libre** (14 sept 2026, sin commitear) — tabla `order_returns`
    (migración `e5a7c9b1d3f4`, aplicada a `nexo.db`), sin datos del comprador. Se sincronizan
    al importar ventas (`services/ml_devoluciones_sync.py`, registra `SyncJob` ml_devoluciones),
    `GET /api/mercadolibre/devoluciones`, panel en la sección Mercado Libre y en el detalle
    admin. Sincronización real contra ML: HTTP 200, 0 reclamos hoy.
21. **Comisiones siempre reales** (14 sept 2026, sin commitear) — `services/ml_comisiones.py`
    (núcleo que antes vivía solo en `/comisiones/recalcular`) corre solo en segundo plano al
    confirmar un import de Excel/CSV o Google Sheets y al conectar Mercado Libre. Backfill real:
    Empresa Demo 201 productos con categoría, 197 combinaciones de comisión real, 0 errores. La
    comisión manual queda solo como respaldo marcado para lo que ML aún no informó.
22. **"¿Conviene?" con regla única** (14 sept 2026, decisión del dueño) — se decide siempre al
    precio real con `classify_product` (la misma de Oportunidades): pérdida → no conviene;
    margen % ≥ mínimo o ganancia ≥ ganancia neta mínima → conviene. El stock no participa. El
    margen objetivo solo arma el precio recomendado y, si es imposible, un aviso. La
    competencia ya no cambia la decisión. Ver `backend/DECISION_NEGOCIO.md`.
23. **Mínimos por defecto** (14 sept 2026, decisión del dueño) — margen mínimo 15 % y ganancia
    neta mínima $3.000 (`umbrales_minimos` en `channel_costs.py`) si la empresa no guardó su
    configuración; migración `f6b8d0a2c4e5` completa las filas existentes vacías. Modificables
    en Configuración; un campo vaciado por el usuario no se exige.
24. **Ventas reembolsadas fuera de las métricas** (14 sept 2026) — `_filtros_orden` (admin.py,
    única fuente de GMV/margen/ventas del admin) excluye las órdenes con devolución
    `money_status = "refunded"`. Retenida o liberada sigue contando.
25. **Conciliación de comisiones con la facturación de ML** (14 sept 2026) — al importar ventas,
    `services/ml_conciliacion.py` pide `GET /billing/integration/group/ML/order/details` (doc
    "Billing Reports by Orders and Packs": lotes de 60, nunca re-pide un pedido facturado, uno
    sin facturar se reintenta 1 vez por día) y guarda en `order_billing` (migración
    `a7c9e1b3d5f6`) el cargo por venta (CV), envío (CXD) y otros, junto a la comisión que
    calcula Nexo (MercadoLibreCategoryFee al precio vendido). `GET /api/mercadolibre/conciliacion`
    + panel en Mercado Libre: coincide (±$1) / diferencia / sin cálculo de Nexo / aún sin facturar.
    Verificado en vivo: HTTP 200, 0 cargos hoy.
26. **Facturas propias por venta** (15 sept 2026) — `app/api/routes/facturas_ml.py`: el dueño
    adjunta a cada venta importada el PDF (máx 1 MB, se valida `%PDF`) y opcionalmente el XML
    de la factura que emitió con su proveedor SII; se reenvía a Mercado Libre
    (`POST /packs/{pack_id}/fiscal_documents`, pack_id de `/orders/{id}` o el ID del pedido) y
    se registra en `order_invoices` (migración `b9d1f3a5c7e9`). Quitar = `DELETE` en ML. Envío
    Full en Chile no admite facturas propias: mensaje claro. Panel en la sección Mercado Libre.
27. **Borradores legales** (15 sept 2026) — `legal/TERMINOS_DE_SERVICIO_BORRADOR.md` y
    `legal/POLITICA_DE_PRIVACIDAD_BORRADOR.md`, escritos a partir de lo que el código guarda
    (sin datos de compradores, tokens cifrados, modo soporte registrado, planes y gracia
    reales). No publicados: requieren abogado y completar datos de la empresa.
28. **Eliminar cuenta** (15 sept 2026) — botón en Configuración → Cuenta, pide contraseña y
    escribir ELIMINAR (`POST /api/auth/eliminar-cuenta`, `services/eliminar_cuenta.py`). Cancela
    antes el cobro mensual de Mercado Pago (si falla, no borra), borra todos los datos de la
    empresa y sus imágenes en disco, y no toca las publicaciones de Mercado Libre. Bloqueado para
    admins de Nexo y en modo soporte.
29. **Revisión de experiencia por perfil** (15 sept 2026) — ver `REVISION_EXPERIENCIA.md`: 4
    cuentas de prueba (pyme, importador, retailer, emprendedor) en `nexo.db` de desarrollo,
    recorrido como admin y como cliente, 28 hallazgos priorizados.
30. **Críticos de la revisión corregidos** (15 sept 2026):
    - `preferencia_efectiva` (rentabilidad.py): ¿Conviene?, precio recomendado y decisión en
      lote eligen solas Clásica/Premium con la comisión real, igual que Oportunidades.
    - Dashboard: "Convienen en Mercado Libre" usa `classify_product` con los mínimos (antes
      venta − compra). Sin costos de ML configurados pide configurarlos.
    - `shipping_min_price_clp` (migración `c3e5a7b9d1f2`): "Descontar el envío desde este
      precio" en Configuración; bajo ese precio no se descuenta el envío manual.
    - Importador: "Descripción" corta = nombre si no hay columna nombre; con varios precios
      gana venta/retail/público sobre mayorista; entiende "Lo compré a / Lo vendo a / Cuántos
      tengo".
    - Pantalla de revisión: al corregir una columna se vuelve a analizar con ese mapeo
      (`/importar/analizar` acepta `mapeo`); nombre, costo y precio marcados como clave, con
      aviso si faltan.
    - Límite del plan: `limitePlan` en la respuesta de importar, aviso en la importación
      (Excel y Google Sheets) y en "Uso del plan" del Dashboard.
31. **Importantes de la revisión corregidos** (15 sept 2026):
    - Oportunidades: "Margen neto promedio (listos)" con el margen real, grupo "Conviene
      publicar" con la regla real, columna "Decisión", buscador por nombre/SKU y filas de a 50
      por grupo con "Mostrar más" (sin volver a pedir datos).
    - ¿Conviene?: "Precio para tu margen objetivo" con el % que busca; sin la etiqueta
      "Decisión preliminar"; sin Mercado Libre conectado muestra "Conectar Mercado Libre" en
      vez de "Preparar publicación" (y el error de preparar ofrece conectar).
    - Productos: la columna es "Venta − compra"; el detalle dice con qué comisión se calculó.
    - Stock: "Usar el stock de cada producto" (`usarStock` en `/stock-mercadolibre/lote`).
    - Importar sin SKU reconoce el producto por nombre (si hay uno solo) en vez de duplicarlo.
    - Sin Mercado Libre conectado se predice la categoría de ML al importar
      (`_solo_predecir_categorias`; `tests/conftest.py` evita la red en los tests).
32. **Menores de la revisión corregidos** (15 sept 2026):
    - Mi plan: en prueba dice "La prueba termina el" y la fecha ya no sale un día antes (fecha local).
    - Sin textos técnicos: fuera "Base de datos", "credenciales configuradas" y "credenciales en
      el servidor"; Configuración sin el panel de notificaciones de demostración.
    - Todo el texto al cliente en tú (sin voseo), frontend y mensajes del backend.
    - Importar: "Falta imagen", "Falta SKU" y "Completa el stock al revisar" ya no mandan la
      fila a "Para revisar".
    - Admin: KPI "Sin Mercado Libre o sin productos", motivo de atención "Llegó al límite de
      productos de su plan", gráfico sin ventas dice "Sin movimientos en el período".
    - Detalle de producto muestra la fecha de creación (`creadoEn`); Dashboard en celular con
      tarjetas de a dos.
33. **Google Sheets: la revisión se recalcula al corregir columnas** (15 sept 2026) —
    `POST /api/google-sheets/importar/analizar` acepta `mapeo` opcional (igual que el importador
    de Excel/CSV); cambiar un selector vuelve a leer la hoja y actualiza contadores y avisos.
34. **Precio recomendado de vitrina** (15 sept 2026) — `precio_vitrina` en `domain/pricing.py`
    redondea hacia arriba al precio terminado en 990 ($84.134 → $84.990); el margen estimado
    se calcula con ese precio, así nunca queda bajo el objetivo. El caso imposible (sin
    margen objetivo alcanzable) sigue devolviendo el mínimo rentable exacto.
35. **QA integral** (15 sept 2026, ver `QA_INTEGRAL.md`) — 4 vendedores ficticios + admin,
    datos borrados al terminar. 6 bugs corregidos con pruebas: fila en blanco en el Excel
    cortaba la importación, precio recomendado ignoraba el envío al cruzar "envío desde",
    suspender no cortaba la sesión abierta, `/api/rentabilidad` 500 con costo sin precio,
    importador aceptaba costo/precio negativo, vendedor veía el esqueleto de `#/admin`.
    Regla de rentabilidad: 0 diferencias en 1.232 productos; aislamiento: 0 fugas.
36. **Ventas reales de Mercado Libre** (15 sept 2026) — `app/domain/ventas_ml.py` +
    `app/api/routes/ventas_ml.py`: `GET /api/mercadolibre/ventas/resumen|grafico|mas-vendidos` y
    `GET /api/mercadolibre/pedidos`, sobre las ventas importadas (sin canceladas ni con dinero
    devuelto). Dashboard y pantalla de Mercado Libre dejan de mostrar $0 fijo en modo real.
    Pendientes/enviados/entregados quedan "—": Mercado Libre no lo informa en la importación.
37. **Productos sin costo de compra** (15 sept 2026) — ej. un repuesto que la empresa ya tiene.
    Sin costo registrado el costo considerado es $0 (`rentabilidad.py::_fila`; en la base sigue
    vacío y `tieneCosto=False`): ganancia = venta − comisión − envío − otros costos, se evalúa
    "¿Conviene?" con la regla de siempre y se publica al precio de venta del Excel. Importar sin
    costo es solo un aviso. Sin costo (o con costo $0) no se calcula "precio para tu margen
    objetivo". Sin precio de venta queda pendiente (no se inventa precio) y al intentar
    publicarlo el bloqueo dice "Todavía no se puede publicar…: Falta el precio de venta"
    (antes decía "no es rentable").
38. **QA fase 2 — estrés y seguridad** (15 sept 2026) — catálogos de 100 a 10.000 productos,
    archivos grandes, límites de plan, multiempresa A/B/C, IDs raros, datos malformados, XSS,
    concurrencia, impersonación y empresa vacía. Corregido:
    - Un plan vencido publicaba en Mercado Libre llamando directo a `/confirmar` (solo la
      vista previa lo bloqueaba); `canceled` pasado el período pagado y `expired` también.
    - Tras varias importaciones grandes el backend dejaba de responder a todas las empresas:
      la predicción de categorías mantenía la conexión de la base tomada mientras esperaba a
      Mercado Libre (pool agotado), las tareas se apilaban y un reinicio quedaba esperándolas.
      Ahora libera la conexión, una tarea por empresa y máximo 200 predicciones por corrida.
    - IDs gigantes (`/api/productos/9223372036854775808`) y PNG corruptos respondían 500.
    - CSV guardado desde Excel en Windows (Windows-1252) se rechazaba con un error técnico.
    - Costo NaN/Infinity/1e308 y configuración de Mercado Libre fuera de rango se aceptaban.
    - Consultas por producto (N+1): con 10.000 productos Productos 13,9 s → 2,8 s,
      Oportunidades 9,4 s → 0,7 s, decisión en lote 14,5 s → 1,2 s, Dashboard 9,3 s → 1,2 s.
    - Dos pestañas del admin en "ver como empresa" mostraban la empresa anterior.
    - Textos con voseo que quedaban.
39. **P3 de la QA fase 2** (15 sept 2026): la misma solicitud de soporte enviada dos veces en
    un minuto se devuelve en vez de duplicarse (y el botón se desactiva mientras envía);
    asunto de soporte máx. 200 y descripción máx. 10.000 caracteres; `/preparar` ignora IDs
    repetidos; solo se puede configurar el canal `mercadolibre`; stock para Mercado Libre
    máx. 1.000.000; la predicción de categorías elige los productos al azar para que los que
    nunca se pueden predecir no bloqueen a los demás.
40. **Concurrencia en Postgres** (15 sept 2026): un choque con una restricción única de la base
    (p. ej. dos importaciones del mismo archivo al mismo tiempo) responde 409 "Otra operación
    modificó estos datos al mismo tiempo" en vez de 500; la importación bloquea la fila de la
    empresa hasta el commit, así dos importaciones simultáneas no pasan el límite del plan.
41. **Pasada visual B2B** (15 sept 2026, solo frontend, sin cambios de lógica): base de texto
    16px (antes 18px), bordes y radios discretos, sin sombras en tarjetas, botones del alto de
    un campo (`btn-sm` para acciones en filas), badges rectangulares chicos, sin animación de
    entrada ni shimmer. Toda grilla de `.stat-card` (y los KPI del admin) se dibuja como una
    franja con divisiones finas en vez de tarjetas sueltas. Dashboard reordenado: franja de
    métricas → qué hacer / primeros pasos → ventas | rentabilidad, alertas y conexiones; se
    quitó "Accesos rápidos" (repetía la barra lateral) y "Ventas importadas" pasó a una línea
    del panel de ventas. Mercado Libre oculta las métricas que ML no informa (antes "—").
    Estados vacíos y títulos con texto funcional; gráficos del admin sin degradado.
    Después, a pedido del dueño: texto a 17px; la barra lateral se achica a solo íconos con el
    botón del encabezado (se recuerda por navegador); las pantallas ya no tienen ancho máximo
    — Configuración y el detalle de cliente del admin reparten sus paneles en dos columnas,
    y el detalle de producto, Ayuda y soporte y el detalle de solicitudes usan dos columnas.
42. **Costo de envío estimado antes de publicar** (16 sept 2026, pedido del dueño: "que mientras
    analiza los márgenes también analice el costo de envío y lo agregue"). Al actualizar las
    comisiones reales, `services/ml_comisiones.py` estima además el envío de cada (categoría,
    precio) con las medidas por defecto que publica Mercado Libre para esa categoría
    (`/categories/{id}/shipping_preferences`) y su calculadora de envío gratis
    (`/users/{id}/shipping_options/free?dimensions=...&item_price=...`); ambas verificadas en
    vivo contra MLC. Se cachea en `mercadolibre_shipping_estimates` (migración d1f3b5a7c9e2).
    Prioridad en el margen: costo REAL de la publicación > estimación > envío manual de
    Configuración. Solo se descuenta si a ese precio el envío gratis es obligatorio (en Chile,
    sobre cierto monto); si no, lo paga el comprador y el costo es $0. Nuevo campo
    `envioMlResuelto`: con envío real, estimado o confirmado que no aplica, el margen deja de
    marcarse como provisional. En la interfaz el envío estimado se muestra como "Estimado".
    De paso, "Eliminar cuenta" ahora borra también esa caché (y la prueba cubre las dos tablas
    de caché de Mercado Libre: en Postgres, dejarlas rompería la clave foránea contra stores).
    Las estimaciones se vuelven a consultar a los 30 días (las tarifas de envío cambian).
43. **Revisión del sistema** (16 sept 2026, ver `REVISION_SISTEMA.md`): lectura completa de
    dominio, rutas, servicios, adaptadores, modelos y frontend. Corregido:
    (a) el webhook de Mercado Pago no era idempotente — el mismo aviso aplicado dos veces
    sumaba otro mes/año de plan (Mercado Pago reintenta hasta recibir un 200);
    (b) al pagar, el período se contaba desde hoy y borraba los días ya pagados: ahora se suma
    a lo que quedaba; (c) la importación de ventas pedía una sola página de 50 pedidos y el
    resto se perdía en silencio: ahora pagina (50 × 20 = 1.000 por corrida, `sort=date_desc`
    verificado en vivo contra MLC). Pruebas nuevas para los tres casos.
    Pendiente de decisión del dueño: el cobro mensual del mes 2 en adelante
    (`subscription_authorized_payment`) sigue sin procesarse, así que un cliente mensual cuyo
    cobro falla conserva acceso; ver REVISION_SISTEMA.md §2.1.
44. **Regla estricta del envío: sin envío no hay veredicto** (16 sept 2026, pedido del dueño:
    "no puedes ver el envío antes de decir si es conveniente o no"). Antes, un envío que faltaba
    se calculaba como $0 y el producto igual salía "Conviene", con una nota chica que decía
    "Provisional". Ahora:
    (a) `ChannelCosts.shipping_unknown` y `net_margin` devuelve None — un envío que falta no es
    un envío de $0. Mismo criterio para la comisión: sin comisión conocida tampoco hay margen
    neto (antes alcanzaba con tener cualquier otro costo cargado para calcular con 0 %).
    (b) `classify_product` responde "Faltan datos" con el motivo ("Falta el costo de envío de
    Mercado Libre para calcular la rentabilidad.") en Oportunidades, Dashboard, "¿Conviene?",
    `/validar`, la columna Decisión y el gate de `/confirmar`, que no deja publicar.
    (c) El precio recomendado tampoco se calcula: `faltantes` trae "costo de envío de Mercado
    Libre" (con envío $0 supuesto recomendaba un precio que no cubría el envío).
    (d) Una estimación vencida (30 días) que no se pudo actualizar vuelve a ser dato faltante,
    con su propio motivo — antes se seguía usando una tarifa vieja como si fuera la de hoy.
    (e) El envío manual de Configuración ya NO completa el cálculo de Mercado Libre: es un
    promedio del dueño, no el envío de esa publicación. El umbral "envío desde $X" ahora se
    aplica al envío que informa Mercado Libre.
    (f) Un costo de compra vacío sigue siendo dato válido (costo considerado $0) — la distinción
    que pidió el dueño: costo vacío = $0, envío desconocido = no se puede determinar.
    Interfaz: se fue la etiqueta "Provisional"; el vocabulario único es "Faltan datos" y la fila
    ofrece "Actualizar envíos" (la misma consulta que trae comisiones y envíos).
    Pruebas nuevas en `tests/test_envio_faltante_rentabilidad.py` (envío disponible, sin costo de
    compra, envío real $0, sin estimación, consulta fallida, estimación vencida, no publicable y
    ninguna pantalla diciendo "Conviene"). Los productos de prueba de la suite ahora dejan el
    envío resuelto explícitamente (`_envio_ml_resuelto`).
11. **Stock de Mercado Libre sincronizado** (14 sept 2026, sin commitear) — antes el stock
    reservado solo se usaba al crear la publicación. Ahora `PUT /{id}/stock-mercadolibre` y
    `/stock-mercadolibre/lote` también mandan `available_quantity` a las publicaciones vivas
    (`services/ml_stock_sync.py`, best effort, doc oficial "Distributed Stock": sin
    multi-origen). Detalle de producto: nuevo campo "Unidades para Mercado Libre".
45. **Obtención automática del envío al importar, con progreso en vivo** (16 sept 2026, pedido
    del dueño: resolver el origen del dato de envío sin pedirle peso ni medidas). No agrega
    ningún mecanismo nuevo de envío: orquesta con progreso los tres que ya existían —
    `actualizar_comisiones_reales` (comisión real + envío ESTIMADO de lo no publicado, medidas
    por defecto de la categoría) y `sincronizar_costos_envio_de_la_cuenta` (envío REAL de lo ya
    publicado, por `item_id`) — y al final clasifica cada producto con la MISMA regla de
    Oportunidades (`classify_product`, sin cambios). Nuevo:
    `POST /api/mercadolibre/analisis-rentabilidad/stream` (NDJSON) en
    `services/analisis_rentabilidad_stream.py`, disparado por el asistente de importación justo
    después de confirmar el Excel — pantalla "Analizando productos… X/Y" con el producto actual,
    comisión/envío/rentabilidad marcados a medida que se resuelven, y el resumen final
    (Conviene/No conviene/Faltan datos). Los tres servicios reusados ganaron un parámetro
    opcional `on_avance` (default `None`, sin efecto en los llamadores existentes) para reportar
    avance sin duplicar ninguna consulta a Mercado Libre ni cambiar qué se guarda.
    Bug encontrado de paso: el botón manual "Actualizar comisiones y envíos" nunca estimaba el
    envío — faltaba pasar `account.external_account_id` (user_id) a `actualizar_comisiones_reales`
    (`routes/mercadolibre.py::recalcular_comisiones`); corregido, con prueba.
    Verificado en vivo contra la cuenta real conectada (201 productos, Empresa Demo): primera
    corrida resolvió el envío de los 201 (0 Faltan datos), 196 Conviene / 5 No conviene,
    coincidiendo con `/api/seleccion`; segunda corrida (todo cacheado) tardó ~5 s. Probado también
    con dos productos nuevos subidos por Excel desde la interfaz real (categoría, comisión y
    envío resueltos de punta a punta) — datos de prueba borrados al terminar.
    Pruebas nuevas en `tests/test_analisis_rentabilidad_stream.py`. Pendiente (documentado en
    `TODO.md`, no construido a propósito): para un producto SIN publicación y sin categoría
    detectable por Mercado Libre, no existe ningún endpoint que dé un costo de envío sin
    dimensiones — ese caso queda en "Faltan datos", nunca inventado.

## En progreso
- Nada a medias. El Admin BI cubre lo pedido (secciones 1–8); ver `TODO.md` para las
  extensiones opcionales que quedaron fuera de alcance a propósito.

## Pendiente
Ver `TODO.md`.
