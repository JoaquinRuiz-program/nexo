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

Esto es solo el modelo — todavía no hay ningún endpoint que lea/escriba en
esta base de datos ni ningún proceso que la llene con datos reales de
WooCommerce o Mercado Libre. Eso es exactamente lo que sigue en la próxima
fase: construir el motor de sincronización (que si probablemente sí
necesite sesiones asíncronas de SQLAlchemy, a diferencia de este diseño) y
los endpoints que el frontend (`js/dataSource.js`) va a consumir en lugar
de `js/demoData.js` — ver la nota en `frontend/js/dataSource.js` sobre ese
mismo punto.

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
    domain/
      security.py          Hash de contraseñas (bcrypt) — nunca texto plano
  alembic/
    env.py                 Configurado para leer DATABASE_URL y ver todos los modelos
    versions/
      91afd89306ea_esquema_inicial.py
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
