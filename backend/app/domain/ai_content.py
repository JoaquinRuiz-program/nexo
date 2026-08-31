"""
Generación de título/descripción/atributos para una publicación — SIMULADA
con reglas, NO con un modelo de IA real (24 de agosto de 2026, pedido
explícito del dueño: dejar el reemplazo por IA real como una pieza aparte,
intercambiable, no mezclada con el resto del sistema).

Regla que gobierna TODO este archivo: nunca se inventa un dato comercial
que no esté en el producto. Si falta la marca, el título no menciona una
marca. Si no hay descripción cargada, se arma una oración con los campos
que sí existen — nunca se completa con una característica supuesta
("resistente al agua", "última generación", etc. NUNCA aparecen acá salvo
que vengan literalmente en los datos del producto).

Cuando llegue un modelo de IA real, el contrato a mantener es el mismo:
estas tres funciones reciben un producto y devuelven texto/datos — quien
las llama (domain/listing_draft.py) no sabe ni le importa si el título
salió de una regla o de un modelo. Reemplazar la implementación acá adentro
no debería obligar a tocar nada más.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Mercado Libre trunca títulos largos — 60 caracteres es el límite típico
# de la mayoría de las categorías (no confirmado con la API real todavía,
# ver GeneratedContent.simulado).
TITLE_MAX_LENGTH = 60


@dataclass(frozen=True)
class GeneratedContent:
    titulo: str
    descripcion: str
    atributos: dict[str, str]
    simulado: bool = True  # False el día que esto lo genere un modelo real


def generate_title(
    *, nombre: str, marca: Optional[str] = None, modelo: Optional[str] = None, max_length: int = TITLE_MAX_LENGTH
) -> str:
    """Antepone la marca y agrega el modelo si existen y no están ya
    mencionados en el nombre — nunca agrega adjetivos ni características
    que no vinieron en los datos.

    `max_length`: 60 por defecto (límite típico), pero se puede pasar el
    `max_title_length` REAL de la categoría (ver
    MercadoLibreAdapter.get_category, 30 de agosto de 2026) para no
    truncar de más ni de menos — nunca se inventa un límite."""
    nombre = nombre.strip()
    partes = [nombre]
    if marca and marca.strip().lower() not in nombre.lower():
        partes.insert(0, marca.strip())
    if modelo and modelo.strip().lower() not in nombre.lower():
        partes.append(modelo.strip())
    titulo = " ".join(partes)
    if len(titulo) > max_length:
        titulo = titulo[: max_length - 1].rstrip() + "…"
    return titulo


def generate_description(
    *, nombre: str, marca: Optional[str] = None, categoria: Optional[str] = None, descripcion_original: Optional[str] = None
) -> str:
    """Si ya hay una descripción cargada, se usa tal cual (es información
    real del vendedor, no hay nada que "mejorar" inventando). Si no hay
    ninguna, arma una oración simple solo con los campos que sí existen."""
    if descripcion_original and descripcion_original.strip():
        return descripcion_original.strip()

    partes = [nombre.strip()]
    if marca:
        partes.append(f"Marca {marca.strip()}")
    if categoria:
        partes.append(f"Categoría: {categoria.strip()}")
    return ". ".join(partes) + "."


def extract_attributes(*, marca: Optional[str] = None, codigo_barras: Optional[str] = None, variant_label: Optional[str] = None) -> dict[str, str]:
    """Extrae SOLO lo que ya viene en los datos del producto — nunca
    "adivina" material, capacidad, modelo, etc. a partir del nombre. Eso
    requeriría interpretar texto libre, que es exactamente el trabajo que
    le corresponde a un modelo de IA real más adelante, no a una regla."""
    atributos: dict[str, str] = {}
    if marca:
        atributos["Marca"] = marca.strip()
    if codigo_barras:
        atributos["Código de barras"] = codigo_barras.strip()
    if variant_label:
        atributos["Variante"] = variant_label.strip()
    return atributos


DESCRIPCION_CORTA_MAX_LENGTH = 160


@dataclass(frozen=True)
class DescripcionGenerada:
    corta: str
    completa: str
    # Lista de líneas tipo "Marca: Torre" — para mostrar como viñetas.
    caracteristicas: list[str]
    # Mismos datos que `caracteristicas`, en forma de dict — para uso
    # programático (ej. mostrar una tabla, o mandarlos como atributos).
    especificaciones: dict[str, str]
    simulado: bool = True


def generate_full_description(
    *,
    nombre: str,
    marca: Optional[str] = None,
    categoria: Optional[str] = None,
    descripcion_original: Optional[str] = None,
    codigo_barras: Optional[str] = None,
    variant_label: Optional[str] = None,
    atributos_confirmados: Optional[dict[str, str]] = None,
) -> DescripcionGenerada:
    """30 de agosto de 2026 — FASE 3 (títulos/descripciones): versión
    "revisable antes de publicar" de la descripción — corta + completa +
    características + especificaciones, para mostrar en /preparar antes de
    que el dueño confirme. Misma regla de siempre: NUNCA se inventa un
    material, medida, garantía, certificación o accesorio que no esté
    literalmente en los datos del producto. `atributos_confirmados` son
    pares nombre-valor que Nexo YA CONFIRMÓ como reales (ej. MODEL/COLOR
    que el dueño completó en /validar) — nunca datos supuestos."""
    especificaciones: dict[str, str] = {}
    if marca:
        especificaciones["Marca"] = marca.strip()
    if categoria:
        especificaciones["Categoría"] = categoria.strip()
    if variant_label:
        especificaciones["Variante"] = variant_label.strip()
    if codigo_barras:
        especificaciones["Código de barras"] = codigo_barras.strip()
    for clave, valor in (atributos_confirmados or {}).items():
        if valor:
            especificaciones[clave] = valor.strip()

    caracteristicas = [f"{clave}: {valor}" for clave, valor in especificaciones.items()]

    if descripcion_original and descripcion_original.strip():
        completa = descripcion_original.strip()
        corta = completa if len(completa) <= DESCRIPCION_CORTA_MAX_LENGTH else completa[: DESCRIPCION_CORTA_MAX_LENGTH - 1].rstrip() + "…"
    else:
        # Sin descripción cargada por el vendedor: se arma una oración
        # simple solo con los campos que sí existen, igual criterio que
        # generate_description — nunca se completa con un adjetivo o
        # característica supuesta.
        oracion = generate_description(
            nombre=nombre, marca=marca, categoria=categoria, descripcion_original=None
        )
        if caracteristicas:
            completa = oracion + "\n\n" + "\n".join(f"- {c}" for c in caracteristicas)
        else:
            completa = oracion
        corta = oracion if len(oracion) <= DESCRIPCION_CORTA_MAX_LENGTH else oracion[: DESCRIPCION_CORTA_MAX_LENGTH - 1].rstrip() + "…"

    return DescripcionGenerada(corta=corta, completa=completa, caracteristicas=caracteristicas, especificaciones=especificaciones)


def generate_content(
    *,
    nombre: str,
    marca: Optional[str] = None,
    categoria: Optional[str] = None,
    descripcion_original: Optional[str] = None,
    codigo_barras: Optional[str] = None,
    variant_label: Optional[str] = None,
) -> GeneratedContent:
    return GeneratedContent(
        titulo=generate_title(nombre=nombre, marca=marca),
        descripcion=generate_description(
            nombre=nombre, marca=marca, categoria=categoria, descripcion_original=descripcion_original
        ),
        atributos=extract_attributes(marca=marca, codigo_barras=codigo_barras, variant_label=variant_label),
    )
