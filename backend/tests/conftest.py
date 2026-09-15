"""
Configuración común de pytest.

15 de septiembre de 2026 — importar un catálogo sin Mercado Libre conectado
predice categorías en segundo plano contra la API pública de Mercado Libre
(services/ml_comisiones.py::_solo_predecir_categorias). Los tests nunca deben
salir a la red real: se desactiva acá para todos. Los tests de esa función la
importan directamente y la prueban con respx.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _sin_prediccion_de_categorias_en_red(monkeypatch):
    async def _no_hacer_nada(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.ml_comisiones._solo_predecir_categorias", _no_hacer_nada)
