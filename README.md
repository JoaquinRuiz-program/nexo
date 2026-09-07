> ## ⚠️ Esto NO es Nexo — es el prototipo original
>
> Lo que hay en la **raíz** de este repositorio (`src/`, `index.html`,
> `package.json`) es el prototipo React/Vite con el que arrancó el
> proyecto: guarda todo en localStorage y no tiene backend.
>
> **El producto real es Nexo**, y son otras dos carpetas:
>
> | | Carpeta | Cómo se despliega |
> |---|---|---|
> | Frontend | `frontend/` | Estático, **sin build** |
> | Backend | `backend/` | FastAPI + PostgreSQL |
>
> Guía de despliegue: **[`backend/DEPLOY.md`](backend/DEPLOY.md)**.
> Nunca publiques la raíz de este repositorio como si fuera Nexo.

# Prototipo original (React/Vite) — Fase 1 + Fase 1.5 + Fase 2

Prototipo funcional y visual para administrar los productos de una tienda:
importación automática de catálogo desde Excel/CSV, procesamiento simulado
por IA, y ahora **simulación completa de publicación en Mercado Libre**
(selección, revisión, publicación individual y masiva, sincronización de
precio/stock). Los datos se guardan en el navegador (localStorage): al
recargar la página se mantienen, pero solo existen en tu equipo.

## Estado actual y arquitectura aprobada (agosto 2026)

Esta sección documenta, sin modificar nada de la lógica existente, en qué
punto está el proyecto y qué se decidió para las próximas fases. Se agregó
como parte de la "etapa de preparación segura" previa a empezar a construir
la arquitectura real (Git + verificación de build + este documento), antes
de tocar cualquier integración externa.

**Lo que funciona de verdad hoy:** UI completa de 9 pantallas, CRUD de
productos, persistencia en localStorage, importación real de Excel/CSV con
detección automática de columnas y de duplicados, y validación de reglas
para publicación.

**Lo que está simulado hoy:** Mercado Libre (`mercadoLibreService.ts` — sin
OAuth, sin llamadas de red, IDs falsos) e IA (`aiService.ts` — reglas
locales, no un modelo). No existe Google Sheets en ninguna forma, ni
siquiera simulada.

**Lo que no existe todavía:** backend, base de datos real, autenticación,
tests automatizados. Hasta esta etapa tampoco existía control de versiones
(Git) — ver más abajo.

**Investigación de la web real** (`lalibreriaonlineoficial.cl`): se
confirmó que usa WordPress + WooCommerce, con su API REST de administración
disponible (`/wp-json/wc/v3/`, requiere credenciales que genera el dueño) y
una API pública de solo lectura (`/wp-json/wc/store/v1/products`) que ya
devuelve productos reales sin necesitar credenciales — aunque, en la
muestra revisada, sin SKU cargado y sin stock numérico exacto.

**Decisiones de arquitectura aprobadas (Fase 0):**

1. WooCommerce será inicialmente la fuente de verdad del catálogo. La
   arquitectura debe quedar preparada para que, en el futuro, la base de
   datos propia pueda convertirse en la fuente central sin rehacer el
   sistema (capa de abstracción `CatalogSource`, un adaptador por origen).
2. El SKU es el identificador comercial principal, distinto del ID interno
   de cada plataforma (`woocommerce_id`, `mercadoLibreId`). No se generan ni
   modifican SKU automáticamente todavía — primero hay que auditar el
   catálogo completo de WooCommerce (Fase 2, ver más abajo).
3. No se asume ningún sistema de punto de venta para la tienda física.
   Queda pendiente de las respuestas del dueño antes de diseñar esa
   integración.
4. Mercado Libre es un canal de venta y logística. El sistema debe
   distinguir claramente entre pedidos gestionados por Mercado Libre
   (incluyendo Mercado Envíos/Full) y pedidos preparados y despachados por
   la librería — sin intentar reemplazar la logística de Full.
5. La arquitectura contempla, sin implementarlo todavía, un flujo futuro de
   venta → pedido → picking → packing → etiqueta → despacho → enviado.
6. La sincronización de stock usará eventos/webhooks como mecanismo
   principal, con reconciliación periódica como respaldo e idempotencia
   para evitar descuentos duplicados.
7. El diseño contempla desde el inicio distintos "fondos" de stock físico,
   incluyendo el stock que eventualmente viva en Mercado Libre Full como
   algo separado del stock que permanece en la librería.

El detalle completo de este análisis (con el flujo de datos completo, las
APIs de cada plataforma, el modelo de datos propuesto y el roadmap por
fases) vive en los documentos de diagnóstico y arquitectura del proyecto,
fuera de este repositorio.

