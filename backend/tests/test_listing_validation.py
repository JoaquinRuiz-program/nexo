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
    RAZONES_GTIN_VACIO_VALIDAS,
    construir_attributes_payload,
    evaluar_atributos,
    gtin_checksum_valido,
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
    assert resultado == AttributeValue(id="ITEM_CONDITION", value_id="2230284", value_name="Nuevo", nombre="Condición del ítem")


def test_resolver_item_condition_usado_encuentra_el_value_id_real():
    resultado = resolver_item_condition(ATRIBUTOS_CUADERNOS, "used")
    assert resultado == AttributeValue(id="ITEM_CONDITION", value_id="2230581", value_name="Usado", nombre="Condición del ítem")


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
    assert AttributeValue(id="BRAND", value_name="Torre", nombre="Marca") in resultado.completos
    assert "BRAND" not in {f.id for f in resultado.faltantes}


def test_valor_ingresado_a_mano_por_el_dueno_completa_un_faltante():
    # Primero, sin nada, BRAND queda faltante.
    sin_dato = evaluar_atributos(ATRIBUTOS_CUADERNOS, "new", datos_conocidos={}, valores_ingresados={})
    assert "BRAND" in {f.id for f in sin_dato.faltantes}

    # El dueño lo completa a mano en la pantalla de publicación.
    con_dato = evaluar_atributos(ATRIBUTOS_CUADERNOS, "new", datos_conocidos={}, valores_ingresados={"BRAND": "Genérica"})
    assert "BRAND" not in {f.id for f in con_dato.faltantes}
    assert AttributeValue(id="BRAND", value_name="Genérica", nombre="Marca") in con_dato.completos


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
    assert AttributeValue(id="ITEM_CONDITION", value_id="2230284", value_name="Nuevo", nombre="Condición del ítem") in resultado.completos
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


# ------------------------------------------------------------------
# EMPTY_GTIN_REASON — bug bloqueante encontrado el 30 de agosto de 2026 en
# la prueba end-to-end real (categoría real MLC424972 "Calculadoras",
# capturada en vivo). Subconjunto real: BRAND (required), MODEL (acá SÍ
# required, a diferencia de Cuadernos donde era solo catalog_required),
# GTIN (conditional_required), EMPTY_GTIN_REASON (conditional_required,
# lista con las 4 opciones reales que devuelve Mercado Libre), ITEM_CONDITION.
# ------------------------------------------------------------------

ATRIBUTOS_CALCULADORAS = [
    {"id": "BRAND", "name": "Marca", "tags": {"catalog_required": True, "required": True}, "value_type": "string"},
    {"id": "MODEL", "name": "Modelo", "tags": {"catalog_required": True, "required": True}, "value_type": "string"},
    {
        "id": "GTIN", "name": "Código universal de producto",
        "tags": {"multivalued": True, "variation_attribute": True, "validate": True, "conditional_required": True},
        "value_type": "string",
    },
    {
        "id": "EMPTY_GTIN_REASON", "name": "Motivo de GTIN vacío", "tags": {"conditional_required": True}, "value_type": "list",
        "values": [
            {"id": "17055158", "name": "El producto es una pieza artesanal"},
            {"id": "17055159", "name": "El producto es un kit o un pack"},
            {"id": "17055160", "name": "El producto no tiene código registrado"},
            {"id": "17055161", "name": "Otra razón"},
        ],
    },
    {
        "id": "ITEM_CONDITION", "name": "Condición del ítem", "tags": {"hidden": True}, "value_type": "list",
        "values": [{"id": "2230284", "name": "Nuevo"}, {"id": "2230581", "name": "Usado"}],
    },
]


def test_empty_gtin_reason_se_omite_cuando_ya_hay_gtin_conocido():
    """Pedir el motivo de un GTIN vacío cuando SÍ hay GTIN es contradictorio
    — Mercado Libre podría rechazar el payload por datos inconsistentes.
    No debe aparecer ni en completos ni en faltantes: no aplica."""
    resultado = evaluar_atributos(
        ATRIBUTOS_CALCULADORAS, "new",
        datos_conocidos={"BRAND": "Casio", "GTIN": "4549526615551"},
        valores_ingresados={"MODEL": "FX-991LA CW"},
    )
    ids_faltantes = {f.id for f in resultado.faltantes}
    ids_completos = {a.id for a in resultado.completos}
    assert "EMPTY_GTIN_REASON" not in ids_faltantes
    assert "EMPTY_GTIN_REASON" not in ids_completos
    assert resultado.listo_para_publicar is True


