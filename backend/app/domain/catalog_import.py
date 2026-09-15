"""
Importador universal de catálogo — funciones puras (sin red, sin DB), igual
que analysis.py y profitability.py.

Puerto directo (a Python) de la lógica que ya existía y funcionaba en
`src/services/importService.ts` (el prototipo React) — no se reinventa el
enfoque, se generaliza: acá se agregan `costo` y `codigo_barras`, que el
prototipo original no tenía porque no existía todavía el concepto de
rentabilidad ni de catálogo universal.

Decisión central (24 de agosto de 2026): el sistema NO debe asumir que
todos los negocios usan las mismas columnas que el primer cliente piloto.
Este módulo
solo reconoce SINÓNIMOS de columna — nunca exige un nombre exacto. Un
Excel de ferretería, de ropa o "desordenado" (columnas con nombres
distintos, datos faltantes) tiene que poder mapearse igual que uno hecho a
medida para este sistema.

No se auto-detectan variantes (talla/color como filas del mismo producto
padre) en esta primera versión — cada fila del archivo se convierte en un
producto con exactamente una variante ("simple"). Es una limitación
conocida, no un olvido: agrupar variantes agrega una categoría entera de
decisiones (qué columna es "el mismo producto", qué combinación de
talla/color) que no se resuelve bien adivinando.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# Orden en el que se intenta detectar cada campo — SÍ afecta el resultado
# acá: "costo" va antes que "precio" a propósito, para que reclame headers
# como "Precio compra" antes de que el matching parcial de "precio" (que
# busca la palabra "precio" como substring) se los lleve por delante — ver
# el comentario en costo dentro de _FIELD_SYNONYMS.
IMPORT_FIELDS = ("sku", "nombre", "marca", "categoria", "costo", "precio", "stock", "descripcion", "imagen_url", "codigo_barras")

# Sinónimos habituales — tomados literalmente de los ejemplos que dio el
# dueño, más las variantes ya usadas en el prototipo React. Todos
# normalizados sin espacios/tildes (ver _normalize_header) para que
# "Precio venta" y "precioventa" comparen igual.
_FIELD_SYNONYMS: dict[str, list[str]] = {
    "sku": ["sku", "codigo", "codigoproducto", "code", "cod", "id"],
    "nombre": ["nombre", "producto", "descripcioncorta", "articulo", "titulo", "name"],
    "marca": ["marca", "fabricante", "brand"],
    "categoria": ["categoria", "category", "rubro", "tipo", "familia"],
    # "vendo"/"vende": planillas informales ("Lo vendo a") — revisión por perfil, 15/09/2026.
    "precio": ["precio", "preciodeventa", "precioventa", "valor", "price", "pvp", "venta", "vendo", "vende"],
    # "preciocompra"/"preciocosto" tienen que estar acá (no solo
    # "costo"/"costodecompra"): un header como "Precio compra" es costo, no
    # precio de venta, aunque empiece con la palabra "precio" — ver
    # IMPORT_FIELDS más abajo, que procesa "costo" antes que "precio" para
    # que estos sinónimos se reclamen primero y no se los coma el matching
    # parcial (substring) de "precio".
    # "compre"/"comprado" ("Lo compré a") y "tengo"/"cuantos" ("Cuántos tengo"):
    # encabezados informales de un revendedor — revisión por perfil, 15/09/2026.
    "costo": ["costo", "costodecompra", "preciocosto", "preciocompra", "preciodecompra", "cost", "costocompra", "compra", "compre", "comprado"],
    "stock": ["stock", "cantidad", "existencia", "existencias", "qty", "unidades", "inventario", "disponible", "tengo", "cuantos"],
    "descripcion": ["descripcion", "description", "detalle", "observacion"],
    "imagen_url": ["imagen", "image", "foto", "picture", "imagenurl", "urlimagen"],
    "codigo_barras": ["codigodebarras", "codigobarras", "ean", "upc", "gtin", "barcode"],
}


def _contradice_intencion(field_name: str, header_normalizado: str) -> bool:
    """14 de septiembre de 2026 — caso real ("Precio de Compra" + "Precio de
    Venta Recomendado"): la coincidencia parcial de "precio" tomaba el precio
    de COMPRA como precio de venta. Un encabezado que habla de compra/costo
    nunca es el precio de venta, y uno que habla de venta nunca es el costo."""
    if field_name == "precio":
        return "compra" in header_normalizado or "costo" in header_normalizado
    if field_name == "costo":
        return "venta" in header_normalizado
    return False


def _normalize_header(header: str) -> str:
    text = header.strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")  # quita tildes
    return re.sub(r"[^a-z0-9]", "", text)


@dataclass
class ColumnMapping:
    """Qué columna del archivo corresponde a cada campo — `None` si no se
    detectó ninguna. El usuario puede corregir esto antes de confirmar."""

    mapping: dict[str, str | None] = field(default_factory=dict)

    def get(self, field_name: str) -> str | None:
        return self.mapping.get(field_name)


def detect_columns(headers: list[str], rows: list[dict[str, Any]] | None = None) -> ColumnMapping:
    """Propone, para cada campo conocido, cuál columna del archivo lo
    representa — sin exigir que el nombre coincida exactamente.

    Cuando un archivo trae dos columnas que podrían servir (ej. "Código" Y
    "SKU" en la misma planilla — un caso real de prueba, no hipotético),
    gana la que matchea el sinónimo más específico: se prueba cada sinónimo
    en orden ("sku" antes que "codigo") buscando una coincidencia EXACTA en
    todos los encabezados antes de pasar al siguiente sinónimo, y solo si
    ninguno matcheó exacto se prueba coincidencia parcial (substring) con el
    mismo orden de prioridad.

    13 de septiembre de 2026 — segunda pasada por CONTENIDO. Si se pasan las
    filas (`rows`), para cada campo que el nombre no logró mapear se mira qué
    tipo de dato tiene cada columna todavía libre (URLs -> imagen, códigos de
    12-14 dígitos -> código de barras, números tipo precio -> precio/costo,
    etc.). Así un Excel con encabezados crípticos ("Col1, Col2...") o sin
    encabezado útil igual se mapea solo. Nunca pisa un match por nombre: el
    nombre siempre gana, el contenido solo completa lo que faltó."""
    normalized = [(h, _normalize_header(h)) for h in headers]
    used: set[str] = set()
    result: dict[str, str | None] = {}

    for field_name in IMPORT_FIELDS:
        synonyms = _FIELD_SYNONYMS[field_name]
        match = None
        for syn in synonyms:
            match = next((h for h, norm in normalized if h not in used and norm == syn), None)
            if match:
                break
        if not match:
            for syn in synonyms:
                candidatos = [
                    h for h, norm in normalized if h not in used and syn in norm and not _contradice_intencion(field_name, norm)
                ]
                if candidatos:
                    match = _preferir_candidato(field_name, candidatos)
                    break
        result[field_name] = match
        if match:
            used.add(match)

    if rows:
        _detectar_por_contenido(headers, rows, result, used)
        _nombre_desde_descripcion(rows, result)

    return ColumnMapping(mapping=result)


# Precio de venta en Mercado Libre: con dos columnas de precio (caso real de
# un importador: "Precio mayorista" y "Precio retail"), la de venta al público
# gana y la mayorista queda al final — revisión por perfil, 15/09/2026.
_PRECIO_PREFERIDO = ("venta", "retail", "publico", "pvp", "final", "detalle", "vendo")
_PRECIO_POSTERGADO = ("mayor", "distribuidor")


def _preferir_candidato(field_name: str, candidatos: list[str]) -> str:
    if field_name != "precio" or len(candidatos) == 1:
        return candidatos[0]

    def rango(header: str) -> int:
        norm = _normalize_header(header)
        if any(p in norm for p in _PRECIO_PREFERIDO):
            return 0
        if any(p in norm for p in _PRECIO_POSTERGADO):
            return 2
        return 1

    return min(candidatos, key=rango)  # a igual rango, el primero del archivo


def _nombre_desde_descripcion(rows: list[dict[str, Any]], result: dict[str, str | None]) -> None:
    """Sin columna de nombre, una "Descripción" con textos cortos ES el nombre
    del producto (caso real: la lista de precios de un importador). Un texto
    largo sigue siendo descripción. Revisión por perfil, 15/09/2026."""
    header = result.get("descripcion")
    if result.get("nombre") is not None or header is None:
        return
    valores = _muestras(rows, header)
    if valores and sum(len(v) for v in valores) / len(valores) <= 80:
        result["nombre"] = header
        result["descripcion"] = None


# ------------------------------------------------------------------
# Detección por contenido (fallback) — 13 de septiembre de 2026.
# ------------------------------------------------------------------

_RE_URL = re.compile(r"^https?://", re.IGNORECASE)
_RE_SOLO_DIGITOS = re.compile(r"^\d+$")


def _muestras(rows: list[dict[str, Any]], header: str, limite: int = 30) -> list[str]:
    """Hasta `limite` valores NO vacíos de una columna, como texto."""
    vals: list[str] = []
    for row in rows:
        v = row.get(header)
        if v is None:
            continue
        t = str(v).strip()
        if t:
            vals.append(t)
        if len(vals) >= limite:
            break
    return vals


def _proporcion(vals: list[str], predicado) -> float:  # noqa: ANN001
    if not vals:
        return 0.0
    return sum(1 for v in vals if predicado(v)) / len(vals)


def _parece_url(v: str) -> bool:
    return bool(_RE_URL.match(v))


def _parece_codigo_barras(v: str) -> bool:
    return bool(_RE_SOLO_DIGITOS.match(v)) and 8 <= len(v) <= 14


def _parece_numero(v: str) -> bool:
    return _to_number(v) is not None


def _valor_numerico(vals: list[str]) -> list[float]:
    nums = [_to_number(v) for v in vals]
    return [n for n in nums if n is not None]


def _detectar_por_contenido(
    headers: list[str],
    rows: list[dict[str, Any]],
    result: dict[str, str | None],
    used: set[str],
) -> None:
    """Completa por CONTENIDO solo los campos donde el dato es inequívoco:
    imagen (URLs), código de barras (8-14 dígitos) y nombre (la columna de
    texto más descriptiva). Modifica `result` y `used` in place.

    Precio, costo y stock NO se adivinan por contenido a propósito: son
    todos columnas de números y confundir cuál es cuál corrompería el
    catálogo entero (importar la columna de stock como precio, por ejemplo).
    Si el nombre de la columna no los identificó, quedan sin mapear y se
    completan a mano en la revisión — "si una no está, se pregunta"."""
    libres = [h for h in headers if h not in used]
    muestras = {h: _muestras(rows, h) for h in libres}

    def reclamar(campo: str, header: str) -> None:
        result[campo] = header
        used.add(header)
        libres.remove(header)

    # Imagen: la mayoría de los valores son URLs.
    if result.get("imagen_url") is None:
        cand = [h for h in libres if _proporcion(muestras[h], _parece_url) >= 0.6]
        if cand:
            reclamar("imagen_url", cand[0])

    # Código de barras: la mayoría son códigos de 8 a 14 dígitos.
    if result.get("codigo_barras") is None:
        cand = [h for h in libres if _proporcion(muestras[h], _parece_codigo_barras) >= 0.6]
        if cand:
            reclamar("codigo_barras", cand[0])

    # Nombre: la columna de texto más larga en promedio. "Texto" = tiene
    # letras (no basta con "no ser número": "Cuaderno 100 hojas" tiene un
    # número adentro pero es claramente un nombre). Un mínimo de largo
    # promedio evita tomar una columna de códigos cortos como si fuera el
    # nombre del producto.
    if result.get("nombre") is None:
        texto = [h for h in libres if muestras[h] and _proporcion(muestras[h], _tiene_letras) >= 0.6]
        texto.sort(key=lambda h: sum(len(v) for v in muestras[h]) / max(1, len(muestras[h])), reverse=True)
        if texto and (sum(len(v) for v in muestras[texto[0]]) / max(1, len(muestras[texto[0]]))) >= 6:
            reclamar("nombre", texto[0])


def _tiene_letras(v: str) -> bool:
    return bool(re.search(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ]", v))


def _sin_separador_de_miles(cuerpo: str, separador: str) -> str:
    """Resuelve un número que usa UN solo símbolo ambiguo (o solo puntos, o
    solo comas): decide si es separador de miles o decimal.

    Es separador de miles solo si el número entero calza exactamente con el
    patrón "1 a 3 dígitos + grupos de exactamente 3" ("3.990", "1.234.567").
    Cualquier otra cosa ("3.14", "3990.50", "0,5") es un decimal."""
    grupos_de_miles = r"\d{1,3}(?:" + re.escape(separador) + r"\d{3})+"
    if re.fullmatch(grupos_de_miles, cuerpo):
        return cuerpo.replace(separador, "")
    return cuerpo.replace(separador, ".")


def _to_number(raw: str) -> float | None:
    """Acepta "3990", "3.990", "3990.50", "3.990,50" (chileno) y "3,990.50"
    (inglés). None si la celda está vacía; None también si no se puede
    parsear (se distingue de "vacío" en el caller).

    13 de septiembre de 2026 — corregido un bug real, encontrado al importar
    un catálogo de prueba con los precios exportados como TEXTO en formato
    chileno: antes se intentaba `float(cleaned)` primero, y `float("3.990")`
    NO falla — devuelve 3.9. Resultado: un catálogo entero importado con los
    precios mil veces más bajos, en silencio y sin marcar ninguna fila como
    error (el margen quedaba absurdo y Oportunidades recomendaba publicar a
    pérdida). Ahora el separador se decide por la forma del número, nunca
    dejando que `float()` resuelva la ambigüedad por su cuenta."""
    text = raw.strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.,\-]", "", text)
    if not cleaned:
        return None

    negativo = cleaned.startswith("-")
    cuerpo = cleaned.lstrip("-")

    tiene_coma = "," in cuerpo
    tiene_punto = "." in cuerpo
    if tiene_coma and tiene_punto:
        # Con los dos símbolos presentes no hay ambigüedad: el decimal es el
        # que aparece ÚLTIMO ("3.990,50" chileno vs "3,990.50" inglés), y el
        # otro es el separador de miles.
        if cuerpo.rfind(",") > cuerpo.rfind("."):
            cuerpo = cuerpo.replace(".", "").replace(",", ".")
        else:
            cuerpo = cuerpo.replace(",", "")
    elif tiene_coma:
        cuerpo = _sin_separador_de_miles(cuerpo, ",")
    elif tiene_punto:
        cuerpo = _sin_separador_de_miles(cuerpo, ".")

    try:
        valor = float(cuerpo)
    except ValueError:
        return None
    return -valor if negativo else valor


@dataclass
class RowResult:
    row_index: int
    sku: str | None
    nombre: str
    marca: str | None
    categoria: str | None
    precio: float | None
    costo: float | None
    stock: int | None
    descripcion: str | None
    imagen_url: str | None
    codigo_barras: str | None
    estado: str  # valido | revision | error
    problemas: list[str]
    duplicado: bool


def build_rows(raw_rows: list[dict[str, Any]], mapping: ColumnMapping) -> list[RowResult]:
    """Aplica el mapeo de columnas a cada fila cruda del archivo, valida, y
    detecta duplicados (por SKU y por nombre) dentro del propio archivo —
    todavía no compara contra lo que ya existe en la base de datos, eso lo
    hace el endpoint al confirmar la importación."""

    def get_raw(row: dict[str, Any], field_name: str) -> str:
        header = mapping.get(field_name)
        if not header:
            return ""
        value = row.get(header, "")
        return "" if value is None else str(value).strip()

    results: list[RowResult] = []
    seen_sku: dict[str, list[int]] = {}
    seen_nombre: dict[str, list[int]] = {}

    for index, row in enumerate(raw_rows):
        sku = get_raw(row, "sku") or None
        nombre = get_raw(row, "nombre")
        marca = get_raw(row, "marca") or None
        categoria = get_raw(row, "categoria") or None
        precio_raw = get_raw(row, "precio")
        costo_raw = get_raw(row, "costo")
        stock_raw = get_raw(row, "stock")
        descripcion = get_raw(row, "descripcion") or None
        imagen_url = get_raw(row, "imagen_url") or None
        codigo_barras = get_raw(row, "codigo_barras") or None

        precio_valido = True
        costo_valido = True

        precio = None
        if precio_raw:
            precio = _to_number(precio_raw)
            precio_valido = precio is not None

        costo = None
        if costo_raw:
            costo = _to_number(costo_raw)
            costo_valido = costo is not None

        # 13 de septiembre de 2026 — el stock NUNCA bloquea la importación.
        # Un valor no numérico se ignora (se trata como "sin stock") en vez
        # de marcar la fila como error: la mayoría de los Excel no traen
        # stock, y si lo traen mal no es motivo para no importar el producto.
        # El stock se completa/pregunta a mano en la revisión.
        stock: int | None = None
        if stock_raw:
            stock_num = _to_number(stock_raw)
            if stock_num is not None:
                stock = int(stock_num)

        problemas: list[str] = []
        if not nombre:
            problemas.append("Falta nombre")
        if not precio_valido:
            problemas.append(f"Precio no válido ({precio_raw!r})")
        if not costo_valido:
            problemas.append(f"Costo no válido ({costo_raw!r})")
        if not sku:
            problemas.append("Falta SKU")
        if not imagen_url:
            problemas.append("Falta imagen")
        if not costo_raw:
            problemas.append("Falta costo de compra")
        if not precio_raw:
            problemas.append("Falta precio de venta")
        if stock is None:
            problemas.append("Completá el stock al revisar")
        # 13 de septiembre de 2026 — categoría y descripción YA NO se marcan
        # como problema: Nexo las resuelve solo más adelante (la categoría la
        # predice Mercado Libre a partir del nombre, ver
        # adapters/mercadolibre.py::predict_category; la descripción la arma
        # domain/ai_content.py con los datos que sí existen). Un Excel normal
        # —código, nombre, costo, precio— no trae ninguna de las dos, y
        # marcarlas hacía que un archivo perfectamente válido se viera lleno
        # de advertencias. Acá solo queda lo que de verdad necesita que una
        # persona haga algo.

        if sku:
            seen_sku.setdefault(sku.lower(), []).append(index)
        if nombre:
            seen_nombre.setdefault(nombre.lower(), []).append(index)

        # Bloqueante = no se puede crear el producto sin arreglar la fila a
        # mano. Faltar SKU/categoría/descripción/imagen/costo es "revisar
        # después", no "no se puede importar" — coherente con que el modelo
        # de datos ya acepta productos sin SKU (WooCommerce real los trae así).
        # El stock quedó fuera de "bloqueante" a propósito (13 de septiembre
        # de 2026): sin stock el producto se importa igual y se completa al
        # revisar. Solo bloquea lo que de verdad impide crear el producto:
        # sin nombre, o un precio/costo escrito que no es un número.
        bloqueante = not nombre or not precio_valido or not costo_valido

        results.append(
            RowResult(
                row_index=index,
                sku=sku,
                nombre=nombre,
                marca=marca,
                categoria=categoria,
                precio=precio,
                costo=costo,
                stock=stock,
                descripcion=descripcion,
                imagen_url=imagen_url,
                codigo_barras=codigo_barras,
                estado="error" if bloqueante else ("revision" if problemas else "valido"),
                problemas=problemas,
                duplicado=False,
            )
        )

    for indices in seen_sku.values():
        if len(indices) > 1:
            for i in indices:
                results[i].duplicado = True
                results[i].problemas.append("SKU duplicado en el archivo")
                results[i].estado = "error"

    for indices in seen_nombre.values():
        if len(indices) > 1:
            for i in indices:
                if not results[i].duplicado:
                    results[i].duplicado = True
                    results[i].problemas.append("Nombre duplicado en el archivo")
                    if results[i].estado != "error":
                        results[i].estado = "revision"

    return results


def summarize_rows(rows: list[RowResult]) -> dict[str, int]:
    return {
        "totalFilas": len(rows),
        "validos": sum(1 for r in rows if r.estado == "valido"),
        "revision": sum(1 for r in rows if r.estado == "revision"),
        "errores": sum(1 for r in rows if r.estado == "error"),
    }


def row_to_dict(r: RowResult) -> dict:
    """Forma JSON de una fila validada — la misma para cualquier origen
    (Excel/CSV subido, Google Sheets), factorizado el 5 de septiembre de
    2026 al agregar el segundo origen para no duplicar este mapeo entre
    app/api/routes/catalogo.py y app/api/routes/google_sheets.py."""
    return {
        "fila": r.row_index,
        "sku": r.sku,
        "nombre": r.nombre,
        "marca": r.marca,
        "categoria": r.categoria,
        "precio": r.precio,
        "costo": r.costo,
        "stock": r.stock,
        "descripcion": r.descripcion,
        "imagenUrl": r.imagen_url,
        "codigoBarras": r.codigo_barras,
        "estado": r.estado,
        "problemas": r.problemas,
        "duplicado": r.duplicado,
    }
