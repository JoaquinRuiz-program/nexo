# Librería Central — Backend (Fase 3, recién iniciada)

Backend real del proyecto, en Python + FastAPI (stack confirmado por el
dueño el 21 de agosto de 2026, sobre la recomendación ya escrita en
`arquitectura-fase0-decisiones.md`). Vive fuera de `src/` (el frontend
React) y de `scripts/woocommerce-audit/` (el script de auditoría) — es un
proyecto Python independiente, con su propio entorno virtual.

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
                          POST .../importar-ventas
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
python -m pytest -q           # 140 tests, no necesita WooCommerce ni Mercado Libre
uvicorn app.main:app --reload --port 8000
```

Con el servidor corriendo, `GET http://localhost:8000/api/productos` ya
responde con el catálogo de prueba — sin necesitar `WOOCOMMERCE_URL` ni
credenciales configuradas.

Con el servidor corriendo: `http://localhost:8000/api/health` (chequeo
básico) y `http://localhost:8000/api/productos/reporte` (el reporte real,
una vez que el `.env` tenga las credenciales de verdad).

## Frontend

El panel visual (`frontend/`, en la raíz del proyecto, al lado de esta
carpeta) consume este endpoint. Necesita este backend corriendo en
`http://localhost:8000` — ver `frontend/README.md` para cómo servirlo.
Por eso `app/main.py` ya trae CORS habilitado para
`http://localhost:5500` y `http://127.0.0.1:5500` (los orígenes exactos que
usa ese frontend en desarrollo local, no un comodín).
