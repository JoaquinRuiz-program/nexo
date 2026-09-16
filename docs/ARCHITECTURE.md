# Arquitectura de Nexo

Mapa de referencia para retomar el proyecto después de una pausa. Describe el
código **real** tal como existe hoy (16 sept 2026) — nada planeado ni
aspiracional. Para detalle profundo de un área, los docs específicos
(`backend/*.md`) tienen la letra chica; esto es el mapa para no perderse.

## 0. Qué es Nexo

SaaS B2B multiempresa: automatiza catálogo, rentabilidad y publicaciones en
Mercado Libre Chile. `Store` = una empresa cliente (tenant). Producto real
(Production Release Candidate), no una demo — ver reglas en `CLAUDE.md`.

## 1. Árbol simplificado

```
nexo/
├── backend/
│   ├── app/
│   │   ├── main.py                # entrypoint FastAPI, monta routers + CORS + /uploads
│   │   ├── config.py               # Settings (variables de entorno), get_settings()
│   │   ├── api/
│   │   │   ├── deps.py             # get_current_store, get_current_session, require_nexo_admin
│   │   │   └── routes/             # UN archivo por área — ver sección 3
│   │   ├── domain/                 # lógica pura, sin red ni DB (testeable directo)
│   │   ├── services/                # orquesta domain + DB + adapters (comisiones, envío, sync)
│   │   ├── adapters/                # clientes HTTP reales: mercadolibre.py, mercadopago.py,
│   │   │                            #   google_sheets.py, woocommerce.py (legado, no en uso)
│   │   └── db/
│   │       ├── session.py          # engine + SessionLocal + get_db()
│   │       ├── base.py             # Base declarativa
│   │       └── models/             # un archivo por grupo de tablas
│   ├── alembic/versions/           # migraciones (31 al 16 sept 2026)
│   ├── tests/                      # pytest, ~980 pruebas
│   ├── nexo.db                     # SQLite dev — NUNCA en git (gitignored)
│   └── *.md                        # docs profundos por área (ver sección 11)
├── frontend/
│   ├── index.html                  # único HTML, carga todo con <script ?v=N>
│   ├── css/styles.css
│   └── js/                         # vanilla JS, todo cuelga de window.LC.* — ver sección 4
├── docs/ARCHITECTURE.md            # este archivo
├── PROGRESS.md                     # bitácora de lo hecho, con fecha
├── TODO.md                         # pendiente, por prioridad
└── CLAUDE.md                       # reglas de trabajo para Claude Code en este repo
```

No documentado (caché/generado): `__pycache__/`, `.venv/`, `node_modules`
(no existe, no hay build step en frontend).

**Ojo con la raíz**: además de lo de arriba, la raíz también tiene
`package.json`, `vite.config.ts`, `tsconfig*.json`, `index.html`, `src/`,
`public/` — **eso NO es Nexo**: es el prototipo React/Vite con el que
arrancó el proyecto (guarda todo en `localStorage`, no habla con el
backend). Queda a propósito, con un `npm run build` que falla adrede,
para que ningún proveedor de hosting lo autodetecte y publique en vez del
frontend real (ver el campo `"comentario"` de `package.json`). También en
la raíz: `legal/` (borradores de Términos/Privacidad, pendientes de
abogado), `scripts/` (generación de datos de prueba + auditoría
WooCommerce), `test-data/` (Excels de ejemplo para probar el importador),
`woocommerce-test-env/` (entorno de prueba de la integración WooCommerce,
hoy sin router activo).

## 2. Entrypoints

- **Backend**: `uvicorn app.main:app` (dev: `--reload --port 8000`; prod:
  `--workers 1`, ver sección 8). `app/main.py` arma la app FastAPI, incluye
  todos los routers de `app/api/routes/`, configura CORS y monta
  `/uploads` (imágenes subidas) con `StaticFiles`.
- **Frontend**: `frontend/index.html`, servido está o no por cualquier
  servidor estático (dev: `python -m http.server 5500` desde `frontend/`).
  No hay build step — los `<script src="...?v=N">` se versionan a mano.
- **Configuración**: `backend/app/config.py` (`Settings`, vía `pydantic`)
  lee `.env`. `backend/.env` real nunca se commitea (secretos).

## 3. Backend — por área

`get_current_store` (`app/api/deps.py`) es el ÚNICO resolutor de tenant en
todo el backend — cualquier endpoint que toque datos de una empresa lo usa.
Un acceso a datos de otra empresa **siempre devuelve 404, nunca 403** (evita
IDOR: no le confirmas a un atacante que el recurso existe).

