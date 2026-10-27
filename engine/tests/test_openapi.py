"""The API contract: engine/openapi.json must match the live schema.

When you change the API on purpose, rewrite the file with
`uv run maku openapi openapi.json` and update the matching types in
app/src/lib/engine.tsx in the same commit.
"""

import json
from pathlib import Path

from maku.api import openapi_schema

SNAPSHOT = Path(__file__).parents[1] / "openapi.json"


def test_openapi_json_matches_the_api():
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    assert committed == openapi_schema(), (
        "The engine API changed. Run `uv run maku openapi openapi.json` "
        "and update app/src/lib/engine.tsx to match."
    )
