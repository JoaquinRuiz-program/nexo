"""
Importa costos de compra (SKU, costo) desde el archivo del dueño — acepta
tanto `.xlsx` como `.csv` directamente: el dueño tiene su información en
Excel, no tiene sentido pedirle que la convierta a mano.

Formato esperado (mismo para ambos formatos): una hoja/archivo con
encabezado y dos columnas, "sku" y "costo" (no sensible a mayúsculas):

    sku,costo                    | sku       | costo  |
    LIB-001,8500                 | LIB-001   | 8500   |
    CUA-001-AZU,1200             | CUA-001... | 1200   |

No inventa nada:
- Un SKU del archivo que no existe en el catálogo se reporta como no
  encontrado — nunca crea un producto nuevo (eso es tarea de la
  sincronización con WooCommerce, no de este import).
- Una fila con costo vacío o no numérico se reporta como inválida y no se
  aplica — no se guarda un $0 que no es un dato real.

Uso por línea de comandos:
    cd backend
    python -m app.db.import_costs ruta/al/archivo.xlsx
    python -m app.db.import_costs ruta/al/archivo.csv

También se usa desde POST /api/costos/importar (app/api/routes/costos.py)
para que el dueño pueda subir el archivo directamente en el panel, sin
tocar una terminal.

29 de agosto de 2026 — `store_id` es obligatorio: antes buscaba el SKU en
TODA la base sin filtrar por tienda (podía actualizar el costo de un
producto de otra empresa si compartía el mismo SKU como texto). Desde la
línea de comandos (sin sesión de usuario) hay que pasarlo explícito — ver
el bloque `__main__` más abajo.
"""

from __future__ import annotations

import csv
import io
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

import openpyxl
from sqlalchemy.orm import Session

from app.db.models import ProductVariant, Store
from app.db.session import SessionLocal

SKU_COLUMN_ALIASES = {"sku"}
COST_COLUMN_ALIASES = {"costo", "cost", "precio_costo", "cost_price"}


@dataclass
class ImportResult:
    actualizados: list[str] = field(default_factory=list)
    no_encontrados: list[str] = field(default_factory=list)
    filas_invalidas: list[str] = field(default_factory=list)


def _find_column(fieldnames: list[str], aliases: set[str]) -> str | None:
    for name in fieldnames:
        if name.strip().lower() in aliases:
            return name
    return None


def _parse_cost(raw: Any) -> float:
    """Acepta un número ya parseado (viene así de .xlsx), "8500", "8500.50"
    o formato chileno "8.500,50" (viene así de un .csv exportado a mano)."""
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    try:
        return float(text)
    except ValueError:
        pass
    return float(text.replace(".", "").replace(",", "."))


def _sku_to_str(raw: Any) -> str:
    """Excel a veces guarda un SKU numérico como float (12345 -> 12345.0);
    se normaliza para que no deje de matchear contra el SKU real (texto)."""
    if isinstance(raw, float) and raw.is_integer():
        return str(int(raw))
    return str(raw).strip()


def _read_rows_csv(fileobj: BinaryIO) -> list[dict[str, Any]]:
    raw = fileobj.read()
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("El CSV no tiene encabezado.")
    sku_col = _find_column(list(reader.fieldnames), SKU_COLUMN_ALIASES)
    cost_col = _find_column(list(reader.fieldnames), COST_COLUMN_ALIASES)
    if not sku_col or not cost_col:
        raise ValueError(f"No se encontraron columnas de sku/costo. Encabezado: {reader.fieldnames}")
    return [{"sku": row.get(sku_col), "costo": row.get(cost_col)} for row in reader]


