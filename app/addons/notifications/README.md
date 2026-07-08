# Notification addon development

Notification addons deliver email, SMS, or push messages. **Core** owns event definitions, merchant-editable templates, rendering, and dispatch; addons implement provider transport only.

## Concern separation

| Core module | Role |
|---|---|
| [`app/services/notification_events.py`](../../services/notification_events.py) | Event catalog, default copy, placeholders |
| [`app/services/notification_templates.py`](../../services/notification_templates.py) | DB template load/save/render |
| [`app/services/notification_dispatch.py`](../../services/notification_dispatch.py) | Pick addon per channel, call transport |
| [`app/services/notifications.py`](../../services/notifications.py) | Order status → dispatch |
| [`app/services/user_accounts.py`](../../services/user_accounts.py) | Verification/reset → dispatch |
| Admin → Messages | `/admin/notifications/messages` — edit copy per event/channel |

**Notification addons** own credentials and API mapping only (`send_email`, `send_sms`, `send_push`).

## Policy

- **One enabled provider per channel** (email, SMS, push). Enabling a new email addon disables other email addons.
- Order notifications fire on status transitions via core commerce (not addon HTTP routes).
- SMS is for **order lifecycle alerts only** — not 2FA or login OTP.
- Failures are logged; they **do not** roll back order status changes.

## Events

| Event key | Trigger | Channels |
|-----------|---------|----------|
| `order_confirmation` | `pending` → `paid` | email, sms, push |
| `order_shipped` | `paid` → `shipped` | email, sms, push |
| `order_delivered` | `shipped` → `delivered` | email, sms, push |
| `email_verification` | registration / resend | email |
| `password_reset` | forgot password | email |

Edit templates at **Admin → Notifications → Edit message templates**.

## NotificationAddon methods

| Method | Purpose |
|--------|---------|
| `supported_channels` | e.g. `["email"]`, `["sms"]`, `["push"]` |
| `send_email(to, subject, body, html=False)` | Transactional email |
| `send_sms(to, body)` | SMS (E.164 phone) |
| `send_push(to, title, body, data=None)` | Push to device token |
| `send_webhook(url, payload)` | Outbound webhook helper |

Unsupported channels should return `channel_not_supported()`.

## Package layout

```
app/addons/notifications/<provider>/
├── README.md
├── __init__.py
├── addon.py
├── routes.py      # build_notification_routers(...) delegate
└── templates/
```

Shared: [`helpers.py`](helpers.py), [`shared_routes.py`](shared_routes.py).

## Route mounting

| Type | URL pattern | Example |
|------|-------------|---------|
| API | `/api/v1/notifications/{addon_id}/...` | Usually empty |
| Admin | `/admin/notifications/{addon_id}/...` | `GET /admin/notifications/postmark` |

OpenAPI tag: **`addons-notifications`**

## Configuration

API keys and credentials are configured in the admin panel (stored in `addon_configs`), not in `.env`. Use `SecretStr` for secrets.

## Installed notification addons

| Addon ID | Channel | README |
|----------|---------|--------|
| `postmark` | email | [postmark/README.md](postmark/README.md) |
| `smtp` | email | [smtp/README.md](smtp/README.md) |
| `resend` | email | [resend/README.md](resend/README.md) |
| `sendgrid` | email | [sendgrid/README.md](sendgrid/README.md) |
| `mailgun` | email | [mailgun/README.md](mailgun/README.md) |
| `ses` | email | [ses/README.md](ses/README.md) |
| `twilio` | sms | [twilio/README.md](twilio/README.md) |
| `vonage` | sms | [vonage/README.md](vonage/README.md) |
| `messagebird` | sms | [messagebird/README.md](messagebird/README.md) |
| `fcm` | push | [fcm/README.md](fcm/README.md) |
| `onesignal` | push | [onesignal/README.md](onesignal/README.md) |
| `pusher_beams` | push | [pusher_beams/README.md](pusher_beams/README.md) |

## OpenAPI

Tag `addons-notifications` in [docs/api/OPENAPI.md](../../../docs/api/OPENAPI.md).
