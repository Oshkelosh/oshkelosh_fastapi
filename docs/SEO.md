# Storefront SEO

Crawler-facing SEO is **server-injected HTML**. The default SPA mirrors the same tags client-side for in-app navigation.

## Dual layer

| Layer | Role | Source of truth for crawlers? |
|-------|------|-------------------------------|
| [`app/storefront/seo.py`](../app/storefront/seo.py) + [`seo_routes.py`](../app/storefront/seo_routes.py) | Inject title, description, canonical, OG/Twitter, robots, JSON-LD into `dist/index.html` | **Yes** |
| Default frontend `SeoHead.svelte` + `lib/utils/seo.ts` | Update `<svelte:head>` after client navigation | No — keep in sync with Python |

Routes registered before the static SPA mount: `/`, `/products`, `/products/{slug}`, `/categories`, `/categories/{slug}`, private noindex paths (`/cart`, `/checkout`, `/account`, `/orders`, …), plus `/sitemap.xml` and `/robots.txt`.

## Indexed vs private

**Indexed (when content exists):** home, products list, product detail (published + slug), categories index, category detail.

**noindex:** `/cart`, `/checkout`, `/account`, `/orders` (and detail), auth pages (`/login`, `/register`, …). Also listed under `Disallow` in `robots.txt`.

## Enriched data

- Home: `Organization` JSON-LD
- Product: `Product` + `Offer` or `AggregateOffer` + `BreadcrumbList`
- Category detail: `BreadcrumbList`
- Offer `priceCurrency` comes from Site Settings `shop_currency` (default `USD`)

Admin edits `meta_title` / `meta_description` on products and categories; empty values fall back to name + store / truncated description. See also [DATABASE.md](DATABASE.md).
