> ⚠️ **ABANDONADO (21 de agosto de 2026):** este entorno de prueba (LocalWP)
> quedó bloqueado por un problema de permisos (`woocommerce_rest_cannot_view`)
> que no se resolvió, y el dueño del proyecto decidió explícitamente dejarlo
> atrás en vez de seguir depurándolo. La ruta que se usa desde entonces para
> validar el catálogo es `scripts/woocommerce-audit/` apuntando directo a la
> Store API pública (sin credenciales) y, próximamente, a la API de
> administración real de `lalibreriaonlineoficial.cl` con una clave de solo
> lectura. Esta carpeta se conserva solo como referencia histórica de ese
> intento — no es parte del flujo de trabajo activo del proyecto.

# WooCommerce de prueba — guía paso a paso (LocalWP)

Este WooCommerce es un entorno de **prueba**, controlado por ti, que corre
en tu propio computador. No tiene ninguna conexión con el WooCommerce real
de la librería (`lalibreriaonlineoficial.cl`) — sirve exclusivamente para
desarrollar y verificar la integración de lectura de `scripts/woocommerce-audit/`
antes de tocar cualquier cosa real.

> **Por qué LocalWP y no el `docker-compose.yml` de esta carpeta:** el
> compose file (WordPress + MariaDB + WP-CLI) está listo y es válido, pero
> el entorno de desarrollo en la nube donde se preparó este proyecto no
> tiene acceso a Docker Hub ni a wordpress.org (restricción de red del
> entorno, no de tu computador). Se conserva el `docker-compose.yml` por si
> alguna vez lo corres en un entorno con acceso a esos registros (tu propio
> Docker Desktop en Windows también serviría — ver la nota al final de este
> documento) — pero el camino recomendado hoy es LocalWP.

## 1. Qué instalar

