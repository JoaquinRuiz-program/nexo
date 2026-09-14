# Nexo en producción — guía de despliegue

30 de agosto de 2026, etapa "primer cliente real". Este documento cubre:
arquitectura recomendada, comparación de opciones de hosting, configuración
de producción exacta, transición de la base de datos y de Mercado Libre, y
el dominio. No asume un proveedor específico — vos elegís, acá está la
comparación.

## Despliegue concreto: Render + Supabase + Resend (14 de septiembre de 2026)

Decisión tomada: backend y frontend en **Render**, PostgreSQL en **Supabase**,
correo en **Resend**. El repo ya trae todo lo que no requiere cuentas:
`render.yaml` (Blueprint en la raíz), driver de Postgres activo en
`requirements.txt`, envío real de mails (`EnviadorResend`, se activa solo con
`RESEND_API_KEY` + `EMAIL_FROM`) y el cron diario. Lo que sigue lo hace una
persona, en este orden:

1. **Dominio.** Comprarlo (ej. Cloudflare Registrar). Se usan dos subdominios
   del MISMO dominio: `app.tudominio.cl` (frontend) y `api.tudominio.cl` (API);
   si no, la cookie de sesión no viaja y el login se rompe.
2. **Supabase.** Crear el proyecto (región cercana, ej. São Paulo) y guardar la
   clave de la base. En *Connect*, copiar la cadena del **pooler en modo sesión**
   (puerto `5432`, usuario `postgres.<ref>`): es IPv4, la única que funciona
   desde Render sin el add-on de IPv4 (la conexión directa es solo IPv6). Formato
   para Nexo:
   `postgresql+psycopg://postgres.<ref>:<clave>@<pooler-host>:5432/postgres?sslmode=require`.
   Confirmar que el backup automático está activo.
3. **Resend.** Crear la cuenta, agregar el dominio y cargar los registros DNS que
   pide (verificación). Crear una API key. `EMAIL_FROM` = `Nexo <noreply@tudominio.cl>`.
4. **Render → New → Blueprint** apuntando a este repo. Crea `nexo-api`,
   `nexo-ciclo-de-vida` y `nexo-app`. `nexo-api` necesita instancia **paga**
   (disco persistente y `preDeployCommand`). Completar los valores `sync: false`:
   - `DATABASE_URL` (paso 2), `TOKEN_ENCRYPTION_KEY` **nueva** (nunca la de dev),
     `FRONTEND_BASE_URL=https://app.tudominio.cl`,
     `BACKEND_PUBLIC_BASE_URL=https://api.tudominio.cl`,
     `CORS_ALLOWED_ORIGINS=https://app.tudominio.cl`,
     `MERCADOLIBRE_*` (paso 6), `RESEND_API_KEY` y `EMAIL_FROM` (paso 3),
     `MERCADOPAGO_*` solo si ya se cobra.
   - En `nexo-ciclo-de-vida`, los **mismos** valores que en `nexo-api`.
   - En `nexo-app`, `API_BASE_URL=https://api.tudominio.cl` (el build genera `js/env.js`).
5. **Dominios en Render.** `api.tudominio.cl` → `nexo-api`, `app.tudominio.cl` →
   `nexo-app` (Render indica los CNAME a cargar en el DNS; HTTPS es automático).
6. **Mercado Libre.** En developers.mercadolibre.cl, Redirect URI
   `https://api.tudominio.cl/api/mercadolibre/callback`, igual carácter por
   carácter a `MERCADOLIBRE_REDIRECT_URI`. Con esto ya no hace falta ngrok.
7. **Verificar.** `GET https://api.tudominio.cl/api/health` → `{"status":"ok"}`;
   el primer deploy ya corrió `alembic upgrade head` (preDeploy). Seguir con
   "Cuentas" y "Primer cliente real" del checklist de abajo.

Costo aproximado: dominio ~US$12/año, `nexo-api` instancia paga + disco 1 GB,
cron por uso, frontend estático gratis, Supabase y Resend con plan gratuito
para empezar.

