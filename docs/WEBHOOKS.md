# Webhooks

Oshkelosh has two webhook directions.

## Inbound (providers → shop)

Payment and supplier addons expose their own routes (for example Stripe or Printify). Core records each provider `event_id` in `processed_webhook_events` so retries are idempotent. Addon `parse_webhook()` must not write the database. See [SECURITY.md](SECURITY.md#payment-webhook-idempotency).

## Outbound (shop → your receiver)

Admin → **Webhooks** configures one HTTPS URL. Core generates the HMAC secret and shows it **once** (copy it into the receiver). Rotate from the same page when you need a new secret.

Selected commerce events are `POST`ed as compact JSON:

```json
{"id":"<uuid>","type":"order.paid","created":1700000000,"data":{"order_id":1,"status":"paid"}}
```

Headers:

| Header | Meaning |
|--------|---------|
| `X-Webhook-Id` | Delivery UUID (idempotency on the receiver) |
| `X-Webhook-Timestamp` | Unix seconds |
| `X-Webhook-Event` | Event type |
| `X-Webhook-Signature` | `t=<timestamp>,v1=<hex>` HMAC-SHA256 of `{timestamp}.{raw_body}` |

Deliveries are attempted once (~5s timeout, no redirects). Failures are stored on the admin page and never fail checkout.

### Events

`order.placed`, `order.paid`, `order.shipped`, `order.delivered`, `order.cancelled`, `user.registered`, `cart.abandoned`. **Send test** POSTs `webhook.test` (signed the same way; checkboxes are not required).

### Verify a delivery

```python
import hashlib, hmac

def verify(secret: str, timestamp: str, body: bytes, header: str) -> bool:
    expected = "t=" + timestamp + ",v1=" + hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header.strip())
```

Reject deliveries whose timestamp is unreasonably old if replay of never-seen ids matters for your receiver.
