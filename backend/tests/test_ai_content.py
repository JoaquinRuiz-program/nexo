"""
Pruebas de app/domain/ai_content.py — sobre todo, que nunca inventa un
dato que no vino en el producto (es una simulación por reglas, no IA real).
"""

from __future__ import annotations

from app.domain.ai_content import (
    extract_attributes,
    generate_content,
    generate_description,
    generate_full_description,
    generate_title,
)


def test_titulo_antepone_la_marca_si_no_esta_ya_en_el_nombre():
    assert generate_title(nombre="Cuaderno universitario", marca="Torre") == "Torre Cuaderno universitario"


def test_titulo_no_duplica_la_marca_si_ya_esta_en_el_nombre():
    assert generate_title(nombre="Mochila Totto urbana", marca="Totto") == "Mochila Totto urbana"


def test_titulo_sin_marca_usa_solo_el_nombre():
    assert generate_title(nombre="Producto genérico") == "Producto genérico"


def test_titulo_se_trunca_al_limite_de_mercado_libre():
    nombre_largo = "Producto con un nombre extremadamente largo que supera el límite típico de caracteres permitidos"
    titulo = generate_title(nombre=nombre_largo, marca="MarcaX")
    assert len(titulo) <= 60
    assert titulo.endswith("…")


def test_descripcion_usa_la_original_si_existe_tal_cual():
    resultado = generate_description(nombre="Producto", descripcion_original="  Descripción real del vendedor.  ")
    assert resultado == "Descripción real del vendedor."


def test_descripcion_sin_original_arma_una_frase_solo_con_datos_reales():
    resultado = generate_description(nombre="Taladro percutor", marca="Bosch", categoria="Herramientas")
    assert resultado == "Taladro percutor. Marca Bosch. Categoría: Herramientas."
    # Nunca inventa un adjetivo o característica que no vino en los datos.
    for palabra_inventada in ["resistente", "última generación", "premium", "profesional"]:
        assert palabra_inventada not in resultado.lower()


def test_atributos_solo_incluye_lo_que_existe():
    atributos = extract_attributes(marca="Bosch", codigo_barras="123456", variant_label=None)
    assert atributos == {"Marca": "Bosch", "Código de barras": "123456"}
    assert "Variante" not in atributos


def test_atributos_vacios_si_no_hay_ningun_dato():
    assert extract_attributes() == {}


def test_generate_content_queda_marcado_como_simulado():
    contenido = generate_content(nombre="Producto de prueba", marca="MarcaX")
    assert contenido.simulado is True
    assert contenido.titulo == "MarcaX Producto de prueba"


# ------------------------------------------------------------------
# generate_title — modelo + max_length real (30 de agosto de 2026, FASE 3)
# ------------------------------------------------------------------


def test_titulo_agrega_el_modelo_si_no_esta_ya_en_el_nombre():
    assert generate_title(nombre="Calculadora Científica", marca="Casio", modelo="FX-991LA CW") == "Casio Calculadora Científica FX-991LA CW"


def test_titulo_no_duplica_el_modelo_si_ya_esta_en_el_nombre():
    assert generate_title(nombre="Cuaderno Moleskine Clásico", marca="Moleskine", modelo="Clásico") == "Cuaderno Moleskine Clásico"


def test_titulo_respeta_el_max_length_real_de_la_categoria_no_el_default():
    nombre_largo = "Producto con un nombre que supera treinta caracteres"
    titulo = generate_title(nombre=nombre_largo, max_length=30)
    assert len(titulo) <= 30
    assert titulo.endswith("…")


def test_titulo_default_sigue_siendo_60_si_no_se_pasa_max_length():
    nombre_largo = "Producto con un nombre extremadamente largo que supera el límite típico de caracteres permitidos"
    assert len(generate_title(nombre=nombre_largo)) <= 60


# ------------------------------------------------------------------
# generate_full_description — corta/completa/características/especificaciones
# (30 de agosto de 2026, FASE 3) — nunca inventa nada.
# ------------------------------------------------------------------


def test_descripcion_completa_usa_la_original_tal_cual():
    resultado = generate_full_description(nombre="Producto", descripcion_original="Descripción real del vendedor.")
    assert resultado.completa == "Descripción real del vendedor."
    assert resultado.corta == "Descripción real del vendedor."


def test_descripcion_corta_se_trunca_si_la_original_es_muy_larga():
    original = "X" * 300
    resultado = generate_full_description(nombre="Producto", descripcion_original=original)
    assert len(resultado.corta) <= 160
    assert resultado.corta.endswith("…")
    assert resultado.completa == original  # la completa NUNCA se trunca


def test_descripcion_sin_original_arma_caracteristicas_solo_con_datos_reales():
    resultado = generate_full_description(
        nombre="Cuaderno Moleskine Clásico", marca="Moleskine", categoria="Cuadernos",
        codigo_barras="9788883701122", variant_label="Negro",
        atributos_confirmados={"MODEL": "Clásico", "COLOR": "Negro"},
    )
    assert resultado.especificaciones == {
        "Marca": "Moleskine", "Categoría": "Cuadernos", "Variante": "Negro",
        "Código de barras": "9788883701122", "MODEL": "Clásico", "COLOR": "Negro",
    }
    assert "Marca: Moleskine" in resultado.caracteristicas
    assert "MODEL: Clásico" in resultado.caracteristicas
    # Nunca inventa un adjetivo o característica que no vino en los datos.
    for palabra_inventada in ["resistente al agua", "última generación", "premium", "profesional", "garantía"]:
        assert palabra_inventada not in resultado.completa.lower()


def test_descripcion_sin_ningun_dato_no_rompe():
    resultado = generate_full_description(nombre="Producto genérico")
    assert resultado.especificaciones == {}
    assert resultado.caracteristicas == []
    assert resultado.completa == "Producto genérico."


def test_descripcion_ignora_atributos_confirmados_vacios():
    resultado = generate_full_description(nombre="Producto", atributos_confirmados={"COLOR": "", "MODEL": "X"})
    assert "COLOR" not in resultado.especificaciones
    assert resultado.especificaciones["MODEL"] == "X"
