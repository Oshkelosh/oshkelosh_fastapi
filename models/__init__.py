"""Oshkelosh domain models.

All SQLModel table classes live here and are exported from this package so
consumers can do ``from models import User, Product, Category`` etc.
"""

from models.user import User
from models.product import Product
from models.product_image import ProductImage
from models.product_variant import ProductVariant
from models.category import Category
from models.cart import Cart
from models.cart_item import CartItem
from models.order import Order
from models.order_item import OrderItem
from models.addon_config import AddonConfig
from models.site_settings import SiteSettings
from models.audit_log import AuditLog
from models.processed_webhook_event import ProcessedWebhookEvent
from models.manual_supplier import ManualSupplier
from models.notification_template import NotificationTemplate
from models.order_idempotency_key import OrderIdempotencyKey
from models.background_job import BackgroundJob

__all__ = [
    "User",
    "Product",
    "ProductImage",
    "ProductVariant",
    "Category",
    "Cart",
    "CartItem",
    "Order",
    "OrderItem",
    "AddonConfig",
    "SiteSettings",
    "AuditLog",
    "ProcessedWebhookEvent",
    "ManualSupplier",
    "NotificationTemplate",
    "OrderIdempotencyKey",
    "BackgroundJob",
]
