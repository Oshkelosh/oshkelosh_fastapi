# Scripts (`scripts`)

Built-in tool for injecting external storefront `<script>` tags (analytics, chat widgets, and similar).

## Overview

| | |
|---|---|
| Addon ID | `scripts` |
| Category | tool |
| Version | 1.0.0 |
| Category guide | [../README.md](../README.md) |

Paste a complete external script tag — for example Umami:

```html
<script defer src="https://analytics.example.com/script.js" data-website-id="…"></script>
```

Core aggregates descriptors via `list_storefront_scripts()` into `GET /api/v1/storefront/config` → `tools.scripts`. The default storefront injects matching tags into `<head>`.

## Enable and configure

1. Open **Admin → Tools → Scripts** at `/admin/tools/scripts`
2. Enable the addon
3. Add a script: name, pasted tag, route scope (`all` / `public` / `private`)

**Private routes** (default storefront): `/account`, `/checkout`, `/orders` (and nested paths).

## Rules

- Exactly one empty external `<script>` tag per entry
- `src` must be `https://`
- No inline JavaScript body
- Allowed attributes: `defer`, `async`, `nomodule`, `type`, `crossorigin`, `integrity`, `referrerpolicy`, `charset`, and `data-*`
- Event handlers (`onclick`, etc.) are rejected

## Storefront descriptor

```json
{
  "id": "…",
  "src": "https://analytics.example.com/script.js",
  "attrs": { "defer": true, "data-website-id": "…" },
  "routes": "all"
}
```
