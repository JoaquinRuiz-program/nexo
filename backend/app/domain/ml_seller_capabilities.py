"""Detección de capacidades de una cuenta de Mercado Libre (30 de agosto de
2026 — soporte User Products, commit 5/N de la fase de publicación).

Función pura — recibe la respuesta CRUDA de GET /users/{id} (ver
MercadoLibreAdapter.get_user_info), nunca llama a la red ni a la base.
Quien la usa (app/api/routes/publicaciones.py) es responsable de llamar a
get_user_info EN CADA /confirmar, siempre fresco, nunca cacheado en
MarketplaceAccount — el dueño lo pidió explícitamente: si Mercado Libre
migra una cuenta al modelo User Products entre dos publicaciones, un valor
cacheado seguiría mandando el payload viejo (title, sin family_name) y
Mercado Libre lo rechazaría con el mismo 400 que ya vimos en la prueba real
del 30 de agosto de 2026.

Confirmado oficialmente (developers.mercadolibre.cl/es_cl/precio-variacion):
"Los vendedores encendidos contarán con el tag 'user_product_seller' el
cual podrás identificar realizando un llamado al API de users." — y una
vez activo ese tag, Mercado Libre exige `family_name` en vez de `title`
para publicaciones NUEVAS."""

from __future__ import annotations

from typing import Any

USER_PRODUCT_SELLER_TAG = "user_product_seller"


def es_user_product_seller(user_info: dict[str, Any]) -> bool:
    """True si la cuenta ya está migrada al modelo User Products de
    Mercado Libre — determina si /confirmar tiene que mandar `family_name`
    en vez de `title`. Acceso defensivo a `tags`: la respuesta real de
    Mercado Libre no siempre trae ese campo (ver GET /users/{id} público,
    que ni siquiera lo incluye — solo la variante autenticada lo trae)."""
    tags = user_info.get("tags") or []
    return USER_PRODUCT_SELLER_TAG in tags