def test_empty_gtin_reason_sigue_pidiendose_si_no_hay_ningun_gtin():
    """El fix es puntual: sin GTIN/EAN/UPC conocido, EMPTY_GTIN_REASON
    sigue siendo un faltante real — no se desactivó el chequeo entero."""
    resultado = evaluar_atributos(
        ATRIBUTOS_CALCULADORAS, "new",
        datos_conocidos={"BRAND": "Casio"},
        valores_ingresados={"MODEL": "FX-991LA CW"},
    )
    assert "EMPTY_GTIN_REASON" in {f.id for f in resultado.faltantes}
    assert "GTIN" in {f.id for f in resultado.faltantes}
    assert resultado.listo_para_publicar is False


def test_empty_gtin_reason_tambien_se_omite_si_el_gtin_lo_completa_el_dueno_a_mano():
    """El GTIN "conocido" puede venir de datos_conocidos (Nexo) o de
    valores_ingresados (el dueño lo completó a mano en /validar) — en
    ambos casos EMPTY_GTIN_REASON deja de aplicar."""
    resultado = evaluar_atributos(
        ATRIBUTOS_CALCULADORAS, "new",
        datos_conocidos={"BRAND": "Casio"},
        valores_ingresados={"MODEL": "FX-991LA CW", "GTIN": "4549526615551"},
    )
    assert "EMPTY_GTIN_REASON" not in {f.id for f in resultado.faltantes}


def test_empty_gtin_reason_nunca_aparece_en_el_payload_final_con_gtin_conocido():
    resultado = evaluar_atributos(
        ATRIBUTOS_CALCULADORAS, "new",
        datos_conocidos={"BRAND": "Casio", "GTIN": "4549526615551"},
        valores_ingresados={"MODEL": "FX-991LA CW"},
    )
    payload = construir_attributes_payload(resultado)
    assert not any(entrada["id"] == "EMPTY_GTIN_REASON" for entrada in payload)


# ------------------------------------------------------------------
# GTIN <-> EMPTY_GTIN_REASON como XOR — segunda mitad del mismo bug real
# (30 de agosto de 2026, prueba end-to-end): responder EMPTY_GTIN_REASON
# también tiene que liberar a GTIN de faltantes, nunca pedir las dos cosas
# a la vez (la contradicción inversa a la ya arreglada arriba).
# ------------------------------------------------------------------


def test_gtin_se_omite_cuando_el_dueno_ya_respondio_el_motivo_de_gtin_vacio():
    resultado = evaluar_atributos(
        ATRIBUTOS_CALCULADORAS, "new",
        datos_conocidos={"BRAND": "Genérica"},
        valores_ingresados={
            "MODEL": "Genérico", "UNITS_PER_PACK": "1",
            "EMPTY_GTIN_REASON": "El producto no tiene código registrado",
        },
    )
    ids_faltantes = {f.id for f in resultado.faltantes}
    assert "GTIN" not in ids_faltantes
    assert "EMPTY_GTIN_REASON" not in ids_faltantes  # el dueño sí lo completó, va a completos
    assert resultado.listo_para_publicar is True

    payload = construir_attributes_payload(resultado)
    assert not any(entrada["id"] == "GTIN" for entrada in payload)
    assert {"id": "EMPTY_GTIN_REASON", "value_name": "El producto no tiene código registrado"} in payload


def test_gtin_sigue_siendo_faltante_si_no_se_respondio_ni_el_codigo_ni_el_motivo():
    """El fix es un XOR, no un apagado del chequeo: sin GTIN Y sin
    EMPTY_GTIN_REASON, las dos cosas siguen pidiéndose (comportamiento ya
    cubierto arriba, se repite acá con el fixture de Calculadoras para
    dejar el XOR completo en un solo lugar)."""
    resultado = evaluar_atributos(
        ATRIBUTOS_CALCULADORAS, "new",
        datos_conocidos={"BRAND": "Genérica"},
        valores_ingresados={"MODEL": "Genérico", "UNITS_PER_PACK": "1"},
    )
    ids_faltantes = {f.id for f in resultado.faltantes}
    assert "GTIN" in ids_faltantes
    assert "EMPTY_GTIN_REASON" in ids_faltantes


