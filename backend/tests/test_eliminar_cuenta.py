"""
Eliminar la cuenta desde la aplicación (15 de septiembre de 2026). Borra
todo lo de la empresa del usuario, nunca lo de otra, y cancela antes el
cobro mensual en Mercado Pago.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from app.config import Settings
from app.db.models import (
    AuthSession,
    ChannelCostSettings,
    MarketplaceAccount,
    MarketplaceListing,
    MarketplaceListingVariant,
    MercadoLibreCategoryFee,
    MercadoLibreShippingEstimate,
    Order,
    OrderBilling,
    OrderInvoice,
    OrderItem,
    OrderReturn,
    Plan,
    Product,
    ProductImage,
    ProductVariant,
    Store,
    StoreSettings,
    Subscription,
    SupportTicket,
    SyncJob,
    SyncLog,
    User,
)
from tests.test_auth import REGISTRO_VALIDO, _sin_intentos_previos, client, db_session  # noqa: F401 — fixtures

NOW = datetime(2026, 9, 15, 12, 0, 0)
PASSWORD = "contraseña-segura-123"


def _registrar(client, db_session, email):
    res = client.post("/api/auth/registro", json={**REGISTRO_VALIDO, "email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    usuario = db_session.query(User).filter_by(email=email).one()
    return usuario, db_session.query(Store).filter_by(owner_user_id=usuario.id).one()


def _llenar_empresa(db_session, tienda, usuario, *, url_imagen="https://cdn.externo.cl/img.png"):
    producto = Product(store=tienda, internal_sku=f"SKU-{tienda.id}", name="Producto", product_type="simple", created_at=NOW, updated_at=NOW)
    db_session.add(producto)
    db_session.flush()
    variante = ProductVariant(product=producto, store_id=tienda.id, variant_sku=f"SKU-{tienda.id}", price=10000, created_at=NOW, updated_at=NOW)
    db_session.add_all([variante, ProductImage(product=producto, url=url_imagen, source="upload", position=0, created_at=NOW)])
    cuenta = MarketplaceAccount(store=tienda, marketplace="mercadolibre", status="connected", external_account_id=f"{tienda.id}")
    db_session.add(cuenta)
    db_session.flush()
    publicacion = MarketplaceListing(account_id=cuenta.id, product_id=producto.id, external_listing_id=f"MLC{tienda.id}", created_at=NOW)
    db_session.add(publicacion)
    db_session.flush()
    db_session.add(MarketplaceListingVariant(listing_id=publicacion.id, variant_id=variante.id))
    orden = Order(store=tienda, channel="mercadolibre", external_order_id=f"200{tienda.id}", order_date=NOW, status="completado", total_amount=10000, created_at=NOW, updated_at=NOW)
    db_session.add(orden)
    db_session.flush()
    db_session.add_all([
        OrderItem(order=orden, variant_id=variante.id, quantity=1, unit_price=10000, created_at=NOW),
        OrderReturn(store_id=tienda.id, order_id=orden.id, external_claim_id=f"{tienda.id}", claim_type="return", fetched_at=NOW),
        OrderBilling(store_id=tienda.id, order_id=orden.id, has_charges=True, billed_sale_fee=1200, billed_shipping=0, billed_other=0, fetched_at=NOW),
        OrderInvoice(store_id=tienda.id, order_id=orden.id, pack_id="1", document_ids="x", file_names="f.pdf", uploaded_at=NOW),
        ChannelCostSettings(store=tienda, channel="mercadolibre", commission_pct=15, updated_at=NOW),
        SupportTicket(store_id=tienda.id, user_id=usuario.id, category="otro", subject="Hola", description="Ayuda", created_at=NOW, updated_at=NOW),
        # Cachés de Mercado Libre de ESTA empresa: también se borran (en
        # Postgres, dejarlas rompería la clave foránea contra stores).
        MercadoLibreCategoryFee(store_id=tienda.id, category_id="MLC1", listing_type_id="gold_special", price=10000,
                                percentage_fee=15, fixed_fee=0, sale_fee_amount=1500, fetched_at=NOW),
        MercadoLibreShippingEstimate(store_id=tienda.id, category_id="MLC1", price=10000, shipping_cost=3050,
                                     mandatory=True, dimensions="5x15x15,300", fetched_at=NOW),
    ])
    job = SyncJob(store_id=tienda.id, direction="ml_stock", triggered_by="manual", started_at=NOW, finished_at=NOW, status="success", products_affected=1)
    db_session.add(job)
    db_session.flush()
    db_session.add(SyncLog(job=job, variant_id=variante.id, level="warning", message="aviso", created_at=NOW))
    db_session.commit()


def _conteo(db_session, store_id):
    return {
        modelo.__name__: db_session.query(modelo).filter_by(store_id=store_id).count()
        for modelo in (Product, ProductVariant, Order, OrderReturn, OrderBilling, OrderInvoice, MarketplaceAccount, ChannelCostSettings,
                       SupportTicket, SyncJob, StoreSettings, Subscription, MercadoLibreCategoryFee, MercadoLibreShippingEstimate)
    }


def _eliminar(client, password=PASSWORD, confirmacion="ELIMINAR"):
    return client.post("/api/auth/eliminar-cuenta", json={"password": password, "confirmacion": confirmacion})


def test_elimina_todo_lo_de_la_empresa_y_nada_de_otra(client, db_session):
    usuario_b, tienda_b = _registrar(client, db_session, "otra@empresa.cl")
    _llenar_empresa(db_session, tienda_b, usuario_b)
    conteo_b = _conteo(db_session, tienda_b.id)
    usuario_a, tienda_a = _registrar(client, db_session, "borrar@empresa.cl")
    _llenar_empresa(db_session, tienda_a, usuario_a)
    id_a, store_a = usuario_a.id, tienda_a.id

    res = _eliminar(client)

    assert res.status_code == 200, res.text
    db_session.expire_all()
    assert db_session.get(User, id_a) is None
    assert db_session.get(Store, store_a) is None
    assert all(valor == 0 for valor in _conteo(db_session, store_a).values())
    assert db_session.query(AuthSession).filter_by(user_id=id_a).count() == 0
    assert db_session.query(MarketplaceListing).count() == 1  # solo la de la otra empresa
    assert db_session.query(MarketplaceListingVariant).count() == 1
    assert db_session.query(OrderItem).count() == 1
    assert db_session.query(ProductImage).count() == 1
    assert db_session.query(SyncLog).count() == 1
    assert _conteo(db_session, tienda_b.id) == conteo_b
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": "borrar@empresa.cl", "password": PASSWORD}).status_code == 401


def test_contraseña_incorrecta_no_borra_nada(client, db_session):
    usuario, tienda = _registrar(client, db_session, "mal@empresa.cl")
    res = _eliminar(client, password="no-es-esta")
    assert res.status_code == 400
    assert db_session.get(User, usuario.id) is not None


def test_sin_escribir_eliminar_no_borra_nada(client, db_session):
    usuario, _tienda = _registrar(client, db_session, "confirma@empresa.cl")
    assert _eliminar(client, confirmacion="si").status_code == 400
    assert db_session.get(User, usuario.id) is not None


def test_un_admin_de_nexo_no_puede_eliminarse(client, db_session):
    usuario, _tienda = _registrar(client, db_session, "admin@nexo.cl")
    usuario.is_nexo_admin = True
    db_session.commit()
    assert _eliminar(client).status_code == 400
    assert db_session.get(User, usuario.id) is not None


def _con_suscripcion_mensual(db_session, tienda):
    sub = db_session.query(Subscription).filter_by(store_id=tienda.id).one()
    sub.mercadopago_preapproval_id = "pre-123"
    sub.billing_cycle = "mensual"
    sub.status = "active"
    db_session.commit()


def test_cancela_el_cobro_mensual_antes_de_borrar(client, db_session, monkeypatch):
    usuario, tienda = _registrar(client, db_session, "mensual@empresa.cl")
    _con_suscripcion_mensual(db_session, tienda)
    canceladas = []

    async def _cancelar(preapproval_id, settings):
        canceladas.append(preapproval_id)

    monkeypatch.setattr("app.services.eliminar_cuenta._cancelar_preapproval", _cancelar)

    assert _eliminar(client).status_code == 200
    assert canceladas == ["pre-123"]


def test_si_no_se_puede_cancelar_el_cobro_no_se_borra_la_cuenta(client, db_session, monkeypatch):
    usuario, tienda = _registrar(client, db_session, "falla@empresa.cl")
    _con_suscripcion_mensual(db_session, tienda)

    async def _falla(preapproval_id, settings):
        raise HTTPException(status_code=502, detail="No pudimos cancelar tu suscripción en Mercado Pago")

    monkeypatch.setattr("app.services.eliminar_cuenta._cancelar_preapproval", _falla)

    assert _eliminar(client).status_code == 502
    db_session.expire_all()
    assert db_session.get(User, usuario.id) is not None


def test_borra_las_imagenes_guardadas_en_disco(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.routes.auth.get_settings", lambda: Settings(uploads_dir=str(tmp_path)))
    usuario, tienda = _registrar(client, db_session, "imagenes@empresa.cl")
    carpeta = tmp_path / "product_images" / str(tienda.id)
    carpeta.mkdir(parents=True)
    (carpeta / "foto.png").write_bytes(b"png")
    otra = tmp_path / "product_images" / "999"
    otra.mkdir(parents=True)
    (otra / "ajena.png").write_bytes(b"png")

    assert _eliminar(client).status_code == 200
    assert not carpeta.exists()
    assert (otra / "ajena.png").exists()