## Arquitectura objetivo

```
Internet
  │
  ▼
Dominio de Nexo (HTTPS)
  │
  ├── app.tudominio.cl  →  Frontend (estático: HTML/CSS/JS, sin build)
  │
  └── api.tudominio.cl  →  Backend FastAPI  →  PostgreSQL
                                │
                                ├── Mercado Libre (OAuth + API real)
                                └── (IA: no aplica hoy — ai_content.py es
                                    reglas locales, no una API externa)
```

Frontend y backend en subdominios **del mismo dominio registrable**
(`app.` y `api.` de `tudominio.cl`) — esto importa de verdad: la cookie de
sesión (`SameSite=Lax`) solo viaja entre subdominios del mismo *site*
registrable. Si terminan en dominios distintos (ej. un `.vercel.app` y un
`.railway.app`), el login se rompe. No hace falta que sea el mismo
servidor, alcanza con que sea el mismo dominio.

## Comparación de opciones (simplicidad y costo bajo primero)

### Frontend (estático, sin build — cualquiera de estos alcanza)

> ⚠️ **QUÉ carpeta se publica: `frontend/` — y solo esa.**
>
> El repositorio tiene, en su **raíz**, un prototipo viejo en React/Vite
> (`src/`, `index.html`, `package.json` con `vite build`) que fue el punto
> de partida del proyecto y **no es Nexo**: guarda datos falsos en
> localStorage y no habla con este backend. Si se apunta el proveedor de
> hosting a la raíz del repositorio, va a autodetectar ese `package.json`,
> correr `vite build` y publicar el prototipo — el cliente vería una app
> que parece Nexo pero con datos inventados.
>
> Configuración correcta en el proveedor (Cloudflare Pages, Netlify, Vercel):
> - **Root directory / directorio de publicación**: `frontend`
> - **Build command**: *vacío* (no hay build: es HTML/CSS/JS servido tal cual)
> - **Output directory**: el mismo `frontend` (no `dist/`)
>
> La ruta es `frontend` **a secas**, sin ningún prefijo: la raíz del
> repositorio git es la carpeta del proyecto en tu máquina, así que su
> nombre no forma parte de ninguna ruta versionada y desaparece al clonar.
> Anteponerle el nombre de esa carpeta haría fallar el despliegue con
> "directory not found".
>
> Red de seguridad (6 de septiembre de 2026): si igual se apunta el
> proveedor a la raíz, el `npm run build` autodetectado **falla a
> propósito** con un error que explica esta misma configuración, en vez de
> publicar el prototipo en silencio. El prototipo se sigue pudiendo
> compilar a mano con `npm run build:prototipo`.

