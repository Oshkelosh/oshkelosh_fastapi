"""Import supplier catalogs into local Product + ProductVariant rows."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlmodel import col

from app.addons.suppliers.catalog_utils import ensure_catalog_products
from app.core.exceptions import ValidationError
from app.db.connection import mark_instance_dirty
from app.services.addons import get_enabled, get_supplier_addon
from app.services.audit import log_change
from app.services.product_defaults import (
    apply_product_creation_defaults,
    assign_product_category_from_type,
    refresh_sync_marker_only,
)
from app.services.product_images import import_images_from_urls
from app.services.product_variants import (
    VARIANT_STATUS_ACTIVE,
    VARIANT_STATUS_ARCHIVED,
    refresh_product_listing_cache,
    resolve_unique_variant_sku,
)
from app.services.site_settings import get_site_settings
from app.storage import get_storage
from models.audit_log import AuditLog
from models.product import Product
from models.product_variant import ProductVariant
from schemas.supplier import SupplierCatalogProduct, SupplierCatalogVariant

logger = logging.getLogger(__name__)

__all__ = [
    "SupplierCatalogProduct",
    "SupplierCatalogSyncOptions",
    "SupplierCatalogSyncResult",
    "get_last_sync_times",
    "list_syncable_suppliers",
    "sync_supplier_catalog",
]


@dataclass
class SupplierCatalogSyncOptions:
    import_status: str = "draft"
    archive_missing: bool = False


@dataclass
class SupplierCatalogSyncResult:
    created: int = 0
    updated: int = 0
    variants_created: int = 0
    variants_updated: int = 0
    skipped: int = 0
    archived: int = 0
    variants_archived: int = 0
    errors: list[str] = field(default_factory=list)
    catalog_total: int = 0
    catalog_importable: int = 0

    def summary_message(self, *, addon_id: str | None = None) -> str:
        if self.errors and not (self.created or self.updated or self.archived):
            return f"Sync failed: {self.errors[0]}"
        parts: list[str] = []
        if self.created:
            parts.append(f"created {self.created} products")
        if self.updated:
            parts.append(f"updated {self.updated} products")
        if self.variants_created:
            parts.append(f"{self.variants_created} variants created")
        if self.variants_updated:
            parts.append(f"{self.variants_updated} variants updated")
        if self.skipped:
            parts.append(f"skipped {self.skipped}")
        if self.archived:
            parts.append(f"archived {self.archived} products")
        if self.variants_archived:
            parts.append(f"archived {self.variants_archived} variants")
        if not parts:
            supplier = addon_id or "supplier"
            if self.catalog_total == 0:
                return (
                    f"Sync complete - no changes. {supplier} returned 0 catalog products; "
                    f"check [{supplier}] logs."
                )
            if self.catalog_importable == 0:
                return (
                    f"Sync complete - no changes. {supplier} returned 0 importable variants "
                    f"({self.catalog_total} products, {self.skipped} skipped); "
                    f"check [{supplier}] logs."
                )
            return "Sync complete - no changes."
        return "Catalog sync: " + ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "variants_created": self.variants_created,
            "variants_updated": self.variants_updated,
            "skipped": self.skipped,
            "archived": self.archived,
            "variants_archived": self.variants_archived,
            "errors": list(self.errors),
            "catalog_total": self.catalog_total,
            "catalog_importable": self.catalog_importable,
            "message": self.summary_message(),
        }


def list_syncable_suppliers() -> list[Any]:
    """Return enabled supplier addons that support catalog sync."""
    return [
        addon
        for addon in get_enabled("supplier")
        if addon.supports_catalog_sync()
    ]


async def get_last_sync_times(session: Any) -> dict[str, datetime]:
    """Return latest supplier_catalog_sync audit timestamp per addon id."""
    stmt = (
        select(
            AuditLog.resource_id,
            func.max(AuditLog.created_at).label("last_sync_at"),
        )
        .where(col(AuditLog.action) == "supplier_catalog_sync")
        .where(col(AuditLog.resource_id).is_not(None))
        .group_by(AuditLog.resource_id)
    )
    result = await session.execute(stmt)
    return {
        str(row.resource_id): row.last_sync_at
        for row in result.all()
        if row.resource_id and row.last_sync_at
    }


async def _persist_addon_runtime_config(session: Any, addon_id: str, addon: Any) -> None:
    if not hasattr(addon, "export_config_updates"):
        return
    updates = addon.export_config_updates()
    if not isinstance(updates, dict) or not updates:
        return
    from app.services.addons import merge_config_updates, persist_addon_config

    merged = merge_config_updates(addon_id, updates)
    await persist_addon_config(session, addon_id, merged, addon.is_enabled)


async def _load_variants_for_product(session: Any, product_id: int) -> list[ProductVariant]:
    result = await session.execute(
        select(ProductVariant).where(col(ProductVariant.product_id) == product_id)
    )
    return list(result.scalars().all())


async def _find_product_by_external_key(
    session: Any,
    external_product_key: str,
) -> Product | None:
    result = await session.execute(
        select(Product).where(
            col(Product.supplier_external_product_key) == external_product_key,
        )
    )
    return result.scalar_one_or_none()


async def _find_variant_by_external_key(
    session: Any,
    addon_id: str,
    external_key: str,
) -> ProductVariant | None:
    result = await session.execute(
        select(ProductVariant).where(
            col(ProductVariant.supplier_addon_id) == addon_id,
            col(ProductVariant.supplier_external_key) == external_key,
        )
    )
    return result.scalar_one_or_none()


def _variant_image_urls(variant: SupplierCatalogVariant) -> list[str]:
    urls = list(variant.image_urls)
    return urls


async def _upsert_variant(
    session: Any,
    product: Product,
    catalog_variant: SupplierCatalogVariant,
    addon_id: str,
    *,
    import_status: str,
    storage: Any,
    result: SupplierCatalogSyncResult,
    seen_variant_keys: set[str],
) -> None:
    if catalog_variant.skip_reason:
        result.skipped += 1
        return

    seen_variant_keys.add(catalog_variant.external_key)
    sku = await resolve_unique_variant_sku(session, catalog_variant.sku)
    existing = await _find_variant_by_external_key(
        session, addon_id, catalog_variant.external_key
    )

    if existing is None:
        variant = ProductVariant(
            product_id=product.id,
            title=catalog_variant.title,
            position=len(await _load_variants_for_product(session, product.id)),
            price_cents=catalog_variant.price_cents,
            inventory_quantity=catalog_variant.inventory_quantity,
            sku=sku,
            status=VARIANT_STATUS_ACTIVE,
            attributes=dict(catalog_variant.attributes),
            supplier_addon_id=addon_id,
            supplier_product_id=catalog_variant.supplier_product_id,
            supplier_variant_id=catalog_variant.supplier_variant_id or None,
            supplier_external_key=catalog_variant.external_key,
        )
        session.add(variant)
        await session.flush()
        await import_images_from_urls(
            session,
            product,
            _variant_image_urls(catalog_variant),
            storage=storage,
            alt_text=catalog_variant.title,
            alt_texts=catalog_variant.image_alt_texts or None,
            variant_id=variant.id,
        )
        result.variants_created += 1
        return

    existing.title = catalog_variant.title
    existing.price_cents = catalog_variant.price_cents
    existing.attributes = dict(catalog_variant.attributes)
    existing.supplier_product_id = catalog_variant.supplier_product_id
    existing.supplier_variant_id = catalog_variant.supplier_variant_id or None
    if existing.status == VARIANT_STATUS_ARCHIVED:
        existing.status = VARIANT_STATUS_ACTIVE
    mark_instance_dirty(session, existing)
    result.variants_updated += 1


async def _upsert_catalog_product(
    session: Any,
    catalog_product: SupplierCatalogProduct,
    addon_id: str,
    *,
    options: SupplierCatalogSyncOptions,
    storage: Any,
    result: SupplierCatalogSyncResult,
    seen_product_keys: set[str],
    seen_variant_keys: set[str],
    actor_user_id: int | None,
    store_name: str,
) -> None:
    importable_variants = [v for v in catalog_product.variants if not v.skip_reason]
    if not importable_variants and all(v.skip_reason for v in catalog_product.variants):
        result.skipped += len(catalog_product.variants)
        return

    seen_product_keys.add(catalog_product.external_product_key)
    product = await _find_product_by_external_key(
        session, catalog_product.external_product_key
    )
    created = product is None

    if created:
        product = Product(
            name=catalog_product.name,
            description=catalog_product.description,
            price_cents=0,
            inventory_quantity=0,
            status=options.import_status,
            supplier_external_product_key=catalog_product.external_product_key,
            options=dict(catalog_product.options),
            tags=[],
            created_by=actor_user_id,
        )
        product.tags = refresh_sync_marker_only(
            product.tags,
            catalog_product.external_product_key,
        )
        session.add(product)
        await session.flush()
        await apply_product_creation_defaults(session, product, store_name=store_name)
        await assign_product_category_from_type(session, product, catalog_product.product_type)
        result.created += 1
    else:
        product.name = catalog_product.name
        product.description = catalog_product.description
        product.tags = refresh_sync_marker_only(
            product.tags,
            catalog_product.external_product_key,
        )
        product.updated_by = actor_user_id
        if product.status == "archived":
            product.status = options.import_status
        result.updated += 1

    if catalog_product.image_urls:
        await import_images_from_urls(
            session,
            product,
            list(catalog_product.image_urls),
            storage=storage,
            alt_text=product.name,
            alt_texts=catalog_product.image_alt_texts or None,
        )

    for catalog_variant in catalog_product.variants:
        await _upsert_variant(
            session,
            product,
            catalog_variant,
            addon_id,
            import_status=options.import_status,
            storage=storage,
            result=result,
            seen_variant_keys=seen_variant_keys,
        )

    variants = await _load_variants_for_product(session, product.id)
    refresh_product_listing_cache(product, variants)
    mark_instance_dirty(session, product)


async def sync_supplier_catalog(
    session: Any,
    addon_id: str,
    options: SupplierCatalogSyncOptions,
    *,
    actor_user_id: int | None = None,
    ip_address: str | None = None,
    for_job_id: str | None = None,
) -> SupplierCatalogSyncResult:
    """Pull supplier catalog and upsert local products with variants."""
    if options.import_status not in ("draft", "published"):
        raise ValidationError(message="import_status must be 'draft' or 'published'")

    # Lazy import avoids circular dependency with background_jobs.
    from app.services.background_jobs import get_active_supplier_sync_job

    active = await get_active_supplier_sync_job(session)
    if active is not None and for_job_id != active.id:
        raise ValidationError(
            message="A supplier sync job is already running",
            details={"job_id": active.id},
        )

    addon = get_supplier_addon(addon_id)
    if addon is None:
        raise ValidationError(
            message=f"Supplier addon '{addon_id}' is not enabled or not configured"
        )
    if not addon.supports_catalog_sync():
        raise ValidationError(message=f"Catalog sync is not supported for supplier '{addon_id}'")

    result = SupplierCatalogSyncResult()
    try:
        raw_catalog = await addon.fetch_catalog_for_import()
        catalog_products = ensure_catalog_products(raw_catalog)
    except Exception as exc:
        result.errors.append(str(exc))
        return result

    result.catalog_total = len(catalog_products)
    result.catalog_importable = sum(
        1
        for product in catalog_products
        for variant in product.variants
        if not variant.skip_reason
    )
    logger.info(
        "[%s] catalog sync: received %d products (%d importable variants)",
        addon_id,
        result.catalog_total,
        result.catalog_importable,
    )

    await _persist_addon_runtime_config(session, addon_id, addon)

    seen_product_keys: set[str] = set()
    seen_variant_keys: set[str] = set()
    site_settings = await get_site_settings(session)
    store_name = site_settings.store_name or "Store"
    storage = get_storage()

    for catalog_product in catalog_products:
        await _upsert_catalog_product(
            session,
            catalog_product,
            addon_id,
            options=options,
            storage=storage,
            result=result,
            seen_product_keys=seen_product_keys,
            seen_variant_keys=seen_variant_keys,
            actor_user_id=actor_user_id,
            store_name=store_name,
        )

    if options.archive_missing:
        variant_result = await session.execute(
            select(ProductVariant).where(col(ProductVariant.supplier_addon_id) == addon_id)
        )
        for variant in variant_result.scalars().all():
            key = variant.supplier_external_key
            if key and key not in seen_variant_keys and variant.status != VARIANT_STATUS_ARCHIVED:
                variant.status = VARIANT_STATUS_ARCHIVED
                mark_instance_dirty(session, variant)
                result.variants_archived += 1
                product = await session.get(Product, variant.product_id)
                if product is not None:
                    variants = await _load_variants_for_product(session, product.id)
                    refresh_product_listing_cache(product, variants)
                    if not any(v.status == VARIANT_STATUS_ACTIVE for v in variants):
                        product.status = "archived"
                        product.updated_by = actor_user_id
                        result.archived += 1
                    mark_instance_dirty(session, product)

    await log_change(
        session,
        actor_user_id=actor_user_id,
        action="supplier_catalog_sync",
        resource_type="supplier",
        resource_id=addon_id,
        changes={
            "created": result.created,
            "updated": result.updated,
            "variants_created": result.variants_created,
            "variants_updated": result.variants_updated,
            "skipped": result.skipped,
            "archived": result.archived,
            "variants_archived": result.variants_archived,
            "catalog_total": result.catalog_total,
            "catalog_importable": result.catalog_importable,
            "import_status": options.import_status,
            "archive_missing": options.archive_missing,
        },
        ip_address=ip_address,
        detail=result.summary_message(addon_id=addon_id),
    )
    await session.commit()
    return result