**Control de versiones:** ⚠️ esta línea decía que el proyecto ya se
versionaba en Git — verificado en el disco real el 21 de agosto de 2026: no
existe ninguna carpeta `.git` en este proyecto. Git **no** está inicializado
todavía. Se deja esta nota en vez de borrar la afirmación original para que
quede claro que es una tarea pendiente (Fase 1 del roadmap: `git init` +
primer commit), no algo ya hecho.

**Fase 2 — estado real (actualizado 21 de agosto de 2026):** el entorno de
prueba local (`woocommerce-test-env/`, LocalWP) quedó bloqueado por un
problema de permisos que no se resolvió, y el dueño del proyecto decidió
explícitamente abandonarlo (ver nota al inicio de `woocommerce-test-env/README.md`).
En su lugar, se validó el flujo completo (WooCommerce real → adaptador →
mapeo a `Product`) contra la **Store API pública** de
`lalibreriaonlineoficial.cl` (sin credenciales, sin riesgo, solo lectura),
con una muestra de 30 productos reales. Eso reveló, con datos reales, dos
casos que el adaptador no contemplaba: productos `type:"variable"` (con
variantes de color) y valores de SKU tipo "N/D" que no son un SKU real —
ambos ya están manejados en `scripts/woocommerce-audit/` (ver abajo). El
siguiente paso, en curso, es generar una clave de administración `wc/v3` de
solo lectura en el sitio real para completar SKU/stock exacto por variante
(que la Store API pública no expone). Ni el adaptador ni ningún script de
este proyecto implementan `getOrders()` ni ninguna operación de escritura —
eso queda para una fase posterior.

## Requisitos

- Node.js 18 o superior
- npm

## Instalación

```bash
npm install
```

## Ejecutar en modo desarrollo

```bash
npm run dev
```

Abre la URL que aparece en la terminal (normalmente `http://localhost:5173`).

## Compilar para producción

```bash
npm run build
npm run preview
```

## Estructura del proyecto

```
src/
  types/        Contratos de datos: product.ts (dominio) e import.ts (importación)
  data/         Datos de prueba (mock) — 17 productos de ejemplo
  services/
    productService.ts     Lógica de negocio de productos (validación, formato, estado, isOutOfSync)
    importService.ts      Lectura de Excel/CSV, detección de columnas, duplicados
    aiService.ts           Simulación de IA — único archivo a reemplazar en Fase 4
    mercadoLibreService.ts Publicación simulada: validación, generación de ID,
                            publishProduct/publishProducts/updateStock/updatePrice/
                            connectMercadoLibre/getPublication/pausePublication —
                            único archivo a reemplazar por la API real en Fase 3
    storageService.ts      Persistencia en localStorage — único archivo a reemplazar
                            por Supabase/PostgreSQL en una futura fase de base de datos
  context/      Estado global de la app (ProductProvider): productos, actividad,
                automatización, y ahora publishProduct/publishProductsBulk/syncPrice/syncStock
  components/
    layout/     Sidebar, header, drawer móvil, layout general
    ui/         Botones, tarjetas, badges de estado, modal — reutilizables
    products/   Formulario de producto, imagen/placeholder
    import/     Componentes del asistente de importación (dropzone, mapeo de
                columnas, resumen, duplicados, barra de progreso)
    publish/    Componentes del flujo de publicación (checklist de validación,
                editor de características, gestor de imágenes, progreso de publicación)
  pages/        Inicio, Productos, Importar productos, Preparar publicación,
                Publicación masiva, Agregar producto, Detalle de producto,
                Pendientes, Configuración
```

Esta separación existe para que las próximas fases se puedan agregar sin
reescribir la interfaz:

- **Base de datos real:** reemplazar `src/services/storageService.ts` (hoy
  localStorage) por consultas a Supabase/PostgreSQL. `ProductContext` ya solo
  llama a `load*`/`save*` de ese archivo, nunca a `localStorage` directamente.
- **Fase 3 — Integración real con Mercado Libre:** `src/services/mercadoLibreService.ts`
  ya define `connectMercadoLibre`, `publishProduct`, `publishProducts`,
  `updateProduct`, `updateStock`, `updatePrice`, `getPublication` y
  `pausePublication` — hoy simulados con validación local y IDs generados,
  listos para reemplazarse por la API oficial (OAuth, `POST /items`, etc.)
  sin tocar componentes ni páginas.
- **Fase 4 — IA real:** `src/services/aiService.ts` expone `processProduct` y
  `processBatch` con una firma estable (mismo input, mismo
  `ProcessedProductInfo` de salida). Cambiar el cuerpo de `processProduct`
  por una llamada a un modelo real no requiere tocar el resto de la app.
- **Fase 5 — Gestión de imágenes:** el punto de reemplazo sigue siendo
  `readImageFile`/`ImagesManager` — hoy guardan base64 local, listos para
  subir a un servicio externo.
