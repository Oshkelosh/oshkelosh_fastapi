# Security

## Authentication surfaces

### Public REST API (`/api/v1/*`)

- Uses **Bearer JWT** access tokens (HS256) in the `Authorization` header.
- **CSRF is not required** for API clients that send Bearer tokens (no browser cookie session).
- Do **not** store API access tokens in cookies without CSRF protection.

### Admin panel (`ADMIN_PREFIX`, default `/admin`)

- Uses **httponly session cookies** signed with `ADMIN_SESSION_SECRET` (separate from `JWT_SECRET_KEY` in production).
- All mutating forms require a **CSRF token** (`csrf_token` field + session claim).
- Session cookie `SameSite` defaults to `lax`; set `ADMIN_COOKIE_SAMESITE=strict` for stricter CSRF protection (may affect cross-site admin flows).

### Admin JSON API (`/api/v1/admin/*`)

- Uses **Bearer JWT** plus `get_admin_user()` authorization checks.
- Intended for scripts, cron jobs, and operator tooling rather than browser navigation.
- Maintenance endpoints such as `POST /api/v1/admin/jobs/abandoned-cart` and `POST /api/v1/admin/jobs/pending-orders` belong here.

## Secrets (production)

| Variable | Requirement |
|----------|-------------|
| `JWT_SECRET_KEY` | Strong secret, ≥32 chars, not the default placeholder |
| `ADMIN_SESSION_SECRET` | Required, ≥32 chars, must differ from `JWT_SECRET_KEY` |
| `JWT_REFRESH_SECRET_KEY` | Optional separate secret for refresh tokens |

Set `APP_ENV=production` and `DEBUG=false` on production deploys.

## Rate limiting

Auth endpoints are limited per client IP (slowapi):

- `POST /api/v1/auth/login` — default `5/minute` (`RATE_LIMIT_LOGIN`)
- `POST /api/v1/auth/register` — default `3/hour` (`RATE_LIMIT_REGISTER`)
- `POST /api/v1/auth/refresh` — default `10/minute` (`RATE_LIMIT_REFRESH`)
- `POST /admin/login` — default `5/minute` (`RATE_LIMIT_ADMIN_LOGIN`)

Disable in tests with `RATE_LIMIT_ENABLED=false`.

If the app sits behind a reverse proxy, configure `TRUSTED_PROXY_IPS` and optionally `TRUSTED_PROXY_HEADERS` so rate limiting keys off the forwarded client IP only when the immediate peer is trusted.

## Password hashing

- **bcrypt** with configurable `BCRYPT_ROUNDS` (default 12, range 10–15).
- Argon2 may be evaluated later; existing bcrypt hashes remain valid.

## PII at rest

User records store JSON fields such as `default_shipping_address`, `payment_customer_ids`, and `oauth_identities` as plaintext in the database. The application does not encrypt these fields; use database or infrastructure-level encryption if your deployment requires it.

## Health endpoints

- `GET /health` — liveness; minimal body in production.
- `GET /health/ready` — readiness (DB + storage); returns `503` when checks fail.

## CORS

In production, allowed methods and headers are restricted (see `app/core/middleware.py`). Origins must be listed in `CORS_ORIGINS`.

## Schema and migrations

At application startup the lifespan hook runs SQLModel `create_all` and then applies supplemental SQL from `migrations/d1/` via `apply_migrations_async()` (see [DATABASE.md](DATABASE.md)). The `schema_migrations` table records **which SQL files ran** — it does not automatically sync ORM model changes. Application tables come from `create_all`; SQL files add indexes, constraints, and other supplemental DDL.

The supplemental SQL is security-critical on D1 deployments. Unique indexes such as `order_idempotency_keys (user_id, key_hash)` and `processed_webhook_events (event_id)` are added there rather than by the D1 HTTP table emitter.

## First-run setup race

`POST /setup` creates the first admin user. Concurrent submissions (multiple tabs or parallel deploys) are guarded by:

- A pre-insert `has_admin_user()` check that redirects when an admin already exists.
- `IntegrityError` handling if two requests pass the check simultaneously (unique email constraint).

Only one admin is created; the loser sees an error message and must sign in normally.

## Payment webhook idempotency

Payment webhooks are processed by [`app/services/payment_webhooks.py`](../app/services/payment_webhooks.py). Core first asks the addon to parse and validate the delivery, then records a `processed_webhook_events` row keyed by `event_id` (unique) before applying side effects. A duplicate delivery hits the unique constraint and returns `{"handled": true, "duplicate": true}` without re-marking the order paid. Addon `parse_webhook()` methods must not write to the database — core owns idempotency and order transitions.

Late payments for already-cancelled orders are preserved on the order, flagged for refund review, and written to the audit log as reconciliation events instead of silently flipping the order back to `paid`.

## Media access

`GET /api/v1/media/{key}` now requires admin authentication. Presigned or resolved media URLs should be treated as operational/admin tools unless a future storefront-safe reader surface is added deliberately.