**[LocalWP](https://localwp.com/)** (a veces llamado "Local by Flywheel") —
una aplicación gratuita para Windows/Mac/Linux que instala WordPress
completo (PHP + MySQL + servidor web) en tu computador con unos pocos
clics, sin que tengas que configurar nada de infraestructura a mano.
Descárgala desde localwp.com, elige la versión para Windows, e instálala
como cualquier programa (el instalador te va a pedir permisos de
administrador la primera vez, es normal).

Espacio aproximado: la aplicación en sí pesa unos 500 MB; cada sitio que
crees (WordPress + WooCommerce + los 20 productos con sus imágenes de
prueba) pesa otros 150-250 MB adicionales. No necesitas más de 1 GB libre
en total para este entorno de prueba.

## 2. Crear el sitio WordPress

Abre LocalWP → botón **"+ Create a new site"** → elige **"New Site"** →
ponle un nombre, por ejemplo `libreria-central-test` (LocalWP arma
automáticamente la URL a partir de este nombre, ver punto 7). En las
opciones de entorno elige **"Preferred"** (la configuración recomendada por
LocalWP, PHP + MySQL + nginx) salvo que tengas una razón para cambiarla.
Crea un usuario administrador cuando te lo pida (anota el usuario y
contraseña — los vas a necesitar solo para entrar al panel si quieres
verificar algo visualmente, no para la auditoría en sí).

Cuando termine, LocalWP muestra el sitio "corriendo" (círculo verde). Con
eso ya tienes WordPress completo funcionando localmente.

## 3. Instalar WooCommerce

Con el sitio corriendo, haz clic derecho sobre el sitio en la lista de
LocalWP → **"Open Site Shell"** (esto abre una terminal ya conectada a ese
sitio, con el comando `wp` — WP-CLI — listo para usar, parada en la carpeta
`app/public` del sitio). Ahí corre:

```
wp plugin install woocommerce --activate
```

Esto descarga e instala WooCommerce y lo activa, sin tener que pasar por el
asistente de configuración del plugin (no hace falta completarlo para lo
que necesitamos). Alternativa si prefieres hacerlo con clics: **"Admin"**
(botón en LocalWP, abre `/wp-admin`) → Plugins → Añadir nuevo → buscar
"WooCommerce" → Instalar → Activar.

Luego, en la misma Site Shell, activa permalinks "bonitos" (WooCommerce los
necesita para que `/wp-json/...` funcione):

```
wp rewrite structure '/%postname%/'
wp rewrite flush --hard
```

## 4. Crear los 20 productos de prueba

Los 20 productos ya están definidos de forma reproducible en
`woocommerce-test-env/seed/products.json`, y el script que los crea en
`woocommerce-test-env/seed/create-products.php` — no se crean a mano.

1. En LocalWP, clic derecho sobre el sitio → **"Open Site Folder"** (abre el
   Explorador de Windows en la carpeta del sitio, algo como
   `C:\Users\Usuario\Local Sites\libreria-central-test\app\public`).
2. Copia ahí la carpeta `woocommerce-test-env\seed\` completa de este
   proyecto, y renómbrala a `lc-seed` (para que quede claro que es temporal
   y no parte de WordPress) — el resultado debería ser
   `...\app\public\lc-seed\products.json`, `...\lc-seed\images\`, etc.
3. Vuelve a **"Open Site Shell"** (queda parado en `app/public`, o sea, en
   el mismo nivel que la carpeta `lc-seed` que acabas de copiar) y corre:

```
wp eval-file lc-seed/create-products.php
```

Vas a ver un resumen con los 20 productos creados (id, nombre, SKU, y qué
caso de prueba representa cada uno). El script es **idempotente**: si lo
corres dos veces, no duplica lo que ya creó — así que si algo falla a mitad
de camino, puedes simplemente volver a correrlo.

## 5. Configurar la API REST y generar la clave de solo lectura

Con WooCommerce activo, en la misma Site Shell corre:

```
wp eval-file lc-seed/create-api-key.php
```

Esto imprime algo así:

```
WOOCOMMERCE_CONSUMER_KEY=ck_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WOOCOMMERCE_CONSUMER_SECRET=cs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

con permisos **de solo lectura únicamente** (`permissions=read` en la base
de datos de WooCommerce) — el mismo criterio de seguridad que usaremos con
el WooCommerce real más adelante. **Copia esas dos líneas ahora** — WooCommerce
no vuelve a mostrar el Consumer Secret después de generado. Si lo pierdes,
no pasa nada grave: vuelve a correr el mismo comando para generar una clave
nueva (y, si quieres, borra la vieja después desde `wp-admin` → WooCommerce
→ Ajustes → Avanzado → API REST).

Alternativa con clics, si prefieres no usar el script: `wp-admin` →
WooCommerce → Ajustes → Avanzado → API REST → **Agregar clave** → permisos
**"Lectura"** → Generar clave de API.

## 6. Qué URL tendrá tu WooCommerce local

LocalWP le asigna a cada sitio un dominio local basado en su nombre, del
tipo `http://libreria-central-test.local` (lo ves en la pantalla principal
del sitio dentro de LocalWP, arriba). Por defecto es `http://` (sin SSL) —
**te recomiendo dejarlo así para este entorno de prueba**, es más simple y
el adaptador de `scripts/woocommerce-audit` ya sabe autenticarse distinto
según el protocolo (por query string en `http://`, por cabecera en
`https://`), así que no necesitas activar el candado SSL de LocalWP para
que esto funcione.

## 7. Configurar las variables de entorno del proyecto

En `scripts/woocommerce-audit/`, copia `.env.example` a `.env` y complétalo
con lo que obtuviste en los pasos 5 y 6:

```
WOOCOMMERCE_URL=http://libreria-central-test.local
WOOCOMMERCE_CONSUMER_KEY=ck_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WOOCOMMERCE_CONSUMER_SECRET=cs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

`.env` está en `.gitignore` — nunca se sube a Git. Solo `.env.example`
(sin valores) queda versionado.

## 8. Conectar el script de auditoría

Con el sitio de LocalWP **corriendo** (círculo verde en la app) y el `.env`
completo:

```bash
cd scripts/woocommerce-audit
npm install        # solo la primera vez
npm run audit
```

El script se conecta a `WOOCOMMERCE_URL`, trae un producto de muestra
primero (para inspeccionar `meta_data`), luego el catálogo completo
paginado, calcula el resumen y los duplicados, y escribe todo en
`reports/woocommerce-audit/` (esa carpeta es local tuya, no se sube a Git).
El mismo comando (`npm run test`, sin necesitar el sitio corriendo) corre
las 20 pruebas automatizadas del adaptador.

## Detener y volver a levantar el entorno

Para detener: botón **"Stop site"** en LocalWP (no borra nada). Para
volver a arrancar: **"Start site"** — tus 20 productos siguen ahí, no hay
que recrearlos. Para empezar completamente de cero: elimina el sitio desde
LocalWP (clic derecho → "Delete Site") y repite los pasos 2 a 7 — el hecho
de que `create-products.php` sea reproducible (a partir de `products.json`)
significa que recrear el catálogo de prueba exacto toma un minuto, no hay
que reconstruirlo a mano.

## Reutilización: mismo script, distinto WooCommerce

`create-products.php` y `create-api-key.php` no saben nada de LocalWP en
particular — son WP-CLI + PHP estándar, así que el mismo procedimiento
funciona igual si alguna vez corres el `docker-compose.yml` de esta carpeta
en un entorno con acceso a Docker Hub (por ejemplo, tu propio Docker
Desktop en Windows, si lo prefieres a LocalWP): `docker compose up -d`,
después `docker compose run --rm wpcli plugin install woocommerce
--activate`, y los mismos dos `wp eval-file` (montando la carpeta `seed/`
dentro del contenedor, que el compose ya deja lista en `/seed`).

El adaptador (`scripts/woocommerce-audit/src/woocommerceAdapter.ts`) tampoco
sabe si está hablando con LocalWP, Docker, o el WooCommerce real de la
librería — solo lee `WOOCOMMERCE_URL` / `WOOCOMMERCE_CONSUMER_KEY` /
`WOOCOMMERCE_CONSUMER_SECRET` del `.env`. El día que se apruebe conectar
contra el WooCommerce real, el cambio es reemplazar esas tres líneas del
`.env` por las credenciales reales (generadas de la misma forma, con
permisos de solo lectura, desde el `wp-admin` real) — no hay que tocar
ni una línea de código.
