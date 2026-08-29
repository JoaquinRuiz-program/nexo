"""
Pruebas de app/domain/ai_content.py — sobre todo, que nunca inventa un
dato que no vino en el producto (es una simulación por reglas, no IA real).
"""

from __future__ import annotations

from app.domain.ai_content import extract_attributes, generate_content, generate_description, generate_title


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
