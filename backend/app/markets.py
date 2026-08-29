from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "markets.json"


def _load_markets() -> dict[str, dict[str, Any]]:
    rows = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("code") or "").upper().strip()
        if not code:
            continue
        out[code] = {k: v for k, v in row.items() if k != "code"}
    return out


MARKETS = _load_markets()


def market_list() -> list[dict[str, Any]]:
    return [{"code": code, **cfg} for code, cfg in MARKETS.items()]
