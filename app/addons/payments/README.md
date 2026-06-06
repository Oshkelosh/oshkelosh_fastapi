# Payment addon development

Payment addons implement checkout, capture, refunds, and webhooks for a payment provider (Stripe, PayPal, etc.).

## Policy

- **One active payment addon** at a time (enabling a new one disables others).
- Prefer the **generic checkout** endpoint for storefronts:  
  `POST /api/v1/orders/{order_id}/checkout`  
  Core calls `PaymentAddon.create_payment()` on the enabled addon.

Provider-specific routes (e.g. Stripe webhooks) remain on the addon for provider callbacks.

## PaymentAddon methods

Implement all abstract methods in [`base.py`](base.py):

| Method | Purpose |
|--------|---------|
| `create_payment(amount, currency, order_id, customer_email)` | Start checkout; return session URL / ids |
| `confirm_payment(payment_id)` | Capture or confirm |
| `refund_payment(payment_id, amount)` | Full or partial refund |
| `get_payment_status(payment_id)` | Poll status |
| `handle_webhook(payload, signature)` | Process provider events |

Amounts are in **smallest currency unit** (cents). `order_id` is the local order primary key as a string.

## Package layout

```
app/addons/payments/<provider>/
├── __init__.py
├── addon.py       # class StripeAddon(PaymentAddon)
├── routes.py      # checkout alias, webhook, admin config
└── templates/
    └── stripe_config.html
```

## Route mounting

| Type | URL pattern | Example |
|------|-------------|---------|
| API | `/api/v1/payments/{addon_id}/...` | `POST /api/v1/payments/stripe/webhook` |
| Admin | `/admin/payments/{addon_id}/...` | `GET /admin/payments/stripe` |

OpenAPI tag: **`addons-payments`**

## Webhook → order paid

When checkout completes, your webhook handler should:

1. Verify signature (production; see TODO in Stripe reference)
2. Extract local `order_id` from provider metadata
3. Load order and call `apply_order_status_change(session, order, "paid")`

Example: [`stripe/routes.py`](stripe/routes.py) `_extract_order_id_from_stripe_event`.

## Configuration

API keys are configured in the admin panel at `/admin/payments/{addon_id}` (stored in `addon_configs`), not in `.env`. Use `SecretStr` for keys in `config_schema()`. Save via admin form + `save_addon_from_form()` or `persist_addon_config()`.

## Storefront integration

```javascript
// After POST /api/v1/orders → order.id
const checkout = await fetch(`/api/v1/orders/${order.id}/checkout`, {
  method: "POST",
  headers: { Authorization: `Bearer ${token}` },
});
const { url } = await checkout.json();
window.location.href = url;  // provider checkout page
```

## Reference addon

[`stripe/`](stripe/) — Checkout Session, webhook handler, admin config UI.

## OpenAPI

See [docs/api/OPENAPI.md](../../../docs/api/OPENAPI.md) — tag `addons-payments` and `orders` (checkout).
