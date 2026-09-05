# Backend — catálogo universal + rentabilidad para Mercado Libre

Backend real del proyecto, en Python + FastAPI. Vive fuera de `src/` (el
frontend React) y de `scripts/woocommerce-audit/` (el script de auditoría)
— es un proyecto Python independiente, con su propio entorno virtual.

## Pivote (24 de agosto de 2026): de "una librería" a plataforma universal

El dueño decidió que el sistema no es exclusivo de un solo rubro — es
una plataforma para cualquier vendedor de Mercado Libre que empieza
subiendo su catálogo en Excel/CSV. El producto es Nexo, ningún cliente
en particular define el límite de la arquitectura. Esto ya estaba mayormente resuelto por
decisiones previas (`store_id` en todo el catálogo, `category` como texto
libre, comisión de canal siempre configurable — nunca hardcodeada) — lo
nuevo de esta fase:

- **`app/domain/catalog_import.py`** — detecta columnas por sinónimo
  (`SKU`/`Codigo`/`ID`, `Precio`/`Precio venta`/`Valor`, etc.), sin exigir
  nombres exactos. Puerto a Python de la lógica que ya existía en
  `src/services/importService.ts`, extendida con costo y código de barras.
- **`app/api/routes/catalogo.py`** — `POST /api/catalogo/importar/analizar`
  (detecta y valida, no escribe nada) y `POST /api/catalogo/importar/confirmar`
  (crea/actualiza productos reales, con imagen si el archivo trae una URL).
- **`app/domain/catalog_selection.py`** + **`GET /api/seleccion`** — "¿qué
  conviene publicar en Mercado Libre?": clasifica cada producto en
  rentable / margen_bajo / no_rentable / sin_stock / sin_datos, con umbrales
  que decide quien llama (nunca hardcodeados), reutilizando el motor de
  rentabilidad ya existente sin recalcular nada.
- **`ProductImage`** (nueva tabla) — referencia a imagen (URL por ahora),
  nunca base64. **`Product.brand`/`source`**, **`ProductVariant.barcode`**
  — nuevos, para que el catálogo no dependa de las columnas exactas de una
  librería.
- **`backend/demo_data/`** — 5 catálogos de prueba REALES (archivos
  `.xlsx`/`.csv` generados con `python -m demo_data.generate_demo_catalogs`,
  no datos inventados en JS): librería, electrónica, ferretería, ropa (con
  variantes de talla/color), y un CSV "desordenado" que simula un negocio
  real sin preparar (columnas con nombres distintos, datos faltantes).
  Verificados en vivo contra el servidor real — incluye productos
  deliberadamente rentables, con margen negativo, sin stock, sin costo y
  sin descripción, para que la selección tenga algo real que descartar.

**Limitación conocida de esta primera versión:** el importador no agrupa
variantes automáticamente (talla/color de un mismo producto) — cada fila
del archivo es un producto con una sola variante. Es una decisión, no un
olvido: agrupar variantes bien requiere más reglas de las que se pueden
adivinar de forma confiable.

**Segunda ronda (mismo día) — flujo completo hasta "borrador de
publicación":**

- 2 bugs reales de detección de columnas, encontrados probando con Excels
  reales (no en el diseño en papel) y corregidos con test de regresión: (1)
  cuando el archivo trae "Código" Y "SKU" a la vez, ahora gana el sinónimo
  más específico; (2) un header como "Precio compra" se estaba matcheando
  como precio de venta en vez de costo (la palabra "precio" como substring
  se comía cualquier columna que la contuviera).
- **`app/domain/ai_content.py`** — título/descripción/atributos generados
  con REGLAS, marcado explícito `simulado=True`, para reemplazar por un
  modelo real más adelante sin tocar el resto del sistema. Nunca inventa
  una característica que no esté en los datos del producto.
- **`app/domain/listing_draft.py`** + **`GET /api/publicaciones/borrador/{id}`**
  / **`POST /api/publicaciones/preparar`** — arma el "borrador de
  publicación" completo (título, descripción, categoría — marcada
  explícitamente como NO oficial de Mercado Libre —, atributos, precio,
  costo, imágenes, margen, y advertencias) sin persistir nada ni tocar
  Mercado Libre.
