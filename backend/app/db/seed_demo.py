"""
Datos de prueba para la base de datos propia — hace las veces de
"WooCommerce real" mientras el dueño no tenga acceso definitivo a la API de
un cliente real (ver decisión del 22 de agosto de 2026: no depender de esas
credenciales para seguir avanzando). Usa exactamente los mismos modelos
(`Product`/`ProductVariant`) que va a llenar, más adelante, el job de
sincronización real de WooCommerce — así que el día que ese job exista, ni
los endpoints ni el frontend necesitan cambiar, solo cambia quién llena la
tabla.

Idempotente: si el usuario demo ya existe, no vuelve a insertar nada (evita
duplicar productos cada vez que se corre).

Uso:
    cd backend
    python -m app.db.seed_demo
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Product, ProductVariant, Store, StoreSettings, User
from app.db.session import SessionLocal
from app.domain.security import hash_password

DEMO_USER_EMAIL = "demo@nexo.local"

# Productos con una sola variante (sin color) — (sku, nombre, categoria, precio, stock)
PRODUCTOS_SIMPLES = [
    ("LIB-001", "Cien años de soledad", "Libros", 12990, 34),
    ("LIB-002", "Rayuela", "Libros", 11490, 22),
    ("LIB-003", "El túnel", "Libros", 8990, 3),
    ("LIB-004", "1984", "Libros", 9990, 0),
    ("LIB-005", "El principito", "Libros", 7990, 48),
    ("LIB-006", "Sapiens: de animales a dioses", "Libros", 16990, 31),
    ("ESC-001", "Diccionario escolar ilustrado", "Escolares", 11990, 20),
    ("ESC-002", "Atlas geográfico escolar", "Escolares", 13990, 8),
    ("AGE-001", "Agenda semanal 2027", "Agendas", 8990, 11),
    ("OFI-001", "Organizador de escritorio", "Oficina", 12990, 5),
    ("OFI-002", "Resma papel carta 500 hojas", "Oficina", 5490, 60),
    ("PAP-001", "Set de lápices de colores x12", "Papelería", 4990, 25),
    ("PAP-002", "Goma de borrar blanca", "Papelería", 690, 0),
]

# Productos con variantes de color — (nombre, categoria, precio_base, [(color, sku, stock), ...])
PRODUCTOS_VARIABLES = [
    (
        "Cuaderno universitario 100 hojas cuadriculado",
        "Cuadernos",
        3490,
        [
            ("Azul", "CUA-001-AZU", 25),
            ("Rojo", "CUA-001-ROJ", 3),
            ("Verde", "CUA-001-VER", 0),
            ("Negro", "CUA-001-NEG", 14),
        ],
    ),
    (
        "Croquera tapa dura A5",
        "Cuadernos",
        5990,
        [
            ("Negro", "CUA-002-NEG", 16),
            ("Kraft", "CUA-002-KRA", 9),
        ],
    ),
    (
        "Resaltador fluorescente",
        "Papelería",
        990,
        [
            ("Amarillo", "PAP-003-AMA", 40),
            ("Rosado", "PAP-003-ROS", 12),
            ("Verde", "PAP-003-VER", 0),
        ],
    ),
]


def seed_demo_data(session: Session) -> Store:
    """Crea (si no existen) el usuario/tienda demo y el catálogo de prueba.
    Devuelve la tienda, ya sea recién creada o la existente."""
    usuario_existente = session.query(User).filter_by(email=DEMO_USER_EMAIL).first()
    if usuario_existente is not None:
        return usuario_existente.stores[0]

    now = datetime.now()

    # No es una cuenta de login real todavía (no hay endpoint de auth) —
    # solo satisface la relación Store -> User que exige el modelo.
    usuario = User(
        email=DEMO_USER_EMAIL,
        password_hash=hash_password("solo-datos-de-prueba"),
        full_name="Cuenta de datos de prueba",
        created_at=now,
        updated_at=now,
    )
    session.add(usuario)

    tienda = Store(owner=usuario, name="Empresa Demo (datos de prueba)", created_at=now)
    session.add(tienda)
    session.add(
        StoreSettings(
            store=tienda,
            company_name="Empresa Demo",
            store_name="Empresa Demo (datos de prueba)",
        )
    )
    session.flush()

    for sku, nombre, categoria, precio, stock in PRODUCTOS_SIMPLES:
        producto = Product(
            store=tienda,
            internal_sku=sku,
            name=nombre,
            product_type="simple",
            category=categoria,
            created_at=now,
            updated_at=now,
        )
        session.add(producto)
        session.flush()
        session.add(
            ProductVariant(
                product=producto,
                store_id=tienda.id,
                variant_sku=sku,
                price=precio,
                stock_quantity=stock,
                manage_stock=True,
                stock_status="instock" if stock > 0 else "outofstock",
                created_at=now,
                updated_at=now,
            )
        )

    for nombre, categoria, precio_base, variantes in PRODUCTOS_VARIABLES:
        producto = Product(
            store=tienda,
            internal_sku=None,  # el padre "variable" no tiene SKU propio, igual que en WooCommerce real
            name=nombre,
            product_type="variable",
            category=categoria,
            created_at=now,
            updated_at=now,
        )
        session.add(producto)
        session.flush()
        for color, sku, stock in variantes:
            session.add(
                ProductVariant(
                    product=producto,
                    store_id=tienda.id,
                    variant_sku=sku,
                    variant_label=color,
                    price=precio_base,
                    stock_quantity=stock,
                    manage_stock=True,
                    stock_status="instock" if stock > 0 else "outofstock",
                    created_at=now,
                    updated_at=now,
                )
            )

    session.commit()
    return tienda


if __name__ == "__main__":
    db = SessionLocal()
    try:
        store = seed_demo_data(db)
        total_productos = db.query(Product).filter_by(store_id=store.id).count()
        total_variantes = db.query(ProductVariant).filter_by(store_id=store.id).count()
        print(f"Tienda demo: {store.name!r} (id={store.id})")
        print(f"Productos: {total_productos} — Variantes/filas: {total_variantes}")
    finally:
        db.close()
