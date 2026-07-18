# Payment addon development

Payment addons implement checkout, capture, refunds, and webhooks for a payment service provider. Each installed package includes its own README with config fields, webhook URLs, and PSP dashboard setup.

## Concern separation

**Core** owns generic orchestration (no PSP-specific branches):

| Core module | Role |
|---|---|
| [`app/services/payment_checkout.py`](../../../services/payment_checkout.py) | Checkout: call addon, persist order payment fields |
| [`app/services/payment_webhooks.py`](../../../services/payment_webhooks.py) | Webhooks: idempotency, `complete_order_payment` |

**Payment addons** own PSP-specific API mapping only:

| Addon method | Role |
|---|---|
| `create_payment(...)` | Start checkout; call PSP API |
| `parse_webhook(payload, signature)` | Return `PaymentWebhookOutcome` — **no DB writes** |
| `get_payment_status(payment_id)` | Authoritative status lookup (also used to verify unsigned webhooks) |
| `verify_webhook(headers, body)` | Prove the webhook came from the provider; fails closed by default |

Most addons use [`shared_routes.py`](shared_routes.py) for admin config UI and a webhook route that delegates to [`payment_webhooks.process_payment_webhook`](../../../services/payment_webhooks.py). `build_payment_routers()` registers `POST /api/v1/payments/{addon_id}/webhook` automatically — addons do not implement webhook handlers inline.

Per-addon checkout aliases (e.g. `POST /api/v1/payments/stripe/checkout`) are **removed**. Storefronts must use the generic order checkout endpoint below; core calls `payment_checkout.start_checkout()`.

The **Dodo** addon uses custom routes — see [`dodo/README.md`](dodo/README.md).

## Policy

- **One active payment addon** at a time (enabling a new one disables others).
- Prefer the **generic checkout** endpoint for storefronts:  
  `POST /api/v1/orders/{order_id}/checkout`  
  Core calls `payment_checkout.start_checkout()` → `PaymentAddon.create_payment()`.

Supplier fulfillment is separate from customer checkout — see [`app/services/fulfillment.py`](../../../services/fulfillment.py).

## PaymentAddon methods

| Method | Purpose |
|--------|---------|
| `create_payment(...)` | Start checkout |
| `parse_webhook(payload, signature)` | Parse event → `PaymentWebhookOutcome` |
| `get_payment_status(payment_id)` | Authoritative payment status lookup |
| `verify_webhook(headers, body)` | Signature/authenticity check; base default rejects everything |
| `webhook_signature_header()` | Override default signature header name when needed |

Amounts are in **smallest currency unit** (cents).

## Package layout

```
app/addons/payments/<provider>/
├── .gitignore
├── README.md
├── __init__.py
├── addon.py       # PSP API mapping only
├── routes.py      # build_payment_routers(...) delegate (or custom for Dodo)
└── templates/
    └── <provider>_config.html
```

Shared: [`helpers.py`](helpers.py) (mock checkout), [`shared_routes.py`](shared_routes.py).

## Route mounting

| Type | URL pattern | Example |
|------|-------------|---------|
| Checkout | `/api/v1/orders/{order_id}/checkout` | Generic — not per-addon |
| Webhook | `/api/v1/payments/{addon_id}/webhook` | Registered by `shared_routes.build_payment_routers()` |
| Admin | `/admin/payments/{addon_id}/...` | `GET /admin/payments/{addon_id}` |

## Configuration

API keys are configured in the admin panel at `/admin/payments/{addon_id}` (stored in `addon_configs`), not in `.env`. Use `SecretStr` for secrets. Enable via the **Enable this payment processor** checkbox on the config page.

### Checkout redirect URLs

Core builds per-order redirect URLs at checkout time from **Site URL** ([`/admin/settings`](../../../admin/templates/site_settings.html)):

| Event | URL |
|-------|-----|
| Success | `{site_url}/orders/{order_id}?payment=return` |
| Cancel | `{site_url}/checkout` |

Resolution order: `site_url` → `PUBLIC_APP_URL` → first CORS origin → `http://localhost:8000` (dev).

[`payment_checkout.start_checkout()`](../../../services/payment_checkout.py) passes `return_url` and `cancel_url` into `PaymentAddon.create_payment()`. Addons may expose optional **advanced override** fields in admin config; when set, overrides win over core-computed URLs.

Storefronts should handle `?payment=return` on the order detail page while the webhook confirms payment.

## Storefront integration

```javascript
const checkout = await fetch(`/api/v1/orders/${order.id}/checkout`, {
  method: "POST",
  headers: { Authorization: `Bearer ${token}` },
});
const { url } = await checkout.json();
window.location.href = url;
```

## Installed payment addons

Each package includes a `README.md` with config, webhook registration, and PSP setup:

| Addon ID | README |
|----------|--------|
| `stripe` | [stripe/README.md](stripe/README.md) (when installed) |
| `paypal` | [paypal/README.md](paypal/README.md) (when installed) |
| `mangopay` | [mangopay/README.md](mangopay/README.md) (when installed) |
| `adyen` | [adyen/README.md](adyen/README.md) (when installed) |
| `checkout` | [checkout/README.md](checkout/README.md) (when installed) |
| `mollie` | [mollie/README.md](mollie/README.md) (when installed) |
| `worldpay` | [worldpay/README.md](worldpay/README.md) (when installed) |
| `airwallex` | [airwallex/README.md](airwallex/README.md) (when installed) |
| `rapyd` | [rapyd/README.md](rapyd/README.md) (when installed) |
| `dodo` | [dodo/README.md](dodo/README.md) (when installed) |

## OpenAPI

See [docs/api/OPENAPI.md](../../../docs/api/OPENAPI.md) — tag `addons-payments` and `orders` (checkout).
