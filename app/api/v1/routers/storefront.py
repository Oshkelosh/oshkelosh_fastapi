"""Public storefront configuration for SPA bootstrapping."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from app.db.connection import get_session
from app.services.storefront_resolver import resolve_frontend_addon
from app.services.site_settings import get_site_settings, site_settings_to_dict
from schemas.storefront import (
    ActiveFrontendInfo,
    SiteSettingsPublic,
    StorefrontConfigResponse,
    StorefrontUnavailableResponse,
)

router = APIRouter(prefix="/storefront", tags=["storefront"])


@router.get(
    "/config",
    response_model=StorefrontConfigResponse,
    responses={
        503: {
            "description": "No frontend addon is enabled",
            "model": StorefrontUnavailableResponse,
        },
    },
    summary="Get storefront bootstrap configuration",
    description="""
Returns merged configuration for the active storefront SPA:

- **`site`**: Site-wide branding from **Admin → Site Settings** (name, colors, fonts, logo).
- **`frontend`**: Active frontend addon id, version, and frontend-specific `config`.

Every storefront must call this on startup. See `app/addons/frontends/README.md`
for integration details and CSS variable names.
    """.strip(),
)
async def get_storefront_config(
    request: Request,
    session=Depends(get_session),
) -> StorefrontConfigResponse:
    frontend = resolve_frontend_addon(request)
    if frontend is None:
        body = StorefrontUnavailableResponse()
        return JSONResponse(status_code=503, content=body.model_dump())

    site = await get_site_settings(session)
    return StorefrontConfigResponse(
        site=SiteSettingsPublic.model_validate(site_settings_to_dict(site)),
        frontend=ActiveFrontendInfo(
            addon_id=frontend.addon_id,
            addon_name=frontend.addon_name,
            version=frontend.version,
            config=(
                frontend._config
                if hasattr(frontend, "_config") and frontend._config
                else {}
            ),
        ),
    )


@router.get(
    "/theme.css",
    response_class=Response,
    summary="Get storefront theme CSS variables",
    description="""
Returns a small CSS file defining `:root` custom properties from site settings.

Link from `index.html` for early paint before JavaScript runs:

```html
<link rel="stylesheet" href="/api/v1/storefront/theme.css" />
```

Variables: `--color-primary`, `--color-secondary`, `--font-sans`.
    """.strip(),
)
async def get_storefront_theme_css(session=Depends(get_session)) -> Response:
    site = await get_site_settings(session)
    css = (
        f":root {{\n"
        f"  --color-primary: {site.primary_color};\n"
        f"  --color-secondary: {site.secondary_color};\n"
        f"  --font-sans: {site.font_family};\n"
        f"}}\n"
    )
    return Response(content=css, media_type="text/css")