| Área | Dónde vive | Depende de |
|---|---|---|
| **Auth / sesión** | `routes/auth.py`, `domain/security.py` (hash bcrypt), `db/models/users.py` (`User`, `AuthSession` — solo se guarda el HASH del token) | `deps.py::get_current_session` |
| **Multiempresa** | `deps.py::get_current_store` (resuelve por `AuthSession.active_store_id`) | Toda ruta de negocio |
| **Admin de plataforma** | `routes/admin.py`, gate `deps.py::require_nexo_admin` (global, `User.is_nexo_admin`) — nunca lo mismo que admin de una empresa | "Ver como empresa" = `AuthSession.viewing_store_id`, nunca crea sesión del cliente |
| **Catálogo / importación** | `routes/catalogo.py` (Excel/CSV), `domain/catalog_import.py` (detección de columnas), `domain/catalog_writer.py` (escribe productos) | dispara `services/ml_comisiones.py` en segundo plano |
| **Google Sheets** | `routes/google_sheets.py`, `adapters/google_sheets.py` | mismo flujo de importación que Excel |
| **Rentabilidad** | `routes/rentabilidad.py::build_profitability_rows/_fila` (ÚNICA fuente de las filas), `domain/profitability.py` (`net_margin`, puro) | ver sección 5 |
| **Selección/Oportunidades** | `routes/seleccion.py`, `domain/catalog_selection.py::classify_product` (ÚNICA regla "conviene") | reusa `build_profitability_rows` |
| **Precio recomendado / ¿Conviene?** | `routes/publicaciones.py` (`/precio-recomendado`, `/decision`, `/decision-lote`), `domain/pricing.py`, `domain/decision.py` | `domain/competencia.py` (opcional) |
| **Comisión real ML** | `services/ml_comisiones.py::actualizar_comisiones_reales` (categoría + comisión, cachea en `MercadoLibreCategoryFee`) | `adapters/mercadolibre.py` |
| **Envío ML** | `routes/rentabilidad.py::aplicar_envio_real_ml` (ÚNICA función que decide el envío del cálculo), `services/ml_shipping_sync.py` (real, por `item_id`), `services/ml_comisiones.py::_actualizar_estimaciones_envio` (estimado, categoría+precio), `domain/ml_shipping.py` (interpretación pura) | ver sección 5 |
| **Análisis en vivo (progreso)** | `services/analisis_rentabilidad_stream.py`, endpoint `POST /api/mercadolibre/analisis-rentabilidad/stream` (NDJSON) | orquesta los dos anteriores + `classify_product`, no reimplementa nada |
| **Publicaciones ML** | `routes/publicaciones.py` (`/validar`, `/preparar`, `/confirmar` = el único endpoint que hace `POST /items` real), `domain/listing_draft.py`, `domain/listing_validation.py`, `domain/ml_listing_payload.py` | revalida todo desde la base en `/confirmar`, nunca confía en pasos previos |
| **OAuth Mercado Libre** | `routes/mercadolibre.py` (`/conectar`, `/callback`), `domain/token_crypto.py` (Fernet) | credenciales de la APP en `.env` (de Nexo); token por empresa en `MarketplaceAccount` |
| **Ventas / importación de pedidos** | `routes/mercadolibre.py::importar_ventas` (paginado), `domain/marketplace_orders.py`, `domain/marketplace_stock.py` | descuenta stock reservado |
| **Devoluciones** | `services/ml_devoluciones_sync.py`, `db/models/returns.py` | |
| **Conciliación de comisiones** | `services/ml_conciliacion.py` | Billing API de ML |
| **Suscripciones / pagos** | `routes/suscripcion.py`, `routes/pagos.py`, `domain/subscription_lifecycle.py`, `domain/plans.py`, `adapters/mercadopago.py` | webhook valida firma HMAC |
| **Admin BI** | `routes/admin.py`, `domain/admin_overview.py` | agrega across todas las empresas, solo accesible a `is_nexo_admin` |
| **Eliminar cuenta** | `services/eliminar_cuenta.py` | borra TODAS las tablas scopeadas a `store_id` (mantener lista actualizada si se agrega una tabla nueva) |
| **Ciclo de vida de planes** | `services/lifecycle.py` (cron diario en prod) | pausa publicaciones si vence sin pagar |

## 4. Frontend — por pantalla

Todo vive en `window.LC.*`. Sin framework, sin build. `router.js` resuelve
el hash (`#/ruta`) a una función de render. Para modificar una pantalla,
mirar primero:

