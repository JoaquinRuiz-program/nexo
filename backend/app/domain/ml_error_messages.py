"""Traduce un error REAL de Mercado Libre (el body de error de POST/PUT
/items, ver MercadoLibreRequestError.response_body en
adapters/mercadolibre.py) a un mensaje que un dueño de negocio no técnico
pueda entender — 1 de septiembre de 2026, ronda de pulido pre-clientes.

Regla de siempre: nunca se muestra JSON crudo, un código interno de
Mercado Libre, ni un stack trace al dueño. El detalle completo (incluido
este `response_body`) sigue disponible para el log del servidor —
quien llama a esto es responsable de loguearlo aparte, esta función solo
devuelve el texto de cara al usuario.

Estructura real confirmada en vivo (primera publicación real contra
Mercado Libre, 1 de septiembre de 2026, categoría MLC180937):

    {
      "cause": [
        {"department": "structured-data", "cause_id": 3704, "type": "warning",
         "code": "item.attribute.missing_catalog_required",
         "references": ["item.attributes"], "message": "..."},
        {"department": "supply", "cause_id": 7711, "type": "error",
         "code": "item.attribute.product_identifier.invalid_format",
         "references": ["item.attributes[2].values"], "message": "..."}
      ],
      "message": "Validation error"
    }

Mercado Libre mezcla "warning" (informativo, no necesariamente bloqueó la
publicación) y "error" (sí bloqueó) en el mismo array — esta función
prioriza los "error" reales para decidir el mensaje; si no hay ninguno
"error" (edge case, la respuesta 400 igual llegó), cae a mirar todos los
`code` disponibles antes de dar el mensaje genérico."""

from __future__ import annotations

from typing import Any, Optional

MENSAJE_GENERICO = "Mercado Libre no pudo confirmar la publicación. Revisá los datos del producto e intentá de nuevo."


def _codigos(response_body: Optional[dict[str, Any]], *, solo_errores: bool) -> list[str]:
    causas = (response_body or {}).get("cause")
    if not isinstance(causas, list):
        return []
    resultado = []
    for causa in causas:
        if not isinstance(causa, dict):
            continue
        if solo_errores and causa.get("type") != "error":
            continue
        codigo = causa.get("code")
        if isinstance(codigo, str):
            resultado.append(codigo)
    return resultado


def mensaje_amigable_error_publicacion(response_body: Optional[dict[str, Any]]) -> str:
    """`response_body` es MercadoLibreRequestError.response_body — puede
    ser None si Mercado Libre no devolvió JSON válido (nunca se inventa un
    mensaje más específico en ese caso, se usa el genérico)."""
    codigos = _codigos(response_body, solo_errores=True) or _codigos(response_body, solo_errores=False)

    if any(c.startswith("item.category") for c in codigos):
        return "La categoría seleccionada no es válida para este producto."
    if any(c.startswith("item.price") for c in codigos):
        return "El precio ingresado no es válido para esta publicación."
    # 6 de septiembre de 2026 — caso real más específico dentro de
    # "item.attribute": el identificador del producto (GTIN/EAN/UPC) mal
    # formado o rechazado — mensaje puntual en vez del genérico de
    # atributos, mismo código real documentado arriba
    # (item.attribute.product_identifier.invalid_format).
    if any("product_identifier" in c for c in codigos):
        return "El código de barras (GTIN/EAN/UPC) de este producto no es válido para Mercado Libre. Corregilo en la ficha del producto."
    if any(c.startswith("item.attribute") for c in codigos):
        return "Faltan algunos datos obligatorios del producto. Revisá los atributos marcados."
    return MENSAJE_GENERICO
