"""
Importa todos los módulos de modelos para que `Base.metadata` (usado por
Alembic y por `Base.metadata.create_all` en los tests) siempre vea el
conjunto completo de tablas, sin importar qué módulo se haya importado
primero en otro lado del código.
"""

from app.db.base import Base
from app.db.models.admin_log import AdminActionLog  # noqa: F401
from app.db.models.channel_costs import ChannelCostSettings  # noqa: F401
from app.db.models.marketplace import (  # noqa: F401
    MarketplaceAccount,
    MarketplaceListing,
    MarketplaceListingVariant,
    MercadoLibreCategoryFee,
)
from app.db.models.orders import Order, OrderItem  # noqa: F401
from app.db.models.products import Product, ProductImage, ProductVariant  # noqa: F401
from app.db.models.returns import OrderReturn  # noqa: F401
from app.db.models.stock import StockMovement  # noqa: F401
from app.db.models.stores import Store, StoreSettings  # noqa: F401
from app.db.models.subscriptions import Plan, Subscription  # noqa: F401
from app.db.models.support import SupportTicket  # noqa: F401
from app.db.models.sync import SyncJob, SyncLog  # noqa: F401
from app.db.models.users import (  # noqa: F401
    AuthSession,
    PasswordResetToken,
    User,
    UserPreferences,
)
from app.db.models.woocommerce_link import WooCommerceProduct, WooCommerceVariation  # noqa: F401

__all__ = [
    "Base",
    "User",
    "UserPreferences",
    "AuthSession",
    "PasswordResetToken",
    "Store",
    "StoreSettings",
    "Plan",
    "Subscription",
    "Product",
    "ProductVariant",
    "ProductImage",
    "WooCommerceProduct",
    "WooCommerceVariation",
    "ChannelCostSettings",
    "MarketplaceAccount",
    "MarketplaceListing",
    "MarketplaceListingVariant",
    "MercadoLibreCategoryFee",
    "Order",
    "OrderItem",
    "OrderReturn",
    "SyncJob",
    "SyncLog",
    "StockMovement",
    "SupportTicket",
    "AdminActionLog",
]
