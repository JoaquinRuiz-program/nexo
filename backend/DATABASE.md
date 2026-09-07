# Base de datos propia del sistema (Fase 3 — diseño + modelos + migraciones + pruebas)

Este documento explica la base de datos que se acaba de agregar al backend.
**No conecta Mercado Libre, no publica productos, no modifica WooCommerce ni
ejecuta ninguna sincronización real** — eso sigue fuera de alcance a
propósito. Lo que hay hoy es: el diseño de datos, los modelos (SQLAlchemy),
las migraciones (Alembic) y las pruebas que confirman que las relaciones y
restricciones funcionan como se decidieron.

La explicación completa del diseño (por qué estas tablas, por qué estas
relaciones, cómo se evitan duplicados, cómo se conecta WooCommerce con
Mercado Libre, qué tecnología se eligió y por qué) se entregó en la
conversación antes de escribir este código, y queda guardada también en el
proyecto de Claude (`claude/diseno-base-de-datos-fase3.md`).

## Cómo levantar la base de datos

No hace falta instalar ningún motor de base de datos para desarrollo o
pruebas — se usa SQLite (un archivo, incluido en Python).

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows (en Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

Por defecto, la base de datos vive en `backend/nexo.db` (un
archivo SQLite que se crea solo). **Hasta el 6 de septiembre de 2026 ese
archivo se llamaba `libreria_central.db`**, nombre heredado del proyecto
original; si venís de una copia anterior, renombralo (`mv
libreria_central.db nexo.db`) o vas a arrancar con una base vacía y
"perder" tus datos locales. Si más adelante se quiere usar PostgreSQL
(recomendado para producción), se define `DATABASE_URL` en `backend/.env`
— ver `.env.example`. El resto del código (modelos, migraciones) no cambia
en absoluto: es la misma URL configurable, no una base de datos distinta
para cada motor.

## Cómo ejecutar las migraciones

Las tablas NO se crean a mano ni con `create_all()` en producción — se usa
Alembic, que deja un historial versionado de cada cambio al esquema.

```bash
cd backend
alembic upgrade head      # crea/actualiza todas las tablas hasta la última versión
alembic downgrade base    # (si hiciera falta deshacer todo)
alembic current           # ver en qué versión está la base de datos actual
```

La migración inicial (`alembic/versions/91afd89306ea_esquema_inicial.py`)
crea las 20 tablas descritas en el diseño. Se generó automáticamente desde
los modelos (`alembic revision --autogenerate`) — cualquier cambio futuro a
los modelos en `app/db/models/` se refleja igual, con una migración nueva.

## Cómo correr las pruebas

```bash
cd backend
python -m pytest -q
```

Las pruebas de la base de datos (`tests/db/`) corren contra SQLite **en
memoria**, aisladas por prueba — nunca tocan `nexo.db`, ni
WooCommerce, ni Mercado Libre.

## Qué se puede probar hoy

- Creación de productos y variantes (todo producto tiene al menos una
  variante, incluso los "simple").
- Que el SKU (de producto y de variante) es único dentro de la tienda,
  pero varios productos sin SKU pueden coexistir sin chocar.
- La relación con WooCommerce (producto ↔ producto de WooCommerce, variante
  ↔ variación de WooCommerce), y que un mismo producto de WooCommerce no se
  puede vincular dos veces.
- La relación con Mercado Libre (publicación, variante de publicación), el
  stock segregado de Full, y que WooCommerce y Mercado Libre se identifican
  como "el mismo producto" únicamente por compartir el mismo ID interno.
- Pedidos y líneas de pedido: el precio se guarda al momento de la venta y
  no cambia después; la idempotencia (tienda + canal + ID externo) evita
  procesar el mismo pedido dos veces; un pedido nunca se pierde aunque no
  se logre emparejar con el catálogo; **ningún campo guarda datos del
  comprador** (se verificó explícitamente con el dueño).
- Sincronización: una corrida (`sync_jobs`) y su detalle por producto
  (`sync_logs`) — reproduce exactamente los dos ejemplos que pidió el dueño
  (línea de éxito con cantidad de productos, línea de error con SKU y
  motivo).
- Historial de stock (`stock_movements`): cada cambio queda en su propia
  fila, nunca se sobreescribe un número.
- Usuarios: la contraseña nunca se guarda en texto plano (se prueba
  explícitamente que el valor guardado no la contiene), el email es único,
  las sesiones y los tokens de recuperación de contraseña guardan solo un
  hash, nunca el token real.
- Suscripciones: plan con límite de productos (o sin límite, Enterprise),
  precios marcados como demo, columnas de Stripe reservadas pero vacías.

## Qué falta para conectar esto con datos reales (próxima fase)

**Actualizado 22 de agosto de 2026 — decisión del dueño:** el acceso a
WooCommerce que se probó hasta ahora no se considera el acceso definitivo de
la librería, así que el desarrollo sigue sin depender de eso. Primera
porción vertical ya construida, con datos de prueba en vez de WooCommerce:

- `app/db/seed_demo.py`: llena `products`/`product_variants` con un
  catálogo de prueba (16 productos, 22 filas contando variantes de color) —
  usa los mismos modelos que usará el futuro job de sincronización real, así
  que ese job no cambiará el endpoint de abajo, solo quién llena la tabla.
- `GET /api/productos` y `GET /api/productos/{id}` (`app/api/routes/productos_db.py`):
  leen el catálogo desde esta base de datos — probado con `pytest` (base en
  memoria) y en vivo contra `nexo.db` real (`alembic upgrade head`
  + `python -m app.db.seed_demo` + servidor corriendo).

Todavía falta: el resto de endpoints que ya lista `frontend/js/dataSource.js`
(`/api/dashboard/resumen`, `/api/estado-sistema`, `/api/sincronizacion`,
`/api/suscripcion`), conectar `dataSource.js` a estos endpoints (sigue en
Demo Mode hoy), y — más adelante — el motor de sincronización real con
WooCommerce (que sí probablemente necesite sesiones asíncronas de
SQLAlchemy, a diferencia de este diseño) para reemplazar `seed_demo.py`
como fuente de la base de datos.

**Actualizado 24 de agosto de 2026 — rentabilidad, no solo catálogo:** el
dueño planteó que el objetivo del sistema es identificar qué productos y
canales son realmente rentables, no solo automatizar publicaciones. Se
agregó `cost_price` a `product_variants` (nullable — sin costo cargado, sin
margen calculado, nunca un $0 inventado) y la tabla `channel_cost_settings`
(comisión/envío/otros costos, por tienda y por canal — "mercadolibre" hoy,
texto libre para agregar otros canales sin migrar el esquema). Ningún costo
tiene un valor por defecto: a pedido explícito del dueño, el sistema NO
asume ninguna comisión de Mercado Libre mientras no se configure — ver
`app/domain/profitability.py`. `app/db/import_costs.py` importa SKU+costo
desde **`.xlsx` o `.csv`** (el dueño tiene su Excel, no hay que pedirle que
lo convierta) — también vía `POST /api/costos/importar` para subirlo sin
terminal. **Todavía no se cargó ningún costo real** porque no tenemos el
Excel del dueño; el 24 de agosto de 2026 se reseteó `nexo.db` a
un estado limpio (catálogo de prueba, cero costos, cero canales
configurados) para que ningún dato de verificación quedara mezclado como si
fuera información real. No se agregaron reglas de rentabilidad ni umbrales
("¿conviene o no?") — eso requeriría inventar un número, y es justo lo que
el dueño pidió evitar.

**Actualizado 24 de agosto de 2026 — stock reservado para Mercado Libre, NO
inventario físico:** decisión explícita del dueño de no construir un
control de inventario físico completo (sin movimientos, ajustes ni
transferencias) — la tienda presencial se sigue controlando "al ojo", fuera
del sistema, a propósito. Se agregó `marketplace_stock` a
`product_variants`: un tope manual ("ofrezco N unidades por ML"),
totalmente separado de `stock_quantity` (lo que reporta WooCommerce). None =
no configurado (no se ofrece por ML); 0 = se ofrecía y se pausó o se agotó
lo reservado — misma distinción que `cost_price`. La regla de descuento por
venta (`app/domain/marketplace_stock.py::apply_sale`) está escrita y
probada, pero todavía no está conectada a ninguna venta real — no hay
sincronización de pedidos de Mercado Libre. Tampoco se creó stock para
WooCommerce ni sincronización de inventario entre canales — ambos
explícitamente fuera de alcance por ahora.

## Mercado Libre real (24 de agosto de 2026 — flujo completo desde el 29 de agosto; arquitectura multiempresa desde el 29 de agosto, segunda ronda)

**Nexo es un SaaS multiempresa — cada empresa cliente es una más, ninguna
es una integración especial.** Dos conceptos que nunca hay que
confundir:

- **Aplicación desarrolladora de Mercado Libre** (`MERCADOLIBRE_CLIENT_ID`/
  `_CLIENT_SECRET`/`_REDIRECT_URI` en `backend/.env`): es de **Nexo**. Se
  crea UNA sola vez y sirve para todas las empresas que usen la plataforma.
  Nunca se le pide a un cliente que cree su propia aplicación.
- **Cuenta vendedora**: es de **cada empresa cliente**. Cada una conecta su
  propio seller de Mercado Libre por OAuth; queda guardada en su propia fila
  de `marketplace_accounts`, scopeada por `store_id` (cada `Store` = una
  empresa cliente distinta — ver `app/db/models/stores.py`). Dos empresas
  conectando cada una su propio seller conviven sin ningún problema:
  ```
  Empresa A (Store 1) -> MarketplaceAccount(store_id=1) -> Seller A
  Empresa B (Store 2) -> MarketplaceAccount(store_id=2) -> Seller B
  ```
  nunca `Nexo -> Mercado Libre` como una única conexión global.

`apply_sale` de la sección anterior ya está conectada — este es el motor
que la usa. Flujo real, de punta a punta, sin ningún dato inventado:

```
Frontend: botón "Conectar Mercado Libre" (Integraciones -> Mercado Libre)
  -> GET /api/mercadolibre/conectar
     - si faltan credenciales, error explicando EXACTAMENTE cuáles
     - si están, arma un state + un par PKCE (code_verifier/code_challenge,
       RFC 7636 — opcional según Mercado Libre, pero siempre se manda) y
       devuelve la URL real de autorización
  -> el navegador navega de verdad a esa URL (no es un fetch: es Mercado
     Libre quien tiene que mostrar su propia pantalla de login)
Dueño inicia sesión en Mercado Libre y autoriza la app (o cancela)
  -> Mercado Libre redirige el navegador a MERCADOLIBRE_REDIRECT_URI
     (este backend) con ?code=...&state=... (o ?error=access_denied si canceló)
GET /api/mercadolibre/callback
  -> valida el state (protección CSRF) y recupera el code_verifier de PKCE
  -> cambia el code por access_token/refresh_token REALES
  -> pide GET /users/me para identificar la cuenta (id, nickname, site_id
     — nunca nombre real, email, teléfono ni dirección, aunque /users/me
     los devuelva)
  -> guarda todo CIFRADO en marketplace_accounts (nunca texto plano)
  -> SIEMPRE redirige el navegador de vuelta al frontend
     (FRONTEND_BASE_URL/?ml=conectado#/mercadolibre, o
     ?ml=error&razon=<código corto> si algo falló) — nunca devuelve un JSON
     crudo, porque quien llega ahí es el navegador real del dueño
Frontend: pantalla Mercado Libre pasa a mostrar "Mercado Libre conectado"
  con la cuenta vendedora, y los botones "Importar ventas ahora" /
  "Administrar" (desconectar)

POST /api/mercadolibre/importar-ventas
  -> antes de llamar a Mercado Libre, revisa si el access_token venció y lo
     renueva solo (refresh_token de un solo uso: Mercado Libre devuelve uno
     NUEVO en cada renovación, y hay que guardar ese, nunca reusar el viejo)
  -> trae pedidos reales de GET /orders/search
  -> por cada pedido nuevo: matchea seller_sku contra product_variants,
     crea Order + OrderItem, descuenta marketplace_stock (apply_sale)
  -> comission_amount de cada pedido es el sale_fee REAL que Mercado Libre
     ya cobró (no una comisión estimada) — ver domain/marketplace_orders.py

POST /api/mercadolibre/desconectar
  -> borra tokens y estado de la cuenta — idempotente, se puede volver a
     conectar (la misma cuenta u otra) en cualquier momento
```

**Nunca se guarda ningún dato del comprador** — el payload real de un
pedido de Mercado Libre trae un objeto `buyer` completo (nombre, email,
teléfono); `map_ml_order` nunca lo toca, ni siquiera para guardarlo cifrado.
Solo se persiste lo necesario para conciliar la operación: ID del pedido,
fecha, SKU, cantidad, precio, estado, comisión. Tampoco se guarda nada
personal de la cuenta VENDEDORA (la del dueño) más allá de lo mínimo para
identificarla: `external_account_id`, `external_account_nickname`,
`external_account_site_id` — tres columnas nuevas en `marketplace_accounts`
(migración `ea44b265af0b`).

**Tokens cifrados, nunca en texto plano** — `access_token_encrypted` /
`refresh_token_encrypted` en `marketplace_accounts`, con Fernet
(`app/domain/token_crypto.py`) y una clave que vive solo en
`TOKEN_ENCRYPTION_KEY` (`.env`, nunca en Git). Sin esa clave configurada,
cifrar/descifrar falla explícito — nunca usa una clave por defecto insegura.

**La conexión es por tienda (`store_id`), nunca global** —
`marketplace_accounts` ya tenía esa columna desde que se creó el modelo;
cada empresa tiene su propia fila, con sus propios tokens, sin tocar el
modelo (ver `uq_marketplace_account_store_marketplace`). El `state` de
OAuth también guarda `store_id` (ver `_new_state` en
`app/api/routes/mercadolibre.py`) — así /callback asocia la cuenta a la
empresa que REALMENTE inició ese intento de conexión, no a "la actual" en
el instante en que Mercado Libre responde.

**Lo único que falta para multiempresa completa** es autenticación real de
usuarios con selector de "empresa activa" (`User`/`AuthSession` ya existen
en `app/db/models/users.py`, pero sin ruta de login en el backend todavía
— `lc_session` del frontend es solo una demo). Hoy `_get_default_store()`
(un único punto, documentado en el código) resuelve "la empresa actual"
como la primera tienda que existe — cuando exista login multiempresa, ese
es el único lugar que hay que reemplazar; el resto de este archivo (tokens,
callback, desconexión, importación de ventas) ya opera por `store_id` y no
cambia. Las pruebas de aislamiento entre empresas
(`tests/test_mercadolibre_endpoints.py`, sección "Arquitectura
multiempresa/multi-seller") demuestran esto operando dos `Store` a la vez:
cada una ve solo su propio seller, desconectar una nunca afecta a la otra,
y renovar el token de una nunca toca el de la otra.

### Cómo probarlo — guía paso a paso

**Lo que tenés que hacer vos (no se puede generar ni inventar):**

1. Entrar a https://developers.mercadolibre.cl (o el sitio del país que
   corresponda) — esto crea la **aplicación de Nexo** (el paso 1 de
   "Arquitectura multiempresa" de más arriba), no la cuenta de ningún
   cliente. Podés usar cualquier cuenta real de Mercado Libre para crearla
   (no hace falta que sea la de ningún cliente en particular).
2. "Mis aplicaciones" -> crear una aplicación nueva.
3. **Redirect URI**: Mercado Libre exige HTTPS siempre, incluso para
   desarrollo — `http://localhost:...` no se puede registrar. La forma más
   simple de probar esto en tu máquina es un túnel HTTPS hacia tu backend
   local, por ejemplo con [ngrok](https://ngrok.com/):
   ```bash
   ngrok http 8000
   ```
   ngrok te da una URL como `https://algo-random.ngrok-free.app` — la
   Redirect URI a registrar en Mercado Libre es
   `https://algo-random.ngrok-free.app/api/mercadolibre/callback`.
4. Mercado Libre te muestra el **App ID** (client id) y el **Secret Key**
   (client secret) — cópialos.
5. Completa en `backend/.env` (copiando `.env.example` si no existe):
   ```
   MERCADOLIBRE_CLIENT_ID=<tu App ID>
   MERCADOLIBRE_CLIENT_SECRET=<tu Secret Key>
   MERCADOLIBRE_REDIRECT_URI=https://algo-random.ngrok-free.app/api/mercadolibre/callback
   TOKEN_ENCRYPTION_KEY=<generada con el comando en .env.example>
   ```
   (`MERCADOLIBRE_AUTH_DOMAIN` y `FRONTEND_BASE_URL` solo si no son los
   valores por default — Chile / `http://localhost:5500`.)

**Lo que hace Nexo (ya construido, no hace falta tocar nada más):**

6. `uvicorn app.main:app --reload --port 8000` (backend) y el frontend
   estático en el puerto 5500 — ver `frontend/README.md`.
7. Abrí Nexo, entrá a Integraciones -> Mercado Libre.
8. Presioná "Conectar Mercado Libre" -> te lleva a la pantalla real de
   Mercado Libre -> autorizá -> volvés a Nexo con "Mercado Libre conectado".
9. "Importar ventas ahora" trae tus pedidos reales; "Administrar" permite
   desconectar.

**Bloqueado hasta que completes esos 5 pasos:** sin credenciales,
`/api/mercadolibre/conectar` devuelve 400 explicando cuál falta — nunca
genera una URL con un client_id inventado.

#### Probar con usuarios de prueba (recomendado antes de usar la cuenta real de la librería)

Mercado Libre no tiene un ambiente "sandbox" separado — en vez de eso deja
crear hasta 10 **usuarios de prueba** por aplicación, que funcionan como
cuentas reales (conectar, autorizar, comprar/vender entre ellos) pero
aislados de tu reputación real. Es la forma correcta de probar el flujo de
conexión — incluido que dos empresas distintas queden separadas — sin
tocar todavía la cuenta real de ningún cliente:

1. Conectá Nexo una vez con **cualquier** cuenta real de Mercado Libre (la
   misma con la que creaste la aplicación en el paso 1 sirve) para obtener
   un `access_token` válido — es el único uso de esa conexión.
2. Con ese token, creá un usuario de prueba:
   ```bash
   curl -X POST -H "Authorization: Bearer <access_token>" \
     -H "Content-Type: application/json" \
     -d '{"site_id":"MLC"}' \
     https://api.mercadolibre.com/users/test_user
   ```
   (`site_id` según el país — `MLC` Chile, `MLA` Argentina, `MLM` México,
   etc.) La respuesta trae `nickname` y `password` del usuario de prueba —
   guardalos, Mercado Libre no los vuelve a mostrar.
3. Repetí el paso 2 para tener un segundo usuario de prueba distinto — así
   podés simular dos empresas clientes conectando cada una su propio
   seller y confirmar que Nexo las mantiene separadas.
4. Desconectá la cuenta real (botón "Administrar" -> "Desconectar") y
   volvé a conectar usando el nickname/password del usuario de prueba en
   la pantalla de login de Mercado Libre.

Fuente oficial: [Realiza pruebas — Developers Mercado Libre](https://developers.mercadolibre.cl/realiza-pruebas).

### Producción — qué cambia respecto a desarrollo local

- **Redirect URI**: la del dominio real donde corra el backend en
  producción (ej. `https://api.tudominio.cl/api/mercadolibre/callback`) —
  hay que registrarla como una Redirect URI **adicional** en la misma
  aplicación de Mercado Libre (o crear una aplicación de producción
  separada, según prefiera el dueño), y actualizar
  `MERCADOLIBRE_REDIRECT_URI` en el `.env` de producción.
- **`FRONTEND_BASE_URL`**: el dominio real donde se sirva el frontend en
  producción, no `localhost`.
- **CORS**: `DEV_FRONTEND_ORIGINS` en `app/main.py` hoy solo lista
  `localhost:5500`/`127.0.0.1:5500` — en producción hay que agregar el/los
  dominio(s) reales (nunca `"*"`).
- **`TOKEN_ENCRYPTION_KEY`**: una clave DISTINTA a la de desarrollo,
  generada una vez y guardada de forma segura (gestor de secretos del
  hosting, nunca en Git) — perderla significa no poder descifrar los
  tokens ya guardados (hay que reconectar todas las cuentas).
- **Estado OAuth (`_pending_states`)**: hoy vive en memoria del proceso —
  válido para un solo proceso/réplica. Si producción corre con más de una
  réplica del backend, hay que moverlo a algo compartido (Redis, o una
  tabla) antes de escalar horizontalmente — anotado en el código, no
  resuelto porque no hace falta con una sola réplica.
- **Base de datos**: `DATABASE_URL` apuntando a PostgreSQL real, no SQLite.

**Limitación conocida, deliberada:** solo se importan pedidos NUEVOS. Si un
pedido ya importado se cancela después en Mercado Libre, el estado se
actualiza acá, pero el `marketplace_stock` que ya se descontó no se
revierte solo — el dueño lo ajusta a mano. Revertir automáticamente es una
función aparte, no construida todavía (no hace falta hasta que haya
pedidos reales para saber si el caso es frecuente).

**Explícitamente fuera de alcance en esta fase** (no construido): ninguna
regla de "conviene/no conviene" vender por Mercado Libre, ninguna comisión
por defecto (nunca 13%, nunca ningún otro número — sale de `sale_fee` real
de cada pedido, o de `ChannelCostSettings` si el dueño lo configura a
mano), WooCommerce (no tocado en esta fase), sincronización de productos/
publicaciones (el modelo `MarketplaceListing` ya existe y está listo para
esa próxima fase, pero no se construyó todavía — primero hace falta una
conexión sólida, que es lo que se completó acá), y ninguna operación de
escritura en Mercado Libre (no crea/edita publicaciones ni actualiza
precio/stock allá — sigue siendo de solo lectura, igual que el adaptador de
WooCommerce cuando se construyó).

## Google Sheets real (5 de septiembre de 2026 — importación de catálogo)

Mismo patrón exacto que "Mercado Libre real" de arriba, reusando el mismo
modelo (`marketplace_accounts`, ahora con `marketplace="google_sheets"`) y
el mismo mecanismo de OAuth con `state` — ver `app/adapters/google_sheets.py`
y `app/api/routes/google_sheets.py`. Diferencias puntuales:

- **Scope mínimo, único**: `https://www.googleapis.com/auth/spreadsheets.readonly`
  — no se pide ningún permiso de Google Drive. Por eso "elegir una hoja de
  cálculo" en Nexo es pegar su link (o ID), no un selector visual de
  archivos de Drive — ese selector exigiría un scope de Drive bastante más
  amplio (o el Picker API de Google, una pieza aparte) para un beneficio
  chico en esta primera versión.
- **Sin PKCE**: la documentación oficial de Google no lo pide para un
  cliente confidencial tipo "Web application" (a diferencia de Mercado
  Libre, que lo recibe siempre aunque sea opcional).
- **Reutiliza el importador universal**: `GoogleSheetsAdapter.get_values`
  convierte la respuesta de la API de Sheets a la misma forma
  `(encabezados, filas)` que ya devuelve `app/domain/spreadsheet_io.py` para
  un Excel/CSV — de ahí en más, `app/domain/catalog_import.py`
  (detección de columnas, validación) y `app/domain/catalog_writer.py`
  (crear/actualizar productos, respetando el límite de productos del plan)
  son el MISMO código que usa `/api/catalogo/importar/*`, sin duplicar nada.
- **`external_account_site_id` reaprovechado como "pestaña elegida"** — para
  Mercado Libre es un código corto ("MLC"); para Google Sheets es el nombre
  de la pestaña de la hoja de cálculo, texto libre. Se amplió esa columna de
  `String(10)` a `String(100)` (migración `7f1a9c3e5d02`) porque un nombre
  de pestaña real fácilmente supera 10 caracteres.
- **Sin sincronización automática**: "volver a sincronizar" es una acción
  manual (botón en la pantalla de Google Sheets) que vuelve a leer la
  pestaña y muestra qué va a cambiar ANTES de importar — no hay ningún
  worker, cron ni webhook corriendo solo.

**Lo único que no se puede generar desde acá** (mismo criterio que
`MERCADOLIBRE_CLIENT_ID`/`_SECRET`): un Client ID y Client Secret de OAuth
reales, creados una vez en https://console.cloud.google.com/apis/credentials
(proyecto de Nexo, con la Google Sheets API habilitada) — ver
`backend/.env.example` para la guía paso a paso completa de
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`GOOGLE_REDIRECT_URI`. A
diferencia de Mercado Libre, Google sí acepta `http://localhost...` como
Redirect URI para desarrollo local — no hace falta un túnel HTTPS para
probar esto antes de tener un dominio real.

## Cobro real con Mercado Pago (6 de septiembre de 2026)

Distinto de Mercado Libre/Google Sheets en algo fundamental: ahí cada
EMPRESA CLIENTE conecta su propia cuenta (OAuth, un token por tienda). Acá
es al revés — **Nexo es el vendedor**, cobrando la mensualidad/anualidad a
sus clientes. Por eso hay una única cuenta de Mercado Pago (la del dueño
de Nexo) y un único `MERCADOPAGO_ACCESS_TOKEN` de servidor para todos los
clientes — nunca OAuth, nunca por tienda. Ver
`app/adapters/mercadopago.py` y `app/api/routes/pagos.py`.

**Dos mecanismos reales de Mercado Pago, uno por ciclo de facturación:**

- **Mensual -> Suscripciones (`POST /preapproval`)**: cobro recurrente
  real — Mercado Pago vuelve a cobrar la tarjeta guardada cada mes solo,
  sin que el cliente tenga que volver.
- **Anual -> Pago único (`POST /checkout/preferences`, "Checkout Pro")**:
  un cobro real por el total del año con el descuento vigente (15%,
  `app/domain/plans.py::DESCUENTO_ANUAL_PCT`), pero NO un cobro recurrente
  de Mercado Pago. Decisión deliberada: la documentación oficial de
  Suscripciones confirma con precisión un cobro recurrente MENSUAL
  (`frequency_type: "months"`, `frequency: 1`); no hay una confirmación
  igual de clara sobre "cobrar automáticamente una sola vez cada 12
  meses" sin ambigüedad. Con dinero real de por medio, se eligió el
  camino 100% documentado en vez de adivinar: el ciclo anual se renueva
  con un nuevo pago único cuando se acerca el vencimiento (Nexo puede
  avisarle al cliente, pero nunca le vuelve a cobrar la tarjeta sin que
  él confirme un nuevo pago). Si en el futuro se confirma oficialmente
  que un cobro anual recurrente automático es seguro y sin ambigüedad,
  ahí se puede migrar — nunca antes de volver a verificar contra la
  documentación oficial vigente en ese momento.

**Flujo:**

```
Frontend: pantalla "Mi plan" -> elegir plan + ciclo -> POST /api/pagos/iniciar
  -> arma external_reference = "nexo:<store_id>:<plan_code>:<ciclo>"
     (nunca escribe nada en Subscription todavía — elegir un plan y
     pagarlo de verdad son cosas distintas)
  -> crea la suscripción/preferencia real en Mercado Pago, devuelve
     `checkoutUrl` (init_point)
Frontend: navega de página completa a checkoutUrl — ahí el dueño de la
  tarjeta la ingresa en el checkout HOSTEADO de Mercado Pago (Nexo nunca
  la ve, ni el número ni nada)
Mercado Pago redirige el navegador a GET /api/pagos/callback (backend,
  nunca directo al frontend — mismo motivo que _frontend_redirect en
  mercadolibre.py: separar los parámetros que agrega Mercado Pago del
  router de hash del frontend) -> SIEMPRE redirige al frontend con un
  aviso genérico ("estamos confirmando tu pago") — esta redirección NUNCA
  decide nada por sí sola, un usuario podría fabricar esa URL a mano.
POST /api/pagos/webhook es la ÚNICA fuente de verdad de "se pagó de
  verdad" — Mercado Pago lo llama servidor a servidor, con una firma
  verificable (header X-Signature, validada contra
  MERCADOPAGO_WEBHOOK_SECRET con HMAC-SHA256). Al recibir uno, se le
  vuelve a preguntar a la propia API de Mercado Pago el estado real
  (GET /preapproval/{id} o GET /v1/payments/{id}) — nunca se confía en
  los datos que trae el cuerpo del webhook a ciegas. Recién ahí se
  activa el plan real: Subscription.status="active",
  billing_cycle, mercadopago_preapproval_id/mercadopago_last_payment_id,
  current_period_end (+30 o +365 días).
POST /api/pagos/cancelar -> cancela de verdad el cobro recurrente en
  Mercado Pago (ciclo mensual) antes de marcar la suscripción cancelada
  localmente — nunca alcanza con borrar el dato local, si no se cancela
  allá Mercado Pago sigue cobrando la tarjeta el mes que viene.
```

**Limitación conocida, no construida todavía:** detectar que un cobro
mensual del mes 2 en adelante FALLÓ (para marcar la suscripción
"past_due") requiere procesar el topic `subscription_authorized_payment`
de los webhooks — no se implementó en esta primera versión (activar el
plan la primera vez sí está cubierto de punta a punta). Tampoco hay
recordatorio automático de "tu plan anual vence pronto" todavía.

**Lo único que no se puede generar desde acá** (mismo criterio que
Mercado Libre/Google): una cuenta de Mercado Pago real y su Access
Token/Webhook Secret de producción — ver `backend/.env.example` para la
guía paso a paso de `MERCADOPAGO_ACCESS_TOKEN`/`MERCADOPAGO_WEBHOOK_SECRET`.

## Estructura agregada

```
backend/
  app/
    db/
      base.py             Base declarativa de SQLAlchemy (de acá cuelgan todos los modelos)
      session.py            Motor + sesiones (SQLite hoy, PostgreSQL en producción)
      models/
        users.py            User, UserPreferences, AuthSession, PasswordResetToken
        stores.py           Store, StoreSettings
        subscriptions.py    Plan (con publication_limit desde el
                          5 de septiembre de 2026), Subscription
        support.py          SupportTicket (Ayuda y soporte, 5 de
                          septiembre de 2026) — ver app/api/routes/soporte.py
                          (cliente) y admin.py (vista global)
        admin_log.py         AdminActionLog (registro simple de acciones
                          administrativas, 6 de septiembre de 2026)
        products.py         Product, ProductVariant
        woocommerce_link.py WooCommerceProduct, WooCommerceVariation
        marketplace.py      MarketplaceAccount, MarketplaceListing, MarketplaceListingVariant
        orders.py           Order, OrderItem
        sync.py             SyncJob, SyncLog
        stock.py            StockMovement
        channel_costs.py    ChannelCostSettings (comisión/envío por canal)
      import_costs.py         Importa costos desde .xlsx o .csv (SKU + costo)
    domain/
      security.py          Hash de contraseñas (bcrypt) — nunca texto plano
      profitability.py       Margen bruto/neto — nunca asume un costo o
                          una comisión que no esté cargada
      marketplace_stock.py    Tope de stock reservado para ML — nunca
                          inventario físico
      plans.py             Planes por defecto + límites de productos/
                          publicaciones (5 de septiembre de 2026)
      image_storage.py       Subida real de imágenes a disco local,
                          validada con Pillow (5 de septiembre de 2026)
                          — servidas por StaticFiles en /uploads/, ver
                          app/main.py
  alembic/
    env.py                 Configurado para leer DATABASE_URL y ver todos los modelos
    versions/
      91afd89306ea_esquema_inicial.py
      f978b9e55d66_costo_de_compra_y_costos_por_canal.py
      d22fcefcb976_stock_reservado_para_mercado_libre.py
  alembic.ini
  tests/db/
    conftest.py             Fixtures: base SQLite en memoria por prueba
    test_products.py
    test_woocommerce_link.py
    test_marketplace.py
    test_orders.py
    test_sync.py
    test_stock.py
    test_users.py
    test_subscriptions.py
```
