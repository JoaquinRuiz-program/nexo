# Nexo en producción — guía de despliegue

30 de agosto de 2026, etapa "primer cliente real". Este documento cubre:
arquitectura recomendada, comparación de opciones de hosting, configuración
de producción exacta, transición de la base de datos y de Mercado Libre, y
el dominio. No asume un proveedor específico — vos elegís, acá está la
comparación.

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
**No hace falta provisionar nada.** Confirmado en el código (`ProductImage.url`, `source="excel_url"`): Nexo nunca sube ni guarda archivos de imagen — solo guarda la URL que ya viene en el Excel del cliente (imágenes alojadas en su propia tienda WooCommerce o donde sea). Si en el futuro Nexo permite subir imágenes directamente, ahí sí hará falta un bucket (S3, Cloudflare R2) — no es necesario para el primer cliente.

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
| `SESSION_COOKIE_SECURE` | `true` | Sin esto, la cookie de sesión no tiene el flag `Secure` en HTTPS real. |
| `TOKEN_ENCRYPTION_KEY` | Generar de cero, nunca reusar la de desarrollo | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Guardarla en un gestor de secretos con backup — perderla desconecta Mercado Libre de todos los clientes (ver sección Mercado Libre). |
| `MERCADOLIBRE_CLIENT_ID` / `MERCADOLIBRE_CLIENT_SECRET` | Los de la app real de Mercado Libre, registrada con la Redirect URI de producción (ver sección Mercado Libre) | Nunca los de una app de prueba. |
| `MERCADOLIBRE_REDIRECT_URI` | `https://api.tudominio.cl/api/mercadolibre/callback` | Tiene que coincidir EXACTO con lo registrado en developers.mercadolibre.cl. |
| `FRONTEND_BASE_URL` | `https://app.tudominio.cl` | A dónde redirige el backend después del OAuth de Mercado Libre. |
| `WOOCOMMERCE_LEGACY_STORE_ID` | El `store_id` real de Librería Central en la base de producción (no el de dev) | Ver `ADMIN_NEXO.md` para cómo consultarlo. Dejar sin definir si no se usa el reporte de WooCommerce todavía. |

`frontend/js/env.js` (el único archivo del frontend que cambia entre entornos):
```js
window.LC.env = { API_BASE_URL: "https://api.tudominio.cl" };
```

### Dependencias — antes de instalar contra Postgres

`backend/requirements.txt` tiene el driver de Postgres **comentado a
propósito** (no hace falta para desarrollo con SQLite). Antes de desplegar:

```bash
# Descomentar en requirements.txt:
psycopg[binary]==3.2.*
```

### Comando de arranque en producción

`uvicorn app.main:app --reload` (el de `README.md`) es **solo para
desarrollo** — `--reload` no debe usarse en producción. Comando real:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

Con **un solo worker** al principio si es posible (ver nota de `_pending_states` en la sección Mercado Libre) — 2 workers ya requeriría mover ese estado a algo compartido (Redis, o una tabla) para que el flujo de conectar Mercado Libre no falle de forma intermitente.

---

## Base de datos — SQLite (dev) → PostgreSQL (producción)

**No migrar los datos del SQLite de desarrollo.** El propio `DATABASE.md`
confirma que el SQLite local está en estado de prueba (catálogo de
prueba, sin costos ni canales configurados) — no hay datos reales de
Librería Central que valga la pena preservar. Arrancar producción con una
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
6. Verificar (opcional): `alembic current`, y una inspección manual (`\dt` en `psql`) para confirmar que las 20 tablas y sus constraints quedaron creadas — en particular `uq_listing_account_product` (protección contra publicaciones duplicadas).
7. **No copiar `libreria_central.db`** a producción bajo ningún concepto.
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
5. Reconectar la cuenta real de Mercado Libre de Librería Central desde cero (OAuth) — **la cuenta hoy conectada en desarrollo es la personal del dueño de Nexo, no la de Librería Central** (confirmado en la auditoría — hay que resolver esto con el cliente antes de ir a producción, no es una tarea de código).

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
| 12 | Rate limiting en login/registro | ⚠️ **No bloqueante para el primer cliente** (ver razonamiento abajo) — hacerlo inmediatamente después de este lanzamiento, antes de un segundo cliente o de que la URL se difunda más. |

**Rate limiting — por qué no bloquea hoy**: el mensaje de login ya es idéntico para "email no existe" y "contraseña incorrecta" (sin enumeración de usuarios), la URL de producción va a ser nueva y desconocida, y hay un solo cliente conocido — el vector de fuerza bruta no tiene a quién apuntar todavía. En cuanto exista un segundo cliente, o la URL deje de ser nueva/desconocida, pasa a ser prioritario.