- **4 escenarios de Excel más** en `backend/demo_data/` (06 a 09): una
  tienda con "Código" Y "SKU" a la vez, un formato de cosmética con
  columnas completamente distintas, un catálogo de juguetería con SKU
  duplicado/precio inválido/costo mayor al precio, y un comercio con 6
  categorías radicalmente distintas en un solo archivo.
- **Flujo completo verificado en vivo, de punta a punta:** subí los 4
  archivos nuevos al servidor real → se importaron 32 de 35 filas (las 3
  omitidas eran, correctamente, un precio inválido y un SKU duplicado) →
  `/api/seleccion` clasificó los 32 sin exigir nada a mano → preparé
  publicaciones de un producto rentable, uno no rentable y uno sin datos, y
  cada borrador trajo exactamente la advertencia esperada.

195/195 tests pasando.

## Tercera ronda (28-29 de agosto de 2026): OAuth blindado + dashboard real

- **OAuth de Mercado Libre endurecido** (`app/api/routes/mercadolibre.py`):
  una `TOKEN_ENCRYPTION_KEY` mal formada ya no escapa como 500 sin headers
  CORS — ahora es un 400 con el detalle exacto, tanto en `/callback` como al
  renovar un token vencido. Una renovación fallida por red (no por rechazo
  de autenticación) devuelve 502 en vez de marcar la cuenta como
  desconectada. +10 tests (caída total de red agotando reintentos,
  `/callback` con error de red o código vencido, renovación automática de
  token vencido en `/importar-ventas` con éxito y con rechazo, clave de
  cifrado inválida). 202/202 tests.
- **`GET /api/dashboard/resumen`** (`app/api/routes/dashboard.py`) — el
  único endpoint que arma todo el Dashboard del frontend en una sola
  llamada: catálogo (stock/alertas), rentabilidad (productos con costo,
  rentables — `None` si no hay costos cargados, nunca un `0` engañoso),
  ventas importadas (conteos, nunca montos) y estado real de conexión con
  Mercado Libre. Reusa `build_profitability_rows` y un nuevo
  `build_estado_conexion` (factorizado de `mercadolibre.py`) — no duplica
  ninguna regla de negocio. `productos_db.py`: `_fila` renombrado a
  `build_producto_fila` (público) para que el dashboard reuse el mismo
  armado de fila que `/api/productos`. +7 tests. **209/209 tests pasando.**
- **Frontend conectado de verdad** (`frontend/js/dataSource.js`): Dashboard,
  Productos y el detalle de producto ya hablan con este backend cuando está
  corriendo, y caen solos a Demo Mode si no responde — ver
  `frontend/README.md`.

Sin credenciales reales de Mercado Libre configuradas todavía (ver sección
"Mercado Libre real" en `DATABASE.md`) — nada de eso se puede probar de
punta a punta hasta que el dueño las genere en developers.mercadolibre.cl.

## Cuarta ronda (29 de agosto de 2026): conexión real de Mercado Libre, de punta a punta

El OAuth ya existía y estaba bien construido, pero el frontend nunca lo
disparaba de verdad (el botón "Conectar" solo mostraba un aviso) y
`/callback` devolvía JSON en vez de llevar al navegador de vuelta a Nexo.
Auditado contra la documentación oficial vigente de Mercado Libre antes de
tocar nada (no de memoria) — un dato que tenía desactualizado: la Redirect
URI exige HTTPS siempre, incluso en desarrollo local (antes decía que HTTP
alcanzaba en localhost). Ver "Mercado Libre real" en `DATABASE.md` para la
guía paso a paso completa, corregida, con `ngrok` como solución de
desarrollo.

- **PKCE** (RFC 7636, `app/adapters/mercadolibre.py`: `generate_pkce_pair`)
  — opcional según Mercado Libre, pero se manda siempre como capa extra
  contra interceptación del código de autorización.
