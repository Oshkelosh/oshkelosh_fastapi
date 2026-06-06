# Notification addon development

Notification addons send email, SMS, or webhooks. The primary integration path for order emails is **core commerce**, not addon HTTP routes.

## Policy

- **One active notification addon** recommended (first enabled wins).
- Emails fire on order status transitions via [`app/services/notifications.py`](../../services/notifications.py).

| Transition | Email |
|------------|-------|
| `pending` → `paid` | Order confirmation |
| `paid` → `shipped` | Shipping notice |
| `shipped` → `delivered` | Delivery confirmation |

Subjects are prefixed with `[{store_name}]` from Site Settings.

## NotificationAddon methods

| Method | Purpose |
|--------|---------|
| `send_email(to, subject, body, html=False)` | Transactional email |
| `send_sms(to, body)` | SMS (optional / provider-specific) |
| `send_webhook(url, payload)` | Outbound webhook |

Failures are logged; they **do not** roll back order status changes.

## Package layout

```
app/addons/notifications/<provider>/
├── addon.py
├── routes.py      # admin config only (optional)
└── templates/
```

Email Postmark sets `admin_mount_prefix()` to `/notifications/email` (shorter URL).

## Route mounting

| Type | URL pattern | Example |
|------|-------------|---------|
| API | `/api/v1/notifications/{addon_id}/...` | Usually empty |
| Admin | `/admin/notifications/{addon_id}/...` | `GET /admin/notifications/email` |

OpenAPI tag: **`addons-notifications`**

## You typically do NOT need public API routes

Order emails are triggered automatically. Implement `send_email()` well. API tokens and from-address are set in the admin panel at `/admin/notifications/email` (stored in `addon_configs`), not in `.env`.

## Reference addon

[`email/`](email/) — Postmark `send_email`, admin config for API token and from-address.

## OpenAPI

Tag `addons-notifications` in [docs/api/OPENAPI.md](../../../docs/api/OPENAPI.md).
