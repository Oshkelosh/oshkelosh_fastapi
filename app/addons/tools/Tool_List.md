# Tool addon roadmap and implementation guide

Planning reference for **optional third-party integrations** under `app/addons/tools/`. Tools extend core commerce at documented seams — analytics, marketing sync, support widgets, third-party tax APIs, and similar — without turning core into a provider-specific monolith.

**Built-in tax and shipping rules** live in core **Site Settings** ([`models/site_settings.py`](../../../models/site_settings.py)). **Supplier-calculated shipping** is implemented on [`SupplierAddon`](../suppliers/base.py). **Manual shipment tracking**, **native abandoned cart**, and **baseline product search** are core features — see [Belongs in core (not tools)](#belongs-in-core-not-tools).

See [README.md](README.md) for category conventions and [../README.md](../README.md) for the full addon checklist.

## Policy

- **Multiple tools may be enabled at once** (unlike payment or frontend addons).
- **One tax tool at a time** is recommended when using third-party tax APIs (TaxJar, Avalara, etc.) — same exclusivity pattern as payments.
- **Core orchestrates** at documented seams; **addons implement** provider APIs, scripts, and admin UI.
- **Do not add provider name checks** in `app/services/*.py`. Extend `ToolAddon` (or add a narrow core seam) instead.
- Credentials live in **`addon_configs`** (admin panel), not `.env`, unless the integration requires a global host setting (e.g. `PUBLIC_APP_URL` for OAuth callbacks).
- New tool packages are discovered at **server startup** (or via `uvicorn --reload` in dev). Enable/configure at **Admin → Tools**.

## Concern separation

| Core owns | Tool addons own |
|-----------|-----------------|
| Commerce lifecycle (cart, orders, checkout, status transitions) | Third-party API clients, OAuth, webhooks |
| Domain models (`User`, `Product`, `Order`, `Cart`) | Provider-specific config schemas and validation |
| Generic orchestration at documented seams (below) | Admin config UI, credentials, outbound event mapping |
| Shared cross-boundary schemas (`StorefrontConfigResponse`, etc.) | Script snippets, pixel config, third-party tax API clients |
| Storefront bootstrap aggregation (`GET /api/v1/storefront/config`) | Public metadata methods (`list_public_providers`, `quote_tax`) |
| Built-in tax/shipping rules (`SiteSettings`, [`checkout_pricing.py`](../../services/checkout_pricing.py)) | — |
| Manual order tracking fields, shipped emails | Tracking automation (AfterShip, 17track) |
| Native abandoned cart job + `cart_abandoned` notification | ESP-side flows via `cart.abandoned` lifecycle sync |
| Baseline `?search=` on `/api/v1/products` (SQL ILIKE) | Meilisearch / Typesense / Algolia backends |

**Rule of thumb:** if a feature needs a new lifecycle hook (e.g. third-party tax at checkout), add a **generic core seam** once in [`checkout_pricing.py`](../../services/checkout_pricing.py), then let each tool addon implement the interface — same pattern as `PaymentAddon.create_payment()` or `SupplierAddon.quote_shipping()`.

## Core prerequisites (for tool authors)

| Prerequisite | Core module | Tools that need it | Status |
|--------------|-------------|-------------------|--------|
| Built-in tax/shipping | [`checkout_pricing.py`](../../services/checkout_pricing.py) | Tax provider tools | Shipped |
| Order tracking fields | [`models/order.py`](../../../models/order.py) + admin | Tracking automation tools | Shipped |
| `lifecycle_events` fan-out | [`lifecycle_events.py`](../../services/lifecycle_events.py) | CRM sync, pixels (lifecycle) | Shipped |
| `cart.abandoned` event | [`notification_events.py`](../../services/notification_events.py) + [`abandoned_cart.py`](../../services/abandoned_cart.py) | Klaviyo, Brevo sync | Shipped |
| `tool_discovery` scripts slot | [`tool_discovery.py`](../../services/tool_discovery.py) | Analytics, consent, chat | Shipped |
| `on_commerce_event('purchase')` | [`tool_discovery.py`](../../services/tool_discovery.py) | Conversion pixels | Shipped |
| `search_products` strategy | [`product_search.py`](../../services/product_search.py) | Meilisearch, Algolia | Shipped (ILIKE fallback; FTS optional later) |

## Core seams (today)

| Event / surface | Core module | Hook |
|-----------------|-------------|------|
| Storefront SSO buttons | [`sso_discovery.py`](../../services/sso_discovery.py) | `ToolAddon.list_public_providers()` on `sso` addon |
| Storefront config | [`storefront.py` router](../../api/v1/routers/storefront.py) | `auth.sso_providers`, `tools.scripts` |
| Order tax & shipping | [`checkout_pricing.py`](../../services/checkout_pricing.py) | Site Settings rules; optional `ToolAddon.quote_tax()`; optional `SupplierAddon.quote_shipping()` |
| Third-party tax | [`tax_discovery.py`](../../services/tax_discovery.py) | First enabled tax tool with `quote_tax()`; falls back to Site Settings |
| Supplier shipping quotes | [`checkout_pricing.py`](../../services/checkout_pricing.py) | `SupplierAddon.quote_shipping()` per fulfillment group |
| Order notifications | [`notifications.py`](../../services/notifications.py) | `tracking_url`, `tracking_number`, `carrier` on `Order` |
| Lifecycle marketing bus | [`lifecycle_events.py`](../../services/lifecycle_events.py) | `ToolAddon.on_lifecycle_event()` — `user.registered`, `order.paid`, `cart.abandoned` |
| Commerce measurement | [`tool_discovery.py`](../../services/tool_discovery.py) | `ToolAddon.on_commerce_event()` — `purchase` on payment completion |
| Storefront scripts | [`tool_discovery.py`](../../services/tool_discovery.py) | `ToolAddon.list_storefront_scripts()` → `storefront/config.tools` |
| Product search | [`product_search.py`](../../services/product_search.py) | `ToolAddon.search_products()` or core ILIKE |
| SEO (sitemap, meta injection) | [`seo.py`](../../storefront/seo.py) | **Core** — not a tool category concern |

## Proposed core seams (future)

| Seam | Suggested location | Purpose |
|------|-------------------|---------|
| `run_scheduled_jobs()` | Lightweight scheduler entrypoint | Product feeds, tracking polls (abandoned cart uses `POST /api/v1/admin/jobs/abandoned-cart` today) |
| SQLite FTS5 index | [`product_search.py`](../../services/product_search.py) | Large-catalog typo tolerance without external engine |

Document new seams in this file and in [../README.md](../README.md#how-core-commerce-uses-addons) when they land.

---

## Installed tools

| Addon ID | Status | README |
|----------|--------|--------|
| `sso` | **Shipped** — Google, Facebook, custom OIDC | [sso/README.md](sso/README.md) |

---

## Recommended build order

### Core first (shipped)

1. Shipment tracking fields + admin + notifications
2. Lifecycle event fan-out (`lifecycle_events.py`)
3. Native abandoned cart (`abandoned_cart.py`, Site Settings toggles)
4. Measurement hooks (`tool_discovery.py`, `on_commerce_event`)
5. Search strategy hook (`product_search.py`; optional FTS later)

### Tools after

1. **Cookie consent** — prerequisite for analytics and ad pixels
2. **Analytics** (Plausible, PostHog, Fathom) — visibility with low integration cost
3. **Tax provider tool** (TaxJar, Avalara) — when built-in Site Settings tax is insufficient
4. **CRM sync** (Klaviyo, Brevo) — lifecycle event sync; ESP may run its own abandoned flows
5. **Tracking automation** (AfterShip, 17track) — polling/webhooks on top of core tracking fields
6. **Conversion pixels** (Meta CAPI, Google Ads, TikTok) — server-side `purchase` via `on_commerce_event`
7. **Site search engine** (Meilisearch, Typesense, Algolia) — when `search_products` delegates
8. **A/B testing** — uses `storefront_resolver` extension point

---

## Lifecycle marketing (tools only)

**Core (not an addon):** native abandoned cart recovery — [`abandoned_cart.py`](../../services/abandoned_cart.py), `cart_abandoned` in [`notification_events.py`](../../services/notification_events.py), Site Settings toggles, cron via `POST /api/v1/admin/jobs/abandoned-cart`.

**Tools:** `klaviyo`, `brevo`, `mailchimp`, `customerio` — profile and event sync via `on_lifecycle_event` (`user.registered`, `order.paid`, `cart.abandoned`). Merchants may run abandoned-cart flows **inside** the ESP in addition to (or instead of) core email reminders.

**Explicit:** do not replace `NotificationAddon` for transactional mail (order confirmation, password reset, etc.).

| Layer | Responsibility |
|-------|----------------|
| Core | `dispatch_lifecycle_event()` with normalized payloads; native `cart_abandoned` notification |
| Addon | API sync, list IDs, consent flags, unsubscribe handling, ESP automation |

---

## Measurement and attribution (tools only)

Analytics and conversion pixels are **sibling tool families** under shared hooks — not one subtype of the other. Merchants enable them independently.

### Analytics (`plausible`, `posthog`, `fathom`, `ga4`)

**Value:** Traffic, funnel, and revenue visibility.

| Layer | Responsibility |
|-------|----------------|
| Core | `list_storefront_scripts()` → `storefront/config.tools.scripts`; optional `purchase` via `on_commerce_event` |
| Addon | Domain/script ID, API key for admin stats widget, provider snippet config |

- Consent category: **`analytics`**
- Gate script injection behind cookie consent when that tool is enabled.

### Conversion pixels (`meta_capi`, `google_ads`, `tiktok_events`)

**Value:** Measurable ad spend for merchants running paid traffic.

| Layer | Responsibility |
|-------|----------------|
| Core | `dispatch_commerce_event('purchase', ...)` on `complete_order_payment` |
| Addon | Pixel ID, access token, test event code, event mapping |

- Consent category: **`marketing`**
- Prefer **server-side** events for reliability; client pixel optional, gated by consent.
- Never log raw email/phone in addon debug output.

**Shared implementation:** [`tool_discovery.py`](../../services/tool_discovery.py) — `list_storefront_scripts()`, `dispatch_commerce_event()`, `storefront/config.tools.consent_categories` placeholder until consent tool ships.

---

## Potential tools

Each entry lists **value**, **integration type**, and **implementation notes** following core-vs-addon separation.

### Tier 1 — High merchant value, strong fit

#### Cookie consent (`consent`)

**Value:** Legal prerequisite for analytics, ad pixels, and third-party chat in the EU and similar jurisdictions.

| Layer | Responsibility |
|-------|----------------|
| Core | `tools.consent_categories` in storefront config; filter scripts by category |
| Addon | Banner copy, policy URLs, category definitions (necessary / analytics / marketing) |

- Should be enabled **before** analytics and pixel tools in production.

---

#### Tax provider (`taxjar`, `quaderno`, `avalara`)

**Value:** Address-based tax/VAT via a third-party API when built-in Site Settings rules are insufficient.

| Layer | Responsibility |
|-------|----------------|
| Core | [`checkout_pricing.py`](../../services/checkout_pricing.py) + [`tax_discovery.py`](../../services/tax_discovery.py) |
| Addon | `quote_tax()` implementation, API client, admin config |

See existing guidelines in prior tax provider section — built-in flat/zone tax remains in **Admin → Site Settings** when no tax tool is enabled.

---

### Tier 2 — Strong value, moderate core touch

#### Tracking automation (`aftership`, `17track`)

**Value:** Auto-register shipments, poll/webhook status, optional `paid → shipped → delivered` transitions.

| Layer | Responsibility |
|-------|----------------|
| Core | `tracking_number`, `tracking_url`, `carrier` on `Order`; admin entry; `{tracking_url}` in shipped emails |
| Addon | Register tracking with provider, carrier mapping, webhook ingestion |

**Not** manual tracking — that is core. Tools automate on top of core fields.

---

#### CRM / email marketing sync (`klaviyo`, `brevo`, `mailchimp`, `customerio`)

See [Lifecycle marketing (tools only)](#lifecycle-marketing-tools-only).

---

#### Live chat / helpdesk (`crisp`, `chatwoot`, `tawk`)

| Layer | Responsibility |
|-------|----------------|
| Core | `list_storefront_scripts()` |
| Addon | Widget ID, optional visitor context route |

---

#### Site search engine (`meilisearch`, `typesense`, `algolia`)

**Value:** Typo-tolerant search when SQL `ILIKE` does not scale.

| Layer | Responsibility |
|-------|----------------|
| Core | `GET /api/v1/products?search=` — ILIKE today; [`product_search.py`](../../services/product_search.py) delegates to enabled tool |
| Addon | Index mapping, query API, admin reindex |

- Index on publish/update/archive from supplier sync and product admin routes.
- Optional core FTS5 later for large catalogs without an external engine.

---

#### A/B testing (`experiments`)

| Layer | Responsibility |
|-------|----------------|
| Core | `resolve_frontend_addon(request)` assigns variant |
| Addon | Experiment definitions, traffic split, conversion reporting |

---

#### Google Merchant / product feed (`merchant_feed`)

| Layer | Responsibility |
|-------|----------------|
| Core | `GET /feeds/{addon_id}.xml` or cron-generated static file |
| Addon | Field mapping, refresh schedule |

---

#### Back-in-stock alerts (`back_in_stock`)

| Layer | Responsibility |
|-------|----------------|
| Core | Waitlist table; notification event `back_in_stock` (future) |
| Addon | SMS/push preferences |

---

### Tier 3 — Useful, narrower or heavier scope

| Tool ID | Value | Notes |
|---------|-------|-------|
| `fraud` (Sift, Signifyd) | Block high-risk orders | Hook at payment webhook |
| `affiliate` (Rewardful) | Referral revenue | Needs attribution on `Order` |
| `low_stock_alerts` | Merchant ops | Admin notification |
| `profit_margins` | POD margin visibility | Admin-only |
| `sentry` | Error monitoring | Ops-focused |
| `webhooks_out` | Zapier/Make | Generic outbound webhooks on order events |

### Belongs in core (Site Settings)

Configured at **Admin → Site Settings** ([`/admin/settings`](../../admin/routes.py)). Consumed by [`checkout_pricing.py`](../../services/checkout_pricing.py).

| Feature | Why core |
|---------|----------|
| Built-in tax rules | Flat rate, tax-inclusive toggle, country/region zones |
| Built-in shipping rules | Flat, free, free-over-threshold, country zones |
| Supplier shipping quotes | [`SupplierAddon.quote_shipping()`](../suppliers/base.py) |
| Abandoned cart toggles | `abandoned_cart_enabled`, delay, max reminders |

Carrier APIs (EasyPost, Shippo) are **not** planned for core or tools — live shipping quotes belong on **supplier addons** where the provider supports them.

### Belongs in core (not tools)

| Feature | Why core | Module |
|---------|----------|--------|
| Manual shipment tracking | Fields, admin UI, shipped notification context | `Order` + admin |
| Native abandoned cart recovery | Notification event + scheduled job | `abandoned_cart.py` |
| Baseline product search | `?search=` ILIKE on products API | `product_search.py` |
| SEO | Sitemap, meta, JSON-LD | `storefront/seo.py` |
| Coupons / gift cards | Pricing model change | — |
| Multi-currency | Touches product, payment, display | — |

---

## Implementation checklist (new tool package)

1. Create `app/addons/tools/<addon_id>/` with `__init__.py`, `addon.py`, `README.md`.
2. Subclass `ToolAddon`; set `addon_id`, `addon_name`, `addon_description`, `version`.
3. Define `config_schema()` (Pydantic v2, `SecretStr` for secrets).
4. Implement `initialize()` / `shutdown()`.
5. Add `routes.py` for admin UI and any public/webhook endpoints.
6. Use [`render_addon_admin_page()`](../admin_helpers.py) for admin templates.
7. If storefront-facing, implement the relevant discovery method and document the config shape.
8. Add tests under `tests/test_<addon_id>.py`.
9. Add row to **Installed tools** in [README.md](README.md) when shipped.
10. If a new core seam was added, update [../README.md](../README.md) and this file.

### Storefront integration pattern

```text
ToolAddon method(s)
    → app/services/tool_discovery.py (or sso_discovery.py, etc.)
    → schemas/storefront.py (typed public config)
    → SPA reads config on startup
```

Push notifications mirror this under `notifications.push` via [`push_discovery.py`](../../services/push_discovery.py).

### Testing

See [`tests/test_sso.py`](../../../tests/test_sso.py), [`tests/test_lifecycle_events.py`](../../../tests/test_lifecycle_events.py), [`tests/test_addons.py`](../../../tests/test_addons.py).

---

## Reference: SSO (implemented pattern)

| Piece | Location |
|-------|----------|
| Addon class | [`sso/addon.py`](sso/addon.py) |
| Discovery | `list_public_providers()` |
| Core aggregator | [`sso_discovery.py`](../../services/sso_discovery.py) |
| Storefront schema | `AuthConfigPublic` |

---

## See also

- [Tools category README](README.md)
- [Addon development guide](../README.md)
- [Notification events](../../services/notification_events.py)
- [Lifecycle events](../../services/lifecycle_events.py)
- [Abandoned cart](../../services/abandoned_cart.py)
- [Tool discovery](../../services/tool_discovery.py)
- [Product search](../../services/product_search.py)
- [Checkout pricing](../../services/checkout_pricing.py)
- [Suppliers](../suppliers/README.md)