- **Fase 6 — Sincronización automática:** se apoyaría en
  `mercadoLibreService.ts` + un temporizador o webhook, reutilizando
  `ProductContext.syncPrice`/`syncStock`/`publishProductsBulk`.

## Auditoría de WooCommerce (Fase 2 — en curso)

⚠️ Actualizado 21 de agosto de 2026 — el flujo activo ya NO depende de
`woocommerce-test-env/` (ver nota de abandono en el README de esa carpeta);
se conserva solo como referencia histórica. El flujo real es: Store API
pública (validado, sin credenciales) → clave `wc/v3` de solo lectura del
sitio real (siguiente paso) → `npm run audit` en `scripts/woocommerce-audit/`.

Dos carpetas, **fuera de `src/`** — no se integran todavía con la
aplicación principal, son herramientas de desarrollo independientes:

```
woocommerce-test-env/
  docker-compose.yml   WordPress + MariaDB + WP-CLI. Preparado para un
                        entorno con acceso a registros de contenedores
                        (Docker Hub) — hoy bloqueado en el entorno cloud de
                        desarrollo, se recomienda usar LocalWP en su lugar
                        (ver README.md de esta carpeta).
  seed/
    products.json        Definición reproducible de los 20 productos de
                          prueba (con sus casos de error deliberados).
    images/               Imágenes placeholder generadas localmente.
    create-products.php   Crea categorías, imágenes y los 20 productos vía
                           WP-CLI (`wp eval-file create-products.php`).
                           Idempotente. Funciona en LocalWP, Docker, o
                           cualquier WP-CLI.
    create-api-key.php    Genera una clave de la API REST de WooCommerce
                           con permisos de SOLO LECTURA
                           (`wp eval-file create-api-key.php`).
  example-output/        Reportes de ejemplo (generados contra un servidor
                          simulado durante el desarrollo, no contra
                          WooCommerce real — ver nota en esa carpeta).
  README.md               Guía paso a paso completa: instalación de
                          LocalWP, creación del sitio, WooCommerce, los 20
                          productos, la clave de API, y cómo conectar el
                          adaptador.

scripts/woocommerce-audit/
  src/
    woocommerceAdapter.ts  Adaptador de SOLO LECTURA sobre la API REST de
                            WooCommerce (getProduct/getProductsPage/
                            getAllProducts/getCategories/getStock, y desde
                            el 21-ago-2026 también getVariationsPage/
                            getAllVariations — trae el SKU/precio/stock real
                            de cada variante de color de un producto
                            type:"variable", que WooCommerce NO expone en el
                            registro del producto padre). Deliberadamente
                            sin getOrders() ni ninguna operación de
                            escritura en esta fase — mismo patrón de
                            un-archivo-por-integración que ya usa el resto
                            del proyecto, así que sirve igual para el
                            WooCommerce de prueba que para el real (solo
                            cambia la URL/credenciales).
    analysis.ts             Funciones puras de análisis: resumen del
                            catálogo, detección de duplicados (SKU y
                            nombre), búsqueda de candidatas a código de
                            barras en meta_data, productos sin SKU/stock/
                            imagen/descripción, y (desde el 21-ago-2026)
                            expandVariableProducts — reemplaza cada
                            producto "variable" por una fila por color con
                            datos reales de su variación, para que las
                            estadísticas no cuenten esos productos como
                            "sin SKU/stock" por error.
    auditCatalog.ts          Script principal (`npm run audit`): conecta,
                            importa el catálogo completo paginado, trae las
                            variaciones de cada producto "variable", expande
                            el catálogo, corre el análisis sobre el catálogo
                            expandido, y escribe los reportes (incluye
                            `catalog-expandido.json/csv`, además del
                            `catalog.json/csv` crudo sin expandir).
    *.test.ts                24 pruebas automatizadas (node:test) — todas
                            pasando. Cubren conexión, autenticación
                            inválida, paginación (productos y variaciones),
                            reintentos ante 429/5xx, timeout, catálogo
                            vacío, expansión de productos "variable", y
                            toda la detección de casos de error.
  .env.example              Plantilla de variables de entorno (sin
                            valores reales).
```

Cómo usarlo, contra la tienda real (con una clave `wc/v3` de solo lectura —
ver `WOOCOMMERCE_URL=https://www.lalibreriaonlineoficial.cl` en el `.env`):

```bash
cd scripts/woocommerce-audit
npm install
cp .env.example .env   # completa WOOCOMMERCE_URL / CONSUMER_KEY / CONSUMER_SECRET
npm run test           # corre las 24 pruebas (no necesita WooCommerce)
npm run audit           # corre la auditoría real y escribe reports/woocommerce-audit/
```

## Qué se puede probar en este prototipo

