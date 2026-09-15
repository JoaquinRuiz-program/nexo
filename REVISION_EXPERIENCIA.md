# Revisión de experiencia — 15 de septiembre de 2026

Recorrido real por la app como **admin** y como **4 clientes de prueba**, uno por perfil de
vendedor de artículos nuevos en Mercado Libre. Cada cliente importó su propia planilla por el
importador real y configuró sus costos de Mercado Libre como lo haría en Configuración (sin
Mercado Libre conectado, así que con comisión de respaldo).

| Perfil | Cuenta de prueba | Planilla | Importados | Oportunidades ML |
|---|---|---|---|---|
| Pyme / tienda especializada (mascotas) | pyme@revision.nexo.local | 40 filas, encabezados claros | 40 | 6 convienen · 9 margen bajo · 25 no rentables |
| Importador / mayorista (electrónica) | importador@revision.nexo.local | 400 filas, título arriba, "Precio mayorista" y "Precio retail", montos "$1.990" | 400 (tras corregir columnas a mano) | 200 convienen · 56 margen bajo · 144 no rentables |
| Retailer multimarca | retailer@revision.nexo.local | 1.100 filas, en inglés, sin costo en algunas, 1 SKU duplicado | 1.000 (límite del plan) | 194 convienen · 114 margen bajo · 666 no rentables · 26 sin costo |
| Emprendedor / revendedor | emprendedor@revision.nexo.local | CSV de 8 filas con encabezados informales | 8 (tras corregir columnas a mano) | 2 convienen · 2 margen bajo · 4 no rentables |

La regla de "¿Conviene?" (Oportunidades, decisión y publicar) dio el mismo resultado en las
tres pantallas para los 4 perfiles.

---

## 1. Críticos — afectan la decisión de qué publicar

