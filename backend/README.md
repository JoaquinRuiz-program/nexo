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

**NO hay todavía, a propósito:** ninguna operación de escritura (crear/
editar producto, actualizar stock) — mismo alcance que el script de
auditoría. Ninguna base de datos propia (el endpoint de hoy consulta
WooCommerce en vivo cada vez, no guarda una copia local — eso es el punto
7.1 de la arquitectura, todavía no construido). Ninguna autenticación de
usuarios del panel. Ninguna integración con Mercado Libre. Ningún manejo de
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
    domain/
      analysis.py          Funciones puras de análisis del catálogo.
      security.py           Hash de contraseñas (bcrypt) — nunca texto plano.
    api/routes/
      productos.py         GET /api/productos/reporte (WooCommerce en vivo)
      productos_db.py       GET /api/productos, GET /api/productos/{id}
                          (base de datos propia, sin WooCommerce)
    db/                    Base de datos propia — ver DATABASE.md
      seed_demo.py           Catálogo de prueba (python -m app.db.seed_demo)
  alembic/                Migraciones — ver DATABASE.md
  tests/
    test_woocommerce_adapter.py
    test_analysis.py
    test_productos_db.py    Pruebas end-to-end de productos_db.py
    db/                    Pruebas del modelo de datos y de seed_demo.py — ver DATABASE.md
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
python -m pytest -q           # 57 tests, no necesita WooCommerce ni Mercado Libre
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
