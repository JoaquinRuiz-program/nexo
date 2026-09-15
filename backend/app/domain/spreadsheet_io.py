"""
Lector genérico de planillas (.xlsx / .csv) — devuelve TODAS las columnas
del archivo, sin asumir cuáles existen. Lo usa el importador universal de
catálogo (app/domain/catalog_import.py) para poder detectar columnas con
cualquier nombre.

Nota: app/db/import_costs.py tiene su propio lector, más simple (solo
extrae "sku"/"costo", dos columnas fijas) — no se unificó con este módulo a
propósito, para no arriesgar el código ya probado de esa importación
mientras se construye esta nueva. Es una duplicación pequeña y conocida,
no un descuido.
"""

from __future__ import annotations

import csv
import io
from itertools import chain
from pathlib import Path
from typing import Any, BinaryIO

import openpyxl


class UnsupportedSpreadsheetFormat(ValueError):
    pass


# 6 de septiembre de 2026 — auditoría pre-producción (P1-2). Hasta hoy la
# importación leía el archivo entero en memoria sin ningún tope: un .xlsx
# grande (o uno chico que descomprime a varios GB, openpyxl descomprime al
# abrir) podía agotar la memoria del proceso. Con un solo worker en
# producción (ver backend/DEPLOY.md), tumbar el proceso deja sin servicio a
# TODAS las empresas, no solo a la que subió el archivo.
#
# Los dos topes son deliberadamente generosos para un catálogo de PyME
# (referencia real: el catálogo del cliente piloto tiene ~60 productos) y
# deliberadamente finitos: nunca "sin límite".
MAX_ARCHIVO_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_FILAS = 20_000

# Cuántas filas del principio se miran, como mucho, buscando la fila de
# encabezados. Muchas planillas de PyME arrancan con un título y una o dos
# líneas de instrucciones (celdas combinadas, una sola columna) antes de la
# tabla real — el caso del archivo "Calculadora de precios" del piloto, donde
# los encabezados verdaderos están recién en la fila 4. El tope evita recorrer
# una hoja enorme si por lo que sea nunca aparece una fila con pinta de tabla.
MAX_FILAS_PREVIA_ENCABEZADO = 25

MENSAJE_ARCHIVO_GRANDE = (
    f"El archivo pesa más de {MAX_ARCHIVO_BYTES // (1024 * 1024)} MB. "
    "Divídelo en partes más chicas o quita columnas/hojas que no uses."
)
MENSAJE_DEMASIADAS_FILAS = (
    f"El archivo tiene más de {MAX_FILAS:,} filas. Importalo por partes.".replace(",", ".")
)


def validar_tamano(contenido: bytes) -> None:
    """Tope de tamaño del archivo subido — se comprueba SIEMPRE en el
    servidor (nunca solo en el navegador, que cualquiera puede saltear)."""
    if len(contenido) > MAX_ARCHIVO_BYTES:
        raise ValueError(MENSAJE_ARCHIVO_GRANDE)


def read_rows(fileobj: BinaryIO, filename: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Devuelve (encabezados originales, filas). Cada fila es un dict
    {encabezado_original: valor}, tal cual viene en el archivo — sin
    filtrar ni renombrar ninguna columna. Filas completamente vacías se
    descartan (no son un dato faltante, son el final de la hoja)."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return _read_csv(fileobj)
    if suffix in (".xlsx", ".xlsm"):
        return _read_xlsx(fileobj)
    raise UnsupportedSpreadsheetFormat(f"Formato no soportado ({suffix or 'sin extensión'}). Usa .csv o .xlsx.")


def _read_csv(fileobj: BinaryIO) -> tuple[list[str], list[dict[str, Any]]]:
    raw = fileobj.read()
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("El archivo CSV no tiene encabezado.")
    headers = list(reader.fieldnames)
    rows: list[dict[str, Any]] = []
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        if len(rows) >= MAX_FILAS:
            raise ValueError(MENSAJE_DEMASIADAS_FILAS)
        rows.append(dict(row))
    return headers, rows


def _cuenta_celdas_con_texto(fila: tuple[Any, ...] | None) -> int:
    if fila is None:
        return 0
    return sum(1 for v in fila if v is not None and str(v).strip() != "")


def _read_xlsx(fileobj: BinaryIO) -> tuple[list[str], list[dict[str, Any]]]:
    workbook = openpyxl.load_workbook(fileobj, read_only=True, data_only=True)
    sheet = workbook.active
    rows_iter = sheet.iter_rows(values_only=True)

    # La fila de encabezados no es necesariamente la primera: se buffea una
    # ventana chica del principio y se toma como encabezado la primera fila con
    # 2 o más celdas con texto (una tabla real). Las filas de arriba (título,
    # instrucciones, en blanco) tienen una sola celda o ninguna y se saltan.
    # Se buffea sólo la ventana para no romper la lectura perezosa (read_only)
    # que protege la memoria con archivos grandes.
    ventana: list[tuple[Any, ...]] = []
    idx_header: int | None = None
    for fila in rows_iter:
        ventana.append(fila)
        if _cuenta_celdas_con_texto(fila) >= 2:
            idx_header = len(ventana) - 1
            break
        if len(ventana) >= MAX_FILAS_PREVIA_ENCABEZADO:
            break

    # Si ninguna fila de la ventana tenía 2+ celdas (catálogo de una sola
    # columna, poco habitual), cae en la primera fila con algo escrito.
    if idx_header is None:
        idx_header = next((i for i, f in enumerate(ventana) if _cuenta_celdas_con_texto(f) >= 1), None)
    if idx_header is None:
        raise ValueError("El archivo Excel está vacío.")

    raw_header = ventana[idx_header]
    headers = [str(h).strip() if h is not None else f"columna_{i + 1}" for i, h in enumerate(raw_header)]
    rows: list[dict[str, Any]] = []
    despues_de_fila_en_blanco = False
    # Las filas que ya se leyeron después del encabezado se procesan primero, y
    # después se sigue con el iterador perezoso desde donde quedó.
    for values in chain(ventana[idx_header + 1 :], rows_iter):
        if values is None or all(v is None or str(v).strip() == "" for v in values):
            # Las filas en blanco se saltan. 15 de septiembre de 2026 (QA
            # integral): antes la primera fila en blanco después de la tabla
            # cortaba la lectura, y un catálogo con una fila vacía en el medio
            # perdía en silencio todos los productos de abajo.
            if rows:
                despues_de_fila_en_blanco = True
            continue
        if despues_de_fila_en_blanco and _cuenta_celdas_con_texto(values) < 2:
            # Después de una fila en blanco, una fila con una sola celda escrita
            # es una nota al pie (como en la "Calculadora de precios" del
            # piloto), no un producto.
            continue
        # Se corta DURANTE la iteración (read_only=True es perezoso): así el
        # tope protege de verdad la memoria, en vez de comprobarlo cuando ya
        # se cargó todo.
        if len(rows) >= MAX_FILAS:
            raise ValueError(MENSAJE_DEMASIADAS_FILAS)
        row = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}
        rows.append(row)
    return headers, rows
