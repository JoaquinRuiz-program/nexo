# Nexo — datos de prueba (`Nexo_Datos_Prueba.xlsx`)

Dataset de prueba **funcional**, no automatizado: sirve para simular a un
cliente real llegando con su catálogo y probar el flujo completo a mano
(Excel → Importar → Nexo → preparación → decisión → imágenes → publicación
→ gestión de publicación). **No reemplaza** los tests automatizados de
`backend/tests/` — ambos se mantienen, con propósitos distintos.

Nunca contiene datos de una empresa real, nombres de clientes reales ni
información personal — es 100% ficticio, pensado para parecer un catálogo
real de una PyME con productos de varios rubros.

## Columnas

Son **exactamente** las que reconoce el importador real de Nexo (ver
`backend/app/domain/catalog_import.py::IMPORT_FIELDS`) — ninguna columna
fue inventada:

| Columna del Excel | Campo interno | Obligatoria |
|---|---|---|
| SKU | `sku` | No (pero recomendada — sin ella no se puede reimportar/actualizar) |
| Nombre | `nombre` | Sí |
| Marca | `marca` | No |
| Categoría | `categoria` | No |
| Costo | `costo` | No |
| Precio | `precio` | No (pero sin precio no se puede publicar) |
| Stock | `stock` | No |
| Descripción | `descripcion` | No |
| Imagen URL | `imagen_url` | No |
| Código de Barras | `codigo_barras` | No |

El importador detecta estas columnas por nombre o sinónimo (no hace falta
que el encabezado sea exacto) — ver `_FIELD_SYNONYMS` en el mismo archivo.

## Contenido: 24 productos, 6 rubros

Tecnología, Hogar, Deporte, Vestuario, Accesorios, Herramientas — SKUs con
prefijo por rubro (`TEC-`, `HOG-`, `DEP-`, `VES-`, `ACC-`, `HER-`) para que
cada fila sea fácil de identificar. No todos estos productos necesariamente
terminan siendo publicables en Mercado Libre — ese es justo el punto: probar
cómo se comporta Nexo con un catálogo variado, no un catálogo perfecto.

## Escenarios cubiertos (y qué esperar al importar)

Al confirmar la importación de este archivo (con `omitir_errores` activado,
el comportamiento por defecto del asistente), el resultado esperado es:

- **18 productos válidos** — se crean sin problema.
- **2 en "revisión"** (`TEC-004`, `DEP-004`) — **sin imagen cargada**: la
  importación los crea igual (falta de imagen nunca bloquea importar), pero
  no van a poder publicarse en Mercado Libre hasta que se les agregue una
  imagen (por URL o subiéndola desde el computador).
- **4 omitidos como error**:
  - `TEC-005` — **precio inválido** (texto "consultar" en vez de un número).
  - `HOG-003` — **datos incompletos** (falta el nombre, campo obligatorio).
  - `ACC-002` (las dos filas) — **SKU duplicado dentro del mismo archivo**
    (a propósito, para probar la regla de duplicados). Ninguna de las dos
    se crea en esa pasada — es el comportamiento correcto: Nexo no puede
    adivinar cuál de las dos versiones es la buena.
- `HOG-004` tiene un **precio negativo** — se importa (el importador no
  valida rango de precio al importar), pero el motor de rentabilidad y el
  gate de publicación en Mercado Libre lo van a marcar como no publicable.
- `HER-004` tiene **stock 0** — útil para probar el indicador de "sin
  stock" en el listado de productos.

### Para probar "reimportar el mismo SKU actualiza, no duplica"

Ese comportamiento (`test_reimportar_el_mismo_sku_actualiza_en_vez_de_duplicar`,
ya cubierto por tests automatizados) se prueba a mano así: importar este
archivo una vez, editar el precio de cualquier fila (ej. `TEC-001`) en una
copia del Excel, y volver a importar esa copia — el producto existente se
actualiza, nunca se duplica.

### Para probar "múltiples imágenes"

El importador de Excel solo acepta **una** URL de imagen por fila (columna
`Imagen URL`) — no existe (ni se inventó) una columna de "varias imágenes".
Para probar el caso de un producto con múltiples imágenes: importar el
archivo y, en la ficha de cualquier producto ya creado, agregar imágenes
adicionales con el subidor real (arrastrar y soltar o elegir archivos desde
el computador) o pegando más URLs — ver sección "Imágenes" del panel de
producto.

### Atributos de Mercado Libre

Los atributos que pide Mercado Libre (talla, color, modelo, etc.) no son
parte del importador de catálogo — se completan en el asistente de
publicación, categoría por categoría. Este dataset incluye productos de
rubros con atributos típicamente distintos (ej. Vestuario suele pedir
talla/color; Tecnología suele pedir marca/modelo) para poder probar esa
variedad al momento de publicar, no al importar.

## Regenerar el archivo

El Excel se genera con un script (nunca se edita el `.xlsx` a mano, para
que quede siempre reproducible y en control de versiones como texto):

```bash
backend/.venv/Scripts/python scripts/generar_excel_datos_prueba.py
```

Editar `scripts/generar_excel_datos_prueba.py` y volver a correrlo para
agregar/cambiar productos.
