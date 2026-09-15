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
| `conviene` | Con el precio real, la venta no deja pérdida y alcanza el margen mínimo % o la ganancia neta mínima $ (o no hay ninguno configurado). |
| `revisar` | Faltan datos para calcular la ganancia (precio o costos del canal). Sin costo de compra registrado se calcula con costo $0. |
| `no_conviene` | La venta deja pérdida, o no alcanza ni el margen mínimo ni la ganancia neta mínima. |

`razon` siempre trae una explicación en texto plano de por qué se llegó a
ese resultado — la decisión nunca se muestra como una etiqueta sin
contexto.

## Regla definitiva (14 de septiembre de 2026, decisión del dueño)

"¿Conviene?" se evalúa SIEMPRE con el **precio real** del producto
(Excel/publicación), nunca con el precio recomendado, y con la misma
clasificación que Oportunidades (`classify_product`, vía
`_criterios_conviene_ml` en `publicaciones.py`, también usada por
`/validar` y el gate de `/confirmar`):

1. Ganancia neta = precio real − costo − comisión (real de ML si existe) −
   envío (real de ML si existe) − otros costos. Sin costo de compra registrado
   (un producto que la empresa ya tiene, ej. un repuesto retirado) el costo
   considerado es $0: la ganancia es lo que queda después de los costos de ML.
   Sin costo tampoco hay precio para el margen objetivo: se publica al precio
   de venta del dueño.
2. Ganancia < 0 → `no_conviene`.
3. Ganancia ≥ 0 → `conviene` si margen % ≥ margen mínimo **o** ganancia ≥
   ganancia neta mínima $; si no cumple ninguna → `no_conviene`.
4. El stock NO participa.

El **margen objetivo** solo calcula el precio recomendado (cuánto cobrar
para alcanzarlo) y ayuda a elegir Clásica/Premium. Si es imposible de
alcanzar, la respuesta trae `avisoMargenObjetivo` ("No es posible alcanzar
tu margen objetivo con estas condiciones.") y la decisión no cambia. La
competencia es información, nunca decide.

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
| `precioActual`, `gananciaActual`, `margenActualPct` | Los números al precio real con los que se decidió. |
| `avisoMargenObjetivo` | Texto del aviso si el margen objetivo es imposible, si no `null`. |
| `precioRecomendado`, `precioMinimoRentable`, `gananciaEstimada`, `margenEstimadoPct` | Los mismos valores que devuelve `/precio-recomendado` (nunca se recalculan dos veces — ambos endpoints comparten `_resolver_recomendacion_precio`). |
| `competencia` | `null` si no hay dato de competencia, o `{precioGanador, rangoPrecioMinimo, rangoPrecioMaximo, posicionPrecioPropio}` si lo hay. |
| `faltantes` | Lista de qué dato falta, solo si `decision == "revisar"` por datos insuficientes. |

## Versión en lote (para una lista de productos)

`GET /api/publicaciones/mercadolibre/decision-lote` — calcula la decisión
para TODAS las variantes de la tienda de una sola vez, usando los mismos
`domain/pricing.py`/`domain/decision.py`, pero **sin consultar
competencia** (pedirle a Mercado Libre una consulta por cada fila de una
tabla no es viable). Devuelve `[{variantId, decision, precioRecomendado,
margenEstimadoPct, faltantes, avisoMargenObjetivo}]`. Como la competencia
ya no decide, la decisión del lote es la misma que la de `/decision` para el
mismo producto. Lo usa el frontend para la columna "Decisión preliminar" en
Oportunidades (`frontend/js/app.js`).

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
