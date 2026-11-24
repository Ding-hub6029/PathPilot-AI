"""Generate docs/openapi.json from the live FastAPI app object.

Run from the project root:
    .venv/bin/python tools/generate_openapi.py
The copy must match GET /api/v1/openapi.json exactly (verified by
tests/test_day2.py::test_openapi_matches_generated_copy and live curl).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app  # noqa: E402


def main() -> Path:
    out = ROOT / "docs" / "openapi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    spec = app.openapi()
    out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {out} ({len(spec.get('paths', {}))} paths, "
          f"openapi {spec.get('openapi')})")
    return out


if __name__ == "__main__":
    main()
