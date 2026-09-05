# Panel de administrador de Nexo

Referencia técnica del panel del dueño de la plataforma (`/api/admin/*`,
`frontend/js/adminPanel.js`) — etapa "preparación para primer cliente
real", 30 de agosto de 2026.

## Qué es

Una segunda capa de usuario, separada de un cliente normal:

- **Cliente**: ve únicamente su propia empresa (todo lo que ya existía).
- **Administrador de Nexo**: dueño de la plataforma, ve/administra TODAS
  las empresas. Nunca tiene una tienda propia.

## Cómo se otorga (nunca vía API)

`User.is_nexo_admin: bool` — un campo simple, no una tabla de roles
aparte (no hace falta granularidad todavía). **Solo se otorga
manualmente**, por script o consola directa contra la base:

```python
from app.db.session import SessionLocal
from app.db.models import User

db = SessionLocal()
usuario = db.query(User).filter_by(email="admin@ejemplo.cl").first()
usuario.is_nexo_admin = True
db.commit()
```

Ningún endpoint de la API puede otorgar ni leer este campo salvo
`require_nexo_admin` (`app/api/deps.py`) — ni siquiera un endpoint de
"actualizar mi perfil".

## Aislamiento

`require_nexo_admin` es el único guard de todo `/api/admin/*` — nunca usa
ni reemplaza `get_current_store` (que sigue siendo, exclusivamente, "la
empresa de esta sesión de cliente"). Un admin de Nexo sin tienda propia
inicia sesión igual (`/api/auth/login`, `/api/auth/me` toleran
`empresa: null` — ver `_sesion_publica`).

El frontend además:
- Nunca navega a pantallas de cliente si la sesión es de un admin (ver
  `router.js` — redirige a `/admin`).
- Oculta los links de cliente en el sidebar para un admin.

## Estados del cliente (calculados, no una columna nueva)

Decisión explícita: no se agregó ninguna columna de "estado" — todo se
deriva de datos que ya existen (ver `app/api/routes/admin.py::_estado_cliente`):

| Estado | Condición |
|---|---|
| `suspendido` | `User.status == "suspended"` (el dueño de la tienda) — ahora también bloquea el login (`app/api/routes/auth.py`). |
| `trial` | Existe una `Subscription` con `status == "trialing"`. |
| `pendiente_configuracion` | Sin cuenta de Mercado Libre conectada Y sin ningún producto cargado. |
| `activo` | Cualquier otro caso. |

"Última actividad" se deriva de `MAX(AuthSession.created_at)` del dueño
— no existe ninguna columna de "last seen" dedicada (evita escribir en
cada request solo para trackear esto).

## Qué nunca se expone

`access_token_encrypted`, `refresh_token_encrypted`, `client_secret`,
`password_hash` — ni el detalle de cliente ni ningún otro endpoint de
este panel los toca. El detalle arma su propio dict campo por campo,
nunca serializa un modelo completo.

## Endpoints

| Endpoint | Qué hace |
|---|---|
| `GET /api/admin/clientes` | Lista todas las empresas con su estado, Mercado Libre conectado, cantidad de productos, última actividad y plan. |
| `GET /api/admin/clientes/{store_id}` | Detalle: usuario, tienda, productos, publicaciones por estado, Mercado Libre (sin tokens), costos configurados, actividad reciente. `erroresRecientes` es siempre `null` — no existe todavía un registro de errores por cliente (se ve en los logs del servidor). |
| `PUT /api/admin/clientes/{store_id}/estado` | Suspender/reactivar (`{"suspendido": true/false}`). |
| `PUT /api/admin/clientes/{store_id}/suscripcion` | Cambiar plan/estado de la suscripción — crea la primera si la tienda no tenía ninguna. |
| `POST /api/admin/clientes/{store_id}/entrar` | **6 de septiembre de 2026 — "entrar como soporte".** Crea una sesión real (misma cookie de siempre) scopeada a esa empresa, con `impersonated_by_admin_id` marcado — el admin pasa a operar Nexo exactamente como lo ve ese cliente, sin pedirle la contraseña. Vida corta (1 hora, nunca "recordarme"), nunca silenciosa: queda en `AdminActionLog` y `GET /api/auth/me` expone `modoSoporte` (el frontend muestra un aviso persistente mientras dure). Prohibido contra otra cuenta de admin (400). Terminarla es el `POST /api/auth/logout` de siempre — no existe forma de "volver" a la sesión de admin anterior en la misma pestaña, porque su token nunca vivió en el servidor sin cifrar (solo el hash); hay que volver a loguearse. |

## Qué NO hace este panel

No modifica precios, stock, productos ni publicaciones de ningún
cliente — eso sigue siendo responsabilidad exclusiva del dueño de esa
empresa, incluso operando en modo soporte (el admin ve/actúa como el
dueño, pero cada acción que haga en ese modo queda igual sujeta a las
reglas normales de esa cuenta — sin atajos adicionales).

## Hallazgos de seguridad corregidos en la misma ronda (no son del panel admin en sí, pero se auditaron juntos)

- **Carrera en `/confirmar`** (publicación real de Mercado Libre):
  `MarketplaceListing` ahora tiene `UniqueConstraint(account_id,
  product_id)` — dos requests casi simultáneas para el mismo producto ya
  no pueden dejar dos registros locales silenciosos. No elimina el riesgo
  de que Mercado Libre reciba dos `POST /items` reales (eso ya pasó antes
  de esta constraint), pero convierte el resultado en un error claro
  (409) en vez de un estado local corrupto.
- **`GET /api/productos/reporte` (WooCommerce) sin scope de tienda**:
  ahora exige `get_current_store` y solo responde para
  `settings.woocommerce_legacy_store_id` (configurable, nunca
  hardcodeado por nombre) — mitigación mínima hasta integrar WooCommerce
  de verdad por tienda.