def _read_rows_xlsx(fileobj: BinaryIO) -> list[dict[str, Any]]:
    workbook = openpyxl.load_workbook(fileobj, read_only=True, data_only=True)
    sheet = workbook.active
    rows_iter = sheet.iter_rows(values_only=True)
    try:
        header = [str(h).strip().lower() if h is not None else "" for h in next(rows_iter)]
    except StopIteration:
        raise ValueError("El archivo Excel está vacío.") from None

    sku_idx = next((i for i, h in enumerate(header) if h in SKU_COLUMN_ALIASES), None)
    cost_idx = next((i for i, h in enumerate(header) if h in COST_COLUMN_ALIASES), None)
    if sku_idx is None or cost_idx is None:
        raise ValueError(f"No se encontraron columnas de sku/costo. Encabezado: {header}")

    rows: list[dict[str, Any]] = []
    for values in rows_iter:
        if values is None or all(v is None for v in values):
            continue  # fila vacía al final de la hoja — no es un dato faltante, no se reporta
        sku = values[sku_idx] if sku_idx < len(values) else None
        costo = values[cost_idx] if cost_idx < len(values) else None
        rows.append({"sku": sku, "costo": costo})
    return rows


def _read_rows(fileobj: BinaryIO, filename: str) -> list[dict[str, Any]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return _read_rows_csv(fileobj)
    if suffix in (".xlsx", ".xlsm"):
        return _read_rows_xlsx(fileobj)
    raise ValueError(f"Formato no soportado ({suffix or 'sin extensión'}). Usa .csv o .xlsx.")


def import_costs(fileobj: BinaryIO, filename: str, session: Session, store_id: int) -> ImportResult:
    """Punto de entrada usado tanto por la línea de comandos como por
    POST /api/costos/importar — no le importa si el archivo vino de disco o
    de un upload HTTP, solo necesita algo que se pueda leer (`fileobj`), el
    nombre original (para saber si es .csv o .xlsx) y la tienda dueña del
    catálogo que se está actualizando (nunca busca un SKU fuera de esa
    tienda)."""
    result = ImportResult()
    for row in _read_rows(fileobj, filename):
        sku_raw = row.get("sku")
        costo_raw = row.get("costo")
        if sku_raw is None or str(sku_raw).strip() == "":
            continue
        sku = _sku_to_str(sku_raw)

        try:
            costo = _parse_cost(costo_raw)
        except (ValueError, TypeError):
            result.filas_invalidas.append(f"{sku}: costo inválido ({costo_raw!r})")
            continue

        variant = session.query(ProductVariant).filter_by(store_id=store_id, variant_sku=sku).first()
        if variant is None:
            result.no_encontrados.append(sku)
            continue
        variant.cost_price = costo
        result.actualizados.append(sku)

    session.commit()
    return result


def import_costs_from_path(path: Path, session: Session, store_id: int) -> ImportResult:
    with path.open("rb") as f:
        return import_costs(f, path.name, session, store_id)


if __name__ == "__main__":
    # Herramienta de línea de comandos (uso manual del dueño/soporte, no
    # HTTP) — sin sesión de usuario, así que la tienda se pasa explícita en
    # vez de resolverse sola; por default toma la primera que exista, que
    # alcanza mientras solo haya una empresa usando esto en desarrollo.
    if len(sys.argv) not in (2, 3):
        print("Uso: python -m app.db.import_costs ruta/al/archivo.csv (o .xlsx) [store_id]")
        sys.exit(1)

    db = SessionLocal()
    try:
        if len(sys.argv) == 3:
            store_id_arg = int(sys.argv[2])
        else:
            primera_tienda = db.query(Store).order_by(Store.id).first()
            if primera_tienda is None:
                print("No hay ninguna tienda creada todavía (correr app/db/seed_demo.py, o pasar un store_id explícito).")
                sys.exit(1)
            store_id_arg = primera_tienda.id

        resultado = import_costs_from_path(Path(sys.argv[1]), db, store_id_arg)
        print(f"Actualizados: {len(resultado.actualizados)}")
        if resultado.no_encontrados:
            print(f"SKU no encontrados en el catálogo ({len(resultado.no_encontrados)}): {', '.join(resultado.no_encontrados[:20])}")
        if resultado.filas_invalidas:
            print(f"Filas con costo inválido ({len(resultado.filas_invalidas)}): {', '.join(resultado.filas_invalidas[:20])}")
    finally:
        db.close()
