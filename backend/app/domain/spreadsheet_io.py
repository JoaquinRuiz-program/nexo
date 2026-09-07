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

MENSAJE_ARCHIVO_GRANDE = (
    f"El archivo pesa más de {MAX_ARCHIVO_BYTES // (1024 * 1024)} MB. "
    "Dividilo en partes más chicas o quitá columnas/hojas que no uses."
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


def _read_xlsx(fileobj: BinaryIO) -> tuple[list[str], list[dict[str, Any]]]:
    workbook = openpyxl.load_workbook(fileobj, read_only=True, data_only=True)
    sheet = workbook.active
    rows_iter = sheet.iter_rows(values_only=True)
    try:
        raw_header = next(rows_iter)
    except StopIteration:
        raise ValueError("El archivo Excel está vacío.") from None

    headers = [str(h).strip() if h is not None else f"columna_{i + 1}" for i, h in enumerate(raw_header)]
    rows: list[dict[str, Any]] = []
    for values in rows_iter:
        if values is None or all(v is None or str(v).strip() == "" for v in values):
            continue
        # Se corta DURANTE la iteración (read_only=True es perezoso): así el
        # tope protege de verdad la memoria, en vez de comprobarlo cuando ya
        # se cargó todo.
        if len(rows) >= MAX_FILAS:
            raise ValueError(MENSAJE_DEMASIADAS_FILAS)
        row = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}
        rows.append(row)
    return headers, rows