| Pantalla | Archivo principal | Datos vía |
|---|---|---|
| Login/registro | `auth.js` | `backendApi.js` |
| Dashboard | `app.js` (`renderDashboard` y afines) | `dataSource.js::getResumen` → `GET /api/dashboard/resumen` |
| Productos / detalle | `app.js` (la mayoría del archivo) | `backendApi.js` |
| Oportunidades | `app.js` (tabla) | `dataSource.js::getOportunidades` → `GET /api/seleccion` |
| Importar catálogo (asistente) | `importFlow.js` (wizard de 5 pasos, incluye la pantalla de progreso en vivo del análisis) | `backendApi.js::confirmarImportacion` + `analizarRentabilidadStream` |
| Google Sheets | `googleSheetsFlow.js` | análogo a `importFlow.js` |
| Mercado Libre (publicar un producto) | `mercadolibrePublicar.js` (flujo ¿Conviene? → Preparar → Revisar → Publicado) | `backendApi.js` |
| Configuración (comisión/envío manual, márgenes) | `app.js` (sección Configuración) | `PUT /api/configuracion/canales/mercadolibre` |
| Admin Nexo | `adminPanel.js` | `GET /api/admin/*` |
| Soporte | `soporte.js` | |

- **`backendApi.js`**: única capa que llama al backend real (`fetch`,
  `credentials:"include"` para la cookie de sesión cross-port en dev). Cada
  función = un endpoint.
- **`dataSource.js`**: capa intermedia que decide modo real vs. demo
  (`LC.demoData`/`LC.demoImportResult`) — nunca mezcla datos reales con
  demo en la misma pantalla.
- **`ui.js`**: helpers compartidos (`toast`, `openModal`, `icon`,
  `escapeHtml`).
- Versionado de caché: cada `<script src="js/x.js?v=N">` en `index.html`
  sube su `N` a mano cuando ese archivo cambia.

## 5. Flujo de datos: Excel → publicación → venta

```
Excel/CSV
  → POST /api/catalogo/importar/analizar   (preview, no escribe nada)
  → POST /api/catalogo/importar/confirmar  (escribe productos; dispara EN
      SEGUNDO PLANO actualizar_comisiones_en_segundo_plano)
  → [frontend] llama POST /analisis-rentabilidad/stream (NDJSON, progreso
      en vivo): por cada producto —
        categoría (predict_category, si falta)
        → comisión real (get_listing_fees, cacheada por categoría+precio)
        → envío: REAL si hay publicación (item_id) > ESTIMADO por
          categoría+precio (medidas por defecto de ML) > si ninguno,
          queda sin resolver
        → classify_product (misma regla que Oportunidades)
  → GET /api/seleccion (tabla final Oportunidades: Conviene / No conviene /
      Faltan datos)
  → el dueño confirma → POST /api/publicaciones/{id}/mercadolibre/confirmar
      (revalida TODO desde la base: precio, stock, imágenes, plan — el
      único lugar que hace POST /items real a Mercado Libre)
  → GET /api/mercadolibre/importar-ventas (paginado) trae pedidos nuevos,
      descuenta stock reservado
  → la rentabilidad ya no es estimada: usa el envío/comisión reales de la
      publicación viva (services/ml_shipping_sync.py corre en varios puntos
      del flujo para mantenerlo actualizado)
```

**OAuth de Mercado Libre**: `GET /conectar` arma la URL de autorización con
`state` (CSRF+PKCE) que lleva embebido el `store_id` que inició el flujo —
así `/callback` sabe a qué empresa asociar la cuenta sin depender de la
cookie de sesión (puede no viajar en el redirect entre dominios). La
conexión resultante (`MarketplaceAccount`) es 1:1 por empresa
(`UniqueConstraint(store_id, marketplace)`); las credenciales de la
aplicación desarrolladora (Client ID/Secret) son de Nexo y viven solo en
`.env`, nunca en la base.

## 6. Reglas de negocio vigentes

- **Ganancia neta** = precio − costo − comisión (real de ML si existe, si
  no la manual de Configuración) − envío de ML − otros costos fijos.
- **Costo de compra vacío** = costo considerado **$0** (dato válido, ej. un
  producto que la empresa ya tenía). **Costo de envío desconocido ≠ $0**:
  es dato faltante, nunca se asume (`ChannelCosts.shipping_unknown`, ver
  `domain/profitability.py::net_margin`).
- **Conviene**: margen % ≥ margen mínimo del canal **O** ganancia ≥
  ganancia neta mínima $ (basta una de las dos), y el envío está resuelto.
- **No conviene**: mismos datos disponibles, pero no alcanza ninguna de las
  dos, o la ganancia es negativa.
