# Decisión de negocio — ¿conviene vender esto? (FASE 6)

Referencia técnica de `GET /api/publicaciones/{variant_id}/mercadolibre/decision`
(FASE 6 del roadmap comercial, 30 de agosto de 2026).

## Qué responde Nexo

Un análisis, nunca una acción. La respuesta trae `"tipo": "DECISION"` —
Nexo v1 **no publica, no modifica precio, no modifica stock, no pausa
nada** en Mercado Libre ni en su propia base. `domain/decision.py` es una
función pura (`evaluar_decision`) que solo interpreta datos ya calculados
por `domain/pricing.py` y `domain/competencia.py` — no consulta la red ni
la base de datos.

```
Producto → Competencia → Precio recomendado → Decisión de negocio → conviene/revisar/no_conviene
   (competencia.py)         (pricing.py)          (decision.py)
```

`pricing.py` sigue calculando precios únicamente — la decisión de negocio
se construye ENCIMA de esa recomendación, en un módulo aparte. Nunca se
mezclan las dos responsabilidades.

## Qué significa cada resultado

| Resultado | Qué significa para el dueño |
|---|---|
| `conviene` | El precio recomendado alcanza el margen objetivo (y el margen mínimo, si hay uno configurado), y no hay ninguna señal de competencia en contra. |
| `revisar` | Falta información para decidir con confianza, o hay una señal mixta (por ejemplo: el precio rentable queda por encima de lo que cobra la competencia). Nunca significa "no publiques" — significa "mirá esto antes de decidir". |
| `no_conviene` | El margen objetivo es matemáticamente imposible, o no se alcanza el margen mínimo aceptable configurado para el canal. |

`razon` siempre trae una explicación en texto plano de por qué se llegó a
ese resultado — la decisión nunca se muestra como una etiqueta sin
contexto.

## Reglas, en orden (la primera que aplica gana)

1. **Sin datos suficientes** para calcular un precio (falta costo, comisión
   del canal o margen objetivo) → `revisar`. Nunca se inventa una decisión
   con datos que faltan.
2. **Margen objetivo matemáticamente imposible** (comisión + margen
   objetivo ≥ 100%) → `no_conviene`.
3. **No alcanza el margen mínimo configurado** → `no_conviene`. Esta regla
   tiene prioridad absoluta, incluso si el margen objetivo sí se alcanzó
   (puede pasar con una configuración contradictoria: mínimo mayor al
   objetivo).
4. **Sin margen mínimo configurado Y sin datos de competencia** → `revisar`:
   no hay ninguna señal externa (ni un mínimo aceptable, ni el mercado) que
   confirme la decisión.
5. **Precio recomendado por encima del rango de competencia** → `revisar`:
   es rentable, pero podría costar más venderlo que lo que muestra el
   mercado.
6. **En cualquier otro caso** (margen objetivo alcanzado, y margen mínimo
   alcanzado o sin configurar-pero-con-competencia-favorable, y el precio
   no queda por encima de la competencia) → `conviene`.

## Qué pasa cuando falta la competencia

La ausencia de datos de competencia (cuenta no conectada, Mercado Libre no
encontró el producto en su catálogo, o la consulta falló) **nunca se
interpreta como "no conviene"** — es una señal neutra. Si además hay un
margen mínimo configurado y se alcanza, el sistema igual puede responder
`conviene` (regla 6), dejándolo explícito en `razon`
("No hay datos de competencia disponibles"). Solo cuando ADEMÁS falta el
margen mínimo configurado, la ausencia de competencia empuja el resultado a
`revisar` (regla 4) — ahí sí no hay ninguna señal externa que respalde la
decisión.

## Por qué no hay un campo `confidence`

Se evaluó explícitamente (consulta a `product-reviewer`, FASE 6) agregar un
nivel de confianza (`alta`/`media`/`baja`). Se decidió no incluirlo en V1:
`competencia.py` hoy no tiene la granularidad para que ese campo aporte una
distinción real más allá de lo que ya transmiten el color y el texto de
`razon` — agregarlo sería complejidad sin valor real. Puede reconsiderarse
si en el futuro se suman más fuentes de datos de competencia.

## Qué devuelve

| Campo | Qué es |
|---|---|
| `decision` | `"conviene"` \| `"revisar"` \| `"no_conviene"`. |
| `razon` | Explicación en texto plano — siempre presente. |
| `precioRecomendado`, `precioMinimoRentable`, `gananciaEstimada`, `margenEstimadoPct` | Los mismos valores que devuelve `/precio-recomendado` (nunca se recalculan dos veces — ambos endpoints comparten `_resolver_recomendacion_precio`). |
| `competencia` | `null` si no hay dato de competencia, o `{precioGanador, rangoPrecioMinimo, rangoPrecioMaximo, posicionPrecioPropio}` si lo hay. |
| `faltantes` | Lista de qué dato falta, solo si `decision == "revisar"` por datos insuficientes. |

## Versión en lote (para una lista de productos)

`GET /api/publicaciones/mercadolibre/decision-lote` — calcula la decisión
para TODAS las variantes de la tienda de una sola vez, usando los mismos
`domain/pricing.py`/`domain/decision.py`, pero **sin consultar
competencia** (pedirle a Mercado Libre una consulta por cada fila de una
tabla no es viable). Devuelve `[{variantId, decision, precioRecomendado,
margenEstimadoPct, faltantes}]`. La ausencia de competencia en este cálculo
no cambia el resultado más de lo que ya contempla la regla 4 — sigue sin
asumir nunca que falta competencia significa "no conviene". Lo usa el
frontend para la columna "Decisión" en Oportunidades
(`frontend/js/app.js`).

## Frontend

Implementado 30 de agosto de 2026 — `frontend/js/mercadolibrePublicar.js`,
ruta `#/publicaciones/:id`: tarjeta de decisión → "Ver análisis" → preparar
publicación → revisar (preview) → publicar (con checkbox + modal de
confirmación explícita antes del POST real). Ver `frontend/README.md`.

## Aislamiento multiempresa

Igual que el resto de `/mercadolibre/*`: resuelve la variante vía
`_variante_de_la_empresa` (mismo mecanismo que usan `/preparar`, `/validar`
y `/confirmar` — nunca uno nuevo), y 404 (nunca 403) si la variante no es
de la tienda autenticada.