### Fase 1 (ya existente)
- Ver el resumen del catálogo y la actividad reciente (Inicio).
- Buscar, filtrar (categoría/estado) y ordenar (precio/stock) productos.
- Agregar, editar y eliminar productos manualmente.
- Ver la lista de productos pendientes con los problemas detectados.
- Revisar Configuración: datos de la librería e integración con Mercado
  Libre (desconectada).

### Fase 1.5 — Importación y procesamiento automático
1. Ve a **Productos → Importar productos**.
2. Sube un archivo `.xlsx`, `.xls` o `.csv` (o descarga primero la
   "Plantilla Excel" desde esa misma pantalla y complétala con tus productos).
   No es necesario que las columnas se llamen exactamente "SKU", "Nombre",
   etc. — por ejemplo, "Código", "Producto" o "Valor" se detectan
   automáticamente.
3. Revisa las columnas detectadas y corrígelas manualmente si hace falta.
4. Verás cuántos productos son válidos, cuáles requieren revisión y cuáles
   tienen errores, con el detalle de cada problema.
5. Si hay SKU duplicados, elige si quieres mantener el primero, el último, o
   revisarlos manualmente.
6. La pantalla de "Procesando catálogo…" simula el trabajo que hará la IA:
   valida la información, verifica SKU/precio/stock, sugiere categoría,
   genera un título y una descripción más prolijos, y detecta atributos
   (marca, hojas, formato, etc.) a partir del nombre original.
7. Al terminar, los productos quedan en tu catálogo con estado 🟢 Listo,
   🟡 Pendiente o 🔴 Error según corresponda.
8. Abre cualquier producto importado para ver, lado a lado, la información
   **original** (tal como venía en el Excel) y la **procesada**
   (lo que preparó el sistema), además de su sección de "Publicación en
   Mercado Libre" (todavía deshabilitada).
9. El Dashboard se actualiza con los nuevos totales y la sección
   "Automatización" muestra la fecha de la última importación/sincronización.

No se implementa todavía: conexión real con Mercado Libre, IA real, base de
datos externa ni autenticación — tal como se definió para esta fase.

### Fase 2 — Preparación y simulación de publicaciones de Mercado Libre

**Publicar un producto individual**
1. Ve a **Productos**. Cualquier producto en estado 🟢 "Listo para publicar"
   tiene un botón **Preparar**.
2. En "Preparar publicación" verás la vista previa (imagen, título, precio,
   stock, marca, descripción), la categoría sugerida (con opción de
   cambiarla) y las características del producto (editables, con botón
   "+ Agregar característica").
3. Más abajo, "Validación de publicación" muestra cada dato con ✓ / ⚠ / ✕.
   Si hay algo bloqueante (✕), el botón "Publicar en Mercado Libre" queda
   deshabilitado y se explica qué falta.
4. Al presionar **Publicar en Mercado Libre** se abre una confirmación
   ("¿Publicar producto?"). Presiona **Simular publicación**.
5. Verás una animación de pasos (validando, preparando imágenes/categoría/
   atributos, enviando, creando) y al final la pantalla "Publicación
   creada" con un ID único tipo `ML-847291`, precio y stock.
6. El producto vuelve a la lista como 🔵 **Publicado**, con ese ID visible
   en la columna "Publicación" de la tabla.

**Publicación masiva**
1. En **Productos**, marca varios checkboxes (los productos en 🔴 error no
   se pueden seleccionar — si lo intentas, se explica por qué).
2. Aparece una barra con "N productos seleccionados" → presiona
   **Publicar seleccionados**.
3. La pantalla "Publicación masiva" agrupa la selección en listos/revisión/
   error y solo publica los listos. Presiona **Publicar N productos** para
   ver el progreso ("1/12 ✓", "2/12 ✓"…) y la pantalla final de
   "Publicación completada".

**Sincronizar precio**
1. Abre un producto ya publicado (por ejemplo "Lápiz Bic HB", que en los
   datos de prueba queda deliberadamente desactualizado) desde **Productos
   → Ver**.
2. Cambia su precio en "Editar información" y vuelve a la publicación: verás
   "Cambio detectado" con el precio local vs. el publicado y la etiqueta
   🟡 Desactualizado.
3. Presiona **Actualizar Mercado Libre** — simula la sincronización y pasa a
   🟢 Sincronizado, quedando registrado en el "Historial de publicación".

**Sincronizar stock**
- Igual que el precio: cambia el stock del producto y usa **Sincronizar
  stock** en la pantalla de publicación ("Mochila Jansport Reforzada" en los
  datos de prueba ya arranca con el stock desactualizado para probarlo sin
  editar nada primero).

El Dashboard también se actualizó: nueva tarjeta "Desactualizados" y una
sección "Mercado Libre" que indica "Modo simulación" con un botón **Conectar
Mercado Libre** (muestra "Disponible en la próxima versión").

