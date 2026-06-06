# Security

## Authentication surfaces

### Public REST API (`/api/v1/*`)

- Uses **Bearer JWT** access tokens (HS256) in the `Authorization` header.
- **CSRF is not required** for API clients that send Bearer tokens (no browser cookie session).
- Do **not** store API access tokens in cookies without CSRF protection.

### Admin panel (`/admin/*`)

- Uses **httponly session cookies** signed with `ADMIN_SESSION_SECRET` (separate from `JWT_SECRET_KEY` in production).
- All mutating forms require a **CSRF token** (`csrf_token` field + session claim).

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

Disable in tests with `RATE_LIMIT_ENABLED=false`.

## Password hashing

- **bcrypt** with configurable `BCRYPT_ROUNDS` (default 12, range 10–15).
- Argon2 may be evaluated later; existing bcrypt hashes remain valid.

## Health endpoints

- `GET /health` — liveness; minimal body in production.
- `GET /health/ready` — readiness (DB + storage); returns `503` when checks fail.

## CORS

In production, allowed methods and headers are restricted (see `app/core/middleware.py`). Origins must be listed in `CORS_ORIGINS`.

## Migrations

SQL files under `migrations/d1/` are tracked in `schema_migrations` and applied once per environment.
