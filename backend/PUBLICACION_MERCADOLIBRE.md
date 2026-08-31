# Publicación real en Mercado Libre — cómo funciona

Referencia técnica del flujo `POST /api/publicaciones/{variant_id}/mercadolibre/confirmar`
(y su gemelo de solo lectura `.../confirmar/preview`) — el único lugar del
backend que puede terminar ejecutando un `POST /items` real contra Mercado
Libre. Última actualización: 30 de agosto de 2026.

## Legacy vs. User Product Seller

Mercado Libre tiene dos modelos de publicación en convivencia:

| | Modelo clásico (legacy) | User Products (`user_product_seller`) |
|---|---|---|
| ¿Cómo se detecta? | Cuenta SIN el tag `user_product_seller` en `GET /users/{id}` (con el token de esa misma cuenta — el endpoint público no devuelve `tags`) | Cuenta CON ese tag |
| Campo raíz del título | `title` (lo manda Nexo) | Ausente — Mercado Libre lo genera automáticamente |
| Campo de agrupación | No existe | `family_name` (obligatorio, lo manda Nexo) |
| `variations[]` | Se podía usar (Nexo nunca lo usó) | Prohibido — cada variante es un User Product distinto |
| Atributo `MODEL` (`catalog_required`, no `required`) | Opcional en v1 | **Obligatorio en la práctica** — Mercado Libre lo rechaza si falta (confirmado empíricamente el 30 de agosto de 2026, error real `item.attribute.missing_catalog_required`) |

**Nexo detecta esto SIEMPRE fresco, en cada `/confirmar`** — nunca lo
cachea en `MarketplaceAccount`. Si Mercado Libre migra una cuenta al
modelo nuevo entre dos publicaciones, un valor cacheado seguiría mandando
el payload viejo y Mercado Libre lo rechazaría. Ver
`app/domain/ml_seller_capabilities.py::es_user_product_seller`.

Fuente oficial: [developers.mercadolibre.cl/es_cl/precio-variacion](https://developers.mercadolibre.cl/es_cl/precio-variacion).

## `family_name`

- Lo arma Nexo (`generate_title` truncado a `settings.max_title_length`
  real de la categoría vía `GET /categories/{id}`), o lo manda el dueño
  explícito en el body (`ConfirmarPublicacionRequest.family_name`).
- Si viene explícito, Nexo NO gasta el llamado extra a `GET /categories/{id}`.
- Se persiste en `MarketplaceListing.family_name` (nullable — `NULL` en
  cualquier publicación legacy).

## GTIN / `EMPTY_GTIN_REASON` — cuatro casos posibles

| Caso | ¿Qué hace Nexo? |
|---|---|
| A. GTIN conocido y con checksum válido | Se manda como `GTIN` en `attributes`. |
| B. GTIN conocido pero con checksum inválido | **Bloqueado localmente, 400, antes de llamar a Mercado Libre** — `app/domain/listing_validation.py::gtin_checksum_valido`. Nunca se corrige el dígito ni se manda igual (confirmado real: Mercado Libre lo rechaza con `item.attribute.product_identifier.invalid_format`). |
| C. El producto genuinamente no tiene GTIN | Se manda `EMPTY_GTIN_REASON` — pero tiene que ser una de las 4 razones REALES de Mercado Libre (`RAZONES_GTIN_VACIO_VALIDAS`), nunca texto libre inventado. |
| D. Nexo todavía no conoce el GTIN (pero el producto probablemente sí tiene uno real) | **Sin resolver automáticamente todavía** — ver "Pendiente" abajo. |

`GTIN` y `EMPTY_GTIN_REASON` son mutuamente excluyentes (XOR): si uno está
resuelto, el otro se omite del todo (ni completo ni faltante) — mandar los
dos juntos es una contradicción que Mercado Libre rechaza.

**Resuelto (30 de agosto de 2026):** `ProductVariant.gtin_confirmado_ausente`
(default `False`) distingue Caso C de Caso D. Se pone en `True` solo vía
`PUT /api/productos/{variant_id}/codigo-barras` con `confirmarSinCodigo: true`
— nunca se infiere. `/confirmar` bloquea puntualmente la razón "El producto
no tiene código registrado" si esa confirmación no existe todavía (las
otras 3 razones reales no tienen la misma ambigüedad, no la exigen). Sigue
pendiente: exponer esto en una UI real (no existe todavía) — hoy solo es
alcanzable vía API.

## Atributos obligatorios bajo User Products

`app/domain/listing_validation.py::_es_requerido` trata como obligatorio:
`required`, `new_required` (si `condition="new"`), `conditional_required`
(siempre, conservador) — y, **solo si `es_user_product_seller=True`**,
también `catalog_required`. Un atributo con tag `read_only` nunca se pide,
sin importar qué otro tag tenga (Mercado Libre lo calcula él mismo).

## Alcance de Nexo v1

Nexo v1 publica **productos simples, no agrupados**: cada variante interna
se publica como un ítem independiente, con `POST /items` (clásico o User
Products según la cuenta). **No implementa todavía**:

- Familias completas de User Products (`POST /user-products-families/...`).
- Variantes agrupadas (múltiples condiciones de venta bajo un mismo
  `family_name` con pickers reales).
- `POST /user-products/{id}/items` (agregar una condición de venta a un
  User Product ya existente).
- Stock distribuido/multiorigen (`stock_locations`, header `x-version`).
- Matching automático contra el catálogo de Mercado Libre
  (`GET /products/search`).
- Migración de publicaciones legacy al modelo nuevo (UPtin).

Todo esto está investigado y documentado como posible trabajo futuro, pero
construirlo ahora sería sobrearquitecturar para lo que Nexo v1 necesita
hoy: publicar un producto por vez, de forma correcta y verificada.

## Análisis de competencia (FASE 4, 30 de agosto de 2026)

`GET /{variant_id}/mercadolibre/competencia` — solo lectura, nunca publica. Busca el producto real en el catálogo de Mercado Libre (`GET /products/search`, por GTIN si es válido, si no por nombre) y trae el ganador real + rango real de precios (`GET /products/{id}` → `buy_box_winner` / `buy_box_winner_price_range`, confirmado oficialmente en developers.mercadolibre.cl/es_cl/competencia-en-catalogo).

**Deliberadamente no implementado todavía** (documentado, no descartado): `/suggestions/items/{id}/details` (benchmark de precio) y `/items/{id}/price_to_win` — ambos exigen que el vendedor YA sea dueño de un ítem publicado, y Nexo todavía no tiene ninguna publicación real. Quedan como el paso lógico siguiente de FASE 4 una vez que exista al menos una publicación.

**Nunca implementado** (no confirmado oficialmente que exista): búsqueda pública de publicaciones por texto libre con precio/envío/reputación en el resultado — no hay ningún endpoint documentado que lo haga; investigado a fondo el 30/08/2026, ver informe de `mercadolibre-researcher`. Los Términos y Condiciones de Mercado Libre prohíben explícitamente suplir este hueco con scraping.

## Endpoints

| Endpoint | Qué hace |
|---|---|
| `POST /{variant_id}/mercadolibre/confirmar/preview` | Corre toda la validación local + remota y arma el payload final — nunca llama a `POST /items`. Nunca expone `access_token`/`refresh_token`/`client_secret`/cookies. |
| `POST /{variant_id}/mercadolibre/confirmar` | Lo mismo, y si todo pasa, ejecuta el `POST /items` real (única función: `_ejecutar_publicacion_real`). |

Ambos comparten la misma validación (`_resolver_publicacion`) — el
preview nunca puede mentir sobre lo que el POST real haría.
