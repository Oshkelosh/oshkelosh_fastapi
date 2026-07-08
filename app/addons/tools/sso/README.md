# SSO Login (`sso`)

Built-in social sign-in for the storefront via Google, Facebook, or custom OpenID Connect providers.

## Overview

| | |
|---|---|
| Addon ID | `sso` |
| Category | tool |
| Version | 1.0.0 |
| Category guide | [../README.md](../README.md) |

Multiple tools may be enabled at once. SSO appears on the storefront when the addon is enabled **and** config `is_active` is true with at least one provider configured.

## Enable and configure

1. Set `PUBLIC_APP_URL` in `.env` to the URL customers use (e.g. `http://localhost:8000`). If unset, the first entry in `CORS_ORIGINS` is used as fallback.
2. Open **Admin → Tools → SSO Login** at `/admin/tools/sso`
3. Enable the addon and at least one provider
4. Register callback URLs (below) with each identity provider

**Dual enable flags:** the addon must be enabled in **Admin → Addons**, and `is_active` must be true in SSO settings.

## Configuration schema

| Field | Type | Description |
|-------|------|-------------|
| `is_active` | bool | Master toggle for SSO flows |
| `google.enabled` | bool | Enable Google sign-in |
| `google.client_id` | string | Google OAuth client ID |
| `google.client_secret` | secret | Google OAuth client secret |
| `facebook.enabled` | bool | Enable Facebook sign-in |
| `facebook.app_id` | string | Facebook app ID |
| `facebook.app_secret` | secret | Facebook app secret |
| `oidc_providers[]` | list | Custom OIDC providers |
| `oidc_providers[].provider_id` | string | URL slug (e.g. `acme` → routes use `oidc_acme`) |
| `oidc_providers[].display_name` | string | Button label on login/register |
| `oidc_providers[].enabled` | bool | Enable this provider |
| `oidc_providers[].issuer_url` | string | OIDC issuer (discovery at `{issuer}/.well-known/openid-configuration`) |
| `oidc_providers[].client_id` | string | OIDC client ID |
| `oidc_providers[].client_secret` | secret | OIDC client secret |
| `oidc_providers[].scopes` | string | Default `openid email profile` |

## Routes

### Public API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/tools/sso/providers` | List enabled providers |
| GET | `/api/v1/tools/sso/{provider}/authorize` | Start OAuth (optional `?redirect=/path`) |
| GET | `/api/v1/tools/sso/{provider}/callback` | OAuth callback (IdP redirect) |
| POST | `/api/v1/tools/sso/exchange` | Exchange short-lived token for JWT pair (rate-limited 30/min) |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/tools/sso` | SSO settings form |
| POST | `/admin/tools/sso/settings` | Save settings |

## Core integration

- **`list_public_providers()`** — exposed in `GET /api/v1/storefront/config` under `auth.sso_providers` via [`app/services/sso_discovery.py`](../../../services/sso_discovery.py)
- **Storefront:** login/register pages render SSO buttons; success redirects to `/auth/sso/callback` for token exchange
- **Account linking:** existing accounts with the same email are auto-linked; SSO sign-ups with verified email are auto-verified

## Callback URLs

Register these with your identity provider (`{PUBLIC_APP_URL}` = your public base URL):

| Provider | Callback URL |
|----------|----------------|
| Google | `{PUBLIC_APP_URL}/api/v1/tools/sso/google/callback` |
| Facebook | `{PUBLIC_APP_URL}/api/v1/tools/sso/facebook/callback` |
| Custom OIDC | `{PUBLIC_APP_URL}/api/v1/tools/sso/oidc_{provider_id}/callback` |

## Google setup

1. Create an OAuth 2.0 Client ID in [Google Cloud Console](https://console.cloud.google.com/).
2. Application type: **Web application**.
3. Authorized redirect URI: Google callback URL above.
4. Copy Client ID and Client secret into **Admin → Tools → SSO**.

## Facebook setup

1. Create an app at [Meta for Developers](https://developers.facebook.com/).
2. Add **Facebook Login** product.
3. Valid OAuth redirect URI: Facebook callback URL above.
4. Copy App ID and App secret into admin settings.

## Custom OIDC

Works with Keycloak, Auth0, Azure AD, and other OIDC-compliant providers. Set **Provider ID** to a lowercase slug; routes use `oidc_{provider_id}`.

## Security notes

- OAuth flows use **PKCE** and signed state tokens (~10 minute lifetime)
- Exchange tokens are short-lived (~60 seconds) and single-use
- Exchange requires a verified email from the provider; banned users are rejected
- Failed OAuth redirects to `/login?error=sso_failed`

## Package layout

```
sso/
├── README.md
├── addon.py
├── config.py
├── service.py
├── routes.py
└── templates/
```

## See also

- [Tools addons](../README.md)
- [Oshkelosh addon guide](../../README.md)
