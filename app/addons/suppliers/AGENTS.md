# Suppliers — AGENTS

## Role

Category package for print-on-demand and fulfillment providers. Multiple suppliers may be active; paid-order fulfillment and catalog sync resolve linkage from **variant** rows. Host gitignores nested provider trees except built-in `manual`.

## File map

- `README.md` — category guide (product/variant model, sync, shipping)
- `base.py` — `SupplierAddon` ABC
- `shared_routes.py` — admin config/save/sync + public products list factory
- `catalog_utils.py` — shared normalization helpers
- `address.py`, `shipping_quote.py` — shared fulfillment helpers
- `manual/` — built-in manual supplier (in host repo)
- `<provider>/` — nested-git or ZIP-installed packages (`printful`, `printify`, …)

## Invariants

- Implement `SupplierAddon`; do not add provider `if` branches in `app/services/*.py`
- Credentials and enable flags live in `addon_configs` (admin UI), not host `.env`
- Shared packing-slip / gift settings live on the suppliers hub (+ Site Settings name/logo/email); provider-only branding stays on each addon page
- Catalog sync DTOs:
  - Parent name/description from provider **product** fields
  - Variant title includes product/design name when the raw variant label is options-only
  - Fill `SupplierCatalogVariant.attributes` from provider option axes when present (Size/Color, …); do not rely on slash-joined titles for storefront pickers
  - Images on variants; leave product `image_urls` empty unless there is a true product-only gallery
  - `product_type` (+ `options["Product type"]`) when available → category on **create** only
- Discover shop/store IDs via provider API when the dashboard does not expose them
- Do not bake browse-host assumptions into provider packages; local media is root-relative `/media/files/...`
- Nested `.git` packages: Admin **Update** overwrites the tree — ship fixes in the addon repo
- Use `app/addons/log.py`; admin mutating forms need CSRF

## Prefer / Avoid

- Prefer: extend the provider package + category ABC; reuse `shared_routes` / `catalog_utils`; map shared `gift_message` / `packing_slip` only when the provider API accepts them
- Avoid: inventing manual shop IDs; putting secrets in host `.env`; editing host services for one provider; putting provider-only branding on the shared suppliers hub

## See also

- [README.md](README.md) — category how-to
- [../AGENTS.md](../AGENTS.md) — host addon boundary
- [../README.md](../README.md) — plugin development
- [../../../AGENTS.md](../../../AGENTS.md), [../../../DESIGN.md](../../../DESIGN.md)
