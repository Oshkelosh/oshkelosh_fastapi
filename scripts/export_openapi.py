#!/usr/bin/env python3
"""Export the OpenAPI schema to docs/api/openapi.json.

Run from the repository root with dependencies installed:

    python scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "docs" / "api" / "openapi.json"


def main() -> int:
    sys.path.insert(0, str(REPO_ROOT))

    from app.main import create_app

    app = create_app()
    schema = app.openapi()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
