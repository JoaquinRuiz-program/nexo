"""
Genera test-data/Nexo_Datos_Prueba.xlsx — 5 de septiembre de 2026.

Dataset de prueba FUNCIONAL (no reemplaza los tests automatizados, ver
backend/tests/) para simular un cliente real subiendo su catálogo a Nexo.
Las columnas son EXACTAMENTE las que reconoce el importador real (ver
backend/app/domain/catalog_import.py::IMPORT_FIELDS) — no se inventó
ninguna columna nueva.

Uso: cd al root del repo y correr
    backend/.venv/Scripts/python scripts/generar_excel_datos_prueba.py
(reescribe test-data/Nexo_Datos_Prueba.xlsx desde cero cada vez).
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.styles import Font

COLUMNAS = ["SKU", "Nombre", "Marca", "Categoría", "Costo", "Precio", "Stock", "Descripción", "Imagen URL", "Código de Barras"]

# Imagen de ejemplo pública y estable (Wikimedia, licencia libre) — sirve
# para probar de verdad el flujo "URL de imagen -> Nexo -> Mercado Libre"
# sin depender de un archivo binario embebido en este script.
IMG = "https://upload.wikimedia.org/wikipedia/commons/6/65/No-Image-Placeholder.svg"

# (sku, nombre, marca, categoria, costo, precio, stock, descripcion, imagen_url, codigo_barras)
FILAS = [
    # ---- Tecnología — casos normales ----
    ("TEC-001", "Mouse inalámbrico 2.4GHz", "Logitech", "Tecnología", 8000, 12990, 40, "Mouse óptico inalámbrico, 3 botones.", IMG, "7891234560016"),
    ("TEC-002", "Teclado mecánico retroiluminado", "Redragon", "Tecnología", 18000, 29990, 15, "Teclado mecánico switches rojos, luz RGB.", IMG, "7891234560023"),
    ("TEC-003", "Audífonos inalámbricos Bluetooth", "JBL", "Tecnología", 15000, 24990, 25, "Audífonos in-ear con estuche de carga.", IMG, ""),
    # Sin imagen — escenario "sin imágenes" (bloquea publicar en ML, no la importación).
    ("TEC-004", "Cargador USB-C 30W", "Anker", "Tecnología", 6000, 9990, 60, "Cargador rápido compatible con la mayoría de notebooks y celulares.", "", ""),
    # Precio inválido (texto, no número) — fila de "revisión" al importar.
    ("TEC-005", "Hub USB 4 puertos", "Ugreen", "Tecnología", 5000, "consultar", 20, "Hub USB 3.0 de 4 puertos.", IMG, ""),

    # ---- Hogar ----
    ("HOG-001", "Set de ollas antiadherentes x5", "Tramontina", "Hogar", 25000, 39990, 12, "Set de 5 ollas con recubrimiento antiadherente.", IMG, "7891234560030"),
    ("HOG-002", "Lámpara de escritorio LED", "Xiaomi", "Hogar", 9000, 15990, 30, "Lámpara LED regulable, 3 niveles de luz.", IMG, "7891234560047"),
    # Datos incompletos — falta el nombre (obligatorio).
    ("HOG-003", "", "Genérico", "Hogar", 3000, 5990, 50, "Organizador plástico multiuso.", IMG, ""),
    # Precio fuera de rango razonable (negativo) — validación de precio.
    ("HOG-004", "Juego de toallas de baño x3", "Cannon", "Hogar", 8000, -1000, 18, "Juego de 3 toallas 100% algodón.", IMG, ""),

    # ---- Deporte ----
    ("DEP-001", "Pelota de fútbol N°5", "Nike", "Deporte", 9000, 14990, 35, "Pelota oficial N°5, uso profesional.", IMG, "7891234560054"),
    ("DEP-002", "Mancuernas ajustables 10kg (par)", "Everlast", "Deporte", 22000, 34990, 10, "Par de mancuernas ajustables de 2 a 10kg.", IMG, "7891234560061"),
    ("DEP-003", "Colchoneta de yoga antideslizante", "Decathlon", "Deporte", 6000, 11990, 45, "Colchoneta 6mm, antideslizante en ambas caras.", IMG, ""),
    ("DEP-004", "Botella deportiva térmica 1L", "Stanley", "Deporte", 7000, 13990, 28, "Botella térmica, mantiene frío 24h.", "", ""),

    # ---- Vestuario (con variantes lógicas de talla/color — atributos de ML) ----
    ("VES-001", "Polera algodón cuello redondo", "Genérica", "Vestuario", 3500, 6990, 100, "Polera 100% algodón, disponible en varios talles.", IMG, ""),
    ("VES-002", "Zapatillas urbanas unisex", "Puma", "Vestuario", 20000, 34990, 22, "Zapatillas urbanas, suela de goma.", IMG, "7891234560078"),
    ("VES-003", "Chaqueta cortavientos", "Columbia", "Vestuario", 18000, 29990, 14, "Chaqueta liviana resistente al agua.", IMG, ""),

    # ---- Accesorios ----
    ("ACC-001", "Correa de cuero genuino", "Genérica", "Accesorios", 4000, 8990, 40, "Correa de cuero, hebilla metálica.", IMG, ""),
    ("ACC-002", "Mochila urbana 20L", "Totto", "Accesorios", 12000, 19990, 25, "Mochila con compartimento para notebook.", IMG, "7891234560085"),
    # Duplicado intencional de ACC-002 (mismo SKU, datos distintos) — al
    # reimportar debe ACTUALIZAR la fila existente, nunca duplicarla.
    ("ACC-002", "Mochila urbana 20L (precio actualizado)", "Totto", "Accesorios", 12000, 17990, 20, "Mochila con compartimento para notebook — precio de liquidación.", IMG, "7891234560085"),
    ("ACC-003", "Lentes de sol polarizados", "Ray-Ban", "Accesorios", 15000, 25990, 18, "Lentes de sol con protección UV400.", IMG, ""),

    # ---- Herramientas ----
    ("HER-001", "Taladro percutor eléctrico", "Bosch", "Herramientas", 28000, 45990, 8, "Taladro percutor 650W, incluye maletín.", IMG, "7891234560092"),
    ("HER-002", "Set de destornilladores x12", "Stanley", "Herramientas", 6000, 10990, 30, "Set de destornilladores punta plana y phillips.", IMG, "7891234560108"),
    ("HER-003", "Cinta métrica 5m", "Stanley", "Herramientas", 1500, 2990, 80, "Cinta métrica con freno y clip.", IMG, ""),
    # Sin stock (0) — escenario adicional útil para probar indicadores de stock.
    ("HER-004", "Sierra circular manual", "Makita", "Herramientas", 32000, 49990, 0, "Sierra circular 1200W, disco de 7-1/4 pulgadas.", IMG, ""),
]


def generar(ruta: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Catálogo"
    ws.append(COLUMNAS)
    for celda in ws[1]:
        celda.font = Font(bold=True)
    for fila in FILAS:
        ws.append(fila)
    for col in ws.columns:
        letra = col[0].column_letter
        ws.column_dimensions[letra].width = max(12, min(45, max(len(str(c.value or "")) for c in col) + 2))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    wb.save(ruta)
    print(f"Generado: {ruta} ({len(FILAS)} filas de producto)")


if __name__ == "__main__":
    raiz = Path(__file__).resolve().parent.parent
    generar(raiz / "test-data" / "Nexo_Datos_Prueba.xlsx")