| Opción | Costo | Notas |
|---|---|---|
| **Cloudflare Pages** (recomendado) | Gratis | HTTPS automático, dominio propio gratis, despliegue por Git push. Sin servidor que mantener. |
| Netlify | Gratis (plan free) | Igual de simple, límites de ancho de banda más bajos en el free tier. |
| Vercel | Gratis (plan free) | Igual de simple; pensado más para frameworks con build, pero sirve estático sin problema. |
| Nginx en un VPS propio | Desde ~US$5/mes | Más control, pero hay que mantener el servidor (parches, HTTPS manual con Let's Encrypt). Innecesario para esta etapa. |

### Backend (FastAPI)
| Opción | Costo aprox. | Notas |
|---|---|---|
| **Render** (recomendado) | US$7-25/mes (Postgres incluido aparte) | Despliegue por Git push, HTTPS automático, logs simples, variables de entorno en el panel. Buen balance simplicidad/precio para 1 cliente. |
| Railway | Desde US$5/mes de uso | Similar a Render, precio por uso en vez de plan fijo — puede salir más barato con tráfico bajo. |
| Fly.io | Desde ~US$5/mes | Más control (regiones, escalado), algo más de curva de aprendizaje. |
| VPS propio (DigitalOcean, Hetzner) | US$4-6/mes | Más barato, pero hay que armar todo a mano (proceso de producción, HTTPS, backups) — no recomendado para el primer cliente, sí razonable más adelante si el costo importa. |

### PostgreSQL
| Opción | Costo aprox. | Notas |
|---|---|---|
| **Render Postgres** (recomendado si el backend ya está en Render) | Desde US$7/mes (o el free tier con límites) | Backups automáticos incluidos, misma plataforma que el backend — menos piezas que coordinar. |
| Supabase | Gratis (plan free, con límites) hasta ~US$25/mes | Backups automáticos, panel de administración propio. Buena opción si se quiere un free tier real para probar. |
| Neon | Gratis (plan free) hasta bajo costo | Postgres serverless, backups/point-in-time incluidos. |
| Railway Postgres | Por uso | Si el backend ya está en Railway, mismo criterio que Render. |

**Recomendación concreta**: Render (backend + Postgres juntos) o Railway — minimizan piezas separadas a mantener, ambos con backup automático y HTTPS gratis. Evitar armar un VPS propio para el primer cliente — es más trabajo de mantenimiento del que vale la pena hoy.

### Dominio
No lo compra Claude — lo comprás vos en cualquier registrador (Cloudflare Registrar, Namecheap, Google Domains/Squarespace). Costo típico: US$10-15/año para un `.cl` o `.com`. Cloudflare Registrar no cobra margen (vende a precio de costo).

### HTTPS
Gratis y automático en todas las opciones recomendadas arriba (Let's Encrypt integrado) — no hace falta comprar ni configurar un certificado a mano.

### Almacenamiento de imágenes
**Actualizado 6 de septiembre de 2026 — esto ya NO es cierto** (quedó obsoleto desde que existe la subida real de imágenes, `app/domain/image_storage.py`): Nexo SÍ guarda archivos ahora — en disco local, servidos con `StaticFiles` en `/uploads/...` (ver `app/main.py`, variable `UPLOADS_DIR`).

Esto funciona bien para un primer cliente/piloto, pero tiene DOS requisitos reales que hay que resolver antes de desplegar, no después:

1. **Disco persistente**: casi todo hosting moderno (Render, Railway, Fly.io) usa contenedores efímeros por defecto — un redeploy borra `UPLOADS_DIR` si no está montado sobre un volumen persistente. Sin esto, las imágenes de los clientes desaparecen en el próximo deploy. Casi todos estos proveedores ofrecen "persistent disk"/"volume" — hay que activarlo explícitamente y apuntar `UPLOADS_DIR` ahí.
2. **`BACKEND_PUBLIC_BASE_URL` tiene que ser la URL pública real** (`https://api.tudominio.cl`) — Mercado Libre pide la imagen desde SUS servidores, nunca desde el navegador del dueño: si esta variable queda en `localhost`, la publicación se crea pero Mercado Libre no puede descargar la imagen.

**Limitación real a tener presente, no a resolver ahora**: con disco local, escalar el backend a más de una instancia/réplica requeriría que todas compartan el mismo disco (no es el caso por defecto) — con un solo cliente o unos pocos, un solo proceso de backend alcanza de sobra, así que esto no bloquea nada hoy. Si más adelante hace falta más de una instancia del backend, ahí sí conviene migrar a un bucket (S3, Cloudflare R2, Backblaze B2) — es un cambio acotado a un solo archivo (`image_storage.py`, que ya trabaja en términos de "una URL", nunca de ruta física en el resto del código), no una reescritura. No se hizo ahora porque agregaría una cuenta/credencial externa nueva sin necesidad real todavía.

### Backups
Cubierto por el proveedor de Postgres elegido (backup automático diario, ver tabla de arriba) — no hace falta construir nada propio. Confirmar en el panel del proveedor que el backup automático está habilitado ANTES de cargar datos reales.

---

## Configuración de producción — variables de entorno exactas

Todas viven en `backend/.env` en desarrollo; en producción, en las
variables de entorno del proveedor de hosting (nunca en un archivo
commiteado a Git — `.env` ya está en `.gitignore`).

| Variable | Valor en producción | Notas |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://usuario:clave@host:5432/nexo` | Del proveedor de Postgres elegido. |
| `CORS_ALLOWED_ORIGINS` | `https://app.tudominio.cl` | **Nuevo** (30 de agosto de 2026) — antes hardcodeado a localhost, ahora configurable. Sin esto, el frontend queda bloqueado por CORS. |
| `SESSION_COOKIE_SECURE` | `true` | Sin esto, la cookie de sesión no tiene el flag `Secure` en HTTPS real. **Ojo**: con `true`, el navegador SOLO manda la cookie por HTTPS — si el backend queda expuesto en HTTP plano, el login "funciona" (responde 200) pero la siguiente request vuelve 401 y nadie puede entrar, sin ningún error visible. Verificado el 6 de septiembre de 2026: es el comportamiento correcto de la cookie, no un bug — pero es la trampa clásica del día del lanzamiento. |
| `TOKEN_ENCRYPTION_KEY` | Generar de cero, nunca reusar la de desarrollo | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Guardarla en un gestor de secretos con backup — perderla desconecta Mercado Libre de todos los clientes (ver sección Mercado Libre). |
| `MERCADOLIBRE_CLIENT_ID` / `MERCADOLIBRE_CLIENT_SECRET` | Los de la app real de Mercado Libre, registrada con la Redirect URI de producción (ver sección Mercado Libre) | Nunca los de una app de prueba. |
| `MERCADOLIBRE_REDIRECT_URI` | `https://api.tudominio.cl/api/mercadolibre/callback` | Tiene que coincidir EXACTO con lo registrado en developers.mercadolibre.cl. |
| `FRONTEND_BASE_URL` | `https://app.tudominio.cl` | A dónde redirige el backend después del OAuth de Mercado Libre y de Google. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Los de la app OAuth real creada en console.cloud.google.com (ver `DATABASE.md`, sección "Google Sheets real") | **5 de septiembre de 2026.** Nunca los de un proyecto de prueba. Pendiente de crear — no bloquea el resto del despliegue, la integración queda deshabilitada (con mensaje claro) hasta que existan. |
| `GOOGLE_REDIRECT_URI` | `https://api.tudominio.cl/api/google-sheets/callback` | Tiene que coincidir EXACTO con la Redirect URI registrada en Google Cloud Console. |
| `MERCADOPAGO_ACCESS_TOKEN` | El de la cuenta de Mercado Pago REAL de Nexo (producción, no de prueba), creado en mercadopago.cl/developers/panel (ver `DATABASE.md`, sección "Cobro real con Mercado Pago") | **6 de septiembre de 2026.** Pendiente de crear — no bloquea el resto del despliegue, `/api/pagos/*` queda deshabilitado (con mensaje claro) hasta que exista. |
| `MERCADOPAGO_WEBHOOK_SECRET` | La clave que genera Mercado Pago al configurar la URL de webhook (`https://api.tudominio.cl/api/pagos/webhook`) en el panel de la app | Sin esto, `/api/pagos/webhook` rechaza cualquier notificación (nunca confía en un aviso de pago sin firma verificable). |
| `WOOCOMMERCE_LEGACY_STORE_ID` | El `store_id` real del cliente piloto de WooCommerce en la base de producción (no el de dev) | Ver `ADMIN_NEXO.md` para cómo consultarlo. Dejar sin definir si no se usa el reporte de WooCommerce todavía. |
| `BACKEND_PUBLIC_BASE_URL` | `https://api.tudominio.cl` | URL con la que Nexo arma el link público de cada imagen subida (6 de septiembre de 2026) Y a dónde redirige Mercado Pago después del checkout (`GET /api/pagos/callback`, ver `DATABASE.md`). Si queda en `localhost`, ninguna de las dos cosas funciona en producción. |
| `UPLOADS_DIR` | Ruta a un disco/volumen PERSISTENTE del proveedor de hosting | Ver sección "Almacenamiento de imágenes" arriba — sin un volumen persistente, un redeploy borra las imágenes de los clientes. |

`frontend/js/env.js` (el único archivo del frontend que cambia entre entornos):
```js
window.LC.env = { API_BASE_URL: "https://api.tudominio.cl" };
```

### Dependencias — antes de instalar contra Postgres

`backend/requirements.txt` ya trae el driver de Postgres activo
(`psycopg[binary]==3.2.*`, desde el 14 de septiembre de 2026): el build de
Render lo instala tal cual. En desarrollo no se usa (SQLite).

### Comando de arranque en producción

`uvicorn app.main:app --reload` (el de `README.md`) es **solo para
desarrollo** — `--reload` no debe usarse en producción. Comando real:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

(`$PORT` es la variable que inyecta el proveedor — Render y Railway la definen solas; en un VPS propio, poné el número a mano.)

**`--workers 1` no es una sugerencia, es un requisito hoy.** Los estados
OAuth pendientes viven en memoria del proceso — `_pending_states` en
`app/api/routes/mercadolibre.py` **y** en `app/api/routes/google_sheets.py`.
Con 2 o más workers (o réplicas), el estado se crea en un proceso y el
callback puede llegar a otro: conectar Mercado Libre o Google Sheets falla
de forma intermitente y sin un error claro. Antes de escalar a más de un
worker hay que mover ese estado a algo compartido (Redis o una tabla).

---

## Base de datos — SQLite (dev) → PostgreSQL (producción)

**No migrar los datos del SQLite de desarrollo.** El propio `DATABASE.md`
confirma que el SQLite local está en estado de prueba (catálogo de
prueba, sin costos ni canales configurados) — no hay datos reales de
ningún cliente que valga la pena preservar. Arrancar producción con una
base vacía y cargar los datos reales por los flujos normales de la app es
más simple y más seguro que escribir un migrador ad-hoc.

Pasos exactos:

1. Provisionar la instancia de PostgreSQL (proveedor elegido), confirmar backup automático habilitado.
2. Descomentar `psycopg[binary]` en `requirements.txt`, `pip install -r requirements.txt`.
3. Generar `TOKEN_ENCRYPTION_KEY` nueva (ver arriba) — nunca reusar la de dev.
4. Configurar todas las variables de entorno de producción (tabla de arriba).
5. Correr las migraciones contra la base vacía:
   ```bash
   cd backend
   alembic upgrade head
   ```
6. Verificar (opcional): `alembic current`, y una inspección manual (`\dt` en `psql`) para confirmar que las 26 tablas y sus constraints quedaron creadas — en particular `uq_listing_account_product` (protección contra publicaciones duplicadas).
7. **No copiar `nexo.db`** a producción bajo ningún concepto.
8. Registrarse como usuario real en la app (paso normal de `/signup`) — esto crea el primer `User`+`Store` reales.
9. Otorgarse `is_nexo_admin=True` manualmente (ver `ADMIN_NEXO.md`) contra la base de producción.
10. A partir de ahí, todo el resto de la carga de datos (catálogo, costos, Mercado Libre) es el checklist de "primer cliente" más abajo — vía la app, nunca por script directo a producción.

Índices: no hacen falta todavía (con 1-5 clientes reales, es prematuro — ver auditoría de `database-architect`). Revisar si algún día hay 50+ empresas o catálogos de 100k+ productos.

---

## Dominio — qué apunta a dónde

| Dominio/subdominio | Apunta a | Se registra en |
|---|---|---|
| `app.tudominio.cl` (o el que elijas) | Frontend estático | DNS del registrador → proveedor de hosting del frontend |
| `api.tudominio.cl` | Backend FastAPI | DNS del registrador → proveedor de hosting del backend |
| Redirect URI de Mercado Libre | `https://api.tudominio.cl/api/mercadolibre/callback` | developers.mercadolibre.cl, en la app real de Mercado Libre — **tiene que coincidir carácter por carácter** con `MERCADOLIBRE_REDIRECT_URI` del `.env` de producción, o el OAuth falla. |
| Redirect URI de Google | `https://api.tudominio.cl/api/google-sheets/callback` | console.cloud.google.com → credenciales del cliente OAuth — mismo criterio, tiene que coincidir EXACTO con `GOOGLE_REDIRECT_URI`. A diferencia de Mercado Libre, Google no exige HTTPS en desarrollo (sí en producción, como cualquier dominio real). |

Cada proveedor de hosting de la comparación de arriba da instrucciones
específicas de qué registro DNS (`CNAME`/`A`) apuntar a su plataforma —
eso depende de cuál elijas, no es algo que se pueda documentar en
abstracto acá.

---

## Mercado Libre — transición de desarrollo a producción

**Desarrollo (hoy)**: `MERCADOLIBRE_REDIRECT_URI` apunta a un túnel ngrok
temporal — se cae apenas se cierra el túnel, y cambia de URL cada vez que
se reinicia.

**Producción**: Mercado Libre exige HTTPS siempre (ya lo exigía en
desarrollo también) — con el dominio real ya no hace falta ningún túnel,
`https://api.tudominio.cl/api/mercadolibre/callback` es una URL estable.

Pasos:
1. Registrar (o editar) la aplicación en developers.mercadolibre.cl con la Redirect URI de producción.
2. Actualizar `MERCADOLIBRE_REDIRECT_URI` en las variables de entorno de producción.
3. El `state` firmado de la conexión OAuth (`app/api/routes/mercadolibre.py`) no depende del dominio — sigue siendo igual de seguro, no requiere ningún cambio de código.
4. **Advertencia de escalado**: `_pending_states` (los estados OAuth pendientes) vive en memoria del proceso — con más de un worker/réplica del backend, un estado creado en un worker puede no encontrarse en el que recibe el callback, y la conexión de Mercado Libre falla de forma intermitente. Arrancar con un solo worker evita esto; si en algún momento hace falta escalar a más, ese estado necesita moverse a algo compartido (Redis, una tabla) antes.
5. Reconectar la cuenta real de Mercado Libre del cliente piloto desde cero (OAuth) — **la cuenta hoy conectada en desarrollo es la personal del dueño de Nexo, no la del cliente piloto** (confirmado en la auditoría — hay que resolver esto con el cliente antes de ir a producción, no es una tarea de código).

**Ninguna publicación real se ejecuta automáticamente** — sigue siendo:
preview → confirmación explícita (checkbox + modal) → un único POST →
verificación de resultado → chequeo de duplicados (ahora también reforzado
a nivel de base de datos, ver `ADMIN_NEXO.md`).

---

## Checklist de seguridad antes de exponer Nexo a Internet

| # | Ítem | Estado |
|---|---|---|
| 1 | `SESSION_COOKIE_SECURE=true` en producción | Configurar en el despliegue |
| 2 | `CORS_ALLOWED_ORIGINS` apuntando a los dominios HTTPS reales | Configurar en el despliegue (ya es configurable en código, 30/08/2026) |
| 3 | `MERCADOLIBRE_REDIRECT_URI` real, registrada en developers.mercadolibre.cl | Configurar en el despliegue |
| 4 | `frontend/js/env.js` con `API_BASE_URL` real | Configurar en el despliegue (ya es configurable en código, 30/08/2026) |
| 5 | `TOKEN_ENCRYPTION_KEY` nueva, con backup seguro | Generar y guardar antes de cargar datos reales |
| 6 | Backup automático de Postgres habilitado | Confirmar en el panel del proveedor antes de cargar datos reales |
| 7 | Aislamiento multiempresa | ✅ Ya cumplido — probado extensamente |
| 8 | Tokens de Mercado Libre cifrados | ✅ Ya cumplido |
| 9 | Panel `/api/admin` protegido, sin fugas de secretos | ✅ Ya cumplido |
| 10 | Sin `debug=True` / stack traces crudos | ✅ Ya cumplido |
| 11 | CSRF | ✅ Ya cumplido — `SameSite=Lax` + `HttpOnly` alcanza con el diseño actual (todo endpoint mutante es POST/PUT) |
| 12 | Rate limiting en login/cambiar-contraseña | ✅ Ya cumplido (13/09/2026, `app/domain/rate_limit.py`) — 5 fallos por email / 20 por IP en 15 min. Vive en memoria del proceso: **otra razón para `--workers 1`** |
| 13 | `MERCADOPAGO_WEBHOOK_SECRET` configurada antes de cobrar a un cliente real | Sin esto, `/api/pagos/webhook` rechaza todo — no hay forma de activar un plan pagado por error sin la firma verificada |
| 14 | Nexo nunca ve/toca un número de tarjeta | ✅ Ya cumplido por diseño — el pago se hace en el checkout hosteado de Mercado Pago (`init_point`), nunca en un formulario propio |
| 15 | Cabeceras de seguridad HTTP | ✅ Ya cumplido (13/09/2026, `app/main.py`) — `X-Frame-Options: DENY`, CSP, `X-Content-Type-Options`, `Referrer-Policy`; `Strict-Transport-Security` se activa solo con `SESSION_COOKIE_SECURE=true` |
| 16 | Dependencias sin vulnerabilidades conocidas | ✅ Verificado 13/09/2026 con `pip-audit` (0 hallazgos tras subir Pillow a 12.3.0). **Volver a correrlo antes de cada despliegue** |

### Pentest — antes de exponer, y después de desplegar

El **13 de septiembre de 2026** se corrió un pentest manual contra una instancia
sembrada con dos empresas y un admin (39 pruebas). **Cero vulnerabilidades
reales.** Aguantaron: IDOR entre empresas (lectura y escritura), escalada a
admin, mass-assignment (`is_nexo_admin`/`store_id` inyectados), falsificación de
sesión, spoofing del webhook de pago, SQLi (→422), path traversal en `/uploads/`,
enumeración de usuarios, y reutilización de cookie tras logout.

Eso cubre la **lógica de la aplicación**. Lo que un pentest manual local NO puede
ver, y hay que verificar **una vez desplegado** (con la URL pública y HTTPS
reales): configuración de TLS, cabeceras en producción, comportamiento del proxy,
CSRF en un navegador real, y timing attacks.

Herramienta recomendada para esa pasada — **Strix** (agente de pentest con IA,
https://github.com/usestrix/strix). Necesita Docker y una API key de un LLM (costo
por uso, unos pocos USD por escaneo). Contra el backend desplegado:

```bash
strix --target https://api.tudominio.cl --instruction "API REST de un SaaS multiempresa. Login POST /api/auth/login con JSON {email,password}, devuelve cookie de sesion. Credenciales de dos empresas distintas y un admin: <email:clave>. Priorizar: acceso cruzado entre empresas, escalamiento a administrador, contexto ver-como-empresa en /api/admin/clientes/{id}/entrar, y spoofing del webhook /api/pagos/webhook."
```

> ⚠️ El rate-limit (ítem 12) le va a estorbar a cualquier escáner: tras 20 logins
> fallidos por IP, todo da 429 por 15 minutos. Para una pasada autenticada, subir
> temporalmente los límites en `app/domain/rate_limit.py` **solo en la instancia de
> prueba**, nunca en la de clientes reales, y revertir al terminar.

---

## Checklist de despliegue — de repositorio a primer cliente

Verificado contra el código real el 6 de septiembre de 2026 (revisión
release candidate). El orden importa: cada paso asume el anterior.

### Infraestructura
- [ ] **PostgreSQL creado** y backup automático confirmado en el panel del proveedor.
- [ ] **`psycopg[binary]` descomentado** en `requirements.txt` (ver "Dependencias" arriba) — sin esto el backend no puede conectar a Postgres.
- [ ] **Backend desplegado** con `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1` (un solo worker, ver la nota de `_pending_states`).
- [ ] **Frontend desplegado** apuntando a `frontend` (root directory dentro del repo, sin prefijos), **sin build** (ver el aviso al principio de este documento: no publicar la raíz del repo).

### Variables de entorno (panel del hosting, nunca un archivo `.env`)
- [ ] `DATABASE_URL` a Postgres.
- [ ] `TOKEN_ENCRYPTION_KEY` **nueva** (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`), guardada en un gestor de secretos con backup — si se pierde, se desconectan todas las cuentas de Mercado Libre.
- [ ] `SESSION_COOKIE_SECURE=true` (y el backend detrás de HTTPS real, o nadie podrá iniciar sesión).
- [ ] `CORS_ALLOWED_ORIGINS=https://app.tudominio.cl`.
- [ ] `FRONTEND_BASE_URL` y `BACKEND_PUBLIC_BASE_URL` con los dominios reales.
- [ ] `UPLOADS_DIR` apuntando a un disco **persistente**.
- [ ] `frontend/js/env.js` con la `API_BASE_URL` real (es el único archivo del frontend que cambia entre entornos).

### Base de datos
- [ ] `alembic upgrade head` ejecutado contra la base vacía de producción.
- [ ] `alembic current` devuelve la última revisión.

### Seguridad (13 de septiembre de 2026)
- [ ] `pip-audit` sin vulnerabilidades conocidas antes de desplegar (`python -m pip install pip-audit && python -m pip_audit`). Se corrió por primera vez el 13 de septiembre: Pillow tenía 40+ CVEs y es justo la librería que abre las imágenes que sube un cliente — se actualizó a 12.3.0.
- [ ] Confirmar que las cabeceras de seguridad llegan en producción: `curl -I https://api.tudominio.cl/api/health` tiene que traer `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Content-Security-Policy` y —solo con `SESSION_COOKIE_SECURE=true`— `Strict-Transport-Security`.
- [ ] El límite de intentos de login (`app/domain/rate_limit.py`) vive en memoria del proceso: **otra razón más para `--workers 1`**. Con varias réplicas cada una contaría por su cuenta y el límite se multiplica.

### Verificación de que levantó
- [ ] `GET https://api.tudominio.cl/api/health` → `{"status":"ok"}`.
- [ ] Los logs de arranque muestran las variables con los secretos **enmascarados** (nunca en claro).

### Cuentas
- [ ] Registrarte desde `/signup` en la app ya desplegada (crea tu `User` + `Store`).
- [ ] Darte `is_nexo_admin = True` a mano contra la base de producción (ver `ADMIN_NEXO.md`).
- [ ] Cerrar sesión, volver a entrar y confirmar que ves el **Panel Nexo**.

### Integraciones (cada una necesita credenciales creadas por una persona)
- [ ] **Mercado Libre**: app registrada en developers.mercadolibre.cl con la Redirect URI de producción; `MERCADOLIBRE_CLIENT_ID/SECRET/REDIRECT_URI` configuradas.
- [ ] **Mercado Pago** (solo si vas a cobrar ya): `MERCADOPAGO_ACCESS_TOKEN` de producción y `MERCADOPAGO_WEBHOOK_SECRET`, con la URL de webhook `https://api.tudominio.cl/api/pagos/webhook` registrada y los topics "Pagos" y "Suscripciones" activados.
- [ ] **Google Sheets** (opcional): `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI`. Sin esto, la integración se muestra deshabilitada con un mensaje claro — no rompe nada.

### Primer cliente real
- [ ] Crear su cuenta (o que se registre) y confirmar que su empresa arranca **vacía** (sin productos, sin ventas).
- [ ] Configurar costos y márgenes de Mercado Libre en Configuración.
- [ ] Importar su catálogo (Excel/CSV o Google Sheets) y verificar los productos reales.
- [ ] Conectar **su** cuenta de Mercado Libre por OAuth (nunca la tuya) y confirmar el estado "Conectado".
- [ ] Actualizar comisiones reales de Mercado Libre y revisar Oportunidades.
- [ ] Preparar una publicación y llegar hasta la pantalla de revisión **sin publicar**, para confirmar de punta a punta antes de la primera publicación real.
