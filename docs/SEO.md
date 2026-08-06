# Storefront SEO

Crawler-facing SEO is **server-injected HTML**. The default SPA mirrors the same tags client-side for in-app navigation.

## Dual layer

| Layer | Role | Source of truth for crawlers? |
|-------|------|-------------------------------|
| [`app/storefront/seo.py`](../app/storefront/seo.py) + [`seo_routes.py`](../app/storefront/seo_routes.py) | Inject title, description, canonical, OG/Twitter, robots, JSON-LD, and catalog `<a>` nav into `dist/index.html` | **Yes** |
| Default frontend `SeoHead.svelte` + `lib/utils/seo.ts` | Update `<svelte:head>` after client navigation; header/footer hubs + breadcrumbs | No — keep in sync with Python |

Routes registered before the static SPA mount: `/`, `/products`, `/products/{slug}`, `/categories`, `/categories/{slug}`, private noindex paths (`/cart`, `/checkout`, `/account`, `/orders`, …), plus `/sitemap.xml` and `/robots.txt`.

## Indexed vs private

**Indexed (when content exists):** home, products list, product detail (published + slug), categories index, category detail.

**noindex:** `/cart`, `/checkout`, `/account`, `/orders` (and detail), auth pages (`/login`, `/register`, …). Also listed under `Disallow` in `robots.txt`.

## Crawlable internal links

Indexed SEO responses inject a visible `<nav aria-label="Catalog">` before `</body>` with contextual `<a href>` links (hubs + capped product/category lists). This is not cloaked (`display:none`); it stays in the HTML after SPA hydrate as a compact catalog index. Caps keep large shops cheap (home ~20, listing/category ~50, siblings ~20). `/sitemap.xml` remains the full-catalog safety net.

The default storefront also exposes Products/Categories in the header and footer so the rendered DOM matches.

## Enriched data

- Home: `Organization` JSON-LD + crawl nav
- Products list / category detail: `CollectionPage` → `ItemList` (same capped product URLs as crawl links) + crawl nav
- Product: `Product` + `Offer` or `AggregateOffer` + `BreadcrumbList` (+ `category` name when set)
- Breadcrumbs:
  - Product with category: `Home → Categories → {Category} → {Product}`
  - Product without category: `Home → Products → {Product}`
  - Category: `Home → Categories → [{Parent} →] {Category}`
- Offer `priceCurrency` comes from Site Settings `shop_currency` (default `USD`)

Product API reads expose `category` / `category_slug` and `category_name` when `category_id` is set.

Admin edits `meta_title` / `meta_description` on products and categories; empty values fall back to name + store / truncated description. See also [DATABASE.md](DATABASE.md).
