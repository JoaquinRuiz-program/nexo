# Revisión del sistema — código, lógica y negocio (16 de septiembre de 2026)

Revisión completa pedida por el dueño después de la pasada visual y del envío
estimado. Cubre backend (dominio, rutas, servicios, adaptadores, modelos),
frontend y las reglas de negocio (planes, cobro, rentabilidad, publicación).

Lo que se revisó leyendo el código, no de memoria: `app/domain/*` (decisión,
precio, rentabilidad, selección, planes, ciclo de vida, envío, comisiones,
importador, stock, límites), `app/api/routes/*` (auth, deps, catálogo,
productos, rentabilidad, selección, publicaciones, Mercado Libre, Google
Sheets, pagos, suscripción, admin, dashboard, configuración), `app/services/*`
(comisiones, envío, stock, devoluciones, conciliación, ciclo de vida, eliminar
cuenta), `app/adapters/*` (Mercado Libre, Mercado Pago) y el frontend completo.

---

## 1. Corregido en esta revisión

| # | Qué estaba mal | Riesgo real | Dónde |
|---|---|---|---|
| 1 | El webhook de Mercado Pago **no era idempotente**: el mismo aviso de pago aplicado dos veces sumaba otro mes (o año) de plan. Mercado Pago reintenta hasta recibir un 200. | Plan regalado; ingresos perdidos sin que nadie lo note. | `routes/pagos.py` (`_ya_aplicado`) |
| 2 | Al pagar, el período **se contaba desde hoy**: renovar antes del vencimiento borraba los días que quedaban pagados. | El cliente pierde días que pagó. | `routes/pagos.py` |
| 3 | La importación de ventas pedía **una sola página** (50 pedidos): con más de 50 pedidos nuevos entre dos importaciones, el resto se perdía en silencio. | Ventas sin importar → métricas, conciliación y stock incompletos. | `routes/mercadolibre.py` + `adapters/mercadolibre.py` |
| 4 | "Eliminar cuenta" no borraba la caché de envío estimado. | En Postgres habría fallado por la clave foránea; en SQLite quedaban datos huérfanos. | `services/eliminar_cuenta.py` |
| 5 | Las estimaciones de envío no vencían nunca. | Una tarifa vieja se mostraría como actual. | `services/ml_comisiones.py` (30 días) |

Pruebas nuevas: webhook repetido (mensual y anual), pago anticipado que suma
los días restantes, importación paginada y segunda importación sin duplicados.

---

## 2. Pendiente de decisión del dueño (negocio)

### 2.1 El cobro del mes 2 en adelante no se procesa (P1)
`POST /api/pagos/webhook` maneja `subscription_preapproval` (alta) y `payment`
(pago único anual), pero **no** `subscription_authorized_payment`, que es el
aviso del cobro mensual recurrente. Consecuencia real: si a un cliente mensual
le rechazan la tarjeta el mes 2, Nexo nunca se entera — su suscripción sigue
`active` y, como el ciclo de vencimiento solo mira `trialing` y `past_due`,
**conserva acceso completo indefinidamente**.

Trabajo: procesar ese aviso (marcar `past_due` si el cobro falla y extender el
período si sale bien). Es la única parte del cobro que quedó a medias.

### 2.2 Renovación anual
Por diseño, el ciclo anual no se cobra solo: al vencer, el cliente vuelve a
pagar. Falta decidir el aviso previo (hoy los recordatorios solo corren para
prueba y pago pendiente).

### 2.3 Qué hacer cuando una publicación deja de convenir
Ya conversado: hoy solo se avisa en Oportunidades. Sigue pendiente tu decisión
entre pausar automáticamente o ajustar el precio.

---

## 3. Riesgos operativos (antes de tener varios clientes)

1. **Un solo proceso**: el estado de OAuth (`_pending_states`) y el límite de
   intentos de login viven en memoria. Con dos réplicas o un reinicio, se
   pierden (una conexión a Mercado Libre a medio hacer falla y hay que
   reintentar; el límite de intentos cuenta por réplica). Ya está documentado
   en el código; hay que resolverlo antes de escalar a más de un worker.