- **`/callback` ahora SIEMPRE redirige el navegador al frontend** (nunca
  JSON) — éxito (`?ml=conectado`) y cada error (`?ml=error&razon=<código
  corto>`, nunca el detalle técnico) — incluido el caso de que el dueño
  cancele la autorización en Mercado Libre (`?error=access_denied`, antes
  rompía con un 422 porque `code` era obligatorio).
- **`POST /api/mercadolibre/desconectar`** — nuevo, idempotente.
- **Cuenta vendedora identificada**: `external_account_nickname` /
  `external_account_site_id` nuevos en `marketplace_accounts` (migración
  `ea44b265af0b`), desde `GET /users/me` — nunca nombre real, email,
  teléfono ni dirección, aunque ese endpoint los devuelva.
- **Frontend conectado de verdad** (`frontend/js/app.js`,
  `renderMercadoLibre`): "Conectar" navega a la URL real de autorización;
  al volver, un banner con el estado real (conectado/no conectado/error en
  lenguaje humano) y "Importar ventas ahora"/"Administrar" (desconectar),
  con feedback de carga en cada botón — nunca deja al usuario sin saber si
  funcionó.
- +14 tests (PKCE en el adapter, `access_denied`, desconectar e idempotencia,
  reconectar después de desconectar, la cuenta queda scopeada por tienda —
  nunca global). **222/222 tests pasando.**

Sin credenciales reales todavía — igual que antes, nada de esto se puede
probar de punta a punta hasta que el dueño las genere.

## Quinta ronda (29 de agosto de 2026): arquitectura multiempresa/multi-seller

El OAuth funcionaba, pero había que confirmar que la arquitectura no
asumía en ningún lado "una única cuenta de Mercado Libre" — Nexo es un
SaaS que va a tener muchas empresas cliente, ninguna con trato especial.
Auditoría completa (modelos, `MarketplaceAccount`, `store_id`, tokens,
OAuth, callback, endpoints, frontend, tests) antes de tocar nada: la base
ya estaba bien encaminada (`store_id` scopea todo desde el modelo
original, `UniqueConstraint(store_id, marketplace)` ya permite que dos
empresas tengan cada una su propio seller sin chocar), pero el `state` de
OAuth no capturaba explícitamente qué empresa inició la conexión.

- **El `state` ahora guarda `store_id`** (`_new_state`/`_consume_state` en
  `app/api/routes/mercadolibre.py`) — `/callback` asocia la cuenta a la
  empresa que REALMENTE inició ese intento, no a "la que sea la actual" en
  el instante en que Mercado Libre responde. Sin esto, el diseño era
  correcto hoy (una sola tienda) pero frágil para cuando exista selección
  real de empresa activa.
- **Documentado en el código, no solo en Markdown**: `_get_default_store`
  ahora explica que es el ÚNICO punto de todo el archivo que decide "la
  empresa actual", y que es justo lo que hay que reemplazar cuando exista
  login multiempresa real — todo lo demás ya opera por `store_id` y no
  cambia. Mismo criterio en el docstring del módulo y en
  `app/db/models/marketplace.py` (por qué `external_account_id` no tiene
  unique constraint global — a propósito, dos empresas pueden conectar
  sellers distintos sin restricción artificial).
- **Mensaje de configuración corregido**: el error de "faltan credenciales
  de Mercado Libre" decía "con la cuenta real de la librería", como si
  cada cliente necesitara su propia aplicación desarrolladora — ahora
  aclara que `MERCADOLIBRE_CLIENT_ID`/`_SECRET` son de la aplicación de
  **Nexo** (se crean una sola vez), nunca credenciales por empresa.
- **+7 tests de aislamiento entre empresas** (`test_mercadolibre_endpoints.py`,
  sección "Arquitectura multiempresa/multi-seller"): dos `Store` conectando
  cada una su seller, `estado` de una nunca expone datos de la otra,
  desconectar una nunca afecta a la otra, renovar el token vencido de una
  nunca toca el token vigente de la otra, el `state` recupera de forma
  segura la empresa que inició la conexión, y `/estado` nunca expone
  tokens ni el client secret. **229/229 tests pasando.**
