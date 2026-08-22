"""
Funciones puras de análisis del catálogo (sin red, sin filesystem) — puerto
directo de scripts/woocommerce-audit/src/analysis.ts. Trabajan sobre dicts
(la forma cruda que devuelve la API de WooCommerce), no sobre un modelo
propio todavía — ese modelo (`Producto` del backend) se construye en una
fase posterior, sobre la base de esto.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional


def normalize(text: str) -> str:
    """Normaliza texto para comparar SKU/nombres sin tildes/mayúsculas/espacios."""
    text = text.strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text)


def summarize_catalog(products: list[dict[str, Any]]) -> dict[str, Any]:
    categories: set[str] = set()
    con_sku = con_gestion_stock = con_stock_numerico = 0
    con_imagenes = con_multiples_imagenes = con_descripcion = 0

    for p in products:
        sku = (p.get("sku") or "").strip()
        if sku:
            con_sku += 1
        if p.get("manage_stock"):
            con_gestion_stock += 1
            if isinstance(p.get("stock_quantity"), (int, float)):
                con_stock_numerico += 1
        images = p.get("images") or []
        if len(images) > 0:
            con_imagenes += 1
        if len(images) > 1:
            con_multiples_imagenes += 1
        if (p.get("description") or "").strip():
            con_descripcion += 1
        for c in p.get("categories") or []:
            categories.add(c["name"])

    total = len(products)
    return {
        "total": total,
        "conSku": con_sku,
        "sinSku": total - con_sku,
        "conGestionStock": con_gestion_stock,
        "sinGestionStock": total - con_gestion_stock,
        "conStockNumerico": con_stock_numerico,
        "sinStockNumerico": total - con_stock_numerico,
        "conImagenes": con_imagenes,
        "sinImagenes": total - con_imagenes,
        "conMultiplesImagenes": con_multiples_imagenes,
        "conDescripcion": con_descripcion,
        "sinDescripcion": total - con_descripcion,
        "cantidadCategorias": len(categories),
        "categorias": sorted(categories),
    }


def detect_duplicates(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    by_sku: dict[str, list[dict[str, Any]]] = {}
    already_grouped: set[int] = set()

    for p in products:
        sku = (p.get("sku") or "").strip()
        if not sku:
            continue
        key = normalize(sku)
        by_sku.setdefault(key, []).append(p)

    for sku_key, items in by_sku.items():
        if len(items) > 1:
            groups.append(
                {
                    "criterio": "sku",
                    "clave": sku_key,
                    "productos": [{"woocommerce_id": p["id"], "nombre": p["name"], "sku": p.get("sku", "")} for p in items],
                }
            )
            already_grouped.update(p["id"] for p in items)

    by_name: dict[str, list[dict[str, Any]]] = {}
    for p in products:
        if p["id"] in already_grouped:
            continue
        key = normalize(p["name"])
        by_name.setdefault(key, []).append(p)

    for name_key, items in by_name.items():
        if len(items) > 1:
            groups.append(
                {
                    "criterio": "nombre",
                    "clave": name_key,
                    "productos": [{"woocommerce_id": p["id"], "nombre": p["name"], "sku": p.get("sku", "")} for p in items],
                }
            )

    return groups


BARCODE_KEY_PATTERN = re.compile(r"barcode|ean|isbn|upc|gtin|c[oó]digo", re.IGNORECASE)
INTERNAL_KEYS = {"_lc_test_case", "_lc_seed_source"}


def find_barcode_candidates(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, list[dict[str, Any]]] = {}
    for p in products:
        for meta in p.get("meta_data") or []:
            key = meta.get("key", "")
            if key in INTERNAL_KEYS or not BARCODE_KEY_PATTERN.search(key):
                continue
            by_key.setdefault(key, []).append({"woocommerce_id": p["id"], "value": meta.get("value")})
    return [{"key": k, "productCount": len(v), "examples": v[:3]} for k, v in by_key.items()]


def products_without_sku(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in products if not (p.get("sku") or "").strip()]


def products_without_stock_management(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in products if not p.get("manage_stock")]


def products_without_images(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in products if not (p.get("images") or [])]


def products_without_description(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in products if not (p.get("description") or "").strip()]


def build_productos_list(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convierte el catálogo (ya expandido por color, si corresponde) en la
    lista plana que necesita la tabla de productos del frontend: un dict por
    fila, con exactamente los campos que la interfaz muestra (SKU, nombre,
    tipo, stock, precio) más los datos crudos de stock/variante que el
    frontend necesita para decidir cómo pintarlos — sin que este módulo
    tenga que adivinar umbrales de "stock bajo" (eso vive en el frontend,
    donde el dueño lo puede ajustar).

    No inventa nada: si WooCommerce no trae un dato (precio vacío, stock
    nulo por no gestionarse), se pasa tal cual (cadena vacía / None), nunca
    se rellena con un valor supuesto.
    """
    rows: list[dict[str, Any]] = []
    for p in products:
        rows.append(
            {
                "id": p["id"],
                "sku": p.get("sku") or "",
                "nombre": p.get("name", ""),
                "tipo": p.get("type", ""),
                "precio": p.get("price") or "",
                "stockQuantity": p.get("stock_quantity"),
                "gestionaStock": bool(p.get("manage_stock")),
                "estadoStock": p.get("stock_status"),
                "esVariante": bool(p.get("esVariante")),
                "colorVariante": p.get("colorVariante"),
                "woocommerceParentId": p.get("woocommerceParentId"),
            }
        )
    return rows


def expand_variable_products(
    products: list[dict[str, Any]],
    variations_by_product_id: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """
    Reemplaza cada producto type:"variable" por una fila por cada variación
    real (SKU/precio/stock de la VARIACIÓN, no del padre). Un producto
    "variable" sin variaciones cargadas se conserva tal cual — nunca se
    descarta silenciosamente. Decisión ya tomada con el dueño: "una fila por
    color", igual criterio que en mapper-v3.mjs (experimento con la Store
    API pública) y en analysis.ts (script de auditoría).
    """
    rows: list[dict[str, Any]] = []

    for p in products:
        if p.get("type") != "variable":
            rows.append({**p, "esVariante": False, "woocommerceParentId": None, "colorVariante": None})
            continue

        variations = variations_by_product_id.get(p["id"], [])
        if not variations:
            rows.append({**p, "esVariante": False, "woocommerceParentId": None, "colorVariante": None})
            continue

        for v in variations:
            color_attr = next(
                (a for a in (v.get("attributes") or []) if re.search(r"color", a.get("name", ""), re.IGNORECASE)),
                None,
            )
            color_label: Optional[str] = color_attr["option"] if color_attr else None
            rows.append(
                {
                    **p,
                    "id": v["id"],
                    "sku": v.get("sku") or "",
                    "price": v.get("price", p.get("price")),
                    "regular_price": v.get("regular_price", p.get("regular_price")),
                    "sale_price": v.get("sale_price", p.get("sale_price")),
                    "description": v.get("description") or p.get("description", ""),
                    "stock_quantity": v.get("stock_quantity"),
                    "manage_stock": v.get("manage_stock", False),
                    "stock_status": v.get("stock_status", p.get("stock_status")),
                    "images": [v["image"]] if v.get("image") else p.get("images", []),
                    "name": f"{p['name']} - {color_label}" if color_label else p["name"],
                    "meta_data": v.get("meta_data", []),
                    "esVariante": True,
                    "woocommerceParentId": p["id"],
                    "colorVariante": color_label,
                }
            )

    return rows
