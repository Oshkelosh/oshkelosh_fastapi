# Storefront SEO

Crawler-facing SEO is **server-injected HTML**. The default SPA mirrors the same tags client-side for in-app navigation.

## Dual layer

| Layer | Role | Source of truth for crawlers? |
|-------|------|-------------------------------|
| [`app/storefront/seo.py`](../app/storefront/seo.py) + [`seo_routes.py`](../app/storefront/seo_routes.py) | Inject title, description, canonical, OG/Twitter, robots, JSON-LD, visible `#seo-intro` (H1 + lede), and catalog `<a>` nav into `dist/index.html` | **Yes** |
| Default frontend `SeoHead.svelte` + `lib/utils/seo.ts` | Update `<svelte:head>` after client navigation; header/footer hubs + breadcrumbs; adopt `#seo-intro` and catalog nav | No — keep in sync with Python |

Routes registered before the static SPA mount: `/`, `/products`, `/products/{slug}`, `/categories`, `/categories/{slug}`, `/articles`, `/articles/{slug}`, private noindex paths (`/cart`, `/checkout`, `/account`, `/orders`, …), plus `/sitemap.xml` and `/robots.txt`.

## Indexed vs private

**Indexed (when content exists):** home, products list, product detail (published + slug), categories index, category detail, articles hub/posts (via enabled tool SEO discovery).

**noindex:** `/cart`, `/checkout`, `/account`, `/orders` (and detail), auth pages (`/login`, `/register`, …). Also listed under `Disallow` in `robots.txt`.

## Tool SEO discovery

Enabled tools may contribute storefront pages through `ToolAddon.resolve_seo_meta()` and `list_sitemap_entries()`, aggregated by `app/services/tool_discovery.py`. Core still owns injection and `/sitemap.xml`; tools return SeoMeta-shaped dicts (no provider branches in core). Nav hubs also merge `list_storefront_nav_links()` into crawl `_hub_links`.

## Visible H1 + intro

Indexed responses inject a visible `<div id="seo-intro" class="page-header">` before `</body>`: one `<h1>` and one intro `<p>` (escaped text, not the full product/article body). It uses the storefront `.page-header` styles and is not `display:none`. The default SPA moves that node to the top of `<main>`, under the shop header. On client-side navigation the node is from the first HTML document, so the layout removes it and pages render their own H1.

`#seo-intro` is H1 + lede only. Full article/product copy stays in the SPA.

## Crawlable internal links

Indexed SEO responses inject `<nav id="seo-catalog-nav" aria-label="Catalog">` before `</body>` (links present for crawlers). The default storefront footer adopts that node on hydrate into the left column under “Powered by …”, so it lives inside `<footer>`. Each hub is one link (`Products`, `Categories`, and `Articles` when the articles tool is enabled) with an optional caret `<details>` menu; anchors stay in HTML when collapsed. Caps keep large shops cheap (home ~20, listing/category ~50, siblings ~20). `/sitemap.xml` remains the full-catalog safety net.

Header keeps a Categories nav entry; the footer catalog strip owns Products/Categories hubs + list menus (not duplicated as plain footer links).

## Enriched data

- Home: `Organization` JSON-LD + crawl nav
- Products list / category detail: `CollectionPage` → `ItemList` (same capped product URLs as crawl links) + crawl nav
- Product: `Product` + `Offer` or `AggregateOffer` + `BreadcrumbList` (+ `category` name when set); product `image` is a list of `ImageObject` entries when images exist
- Breadcrumbs:
  - Product with category: `Home → Categories → {Category} → {Product}`
  - Product without category: `Home → Products → {Product}`
  - Category: `Home → Categories → [{Parent} →] {Category}`
- Offer `priceCurrency` comes from Site Settings `shop_currency` (default `USD`)

Product API reads expose `category` / `category_slug` and `category_name` when `category_id` is set.

Admin edits `meta_title` / `meta_description` on products and categories; empty values fall back to name + store / truncated description. See also [DATABASE.md](DATABASE.md).

## Image SEO

Page SEO already ships `og:image` / `twitter:image`. Image-specific signals:

| Signal | Owner |
|--------|--------|
| Google image sitemap (`xmlns:image` on product URLs) | Core [`render_sitemap_xml`](../app/storefront/seo.py) |
| `og:image:alt` / `twitter:image:alt` | Core injection + default SPA `SeoHead.svelte` |
| Product JSON-LD `ImageObject` gallery (`contentUrl` + alt as `name`/`description`) | Core + SPA `seo.ts` mirror |
| Visible `<img alt>` / `srcset` / LCP eager hero | Default SPA (`ProductCard`, `ProductGallery`, `product.ts`) |
| Edit alt after upload | Admin product form + `PATCH /api/v1/products/{id}/images/{image_id}` |

Default SPA lives under [`app/addons/frontends/default/`](../app/addons/frontends/default/) (nested git; host ignores the package). Edit `source/`, then `npm run build` in `source/` to refresh `dist/`; commit inside the addon repo.

### Ops checklist (production)

- Fill meaningful `alt_text` on product images (Admin → Products → edit → Save alt). Prefer subject + product name over empty or filename-like text.
- Confirm image URLs are publicly crawlable (local media mount or R2/CDN public base), not only admin `GET /api/v1/media/{key}`.
- Submit `/sitemap.xml` in Search Console; after deploy, spot-check a product URL (view-source for `og:image:alt` and `<image:image>` in the sitemap).
- Ensure products used in social shares have a primary image so OG does not fall back to the store logo only.