- **`DATABASE.md`**: nueva guía para probar con **usuarios de prueba** de
  Mercado Libre (hasta 10 por aplicación, vía `POST
  /users/test_user`) en vez de la cuenta real de la librería — así se
  puede simular dos empresas clientes conectando cada una su propio seller
  sin arriesgar la cuenta real de nadie.

No se tocó: publicación de productos, sincronización masiva, scheduler,
billing/suscripciones ni autenticación multiempresa completa (login +
selector de empresa activa) — quedan para después de que la conexión OAuth
esté probada con una cuenta real.

## Sexta ronda (29 de agosto de 2026, mismo día): comisión REAL de Mercado Libre por producto

A pedido del dueño: "la comisión de Mercado Libre varía por producto" —
antes `ChannelCostSettings.commission_pct` era un único % manual para todo
el canal, la misma limitación que ya evitaba inventar un "13% por
defecto". Ahora, con la cuenta conectada, Nexo consulta la comisión REAL
de Mercado Libre por producto — verificado en vivo contra la API real
(no solo mockeado): libros mostraron 13%/17% (Clásica/Premium) y
cuadernos/útiles 15%/19%, la misma corrida, confirmando que sí varía por
categoría tal como se pidió.

- **`MercadoLibreAdapter.predict_category`** (`GET /domain_discovery`,
  público, sin token) y **`get_listing_fees`** (`GET /listing_prices`,
  requiere el permiso "Publicación y sincronización" en la app — "Venta y
  envíos" NO alcanza, confirmado en vivo con un 403 antes de habilitarlo).
- **`POST /api/mercadolibre/comisiones/recalcular`**: predice la categoría
  de cada producto por su nombre (una sola vez, se guarda en
  `Product.ml_category_id`) y cachea la comisión real por
  (tienda, categoría, tipo de publicación, precio exacto) en
  `MercadoLibreCategoryFee` — nunca se re-consulta lo ya cacheado. A
  propósito NO se llama durante la carga de un Excel (sería lento con
  catálogos grandes): es un botón aparte ("Actualizar comisiones reales de
  Mercado Libre" en Oportunidades) que el dueño dispara cuando quiere.
- **`GET /api/rentabilidad`/`GET /api/seleccion`**: cada fila ahora incluye
  `comisionMlReal` (Clásica y Premium en paralelo, con su margen neto
  real) — sin elegir una por el dueño; `ChannelCostSettings.listing_type_pref`
  (classic/premium, ya expuesto por `PUT /api/configuracion/canales/mercadolibre`,
  todavía sin UI propia) queda para cuando el dueño decida cuál usa.
- **Bug real encontrado y corregido de paso**: `build_profitability_rows`
  (motor de Rentabilidad/Oportunidades/Dashboard) consultaba `Product` y
  `ChannelCostSettings` SIN filtrar por `store_id` — invisible con una sola
  tienda, pero mezclaba el catálogo de TODAS las empresas apenas hubiera
  una segunda. Corregido + test de regresión.
- **+16 tests** (adaptador, `app/domain/ml_fees.py`, endpoint de
  recálculo, aislamiento entre empresas de la comisión cacheada, y el bug
  de scoping de arriba). **245/245 tests pasando.**

No se tocó: publicación de productos ni ninguna otra automatización — esto
es solo información para decidir, igual que el resto de Rentabilidad.

## Séptima ronda (29 de agosto de 2026, mismo día): autenticación real + multiempresa

Base para convertir Nexo en SaaS real: hasta acá, ningún endpoint de
negocio pedía login — todos operaban sobre "la única tienda que existe"
(`_get_default_store`, duplicado en varios routers). Dos commits, como se
acordó de antemano:

**Commit 1 — auth**: `app/api/routes/auth.py` (registro/login/logout/me,
reusa `User`/`AuthSession`/`Store`/`StoreSettings`/bcrypt que ya existían
sin usarse) + `app/api/deps.py` (`get_current_user`/`get_current_store` —
cookie de sesión HttpOnly + SameSite=Lax, nunca localStorage). Migración
`auth_sessions.active_store_id` (batch mode, SQLite no soporta ALTER TABLE
ADD CONSTRAINT directo). CORS con `allow_credentials=True`. +16 tests.

**Commit 2 — multiempresa**: todos los routers de negocio migrados a
`Depends(get_current_store)`, `_get_default_store` eliminado en todos
lados. Se encontraron y corrigieron dos huecos reales de aislamiento que
no era solo el bug de `rentabilidad.py` de la ronda anterior:
`productos_db.py` (`GET/PUT /api/productos/{id}` buscaba la variante SOLO
por ID, sin verificar tienda — un IDOR real una vez que hubiera más de un
cliente) y `import_costs.py` (buscaba el SKU en toda la base, sin
`store_id`). `/api/mercadolibre/callback` NO se tocó a propósito: sigue
resolviendo la empresa desde el `state` (no desde la sesión), porque el
navegador llega ahí recién saliendo de Mercado Libre y ese mecanismo ya
estaba armado así desde antes, precisamente para este momento.

Aislamiento probado por HTTP real por primera vez (antes había que llamar
funciones directo porque no existía una segunda sesión de usuario posible):
`tests/test_aislamiento_multiempresa.py` registra dos empresas con
`POST /api/auth/registro` reales y confirma que ninguna ve, lista ni puede
modificar (ni adivinando un ID) nada de la otra — catálogo, costos,
rentabilidad, dashboard, borradores de publicación. **+31 tests
(16 de auth + 15 de aislamiento). 277/277 tests pasando.**

No se tocó: publicación real, WooCommerce, billing/planes — alcance
exclusivo auth + multiempresa, como se pidió.

## Qué hay hoy (22 de agosto de 2026) — y qué NO hay todavía

**Hay:** un adaptador de WooCommerce (`app/adapters/woocommerce.py`), puerto
directo y fiel de `scripts/woocommerce-audit/src/woocommerceAdapter.ts` —
mismo comportamiento exacto (autenticación por query/basic según esquema,
reintentos con backoff ante 429/5xx, sin reintentar 401/403, cuerpo del
error expuesto, variaciones de color de productos "variable"). Funciones de
análisis (`app/domain/analysis.py`), puerto directo de `analysis.ts`
(resumen del catálogo, duplicados, candidatas a código de barras,
`expand_variable_products`, y `build_productos_list` — agregada al conectar
el frontend, ver abajo). Un primer endpoint real,
`GET /api/productos/reporte`, que conecta con las credenciales del `.env`,
trae el catálogo completo con sus variaciones, y devuelve el mismo tipo de
reporte que ya generaba `npm run audit`, más una lista completa por
producto (`productos: [...]`) para la tabla del frontend. CORS habilitado
para los orígenes exactos que usa el frontend en desarrollo local
(`http://localhost:5500` y `http://127.0.0.1:5500` — nada de "cualquier
origen").

**Nuevo (22 de agosto de 2026): la base de datos propia del sistema** —
modelos de SQLAlchemy, migraciones con Alembic, y pruebas de creación/
relaciones/restricciones para las 20 tablas del diseño (usuarios, tiendas,
suscripciones, catálogo, relación con WooCommerce, relación con Mercado
Libre, pedidos, sincronización, historial de stock). Todavía NO hay ningún
endpoint que lea o escriba en esta base — es solo el modelo, listo para la
próxima fase. Ver **`DATABASE.md`** para el detalle completo (cómo
levantarla, cómo correr las migraciones, qué prueba cada test).

48/48 tests pasando (`pytest`) — 18 del backend HTTP/WooCommerce ya
existente + 30 nuevos del modelo de datos.

**Un bug real encontrado y corregido el 22 de agosto de 2026:** al probar el
backend contra un WooCommerce inalcanzable (para simular el frontend con la
tienda caída), un error de conexión (`httpx.ConnectError`) escapaba sin
envolver después de agotar los reintentos, y terminaba en un HTTP 500 con
traceback crudo en vez del HTTP 502 con mensaje claro que ya existía para
este caso. Corregido en `_request_with_retry`
(`app/adapters/woocommerce.py`) para que ese error también se envuelva en
`WooCommerceRequestError`, con un test de regresión
(`test_error_de_conexion_se_envuelve_en_woocommerce_request_error`).

**Nuevo (22 de agosto de 2026): primer endpoint respaldado por la base de
datos propia.** El acceso a WooCommerce probado hasta ahora no se considera
el acceso definitivo de la librería, así que el desarrollo sigue sin
depender de eso: `app/db/seed_demo.py` llena `products`/`product_variants`
con un catálogo de prueba (16 productos, 22 filas con variantes de color),
usando los mismos modelos que usará el futuro job de sincronización real de
WooCommerce. `GET /api/productos` y `GET /api/productos/{id}`
(`app/api/routes/productos_db.py`) leen ese catálogo desde la base de
datos — sin tocar WooCommerce. 57/57 tests pasando. Ver **`DATABASE.md`**,
sección "Qué falta", para el detalle.

**Nuevo (24 de agosto de 2026): rentabilidad por canal.** El dueño planteó
que el objetivo no es solo automatizar ventas, sino saber qué productos
convienen realmente — un mismo producto puede ser rentable en tienda física
y no por Mercado Libre (comisión + envío pueden dejar un margen mínimo o
negativo). Se agregó `cost_price` a `ProductVariant` (nullable — un producto
sin costo cargado nunca muestra un margen inventado) y una tabla
`channel_cost_settings` para comisión/envío/otros costos **por canal,
siempre configurables** — a pedido explícito del dueño, el sistema NO asume
ningún porcentaje de comisión de Mercado Libre por defecto (nada de "13%
típico"); sin configurar, el margen neto de ese canal simplemente no se
calcula. `GET /api/rentabilidad` devuelve margen bruto (tienda) y neto (por
canal) en pesos y en porcentaje, con los productos sin costo al final, nunca
mezclados como si valieran $0. `PUT /api/configuracion/canales/{channel}`
configura los costos de un canal.

**Actualizado (24 de agosto de 2026): el dueño confirmó que no tenemos
ninguno de los datos reales todavía** (ni costos, ni comisión de ML, ni
ventas reales) — así que se dejó de agregar reglas/umbrales de rentabilidad
y se enfocó en dejar la estructura lista para cuando esos datos lleguen:

- `app/db/import_costs.py` ahora acepta **`.xlsx` y `.csv`** — el dueño
  tiene su información en Excel, no tiene sentido pedirle que la convierta a
  mano. También corregido: un SKU numérico en Excel (12345 en vez de
  "12345") se normaliza a texto antes de buscar el match.
- `POST /api/costos/importar` sube el archivo directamente por HTTP (mismo
  motor que el script de línea de comandos) — para cuando el panel tenga un
  botón "Importar costos" en vez de requerir la terminal.
- `GET /api/rentabilidad` ahora devuelve `{resumen, productos}` en vez de
  una lista pelada — `resumen.productosConCosto === 0` es exactamente lo
  que una futura pantalla necesita para mostrar "⚠️ Aún no hay costos de
  compra cargados" en vez de una tabla vacía o con números inventados.
- La base de datos local (`libreria_central.db`) se reseteó a un estado
  limpio antes de terminar esta fase: catálogo de prueba sí, costos y
  canales configurados NO — para que ningún dato de verificación quede
  mezclado como si fuera información real.

**Nuevo (24 de agosto de 2026): stock reservado para Mercado Libre, no
inventario físico.** Decisión explícita del dueño: el sistema no debe
convertirse en un control de inventario físico completo — la tienda
presencial se sigue controlando "al ojo", a propósito, sin movimientos,
ajustes ni transferencias. Se agregó `marketplace_stock` a `ProductVariant`:
un tope manual que el dueño fija ("ofrezco 5 unidades por ML"), completamente
separado de `stock_quantity` (lo que reporta WooCommerce). `PUT
/api/productos/{id}/stock-mercadolibre` lo configura (5 → 10 → 0 → null, en
cualquier momento); `app/domain/marketplace_stock.py` tiene la regla de
descuento (`apply_sale`) que va a usar el futuro procesamiento de ventas de
ML — probada, pero **todavía no conectada a ninguna venta real** (no hay
sincronización de pedidos de Mercado Libre todavía). Ni WooCommerce ni
sincronización de inventario entre canales — explícitamente fuera de
alcance. 104/104 tests pasando.

**Nuevo (24 de agosto de 2026): OAuth real de Mercado Libre + importación
de sus ventas.** Ver el detalle completo en **`DATABASE.md`**, sección
"Mercado Libre real". En resumen: `app/adapters/mercadolibre.py` habla con
la API real (OAuth + `/orders/search`); los tokens se cifran en la base
(nunca texto plano, `app/domain/token_crypto.py`); `POST
/api/mercadolibre/importar-ventas` trae pedidos reales, los matchea por SKU,
y descuenta `marketplace_stock` — sin guardar ningún dato del comprador.
**Sin credenciales reales del dueño (MERCADOLIBRE_CLIENT_ID/SECRET,
TOKEN_ENCRYPTION_KEY en `.env`), nada de esto se puede usar todavía** —
`/api/mercadolibre/conectar` lo dice explícitamente en vez de simular una
conexión. 140/140 tests pasando.

**NO hay todavía, a propósito:** ninguna operación de escritura en
WooCommerce (crear/editar producto, actualizar stock) — mismo alcance que
el script de auditoría original. Ninguna escritura tampoco en Mercado
Libre (no crea/edita publicaciones, no actualiza precio/stock allá).
Ninguna autenticación de usuarios del panel. Ningún manejo de
pedidos/stock centralizado/webhooks. Todo eso sigue el roadmap ya acordado
en `arquitectura-fase0-decisiones.md`, sección 7.10 (este backend arranca en
la Fase 3, recién empezando).

**Verificación:** todo lo de arriba se probó con `pytest` (mocks vía
`respx`, mismo patrón que los tests de TypeScript) y con corridas
end-to-end reales del servidor contra un servidor HTTP mock local que
simula distintos escenarios (catálogo con variaciones, backend caído,
credenciales faltantes, WooCommerce inalcanzable, autenticación rechazada).
Con las credenciales reales ya configuradas en tu `.env`, el endpoint
`/api/productos/reporte` responde con el catálogo real de la tienda.

## Estructura

```
backend/
  app/
    main.py              Punto de entrada (FastAPI app, endpoint /api/health)
    config.py             Carga de .env (con la misma protección contra
                          variables de entorno sueltas que auditCatalog.ts;
                          ahora también DATABASE_URL, ver DATABASE.md)
    adapters/
      woocommerce.py       El adaptador — el "motor" pedido explícitamente
                          por el dueño como núcleo de esta app.
      mercadolibre.py        OAuth real + lectura de pedidos — solo
                          lectura, sin escribir nada en Mercado Libre.
    domain/
      analysis.py          Funciones puras de análisis del catálogo.
      profitability.py       Margen bruto/neto por canal — nunca asume un
                          costo o una comisión que no esté cargada.
      marketplace_stock.py    Regla del tope de stock reservado para ML —
                          nunca inventario físico (ver DATABASE.md).
      marketplace_orders.py   Mapea un pedido real de ML a Order/OrderItem
                          — nunca extrae datos del comprador.
      token_crypto.py          Cifra/descifra los tokens de Mercado Libre.
      security.py           Hash de contraseñas (bcrypt) — nunca texto plano.
    api/routes/
      productos.py         GET /api/productos/reporte (WooCommerce en vivo)
      productos_db.py       GET/PUT /api/productos... incluye
                          PUT /api/productos/{id}/stock-mercadolibre
      rentabilidad.py        GET /api/rentabilidad (margen por producto y canal)
      configuracion.py       GET/PUT /api/configuracion/canales/{channel}
      costos.py                POST /api/costos/importar (sube .xlsx/.csv)
      mercadolibre.py         GET .../estado, .../conectar, .../callback,
                          POST .../importar-ventas, .../desconectar
      catalogo.py              POST /api/catalogo/importar/analizar,
                          /confirmar — importador universal por Excel/CSV
      seleccion.py              GET /api/seleccion — qué conviene publicar
      publicaciones.py          GET/POST /api/publicaciones/... — borrador
                          de publicación, simulado
      dashboard.py              GET /api/dashboard/resumen — todo el
                          Dashboard del frontend en una sola llamada
    db/                    Base de datos propia — ver DATABASE.md
      seed_demo.py           Catálogo de prueba (python -m app.db.seed_demo)
      import_costs.py         Importa costos desde .xlsx o .csv
                          (python -m app.db.import_costs archivo.xlsx)
  alembic/                Migraciones — ver DATABASE.md
  tests/
    test_woocommerce_adapter.py
    test_analysis.py
    test_productos_db.py    Pruebas end-to-end de productos_db.py (incluye
                          stock-mercadolibre)
    test_profitability.py   Pruebas de domain/profitability.py
    test_marketplace_stock.py  Pruebas de domain/marketplace_stock.py
    test_marketplace_orders.py Pruebas de domain/marketplace_orders.py
                          (incluye "nunca guarda datos del comprador")
    test_token_crypto.py     Pruebas de domain/token_crypto.py
    test_mercadolibre_adapter.py    Pruebas del adaptador (respx, sin red real)
    test_mercadolibre_endpoints.py  Pruebas end-to-end de OAuth + importar-ventas
    test_rentabilidad.py    Pruebas end-to-end de rentabilidad.py y configuracion.py
    test_costos.py           Pruebas end-to-end de subir .xlsx/.csv por HTTP
    db/                    Pruebas del modelo de datos, seed_demo.py e import_costs.py — ver DATABASE.md
  requirements.txt
  pytest.ini
  .env.example
  DATABASE.md             Diseño y uso de la base de datos (Fase 3)
```

## Cómo correrlo

Ver instrucciones completas en la respuesta donde se entregó este backend.
Resumen:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # y completa las credenciales reales (opcional para lo de abajo)
alembic upgrade head           # crea la base de datos local (ver DATABASE.md)
python -m app.db.seed_demo    # catálogo de prueba — no necesita WooCommerce
python -m pytest -q           # 277 tests, no necesita WooCommerce ni Mercado Libre
uvicorn app.main:app --reload --port 8000
```

Con el servidor corriendo, `GET http://localhost:8000/api/productos` ya
responde con el catálogo de prueba — sin necesitar `WOOCOMMERCE_URL` ni
credenciales configuradas.

Con el servidor corriendo: `http://localhost:8000/api/health` (chequeo
básico) y `http://localhost:8000/api/productos/reporte` (el reporte real,
una vez que el `.env` tenga las credenciales de verdad).

### Volver a un estado limpio (antes de entregar, o entre pruebas)

`libreria_central.db` es un archivo local (gitignored, nunca se sube) — el
catálogo de `seed_demo.py` es solo para desarrollo/demo, nunca datos reales
del dueño. Para borrar todo (catálogo de prueba, costos, cuentas de
Mercado Libre de prueba, pedidos importados en pruebas) y dejar la base
vacía, lista para datos reales o para volver a sembrar el catálogo demo:

```bash
cd backend
rm libreria_central.db        # Windows: del libreria_central.db
alembic upgrade head           # recrea el esquema vacío
python -m app.db.seed_demo    # opcional — solo si querés el catálogo demo de nuevo
```

## Frontend

El panel visual (`frontend/`, en la raíz del proyecto, al lado de esta
carpeta) consume este endpoint. Necesita este backend corriendo en
`http://localhost:8000` — ver `frontend/README.md` para cómo servirlo.
Por eso `app/main.py` ya trae CORS habilitado para
`http://localhost:5500` y `http://127.0.0.1:5500` (los orígenes exactos que
usa ese frontend en desarrollo local, no un comodín).
