# Services — AGENTS

## Role

Core business logic. Routers stay thin. **Orchestration seams** resolve enabled addons and call ABC methods. **Utilities** are core-only helpers (persistence, formatting, discovery glue).

## File map

See [README.md](README.md) for the seam vs utility module table (`checkout_pricing`, `payment_checkout`, `payment_webhooks`, `fulfillment`, `supplier_catalog_sync`, `notifications`, `commerce`, …).

## Invariants

- No provider name checks (`stripe`, `printify`, …) in these modules
- Seams call addon ABC methods; new providers extend the ABC, not this layer
- Async sessions: no lazy loads — use explicit loaders in `commerce.py`
- Webhook handling: idempotency and DB writes stay in core seams; addons parse only

## Prefer / Avoid

- Prefer: new seam method on the matching ABC when a cross-provider capability is needed
- Avoid: embedding PSP/supplier HTTP clients or credentials here

## See also

- [README.md](README.md)
- [../addons/AGENTS.md](../addons/AGENTS.md)
- [../../AGENTS.md](../../AGENTS.md)
