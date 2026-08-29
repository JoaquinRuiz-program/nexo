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
    rows = [dict(row) for row in reader if any((v or "").strip() for v in row.values())]
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
        row = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}
        rows.append(row)
    return headers, rows
