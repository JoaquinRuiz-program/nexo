"""
Pruebas de app/db/seed_demo.py — el generador de datos de prueba que hace de
"WooCommerce real" mientras no tengamos acceso definitivo al de la librería.
Corre contra la misma base SQLite en memoria que el resto de tests/db/ (ver
conftest.py), nunca contra libreria_central.db.
"""

from __future__ import annotations

from app.db.models import Product, ProductVariant, Store, User
from app.db.seed_demo import DEMO_USER_EMAIL, seed_demo_data


def test_seed_crea_tienda_y_productos(db_session):
    store = seed_demo_data(db_session)

    assert isinstance(store, Store)
    assert db_session.query(User).filter_by(email=DEMO_USER_EMAIL).count() == 1
    assert db_session.query(Product).count() > 0
    assert db_session.query(ProductVariant).count() > 0


def test_seed_incluye_productos_simples_y_variables(db_session):
    seed_demo_data(db_session)

    simples = db_session.query(Product).filter_by(product_type="simple").all()
    variables = db_session.query(Product).filter_by(product_type="variable").all()
    assert len(simples) > 0
    assert len(variables) > 0
    # Todo producto variable tiene más de una variante (una por color).
    assert all(len(p.variants) > 1 for p in variables)
    # Todo producto simple tiene exactamente una variante.
    assert all(len(p.variants) == 1 for p in simples)


def test_seed_es_idempotente(db_session):
    store1 = seed_demo_data(db_session)
    productos_antes = db_session.query(Product).count()
    variantes_antes = db_session.query(ProductVariant).count()

    store2 = seed_demo_data(db_session)

    assert store2.id == store1.id
    assert db_session.query(Product).count() == productos_antes
    assert db_session.query(ProductVariant).count() == variantes_antes
