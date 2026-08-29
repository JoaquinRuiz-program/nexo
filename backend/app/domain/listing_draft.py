"""
"Borrador de publicación" (24 de agosto de 2026) — lo que el dueño revisa
antes de aprobar. Todavía NO existe publicación real en Mercado Libre: este
objeto se calcula al vuelo en cada request, no se guarda en ninguna tabla.
Cuando exista la integración real, el paso de "aprobar" recién ahí crea un
`MarketplaceListing` de verdad (ver app/db/models/marketplace.py) — hasta
entonces, este módulo es puro cálculo/preview, sin efectos.

Combina, sin inventar nada nuevo:
- Contenido (título/descripción/atributos) de domain/ai_content.py —
  simulado con reglas, ver ese archivo.
- Rentabilidad y clasificación ya calculadas por
  domain/catalog_selection.py — este módulo no recalcula ningún margen.
- Categoría: se propone la del producto tal cual está cargada, marcada
  EXPLÍCITAMENTE como no oficial — no hay conexión con las categorías
  reales de Mercado Libre todavía.
"""

from __future__ import annotations

from typing import Any, Optional

from app.domain.ai_content import generate_content

# rentable -> se puede publicar tal cual; margen_bajo -> se puede publicar,
# pero se le avisa al dueño; el resto -> no se recomienda publicar sin que
# el dueño lo decida a mano (nunca se bloquea del todo, solo se marca).
_ESTADO_POR_CLASIFICACION = {
    "rentable": "listo_para_publicar",
    "margen_bajo": "requiere_revision",
    "no_rentable": "no_recomendado",
    "sin_stock": "no_recomendado",
    "sin_datos": "no_recomendado",
}


def build_draft(
    row: dict[str, Any],
    *,
    categoria: Optional[str],
    descripcion: Optional[str],
    imagenes: list[str],
    codigo_barras: Optional[str],
    variant_label: Optional[str],
    marca: Optional[str],
) -> dict[str, Any]:
    contenido = generate_content(
        nombre=row["nombre"],
        marca=marca,
        categoria=categoria,
        descripcion_original=descripcion,
        codigo_barras=codigo_barras,
        variant_label=variant_label,
    )
    clasificacion = row.get("clasificacion", "sin_datos")

    return {
        "id": row["id"],
        "sku": row["sku"],
        "tituloPropuesto": contenido.titulo,
        "descripcionPropuesta": contenido.descripcion,
        "contenidoSimulado": contenido.simulado,
        "categoriaSugerida": categoria,
        "categoriaEsOficialDeMercadoLibre": False,
        "marca": marca,
        "codigoBarras": codigo_barras,
        "atributos": contenido.atributos,
        "precio": row.get("precio"),
        "costo": row.get("costo"),
        "imagenes": imagenes,
        "rentabilidad": {
            "margenTiendaClp": row.get("margenTiendaClp"),
            "margenTiendaPct": row.get("margenTiendaPct"),
            "margenMercadoLibreClp": row.get("margenMercadoLibreClp"),
            "margenMercadoLibrePct": row.get("margenMercadoLibrePct"),
        },
        "clasificacion": clasificacion,
        "razonClasificacion": row.get("razon"),
        "estado": _ESTADO_POR_CLASIFICACION.get(clasificacion, "requiere_revision"),
        "advertencias": _advertencias(clasificacion, row.get("razon"), categoria, imagenes),
    }


def _advertencias(clasificacion: str, razon: Optional[str], categoria: Optional[str], imagenes: list[str]) -> list[str]:
    avisos: list[str] = []
    if not imagenes:
        avisos.append("Sin imagen cargada.")
    if not categoria:
        avisos.append("Sin categoría — se recomienda completarla antes de publicar.")
    if clasificacion != "rentable" and razon:
        avisos.append(razon)
    return avisos