> **Estado:** los 8 críticos se corrigieron el 15 de septiembre de 2026 (ver PROGRESS.md #30).

1. **La comisión real no se usaba en todas las pantallas.** Rentabilidad y Oportunidades ya
   elegían solas Clásica o Premium con la comisión real. Pero "¿Conviene?", el precio
   recomendado y la decisión en lote recibían la preferencia vacía ("Comparar ambas", el valor
   por defecto) y calculaban con la comisión de respaldo manual.
   *Corregido:* las tres usan la misma elección automática (`preferencia_efectiva`).
2. **El Dashboard contradice a Oportunidades.** "X productos con buena oportunidad de venta" y
   "Rentables" usan venta − compra, sin comisión ni envío. Pyme: 40 "buena oportunidad" en el
   Dashboard vs 6 que convienen en Mercado Libre. Retailer: 814 vs 194.
   *Propuesta:* usar la misma clasificación de Oportunidades.
3. **El costo de envío manual se aplica igual a todos los productos.** Un envío fijo de $3.500
   deja con pérdida cualquier producto barato. Pyme: un snack de $4.990 queda en −57 %.
   Importador: un power bank de $1.990 queda en −123 %. Es el perfil más afectado: 144 de 400
   no rentables.
   *Propuesta:* envío por tramo de precio (ej. solo sobre cierto precio) o marcarlo como
   provisional y no descartar el producto hasta tener el envío real.
4. **Importador: "Descripción" no se toma como nombre.** Si la planilla no tiene columna
   "Nombre" pero sí "Descripción" con nombres cortos, las 400 filas quedan con error "Falta
   nombre".
5. **Importador: con dos precios elige el mayorista.** Con "Precio mayorista" y "Precio
   retail", Nexo propone el mayorista como precio de venta en Mercado Libre.
   *Propuesta:* preferir retail / venta / público / PVP.
6. **Importador: no entiende encabezados informales.** "Lo compré a", "Lo vendo a" y "Cuántos
   tengo" no se detectan: el emprendedor queda sin costo, precio ni stock.
7. **La pantalla de revisión del importador no ayuda a corregir.**
   - Al cambiar una columna, los contadores y avisos por fila no se recalculan (siguen diciendo
     "Falta costo de compra").
   - Deja importar sin costo ni precio, sin advertir que así no se puede calcular nada.
   - Costo y precio se ven igual que campos opcionales como "Código de barras".
8. **El límite del plan corta la importación en silencio.** El retailer subió 1.100 filas y
   entraron 1.000. La respuesta no dice que fue por el límite del plan, el detalle muestra solo
   20 omitidas y el Dashboard muestra "1000/1000" sin explicar que quedaron 100 fuera.

## 2. Importantes

> **Estado:** corregidos el 15 de septiembre de 2026 (ver PROGRESS.md #31). En el 11 se agregó
> el contexto del margen objetivo; el redondeo a un precio "de vitrina" quedó pendiente.

9. **"Margen promedio (listos): 30 %" no es real:** es el margen objetivo. Los 6 listos de la
   pyme dejan entre 8,8 % y 20,5 %.
10. **"Alta oportunidad — buen margen"** incluye productos que pasan solo por la ganancia neta
    mínima ($), con 8,8 % o 10 % de margen.
11. **Precio recomendado sin redondear y sin contexto:** "$84.134" para un producto a $61.990,
    sin decir que sale del margen objetivo (30 %). En la API llega con decimales (84133.93).
12. **Texto desactualizado:** "Decisión preliminar — sin datos de competencia". La competencia
    ya no cambia la decisión.
13. **Sin Mercado Libre conectado, "Preparar publicación" muestra un error con "Reintentar"**
    en vez de un botón "Conectar Mercado Libre".
14. **Tres "márgenes" distintos para el mismo producto.** En Productos, "Margen" es venta −
    compra (ej. 44 %). El detalle dice "Calculado con tu costo y precio reales — sin asumir
    ninguna comisión que no hayas confirmado", pero usa la comisión de respaldo.
15. **El stock del Excel no sirve para Mercado Libre:** hay que reservar las unidades de nuevo
    ("Unidades para Mercado Libre: Sin definir").
16. **Reimportar una planilla sin SKU duplica los productos** (`catalog_writer` solo reconoce
    por SKU).
17. **Oportunidades dibuja todas las filas de una vez** (1.000 en el retailer), sin paginación,
    buscador ni filtro por categoría o marca.
18. **La categoría de Mercado Libre no se predice si la cuenta no está conectada**, aunque la
    predicción es pública.

## 3. Menores y textos

> **Estado:** corregidos el 15 de septiembre de 2026 (ver PROGRESS.md #32). El 19 ya se había
> corregido junto con los críticos.

19. Dashboard: "0/150 publicaciones · cerca del límite". El aviso es por los productos y quedó
    pegado a la línea de publicaciones.
20. Mi plan: en prueba gratuita dice "Próxima renovación" y muestra la fecha un día antes
    (28 sept en vez de 29). `new Date("2026-09-29")` se interpreta en UTC.
21. Textos técnicos para el cliente:
    - "Las credenciales ya están listas — falta autorizar la cuenta".
    - "Base de datos: Funcionando correctamente".
    - Google Sheets: "falta configurar las credenciales en el servidor".
22. Configuración con textos desactualizados:
    - "Sin margen objetivo cargado, esas pantallas van a mostrar 'faltan datos'".
    - "Necesita haber corrido 'Actualizar comisiones reales'".
23. Configuración: "Estas notificaciones son solo de demostración por ahora".
24. Mezcla de voseo ("elegís", "escribinos", "Hacé click") y tú ("Elige", "inicias").
25. Importación: un archivo completo queda "Para revisar" en todas sus filas solo por
    "Falta imagen" (pyme: 0 listas, 40 para revisar). Al emprendedor le aparece "Falta SKU" en
    cada fila.
26. Admin:
    - "Pendientes de configuración: 0" mientras 4 clientes no configuraron nada.
    - El detalle dice "Todavía no existe un registro de errores por cliente", pero ya existe el
      historial de sincronizaciones.
    - El gráfico sin ventas muestra "máx $1".
    - No marca al cliente que llegó al límite de su plan.
27. Detalle de producto: "Creado: —" aunque el producto tiene fecha.
28. Celular: sin scroll horizontal, pero las tarjetas del Dashboard van una por fila (scroll
    muy largo).

## 4. Lo que funcionó bien

- Detección de la fila de encabezados con título arriba y montos "$1.990".
- Encabezados en inglés (SKU / Title / Cost / Price / Qty).
- SKU duplicado detectado y omitido.
- Productos sin costo quedan en "revisar", nunca como rentables.
- "Ver como empresa" con confirmación, aviso persistente y salida limpia al panel.
- Eliminar cuenta: pide contraseña y ELIMINAR, valida en pantalla y avisa qué pasa con
  Mercado Libre y Mercado Pago.
- La decisión es consistente entre Oportunidades, `/decision` y `/decision-lote` en los 4
  perfiles.

## 5. Ideas por perfil

- **Pyme:** mostrar cuánto habría que subir el precio para que convenga, además del precio
  recomendado.
- **Importador:** soportar precio por volumen y costos por unidad bajos. Hoy el envío y los
  costos fijos por unidad dominan el resultado.
- **Retailer:** paginación, filtros y ordenar por ganancia. Un resumen de "capital inmovilizado
  en productos que no convienen" (stock × costo).
- **Emprendedor:** una calculadora rápida "si compro a $X y vendo a $Y, ¿gano?", sin tener que
  importar una planilla.
