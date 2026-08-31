"""Construcción del payload final de POST /items (30 de agosto de 2026 —
soporte User Products, commit 5/N de la fase de publicación).

Función pura — antes vivía inline dentro de
app/api/routes/publicaciones.py::confirmar_publicacion_mercadolibre; se
extrae acá para poder tener dos ramas (modelo clásico / User Products) sin
mezclar la construcción del payload de Mercado Libre con el resto de la
lógica de negocio del endpoint (rentabilidad, duplicados, tokens).

Regla real confirmada oficialmente (developers.mercadolibre.cl/es_cl/precio-variacion,
tabla "Estructura de entidad ítem"): una cuenta con el tag
`user_product_seller` (ver domain/ml_seller_capabilities.py) exige
`family_name` en el body y RECHAZA el campo `title` — "el campo title no
debe ser enviado por el vendedor ya que Mercado Libre lo completará
automáticamente". Una cuenta SIN ese tag sigue funcionando exactamente
como hasta el commit anterior: `title`, sin `family_name`.

Devuelve el payload real (lo que se manda a Mercado Libre) Y, por
separado, el título que Nexo debe guardar localmente en
`MarketplaceListing.title` — nunca hay que leer `payload["title"]` a
ciegas después de armar esto, porque en la rama User Products esa clave
directamente no existe."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PayloadPublicacion:
    payload: dict
    titulo_local: str


def construir_payload_publicacion(
    *,
    titulo: str,
    category_id: str,
    price: float,
    currency_id: str,
    available_quantity: int,
    listing_type_id: str,
    pictures: list[dict[str, str]],
    attributes: list[dict[str, str]],
    es_user_product_seller: bool,
    family_name: Optional[str] = None,
) -> PayloadPublicacion:
    """`titulo` es siempre el título que Nexo calculó (generate_title) —
    se usa tal cual para guardar localmente. Se manda a Mercado Libre SOLO
    si la cuenta NO es user_product_seller; si lo es, se manda
    `family_name` en su lugar y `titulo` queda solo para uso interno de
    Nexo (Mercado Libre genera su propio título real, que se lee recién de
    la RESPUESTA de POST /items, nunca de este payload)."""
    payload: dict = {
        "category_id": category_id,
        "price": price,
        "currency_id": currency_id,
        "available_quantity": available_quantity,
        "buying_mode": "buy_it_now",
        "listing_type_id": listing_type_id,
        "pictures": pictures,
        "attributes": attributes,
        "shipping": {"mode": "not_specified"},
    }
    if es_user_product_seller:
        if not family_name:
            raise ValueError("family_name es obligatorio para una cuenta user_product_seller.")
        payload["family_name"] = family_name
    else:
        payload["title"] = titulo

    return PayloadPublicacion(payload=payload, titulo_local=titulo)
