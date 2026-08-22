"""
Pruebas de trazabilidad de sincronización — deben poder reconstruir
exactamente los dos ejemplos que dio el dueño:

  21/08/2026 20:31 — WooCommerce → Mercado Libre — 153 productos — Correcto
  21/08/2026 20:35 — WooCommerce → Mercado Libre — Error — SKU-123 — stock inválido

No se ejecuta ninguna sincronización real acá — solo se prueba que la
estructura puede guardar y consultar este historial.
"""

from __future__ import annotations

from datetime import datetime

from app.db.models import Product, ProductVariant, SyncJob, SyncLog


def test_sincronizacion_exitosa_se_puede_leer_como_una_linea_de_historial(db_session, a_store, now):
    job = SyncJob(
        store=a_store,
        direction="woocommerce_to_ml",
        triggered_by="manual",
        started_at=datetime(2026, 8, 21, 20, 31),
        finished_at=datetime(2026, 8, 21, 20, 32),
        status="success",
        products_affected=153,
    )
    db_session.add(job)
    db_session.commit()

    linea = f"{job.started_at.strftime('%d/%m/%Y %H:%M')} — {job.direction} — {job.products_affected} productos — {job.status}"
    assert "153 productos" in linea
    assert job.status == "success"


def test_sincronizacion_con_error_registra_el_producto_y_el_motivo(db_session, a_store, now):
    product = Product(store=a_store, name="Producto con error", product_type="simple", created_at=now, updated_at=now)
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(product=product, store_id=a_store.id, variant_sku="SKU-123", created_at=now, updated_at=now)
    db_session.add(variant)
    db_session.flush()

    job = SyncJob(
        store=a_store,
        direction="woocommerce_to_ml",
        started_at=datetime(2026, 8, 21, 20, 35),
        status="error",
        products_affected=0,
    )
    db_session.add(job)
    db_session.flush()
    db_session.add(SyncLog(job=job, variant=variant, level="error", message="stock inválido", created_at=now))
    db_session.commit()

    assert job.logs[0].message == "stock inválido"
    assert job.logs[0].variant.variant_sku == "SKU-123"
    assert job.status == "error"


def test_una_sincronizacion_puede_tener_varios_logs(db_session, a_store, now):
    job = SyncJob(store=a_store, direction="ml_to_woocommerce", started_at=now, status="partial_error", products_affected=50)
    db_session.add(job)
    db_session.flush()
    db_session.add_all(
        [
            SyncLog(job=job, level="info", message="Sincronización iniciada", created_at=now),
            SyncLog(job=job, level="error", message="Producto SKU-9 sin stock válido", created_at=now),
            SyncLog(job=job, level="warning", message="Precio no coincide, se usó el de origen", created_at=now),
        ]
    )
    db_session.commit()

    assert len(job.logs) == 3
    assert sum(1 for log in job.logs if log.level == "error") == 1
