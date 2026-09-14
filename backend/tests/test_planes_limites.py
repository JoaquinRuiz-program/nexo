"""
Límites de productos por plan (14 de septiembre de 2026, decisión del dueño):
Nexo Básico 1.000 productos, Nexo Pro 5.000. Publicaciones sin cambios.
"""

from __future__ import annotations

from app.domain.plans import DEFAULT_PLANS


def _formato(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def test_limites_de_productos_por_plan():
    planes = {p["code"]: p for p in DEFAULT_PLANS}
    assert planes["basico"]["product_limit"] == 1000
    assert planes["pro"]["product_limit"] == 5000
    assert planes["basico"]["publication_limit"] == 150
    assert planes["pro"]["publication_limit"] == 800


def test_el_texto_del_plan_dice_el_mismo_limite_que_se_aplica():
    """Nunca un "Hasta 200 productos" en pantalla con un límite real de 1.000."""
    for plan in DEFAULT_PLANS:
        assert f"Hasta {_formato(plan['product_limit'])} productos" in plan["features"]
