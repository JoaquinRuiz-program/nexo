"""
Pruebas de app/domain/listing_validation.py — funciones puras, sin red ni
DB, igual que test_ml_fees.py. `ATRIBUTOS_CUADERNOS` es un fixture con
datos REALES: capturado en vivo el 29 de agosto de 2026 contra
GET https://api.mercadolibre.com/categories/MLC180937/attributes (la
categoría "Cuadernos" verificada en la ronda de comisiones), no inventado.
"""

from __future__ import annotations

from app.domain.listing_validation import (
    AttributeValue,
    construir_attributes_payload,
    evaluar_atributos,
    resolver_item_condition,
)

# Subconjunto real de la respuesta de Mercado Libre — BRAND (required +
# catalog_required), MODEL (solo catalog_required, NO required), LINE (sin
# tags), GTIN (conditional_required), ITEM_CONDITION (hidden, con values
# reales "Nuevo"/"Usado").
ATRIBUTOS_CUADERNOS = [
    {
        "id": "BRAND",
        "name": "Marca",
        "tags": {"catalog_required": True, "required": True},
        "value_type": "string",
        "value_max_length": 255,
    },
    {
        "id": "MODEL",
        "name": "Modelo",
        "tags": {"catalog_required": True},
        "value_type": "string",
        "value_max_length": 255,
    },
    {
        "id": "LINE",
        "name": "Línea",
        "tags": {},
        "value_type": "string",
        "value_max_length": 255,
    },
    {
        "id": "GTIN",
        "name": "Código universal de producto",
        "tags": {"multivalued": True, "variation_attribute": True, "used_hidden": True, "validate": True, "conditional_required": True},
        "value_type": "string",
        "value_max_length": 255,
    },
    {
        "id": "ITEM_CONDITION",
        "name": "Condición del ítem",
        "tags": {"hidden": True},
        "value_type": "list",
        "values": [{"id": "2230284", "name": "Nuevo"}, {"id": "2230581", "name": "Usado"}],
    },
]


def test_resolver_item_condition_nuevo_encuentra_el_value_id_real():
    resultado = resolver_item_condition(ATRIBUTOS_CUADERNOS, "new")
    assert resultado == AttributeValue(id="ITEM_CONDITION", value_id="2230284", value_name="Nuevo")


def test_resolver_item_condition_usado_encuentra_el_value_id_real():
    resultado = resolver_item_condition(ATRIBUTOS_CUADERNOS, "used")
    assert resultado == AttributeValue(id="ITEM_CONDITION", value_id="2230581", value_name="Usado")


def test_resolver_item_condition_sin_atributo_en_la_categoria_devuelve_none():
    assert resolver_item_condition([{"id": "BRAND", "tags": {}}], "new") is None


def test_resolver_item_condition_condition_desconocida_devuelve_none():
    # Nunca inventa un value_id para un "condition" que Nexo no reconoce.
    assert resolver_item_condition(ATRIBUTOS_CUADERNOS, "refurbished") is None


def test_catalog_required_solo_nunca_es_obligatorio_en_v1():
    # MODEL solo tiene catalog_required (no "required") — no aplica en v1,
    # que no publica en modo catálogo (ver informe de arquitectura).
    resultado = evaluar_atributos(ATRIBUTOS_CUADERNOS, "new", datos_conocidos={}, valores_ingresados={})
    ids_faltantes = {f.id for f in resultado.faltantes}
    assert "MODEL" not in ids_faltantes


def test_atributo_sin_tags_nunca_es_obligatorio():
    resultado = evaluar_atributos(ATRIBUTOS_CUADERNOS, "new", datos_conocidos={}, valores_ingresados={})
    assert "LINE" not in {f.id for f in resultado.faltantes}


def test_brand_requerido_sin_dato_conocido_queda_en_faltantes():
    resultado = evaluar_atributos(ATRIBUTOS_CUADERNOS, "new", datos_conocidos={}, valores_ingresados={})
    faltante = next(f for f in resultado.faltantes if f.id == "BRAND")
    assert faltante.nombre == "Marca"
    assert faltante.value_type == "string"


def test_brand_requerido_con_dato_conocido_de_nexo_queda_completo_nunca_faltante():
    resultado = evaluar_atributos(ATRIBUTOS_CUADERNOS, "new", datos_conocidos={"BRAND": "Torre"}, valores_ingresados={})
    assert AttributeValue(id="BRAND", value_name="Torre") in resultado.completos
    assert "BRAND" not in {f.id for f in resultado.faltantes}