- **Faltan datos** (`sin_datos`): falta precio, canal sin comisión/envío
  configurado, **o el costo de envío de Mercado Libre no está resuelto**
  (regla estricta, 16 sept 2026 — nunca "Conviene"/"No conviene" con un
  envío supuesto).
- **Margen objetivo**: solo sirve para calcular el *precio recomendado*
  (nunca se aplica solo); si es matemáticamente imposible, se avisa pero no
  cambia la decisión.
- **Envío — prioridad**: real de la publicación (`item_id`) > estimado
  por categoría+precio (vence a los 30 días) > **nada** — el envío manual
  de Configuración YA NO decide la rentabilidad de Mercado Libre.
- **Oficial de ML vs. estimado**: comisión y envío REAL siempre vienen de
  un endpoint de Mercado Libre con datos de ESE producto/publicación. El
  envío ESTIMADO usa medidas por defecto de la categoría (también dato de
  ML, nunca inventado por Nexo) — se marca explícitamente como
  `envioMlFuente: "estimado_ml"`, nunca se presenta como si fuera real.
- **Qué NO inventa Nexo**: números demo, comisión/envío por defecto,
  copiar el envío de "un producto parecido", clasificar sin los datos
  completos. Sin dato → se dice explícitamente qué falta.

## 7. Base de datos

- **Motor**: SQLite en dev (`backend/nexo.db`, gitignored), Postgres en
  prod (`DATABASE_URL`). Mismos modelos, sin cambiar código.
- **Aislamiento**: toda tabla de negocio tiene `store_id`; ninguna consulta
  de una ruta de empresa debe omitir ese filtro (lo centraliza
  `get_current_store`, pero cada query sigue debiendo usarlo).
- **Tablas críticas**: `stores`, `users`, `auth_sessions` (multiempresa +
  login), `products`/`product_variants` (catálogo), `marketplace_accounts`
  (token OAuth cifrado por empresa), `marketplace_listings` (publicaciones,
  con el envío real cacheado), `mercadolibre_category_fees` /
  `mercadolibre_shipping_estimates` (cachés que alimentan la rentabilidad),
  `channel_cost_settings` (config de márgenes por empresa), `subscriptions`.
- **Datos sensibles**: `password_hash` (bcrypt), `auth_sessions.token_hash`
  (SHA-256, nunca el token), tokens de ML/Google cifrados con Fernet
  (`TOKEN_ENCRYPTION_KEY`) en `marketplace_accounts`. Ninguna respuesta de
  API expone estos campos.
- **Migraciones**: Alembic, `backend/alembic/versions/` (31 al 16 sept
  2026). Instalación nueva: `alembic upgrade head` sobre una base vacía
  (verificado que funciona limpio, ver `PROGRESS.md`).
- Detalle de cada tabla: `backend/DATABASE.md`.

## 8. Integraciones externas

| Integración | Adapter | Notas |
|---|---|---|
| **Mercado Libre** | `adapters/mercadolibre.py` | OAuth + REST. Requiere permiso "Publicación y sincronización" en developers.mercadolibre.cl para comisiones/publicar (no alcanza con "Venta y envíos"). Todos los endpoints de envío/comisión están documentados con la fecha en que se verificaron en vivo (ver docstrings). |
| **Mercado Pago** | `adapters/mercadopago.py` | `/preapproval` (mensual), `/checkout/preferences` (anual). Webhook `POST /api/pagos/webhook` valida `X-Signature` HMAC y vuelve a preguntarle a MP el estado real (nunca confía en el payload). **Pendiente conocido**: `subscription_authorized_payment` (cobro del mes 2+) no se procesa — ver `TODO.md`. |
| **Google Sheets** | `adapters/google_sheets.py` | Mismo pipeline de importación que Excel. |
| **WooCommerce** | `adapters/woocommerce.py` | Legado de una etapa anterior del producto (antes del pivote a multi-rubro/ML) — no está enchufado a ningún router activo hoy. |
| **Resend (mail)** | código listo (`EnviadorResend`), sin `RESEND_API_KEY` configurada — pendiente del dueño. |

Nunca copiar credenciales reales a ningún doc — todas viven solo en
`backend/.env` (no versionado).

## 9. Deploy — estado actual

**Nada desplegado todavía** (decisión del dueño, pospuesto). Plan ya
decidido y documentado en `backend/DEPLOY.md`: Render (backend + frontend
estático) + Supabase (Postgres) + Resend (mail).

- `uvicorn app.main:app --workers 1` — **1 worker es un requisito, no una
  sugerencia**: el estado de OAuth pendiente (`_pending_states`) y el
  límite de intentos de login viven en memoria del proceso; con 2+ workers
  se pierden/duplican. Antes de escalar hay que moverlos a algo compartido.
