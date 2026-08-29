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

Por defecto, la base de datos vive en `backend/libreria_central.db` (un
archivo SQLite que se crea solo). Si más adelante se quiere usar PostgreSQL
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
memoria**, aisladas por prueba — nunca tocan `libreria_central.db`, ni
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
  memoria) y en vivo contra `libreria_central.db` real (`alembic upgrade head`
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
Excel del dueño; el 24 de agosto de 2026 se reseteó `libreria_central.db` a
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

## Mercado Libre real (24 de agosto de 2026)

`apply_sale` de la sección anterior ya está conectada — este es el motor
que la usa. Flujo real, sin ningún dato inventado:

```
Dueño abre GET /api/mercadolibre/conectar
  -> si faltan credenciales, error explicando EXACTAMENTE cuáles
  -> si están, devuelve la URL real de autorización de Mercado Libre
Dueño inicia sesión en Mercado Libre y autoriza la app
  -> Mercado Libre redirige a GET /api/mercadolibre/callback?code=...
  -> se cambia el code por access_token/refresh_token REALES
  -> se guardan CIFRADOS en marketplace_accounts (nunca texto plano)
POST /api/mercadolibre/importar-ventas
  -> trae pedidos reales de GET /orders/search
  -> por cada pedido nuevo: matchea seller_sku contra product_variants,
     crea Order + OrderItem, descuenta marketplace_stock (apply_sale)
  -> comission_amount de cada pedido es el sale_fee REAL que Mercado Libre
     ya cobró (no una comisión estimada) — ver domain/marketplace_orders.py
```

**Nunca se guarda ningún dato del comprador** — el payload real de un
pedido de Mercado Libre trae un objeto `buyer` completo (nombre, email,
teléfono); `map_ml_order` nunca lo toca, ni siquiera para guardarlo cifrado.
Solo se persiste lo necesario para conciliar la operación: ID del pedido,
fecha, SKU, cantidad, precio, estado, comisión.

**Tokens cifrados, nunca en texto plano** — `access_token_encrypted` /
`refresh_token_encrypted` en `marketplace_accounts`, con Fernet
(`app/domain/token_crypto.py`) y una clave que vive solo en
`TOKEN_ENCRYPTION_KEY` (`.env`, nunca en Git). Sin esa clave configurada,
cifrar/descifrar falla explícito — nunca usa una clave por defecto insegura.

**Bloqueado hoy, y por qué:** no hay ninguna cuenta real conectada porque
faltan las credenciales que solo el dueño puede generar:

1. `MERCADOLIBRE_CLIENT_ID` / `MERCADOLIBRE_CLIENT_SECRET` — se obtienen
   creando una aplicación en https://developers.mercadolibre.cl **con la
   cuenta de Mercado Libre real de la librería** (no una cuenta de prueba:
   necesitamos leer sus pedidos reales).
2. `MERCADOLIBRE_REDIRECT_URI` — hay que decidir/registrar la URL pública a
   la que Mercado Libre redirige después del login (en desarrollo local,
   `http://localhost:8000/api/mercadolibre/callback`; en producción, tiene
   que ser una URL HTTPS real del servidor donde corra este backend).
3. `TOKEN_ENCRYPTION_KEY` — esta sí se genera local, no depende de Mercado
   Libre (comando exacto en `.env.example`).

Sin estos tres datos, `/api/mercadolibre/conectar` devuelve 400 explicando
cuál falta — nunca genera una URL con un client_id inventado.

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
mano), WooCommerce (no tocado en esta fase), y ninguna operación de
escritura en Mercado Libre (no crea/edita publicaciones ni actualiza
precio/stock allá — sigue siendo de solo lectura, igual que el adaptador de
WooCommerce cuando se construyó).

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
        subscriptions.py    Plan, Subscription
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