def test_valor_ingresado_a_mano_por_el_dueno_completa_un_faltante():
    # Primero, sin nada, BRAND queda faltante.
    sin_dato = evaluar_atributos(ATRIBUTOS_CUADERNOS, "new", datos_conocidos={}, valores_ingresados={})
    assert "BRAND" in {f.id for f in sin_dato.faltantes}

    # El dueño lo completa a mano en la pantalla de publicación.
    con_dato = evaluar_atributos(ATRIBUTOS_CUADERNOS, "new", datos_conocidos={}, valores_ingresados={"BRAND": "Genérica"})
    assert "BRAND" not in {f.id for f in con_dato.faltantes}
    assert AttributeValue(id="BRAND", value_name="Genérica") in con_dato.completos


def test_conditional_required_sin_dato_queda_en_faltantes_nunca_se_asume_que_no_aplica():
    resultado = evaluar_atributos(ATRIBUTOS_CUADERNOS, "new", datos_conocidos={}, valores_ingresados={})
    assert "GTIN" in {f.id for f in resultado.faltantes}


def test_gtin_con_codigo_de_barras_conocido_por_nexo_queda_completo():
    resultado = evaluar_atributos(ATRIBUTOS_CUADERNOS, "new", datos_conocidos={"GTIN": "7891234567890"}, valores_ingresados={})
    assert "GTIN" not in {f.id for f in resultado.faltantes}


def test_item_condition_se_agrega_a_completos_sin_pedirselo_al_dueno():
    # ITEM_CONDITION no tiene tag "required" (está "hidden") pero igual se
    # resuelve y se agrega — nunca debería aparecer como faltante si la
    # categoría ofrece el value_name correspondiente.
    resultado = evaluar_atributos(ATRIBUTOS_CUADERNOS, "new", datos_conocidos={}, valores_ingresados={})
    assert AttributeValue(id="ITEM_CONDITION", value_id="2230284", value_name="Nuevo") in resultado.completos
    assert "ITEM_CONDITION" not in {f.id for f in resultado.faltantes}


def test_faltante_con_value_type_list_incluye_las_opciones_reales():
    # Categoría sintética con un atributo "list" obligatorio, para probar
    # que las opciones viajan completas (nunca un campo de texto libre
    # cuando la categoría define valores fijos).
    atributos = [
        {
            "id": "COLOR",
            "name": "Color",
            "tags": {"required": True},
            "value_type": "list",
            "values": [{"id": "52049", "name": "Azul"}, {"id": "62050", "name": "Rojo"}],
        }
    ]
    resultado = evaluar_atributos(atributos, "new", datos_conocidos={}, valores_ingresados={})
    faltante = next(f for f in resultado.faltantes if f.id == "COLOR")
    assert faltante.opciones == [{"id": "52049", "name": "Azul"}, {"id": "62050", "name": "Rojo"}]


def test_listo_para_publicar_es_true_solo_sin_faltantes():
    con_faltantes = evaluar_atributos(ATRIBUTOS_CUADERNOS, "new", datos_conocidos={}, valores_ingresados={})
    assert con_faltantes.listo_para_publicar is False

    sin_faltantes = evaluar_atributos(
        ATRIBUTOS_CUADERNOS, "new", datos_conocidos={"BRAND": "Torre", "GTIN": "7891234567890"}, valores_ingresados={}
    )
    assert sin_faltantes.listo_para_publicar is True


def test_new_required_solo_aplica_si_condition_es_new():
    atributos = [{"id": "WARRANTY", "name": "Garantía", "tags": {"new_required": True}, "value_type": "string"}]
    con_nuevo = evaluar_atributos(atributos, "new", datos_conocidos={}, valores_ingresados={})
    assert "WARRANTY" in {f.id for f in con_nuevo.faltantes}

    con_usado = evaluar_atributos(atributos, "used", datos_conocidos={}, valores_ingresados={})
    assert "WARRANTY" not in {f.id for f in con_usado.faltantes}


def test_construir_attributes_payload_nunca_incluye_condition_a_nivel_raiz():
    resultado = evaluar_atributos(
        ATRIBUTOS_CUADERNOS, "new", datos_conocidos={"BRAND": "Torre", "GTIN": "7891234567890"}, valores_ingresados={}
    )
    payload = construir_attributes_payload(resultado)

    assert {"id": "BRAND", "value_name": "Torre"} in payload
    assert {"id": "GTIN", "value_name": "7891234567890"} in payload
    assert {"id": "ITEM_CONDITION", "value_id": "2230284", "value_name": "Nuevo"} in payload
    # "condition" nunca es una clave del payload de attributes ni aparece
    # como entrada propia — ver precisión explícita del dueño.
    assert not any(entrada.get("id") == "condition" for entrada in payload)
    assert all(set(entrada.keys()) <= {"id", "value_id", "value_name"} for entrada in payload)


def test_atributo_sin_id_se_ignora_sin_romper():
    atributos_con_basura = ATRIBUTOS_CUADERNOS + [{"name": "Sin id", "tags": {"required": True}}]
    resultado = evaluar_atributos(atributos_con_basura, "new", datos_conocidos={}, valores_ingresados={})
    assert all(f.id for f in resultado.faltantes)
