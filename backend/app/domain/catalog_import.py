"""
Importador universal de catálogo — funciones puras (sin red, sin DB), igual
que analysis.py y profitability.py.

Puerto directo (a Python) de la lógica que ya existía y funcionaba en
`src/services/importService.ts` (el prototipo React) — no se reinventa el
enfoque, se generaliza: acá se agregan `costo` y `codigo_barras`, que el
prototipo original no tenía porque no existía todavía el concepto de
rentabilidad ni de catálogo universal.

Decisión central (24 de agosto de 2026): el sistema NO debe asumir que
todos los negocios usan las mismas columnas que la librería. Este módulo
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
    "precio": ["precio", "preciodeventa", "valor", "price", "pvp"],
    # "preciocompra"/"preciocosto" tienen que estar acá (no solo
    # "costo"/"costodecompra"): un header como "Precio compra" es costo, no
    # precio de venta, aunque empiece con la palabra "precio" — ver
    # IMPORT_FIELDS más abajo, que procesa "costo" antes que "precio" para
    # que estos sinónimos se reclamen primero y no se los coma el matching
    # parcial (substring) de "precio".
    "costo": ["costo", "costodecompra", "preciocosto", "preciocompra", "cost", "costocompra"],
    "stock": ["stock", "cantidad", "existencia", "existencias", "qty", "unidades"],
    "descripcion": ["descripcion", "description", "detalle", "observacion"],
    "imagen_url": ["imagen", "image", "foto", "picture", "imagenurl", "urlimagen"],
    "codigo_barras": ["codigodebarras", "codigobarras", "ean", "upc", "gtin", "barcode"],
}


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


def detect_columns(headers: list[str]) -> ColumnMapping:
    """Propone, para cada campo conocido, cuál columna del archivo lo
    representa — sin exigir que el nombre coincida exactamente.

    Cuando un archivo trae dos columnas que podrían servir (ej. "Código" Y
    "SKU" en la misma planilla — un caso real de prueba, no hipotético),
    gana la que matchea el sinónimo más específico: se prueba cada sinónimo
    en orden ("sku" antes que "codigo") buscando una coincidencia EXACTA en
    todos los encabezados antes de pasar al siguiente sinónimo, y solo si
    ninguno matcheó exacto se prueba coincidencia parcial (substring) con el
    mismo orden de prioridad."""
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
                match = next((h for h, norm in normalized if h not in used and syn in norm), None)
                if match:
                    break
        result[field_name] = match
        if match:
            used.add(match)

    return ColumnMapping(mapping=result)


def _to_number(raw: str) -> float | None:
    """Acepta "3990", "3.990", "3990.50" o formato chileno "3.990,50". None
    si la celda está vacía; NaN-como-None si no se puede parsear (se
    distingue de "vacío" en el caller)."""
    text = raw.strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.,\-]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        pass
    try:
        return float(cleaned.replace(".", "").replace(",", "."))
    except ValueError:
        return None


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
        stock_valido = True

        precio = None
        if precio_raw:
            precio = _to_number(precio_raw)
            precio_valido = precio is not None

        costo = None
        if costo_raw:
            costo = _to_number(costo_raw)
            costo_valido = costo is not None

        stock: int | None = None
        if stock_raw:
            stock_num = _to_number(stock_raw)
            stock_valido = stock_num is not None
            if stock_num is not None:
                stock = int(stock_num)

        problemas: list[str] = []
        if not nombre:
            problemas.append("Falta nombre")
        if not precio_valido:
            problemas.append(f"Precio no válido ({precio_raw!r})")
        if not costo_valido:
            problemas.append(f"Costo no válido ({costo_raw!r})")
        if not stock_valido:
            problemas.append(f"Stock no válido ({stock_raw!r})")
        if not sku:
            problemas.append("Falta SKU")
        if not categoria:
            problemas.append("Falta categoría")
        if not descripcion:
            problemas.append("Falta descripción")
        if not imagen_url:
            problemas.append("Falta imagen")
        if not costo_raw:
            problemas.append("Falta costo de compra")
        if not precio_raw:
            problemas.append("Falta precio de venta")

        if sku:
            seen_sku.setdefault(sku.lower(), []).append(index)
        if nombre:
            seen_nombre.setdefault(nombre.lower(), []).append(index)

        # Bloqueante = no se puede crear el producto sin arreglar la fila a
        # mano. Faltar SKU/categoría/descripción/imagen/costo es "revisar
        # después", no "no se puede importar" — coherente con que el modelo
        # de datos ya acepta productos sin SKU (WooCommerce real los trae así).
        bloqueante = not nombre or not precio_valido or not costo_valido or not stock_valido

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
