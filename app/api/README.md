# API Surfaces

Oshkelosh exposes three admin-facing HTTP surfaces plus the storefront API:

## Public storefront API

- Prefix: `API_V1_PREFIX` (default `/api/v1`)
- Auth: Bearer JWT where required
- Audience: storefront SPA, mobile apps, server-to-server integrations

## Admin HTML panel

- Prefix: `ADMIN_PREFIX` (default `/admin`)
- Auth: signed admin session cookie + CSRF tokens on mutating forms
- Audience: human operators in a browser

## Admin JSON API

- Prefix: `API_V1_PREFIX + /admin` (default `/api/v1/admin`)
- Auth: Bearer JWT with admin privileges
- Audience: scripts, CI jobs, background maintenance triggers

Use the JSON admin API for automation and cron-style maintenance. Current maintenance entrypoints include:

- `POST /api/v1/admin/jobs/abandoned-cart`
- `POST /api/v1/admin/jobs/pending-orders`

The startup lifespan still runs stale pending-order cleanup once as defense-in-depth, but production should also invoke the JSON maintenance endpoints on a schedule.