def test_gtin_conocido_gana_si_por_error_tambien_viene_un_motivo_de_gtin_vacio():
    """Caso contradictorio de origen (GTIN real Y un motivo de "vacío" al
    mismo tiempo) — gana el dato más concreto: se manda el GTIN real, se
    descarta el motivo, nunca las dos cosas juntas."""
    resultado = evaluar_atributos(
        ATRIBUTOS_CALCULADORAS, "new",
        datos_conocidos={"BRAND": "Casio", "GTIN": "4549526615551"},
        valores_ingresados={"MODEL": "FX-991LA CW", "EMPTY_GTIN_REASON": "Otra razón"},
    )
    payload = construir_attributes_payload(resultado)
    assert {"id": "GTIN", "value_name": "4549526615551"} in payload
    assert not any(entrada["id"] == "EMPTY_GTIN_REASON" for entrada in payload)


# ------------------------------------------------------------------
# gtin_checksum_valido — 30 de agosto de 2026, segundo bug real de la
# prueba end-to-end (Moleskine): un GTIN con checksum inválido llegaba
# intacto hasta POST /items. Nunca corrige el dígito, solo detecta si el
# que ya tenemos es matemáticamente válido.
# ------------------------------------------------------------------


def test_gtin_checksum_valido_acepta_un_ean13_real():
    # Moleskine Classic Notebook, Large, Ruled, Black, Hard Cover — EAN
    # real encontrado en la investigación del 30 de agosto de 2026
    # (eandata.com/UPCitemdb), checksum verificado a mano.
    assert gtin_checksum_valido("9788883701122") is True


def test_gtin_checksum_invalido_rechaza_el_codigo_real_que_fallo_en_mercado_libre():
    # El código que efectivamente mandamos y Mercado Libre rechazó de
    # verdad ("Product Identifier [GTIN] contains values with invalid
    # format") en la prueba real del 30 de agosto de 2026.
    assert gtin_checksum_valido("8058647628161") is False


def test_gtin_checksum_valido_rechaza_longitud_invalida():
    assert gtin_checksum_valido("12345") is False


def test_gtin_checksum_valido_rechaza_no_numerico():
    assert gtin_checksum_valido("805864762816X") is False


def test_gtin_checksum_valido_rechaza_vacio_o_none():
    assert gtin_checksum_valido("") is False
    assert gtin_checksum_valido(None) is False


# ------------------------------------------------------------------
# catalog_required bajo user_product_seller — 30 de agosto de 2026, mismo
# bug real: MODEL solo tenía tag catalog_required (nunca required) pero
# Mercado Libre lo exigió igual al crear el ítem real
# (item.attribute.missing_catalog_required). Nunca cambia el
# comportamiento legacy (es_user_product_seller=False, default).
# ------------------------------------------------------------------


def test_catalog_required_no_es_obligatorio_en_legacy():
    resultado = evaluar_atributos(ATRIBUTOS_CUADERNOS, "new", datos_conocidos={"BRAND": "Torre"}, valores_ingresados={})
    assert "MODEL" not in {f.id for f in resultado.faltantes}


def test_catalog_required_es_obligatorio_bajo_user_product_seller():
    resultado = evaluar_atributos(
        ATRIBUTOS_CUADERNOS, "new", datos_conocidos={"BRAND": "Torre"}, valores_ingresados={},
        es_user_product_seller=True,
    )
    assert "MODEL" in {f.id for f in resultado.faltantes}


def test_catalog_required_se_completa_con_valor_ingresado_a_mano_bajo_user_product_seller():
    resultado = evaluar_atributos(
        ATRIBUTOS_CUADERNOS, "new", datos_conocidos={"BRAND": "Torre"},
        valores_ingresados={"MODEL": "Universitario", "COLOR": "Azul"}, es_user_product_seller=True,
    )
    assert "MODEL" not in {f.id for f in resultado.faltantes}
    assert {"id": "MODEL", "value_name": "Universitario"} in construir_attributes_payload(resultado)


def test_atributo_read_only_nunca_se_pide_aunque_sea_catalog_required():
    """MANUAL_TITLE es catalog_required Y read_only en la categoría real
    MLC180937 — Nexo no puede completarlo (lo calcula Mercado Libre), así
    que nunca debe aparecer como faltante, ni siquiera bajo
    user_product_seller."""
    atributos = ATRIBUTOS_CUADERNOS + [
        {"id": "MANUAL_TITLE", "name": "Título manual", "tags": {"catalog_required": True, "hidden": True, "read_only": True}, "value_type": "string"}
    ]
    resultado = evaluar_atributos(
        atributos, "new", datos_conocidos={"BRAND": "Torre"},
        valores_ingresados={"MODEL": "Universitario", "COLOR": "Azul"}, es_user_product_seller=True,
    )
    assert "MANUAL_TITLE" not in {f.id for f in resultado.faltantes}
