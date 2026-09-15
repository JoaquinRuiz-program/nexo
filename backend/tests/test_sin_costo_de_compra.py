"""Productos sin costo de compra registrado (15 de septiembre de 2026) — ej. un
repuesto que una automotora retiró de un vehículo y quiere vender. El costo
considerado es $0, la ganancia descuenta igual comisión, envío y otros costos
de Mercado Libre, y el precio de venta del Excel se respeta."""

from __future__ import annotations

from app.domain.catalog_import import AVISO_SIN_COSTO, build_rows, detect_columns
from tests.test_rentabilidad import _producto_con_precio_y_costo, a_store, client, db_session  # noqa: F401 — fixtures


def _configurar_ml(client, **extra):
    body = {"commission_pct": 15.0, "shipping_cost": 5000, "other_fixed_cost": 0, "min_margin_pct": 15, "min_profit_clp": 3000, "target_margin_pct": 30}
    body.update(extra)
    assert client.put("/api/configuracion/canales/mercadolibre", json=body).status_code == 200


def _fila(client, sku):
    productos = client.get("/api/seleccion", params={"canal": "mercadolibre"}).json()["productos"]
    return next(p for p in productos if p["sku"] == sku)


def test_caso_a_con_costo_usa_la_logica_normal(client, db_session, a_store):
    _producto_con_precio_y_costo(db_session, a_store, sku="A", nombre="Producto comprado", precio=80000, costo=50000)
    _configurar_ml(client)
    fila = _fila(client, "A")
    assert fila["tieneCosto"] is True
    assert fila["margenMercadoLibreClp"] == 80000 - 50000 - 12000 - 5000
    assert fila["clasificacion"] == "rentable"


def test_caso_b_y_f_sin_costo_se_calcula_con_costo_cero_y_descuenta_costos_ml(client, db_session, a_store):
    _producto_con_precio_y_costo(db_session, a_store, sku="B", nombre="Repuesto retirado", precio=80000, costo=None)
    _configurar_ml(client, other_fixed_cost=1000)
    fila = _fila(client, "B")
    assert fila["tieneCosto"] is False and fila["costo"] is None
    # Comisión 15 % (12.000), envío (5.000) y otros costos (1.000) se descuentan igual.
    assert fila["margenMercadoLibreClp"] == 80000 - 12000 - 5000 - 1000
    assert fila["clasificacion"] == "rentable"

    decision = client.get(f"/api/publicaciones/{fila['id']}/mercadolibre/decision").json()
    assert decision["decision"] == "conviene"
    assert decision["gananciaActual"] == 62000


def test_caso_e_sin_costo_se_respeta_el_precio_de_venta_y_no_se_inventa_otro(client, db_session, a_store):
    _producto_con_precio_y_costo(db_session, a_store, sku="E", nombre="Repuesto", precio=80000, costo=None)
    _configurar_ml(client)
    variant_id = _fila(client, "E")["id"]

    borrador = client.get(f"/api/publicaciones/borrador/{variant_id}", params={"canal": "mercadolibre"})
    assert borrador.status_code == 200, borrador.text
    assert borrador.json()["precio"] == 80000
    # El precio para el margen objetivo sale del costo: sin costo no se recomienda uno.
    precio = client.get(f"/api/publicaciones/{variant_id}/mercadolibre/precio-recomendado").json()
    assert precio["precioRecomendado"] is None
    assert "costo de compra" in precio["faltantes"]


def test_caso_c_sin_costo_y_sin_precio_queda_pendiente(client, db_session, a_store):
    _producto_con_precio_y_costo(db_session, a_store, sku="C", nombre="Sin precio", precio=None, costo=None)
    _configurar_ml(client)
    fila = _fila(client, "C")
    assert fila["clasificacion"] == "sin_datos"
    assert fila["margenMercadoLibreClp"] is None
    decision = client.get(f"/api/publicaciones/{fila['id']}/mercadolibre/decision").json()
    assert decision["decision"] == "revisar"


def test_caso_d_costo_explicito_cero_no_es_un_dato_invalido(client, db_session, a_store):
    _producto_con_precio_y_costo(db_session, a_store, sku="D", nombre="Costo cero", precio=80000, costo=0)
    _configurar_ml(client)
    fila = _fila(client, "D")
    assert fila["tieneCosto"] is True and fila["costo"] == 0
    assert fila["margenMercadoLibreClp"] == 80000 - 12000 - 5000
    assert fila["clasificacion"] == "rentable"


def test_importador_sin_costo_no_rechaza_ni_deja_en_revision():
    mapping = detect_columns(["Nombre", "Costo", "Precio"])
    filas = build_rows([
        {"Nombre": "Repuesto sin costo", "Costo": "", "Precio": "80000"},
        {"Nombre": "Costo cero", "Costo": "0", "Precio": "80000"},
        {"Nombre": "Sin costo ni precio", "Costo": "", "Precio": ""},
    ], mapping)
    sin_costo, costo_cero, sin_nada = filas
    assert (sin_costo.estado, sin_costo.costo, sin_costo.precio) == ("valido", None, 80000)
    assert AVISO_SIN_COSTO in sin_costo.problemas
    assert (costo_cero.estado, costo_cero.costo) == ("valido", 0)
    assert AVISO_SIN_COSTO not in costo_cero.problemas
    assert sin_nada.estado == "revision" and "Falta precio de venta" in sin_nada.problemas