2. **Comisión cacheada sin vencimiento**: la comisión real por (categoría,
   precio) no se vuelve a consultar nunca. Si Mercado Libre cambia sus
   comisiones, Nexo calcula con la vieja. El envío estimado ya vence a los 30
   días; conviene hacer lo mismo con la comisión.
3. **Tailwind por CDN**: si el CDN no carga, la interfaz queda sin estilos (hay
   un respaldo mínimo para que no se vea rota, pero es parcial). Para producción
   conviene servir el CSS desde el propio dominio.
4. **Topes por corrida**: devoluciones (10 páginas), conciliación (600 pedidos),
   comisiones y envíos (200 combinaciones) y ahora ventas (1.000 pedidos). Son
   deliberados y lo que no entra se procesa en la corrida siguiente, pero
   conviene tenerlos presentes con un vendedor grande.
5. **Reembolso parcial**: una venta con devolución de dinero se excluye entera
   de las métricas del admin. Un reembolso parcial no se distingue todavía.
6. **Stock reservado tras una cancelación**: si un pedido ya importado se
   cancela, el stock reservado para Mercado Libre no se devuelve solo.

---

## 4. Lo que está sólido

- **Aislamiento entre empresas**: `get_current_store` es el único resolutor de
  empresa; los accesos cruzados responden 404, nunca 403. El panel de admin
  cuelga siempre de `require_nexo_admin`, y "ver como empresa" no crea una
  sesión del cliente: marca un contexto en la sesión del admin, queda
  registrado y se avisa en pantalla mientras dura.
- **Datos sensibles**: contraseñas con hash, tokens de Mercado Libre y Google
  cifrados (Fernet), sesiones guardadas como hash, y ninguna respuesta de la
  API expone tokens ni `password_hash`. El webhook de Mercado Pago valida
  firma HMAC y siempre le vuelve a preguntar a Mercado Pago el estado real.
- **Una sola regla de rentabilidad**: Oportunidades, "¿Conviene?", el
  Dashboard y el bloqueo al publicar usan la misma función y los mismos
  mínimos. No hay dos formas de calcular el mismo margen.
- **Nunca se inventan datos**: sin costo, sin precio o sin comisión, el sistema
  dice qué falta en vez de asumir un número. El costo de envío distingue el
  real de la publicación, el estimado y el no disponible.
- **Publicar es difícil de hacer mal**: se revalida todo contra la base en el
  momento (precio, stock reservado, imágenes, código de barras, atributos,
  plan vigente, límite del plan, duplicados) y el POST real a Mercado Libre
  nunca se reintenta solo.
- **Errores hacia afuera**: el cliente nunca ve rutas, variables de entorno ni
  respuestas crudas de Mercado Libre; ese detalle queda en el log.
- **Pruebas**: 960+ pruebas automáticas, incluidas las de aislamiento entre
  empresas, pagos y publicación.

---

## 5. Reglas de negocio, tal como están hoy

- **Planes**: Básico $80.000/mes (1.000 productos, 150 publicaciones) y Pro
  $200.000/mes (5.000 y 800). Anual con 15 % de descuento. Prueba de 14 días.
- **Vencimiento**: 5 días de gracia con avisos a los 5, 3 y 1 día; pasada la
  gracia se pausan las publicaciones reales en Mercado Libre y se reactivan
  solas al pagar (solo las que pausó Nexo).
- **Rentabilidad**: ganancia = precio − costo − comisión real − envío − otros.
  Sin costo de compra registrado se calcula con costo $0. Conviene si alcanza
  el margen mínimo (15 % por defecto) **o** la ganancia mínima ($3.000).
  Sin costo de envío de Mercado Libre no hay veredicto: "Faltan datos"
  (16 sept 2026, ver PROGRESS.md #44). Un envío que falta nunca se toma
  como $0.
- **Precio recomendado**: el que alcanza el margen objetivo, redondeado hacia
  arriba a un precio terminado en 990. Nunca se aplica solo.
- **Envío**: el real de la publicación manda; si no hay, el estimado de
  Mercado Libre para esa categoría y precio (vigente 30 días); si no hay
  ninguno de los dos, es dato faltante. El envío manual de Configuración ya
  no completa el cálculo.
