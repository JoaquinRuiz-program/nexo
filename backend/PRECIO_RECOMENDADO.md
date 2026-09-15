# Precio recomendado — cómo funciona

Referencia técnica de `GET /api/publicaciones/{variant_id}/mercadolibre/precio-recomendado`
(FASE 5 del roadmap comercial, 30 de agosto de 2026).

## Qué responde Nexo

Una **recomendación**, nunca un cambio real. La respuesta siempre trae
`"tipo": "RECOMENDACION"` — Nexo v1 **no modifica ningún precio real** en
Mercado Libre ni en su propia base. Aplicar el precio recomendado, cuando
exista esa función, va a requerir una acción explícita del dueño en un
commit futuro.

## Cómo se calcula

```
Producto → Costo → Comisión ML → Competencia → Precio recomendado → Rentabilidad
```

1. **Costo real** — `ProductVariant.cost_price`, el mismo dato que usa
   `domain/profitability.py`. Sin costo cargado, no hay recomendación.
2. **Comisión + costos del canal** — `ChannelCostSettings` (mismo modelo
   que ya usa Rentabilidad), scopeado por `store_id` + `channel="mercadolibre"`.
3. **Margen objetivo y margen mínimo** — dos campos nuevos en
   `ChannelCostSettings` (`target_margin_pct`, `min_margin_pct`), **configurables
   por canal**, `NULL` por defecto (nunca un 25% inventado). Se configuran
   vía `PUT /api/configuracion/canales/{channel}`.
4. **Competencia (opcional)** — reutiliza `domain/competencia.py` (FASE 4)
   y el mismo `_buscar_producto_en_catalogo` que usa `/competencia`, nunca
   una segunda forma de consultar Mercado Libre. Si la cuenta no está
   conectada, o Mercado Libre no encuentra el producto, o la consulta
   falla por cualquier motivo — **la recomendación se calcula igual**, solo
   sin la comparación de mercado.
5. **Cálculo puro** — `domain/pricing.py::recomendar_precio`. Reutiliza
   `domain/profitability.py` (`ChannelCosts`, `net_margin`, `net_margin_pct`)
   para el margen — nunca duplica esa fórmula.

## Qué devuelve

| Campo | Qué es |
|---|---|
| `precioMinimoRentable` | Precio de equilibrio (margen neto = 0%) — dato factual, no una sugerencia. |
| `precioRecomendado` | Precio tal que el margen neto real alcance el `target_margin_pct` configurado, redondeado **hacia arriba** a un precio de vitrina terminado en 990 (`precio_vitrina`: $84.134 → $84.990; desde el 15 sept 2026). El margen estimado se calcula con ese precio redondeado. Con "envío desde $X" (envío manual), si se descuenta el envío se decide con el precio **recomendado**, no con el actual (QA integral, 15 sept 2026). |
| `margenEstimadoClp` / `margenEstimadoPct` | El margen neto REAL a ese precio (mismo cálculo que Rentabilidad). |
| `gananciaEstimada` | Alias de `margenEstimadoClp` — lo que pidió el dueño explícitamente. |
| `precioMercadoGanador`, `posicionFrenteACompetencia` | De `domain/competencia.py` — `null` si no hay competencia disponible. |
| `alcanzaMargenObjetivo` | `False` solo en el caso extremo donde comisión + margen objetivo suman ≥100% (matemáticamente imposible) — ahí se recomienda el mínimo rentable en su lugar. |
| `alcanzaMargenMinimo` | Dato factual (no una decisión): compara el margen estimado contra `min_margin_pct`. `null` si no hay mínimo configurado. |
| `clasificacion` | Campo histórico, siempre `null` — el motor "¿conviene vender?" quedó implementado en FASE 6 como un módulo aparte (`domain/decision.py`, ver [DECISION_NEGOCIO.md](DECISION_NEGOCIO.md)) en vez de escribirse acá, para no mezclar el cálculo de precio con la decisión de negocio. Usar `GET /{variant_id}/mercadolibre/decision`. |

## Qué pasa cuando faltan datos

Nunca se inventa un costo, comisión o margen. Si falta el costo, la
comisión/costos del canal, o el margen objetivo, la respuesta es:

```json
{"tipo": "RECOMENDACION", "estado": "datos_insuficientes", "faltantes": ["costo de compra"], "precioRecomendado": null, ...}
```

`faltantes` lista exactamente qué dato falta — nunca un precio calculado
con un supuesto.

## Datos opcionales

Solo la **competencia** es opcional — todo lo demás (costo, comisión,
margen objetivo) es obligatorio para poder calcular algo. `min_margin_pct`
también es opcional: sin configurarlo, `alcanzaMargenMinimo` queda en
`null` en vez de asumir un mínimo.
