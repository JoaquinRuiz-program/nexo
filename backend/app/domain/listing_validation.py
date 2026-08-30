"""
Validación de atributos de Mercado Libre para publicar un producto real
(29 de agosto de 2026 — fase de publicación, commit 1/N: solo domain puro,
sin wirear a ningún endpoint todavía).

Funciones puras — reciben la respuesta CRUDA de GET
/categories/{id}/attributes (ver MercadoLibreAdapter.get_category_attributes)
+ lo que Nexo ya sabe del producto, y devuelven qué atributos están listos
y cuáles faltan. Nunca llaman a la red ni a la base — eso es trabajo de
quien las use (el endpoint de publicación, todavía sin construir).

Regla que gobierna todo este archivo (misma que ya rige domain/ai_content.py):
NUNCA se inventa un valor. Un atributo obligatorio sin dato conocido queda
en `faltantes` — nunca se completa con un valor supuesto, ni con el primero
de una lista de opciones, ni con un value_id fijo copiado de otra categoría.

Estructura real de un atributo (verificado en vivo el 29 de agosto de 2026
contra GET /categories/MLC180937/attributes — categoría real "Cuadernos"):

    {
      "id": "BRAND",
      "name": "Marca",
      "tags": {"required": true, "catalog_required": true},
      "value_type": "string",
      ...
    }
    {
      "id": "ITEM_CONDITION",
      "name": "Condición del ítem",
      "tags": {"hidden": true},
      "value_type": "list",
      "values": [{"id": "2230284", "name": "Nuevo"}, {"id": "2230581", "name": "Usado"}]
    }

`catalog_required` NO se trata como obligatorio acá — solo aplica a
publicaciones dentro del catálogo de Mercado Libre (un modo de publicación
que esta fase no construye, ver informe de arquitectura). Los tags que sí
determinan "obligatorio" en v1 son exactamente los que se pidió
contemplar: `required`, `new_required`, `conditional_required`.

Precisión explícita del dueño (29 de agosto de 2026) sobre `condition`:
Nexo puede seguir usando internamente `condition` ("new"/"used") como el
dato que recibe del frontend, pero ese valor NUNCA se manda como campo
raíz a Mercado Libre — se transforma acá en una entrada dentro de
`attributes` con `id: "ITEM_CONDITION"` y el `value_id` real, resuelto
dinámicamente buscando dentro de los `values` que la categoría
efectivamente ofrece (nunca un value_id fijo: confirmado en la
investigación que puede variar, y en la prueba en vivo de arriba que
"Nuevo"/"Usado" son value_id concretos de ESA categoría, no una constante
universal a asumir sin verificar).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Tags que hacen que un atributo sea obligatorio para v1 (ver docstring del
# módulo — `catalog_required` queda afuera a propósito).
_TAG_SIEMPRE_REQUERIDO = "required"
_TAG_REQUERIDO_SI_NUEVO = "new_required"
_TAG_REQUERIDO_CONDICIONAL = "conditional_required"

ITEM_CONDITION_ATTRIBUTE_ID = "ITEM_CONDITION"

# Mapeo interno (Nexo) -> nombre real que Mercado Libre usa para el valor
# de ITEM_CONDITION. Nunca un value_id: se busca por nombre dentro de los
# `values` reales de la categoría (ver resolver_item_condition).
_NOMBRE_CONDICION_ML = {"new": "nuevo", "used": "usado"}


@dataclass(frozen=True)
class AttributeValue:
    """Una entrada lista para ir dentro del array `attributes` del payload
    real de POST /items."""

    id: str
    value_id: Optional[str] = None
    value_name: Optional[str] = None


@dataclass(frozen=True)
class MissingAttribute:
    """Un atributo obligatorio de la categoría para el que Nexo NO tiene
    ningún dato — el dueño tiene que completarlo a mano antes de publicar."""

    id: str
    nombre: str
    value_type: str
    # [{"id","name"}] cuando value_type == "list" (para ofrecer un
    # selector con las opciones reales, nunca un campo de texto libre que
    # podría mandar un valor que la categoría no acepta).
    opciones: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ResultadoValidacion:
    completos: list[AttributeValue]
    faltantes: list[MissingAttribute]

    @property
    def listo_para_publicar(self) -> bool:
        return not self.faltantes


def _es_requerido(tags: dict[str, Any], condition: str) -> bool:
    if tags.get(_TAG_SIEMPRE_REQUERIDO):
        return True
    if condition == "new" and tags.get(_TAG_REQUERIDO_SI_NUEVO):
        return True
    if tags.get(_TAG_REQUERIDO_CONDICIONAL):
        # v1 es conservador: se pide el dato igual, nunca se asume que "no
        # aplica" — mejor pedir de más que arriesgar un rechazo real de
        # Mercado Libre por un atributo condicional que sí hacía falta.
        return True
    return False


def resolver_item_condition(atributos_categoria: list[dict[str, Any]], condition: str) -> Optional[AttributeValue]:
    """Busca, dentro de los `values` REALES que la categoría ofrece para
    ITEM_CONDITION, el que corresponde al `condition` interno de Nexo
    ("new"/"used"). None si la categoría no tiene ese atributo, o no ofrece
    ese valor — nunca se inventa un value_id que no vino en la respuesta
    real de Mercado Libre."""
    nombre_buscado = _NOMBRE_CONDICION_ML.get(condition)
    if nombre_buscado is None:
        return None
    atributo = next((a for a in atributos_categoria if a.get("id") == ITEM_CONDITION_ATTRIBUTE_ID), None)
    if atributo is None:
        return None
    for valor in atributo.get("values") or []:
        nombre = (valor.get("name") or "").strip().lower()
        if nombre == nombre_buscado:
            return AttributeValue(id=ITEM_CONDITION_ATTRIBUTE_ID, value_id=valor.get("id"), value_name=valor.get("name"))
    return None


def evaluar_atributos(
    atributos_categoria: list[dict[str, Any]],
    condition: str,
    datos_conocidos: dict[str, str],
    valores_ingresados: Optional[dict[str, str]] = None,
) -> ResultadoValidacion:
    """
    atributos_categoria: respuesta CRUDA de GET /categories/{id}/attributes
      (ver MercadoLibreAdapter.get_category_attributes) — nunca se filtra
      ni se cachea acá, cada llamada evalúa lo que realmente devolvió
      Mercado Libre en ese momento para esa categoría.
    condition: "new" | "used" — el dato interno de Nexo, nunca se manda
      como campo raíz a Mercado Libre (ver docstring del módulo).
    datos_conocidos: lo que Nexo ya tiene del producto sin preguntarle
      nada al dueño, ej. {"BRAND": producto.brand, "GTIN": variante.barcode}
      — arma este dict quien llame a esta función; nunca se inventa acá
      adentro. Distintas categorías pueden llamar al identificador del
      producto GTIN, EAN o UPC según el caso — quien arma el dict decide
      bajo qué id(s) ofrecer el mismo dato conocido.
    valores_ingresados: lo que el dueño ya completó a mano en esta sesión
      de publicación, para atributos que Nexo no puede saber solo.
    """
    valores_ingresados = valores_ingresados or {}
    completos: list[AttributeValue] = []
    faltantes: list[MissingAttribute] = []

    condicion_resuelta = resolver_item_condition(atributos_categoria, condition)

    for atributo in atributos_categoria:
        attr_id = atributo.get("id")
        if not attr_id:
            continue
        tags = atributo.get("tags") or {}

        if attr_id == ITEM_CONDITION_ATTRIBUTE_ID:
            if condicion_resuelta is not None:
                completos.append(condicion_resuelta)
            elif _es_requerido(tags, condition):
                faltantes.append(_faltante_desde(atributo))
            continue

        if attr_id in valores_ingresados:
            completos.append(AttributeValue(id=attr_id, value_name=valores_ingresados[attr_id]))
            continue
        if attr_id in datos_conocidos:
            completos.append(AttributeValue(id=attr_id, value_name=datos_conocidos[attr_id]))
            continue

        if _es_requerido(tags, condition):
            faltantes.append(_faltante_desde(atributo))

    return ResultadoValidacion(completos=completos, faltantes=faltantes)


def _faltante_desde(atributo: dict[str, Any]) -> MissingAttribute:
    return MissingAttribute(
        id=atributo["id"],
        nombre=atributo.get("name") or atributo["id"],
        value_type=atributo.get("value_type") or "string",
        opciones=[
            {"id": v.get("id"), "name": v.get("name")}
            for v in (atributo.get("values") or [])
            if v.get("id") and v.get("name")
        ],
    )


def construir_attributes_payload(resultado: ResultadoValidacion) -> list[dict[str, str]]:
    """El array `attributes` final tal cual se manda a POST /items.

    Nunca incluye una clave `condition` a nivel raíz del payload — ese
    campo NO existe en la salida de esta función a propósito (precisión
    explícita del dueño, 29 de agosto de 2026): ITEM_CONDITION viaja acá
    adentro, como cualquier otro atributo, nunca como campo separado."""
    payload: list[dict[str, str]] = []
    for atributo in resultado.completos:
        entrada: dict[str, str] = {"id": atributo.id}
        if atributo.value_id:
            entrada["value_id"] = atributo.value_id
        if atributo.value_name:
            entrada["value_name"] = atributo.value_name
        payload.append(entrada)
    return payload