- Variables de entorno de producción: `DATABASE_URL` (Postgres),
  `TOKEN_ENCRYPTION_KEY` (**nueva**, nunca la de dev),
  `SESSION_COOKIE_SECURE=true`, `BACKEND_PUBLIC_BASE_URL` (URL pública
  real — si queda en `localhost`, ni las imágenes ni el callback de MP
  funcionan), `UPLOADS_DIR` (debe apuntar a un **disco persistente**: un
  redeploy sin volumen montado borra las imágenes de los clientes),
  `MERCADOLIBRE_*`, `MERCADOPAGO_*`, `RESEND_API_KEY`/`EMAIL_FROM`.
  `app.` y `api.` deben ser subdominios del MISMO dominio (afecta la
  cookie de sesión).
- Cron diario (`python -m app.services.lifecycle`) definido en
  `render.yaml`, se activa solo al desplegar.
- Migraciones verificadas contra una base vacía y contra Postgres
  (offline SQL generado sin errores) — ver `PROGRESS.md`.
- Legal (Términos/Privacidad): borradores en `legal/`, pendientes de
  revisión de abogado y de completar datos de la empresa.

## 10. Tests

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q          # suite completa
.venv/Scripts/python.exe -m pytest -q tests/test_rentabilidad.py tests/test_envio_faltante_rentabilidad.py  # solo rentabilidad/envío
```

- **Estado al 16 sept 2026: 979/979 pasan.**
- Un archivo de test por área, nombrado por lo que prueba (no por el
  archivo de código que cubre 1:1). Los que más importa correr antes de
  tocar cada zona:
  - Rentabilidad/envío: `test_rentabilidad.py`,
    `test_envio_faltante_rentabilidad.py`, `test_envio_estimado.py`,
    `test_criticos_rentabilidad.py`, `test_sin_costo_de_compra.py`.
  - Publicar en ML: `test_publicaciones_endpoint.py`.
  - Multiempresa/seguridad: `test_aislamiento_multiempresa.py`.
  - OAuth/comisiones/envío real ML: `test_mercadolibre_endpoints.py`,
    `test_analisis_rentabilidad_stream.py`.
  - Pagos/suscripción: `test_pagos_endpoints.py`.
- `tests/auth_helpers.py::autenticar` arma una sesión real sin pasar por
  `/login` (más rápido, igual de real).

## 11. Otros docs (más profundos que este mapa)

- **`docs/LOCAL_DEVELOPMENT.md` — cómo levantar Nexo en local desde cero**
  (instalar, `.env`, base de datos, correr backend + frontend, puertos,
  verificar, tests). Empezar por ahí para retomar el proyecto.
- `backend/DATABASE.md` — modelos y relaciones, campo por campo.
- `backend/DEPLOY.md` — guía paso a paso de despliegue.
- `backend/DECISION_NEGOCIO.md` — motor "¿Conviene?" en detalle.
- `backend/PRECIO_RECOMENDADO.md` — cálculo del precio recomendado.
- `backend/PUBLICACION_MERCADOLIBRE.md` — flujo de publicación real.
- `backend/ADMIN_NEXO.md` — panel de administración de Nexo.
- `REVISION_SISTEMA.md` — última auditoría completa de código/negocio
  (16 sept 2026): qué está sólido, qué queda pendiente de decisión.
- `PROGRESS.md` / `TODO.md` — bitácora y pendientes, con fecha.

## 12. "Quiero cambiar X, ¿dónde miro primero?"

| Quiero cambiar... | Empezar por |
|---|---|
| Cómo se calcula el margen/ganancia | `backend/app/domain/profitability.py` |
| Cuándo algo es "Conviene"/"No conviene"/"Faltan datos" | `backend/app/domain/catalog_selection.py::classify_product` |
| El costo de envío usado en rentabilidad | `backend/app/api/routes/rentabilidad.py::aplicar_envio_real_ml` |
| Qué se publica realmente en Mercado Libre | `backend/app/api/routes/publicaciones.py::confirmar_publicacion_mercadolibre` |
| La tabla de Oportunidades (frontend) | `frontend/js/app.js` (render) + `frontend/js/importFlow.js` (dentro del asistente) |
| El asistente de importación / progreso en vivo | `frontend/js/importFlow.js` + `backend/app/services/analisis_rentabilidad_stream.py` |
| Permisos/aislamiento entre empresas | `backend/app/api/deps.py::get_current_store` |
| Cobro/suscripciones | `backend/app/domain/subscription_lifecycle.py` + `backend/app/api/routes/pagos.py` |
