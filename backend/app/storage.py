from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DB_PATH = DATA_DIR / "bordermargin.db"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    with _connect() as conn:
        existing = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='market_snapshots'").fetchone()
        if existing:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(market_snapshots)").fetchall()}
            if "origin_code" not in cols or "origin_name" not in cols:
                conn.execute("ALTER TABLE market_snapshots RENAME TO market_snapshots_legacy")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market TEXT NOT NULL,
                reporter_code TEXT NOT NULL,
                currency TEXT NOT NULL,
                hs_code TEXT NOT NULL,
                origin_code TEXT NOT NULL DEFAULT '',
                origin_name TEXT NOT NULL DEFAULT '',
                start_year INTEGER NOT NULL,
                end_year INTEGER NOT NULL,
                synced_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE(market, hs_code, origin_code, start_year, end_year)
            )
            """
        )
        legacy = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='market_snapshots_legacy'").fetchone()
        if legacy:
            conn.execute(
                """
                INSERT OR IGNORE INTO market_snapshots (
                    id, market, reporter_code, currency, hs_code, origin_code, origin_name,
                    start_year, end_year, synced_at, payload_json
                )
                SELECT id, market, reporter_code, currency, hs_code, '', '', start_year, end_year, synced_at, payload_json
                FROM market_snapshots_legacy
                """
            )
            conn.execute("DROP TABLE market_snapshots_legacy")


        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_scan_cache (
                project_id INTEGER PRIMARY KEY,
                hs_code TEXT NOT NULL,
                origin_code TEXT NOT NULL DEFAULT '',
                origin_name TEXT NOT NULL DEFAULT '',
                scanned_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        listing_existing = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='listing_snapshots'").fetchone()
        if listing_existing:
            listing_cols = {row[1] for row in conn.execute("PRAGMA table_info(listing_snapshots)").fetchall()}
            if "project_id" not in listing_cols or "market_code" not in listing_cols:
                conn.execute("ALTER TABLE listing_snapshots RENAME TO listing_snapshots_legacy")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS listing_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL DEFAULT 0,
                market_code TEXT NOT NULL DEFAULT '',
                environment TEXT NOT NULL,
                marketplace TEXT NOT NULL,
                query TEXT NOT NULL,
                synced_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE(project_id, market_code, environment, marketplace, query)
            )
            """
        )
        listing_legacy = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='listing_snapshots_legacy'").fetchone()
        if listing_legacy:
            rows = conn.execute("SELECT id, environment, marketplace, query, synced_at, payload_json FROM listing_snapshots_legacy ORDER BY id").fetchall()
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                except Exception:
                    payload = {}
                project_id = int(payload.get("project_id") or 0)
                market_code = str(payload.get("market_code") or payload.get("market") or "").upper()
                conn.execute(
                    """INSERT OR REPLACE INTO listing_snapshots
                    (id, project_id, market_code, environment, marketplace, query, synced_at, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (row["id"], project_id, market_code, row["environment"], row["marketplace"], row["query"], row["synced_at"], row["payload_json"]),
                )
            conn.execute("DROP TABLE listing_snapshots_legacy")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tariff_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market TEXT NOT NULL,
                hs_code TEXT NOT NULL,
                rate REAL NOT NULL,
                reference_year INTEGER,
                note TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(market, hs_code)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tax_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market TEXT NOT NULL,
                rate REAL NOT NULL,
                reference_year INTEGER,
                note TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(market)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_briefs (
                project_id INTEGER NOT NULL,
                market TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(project_id, market)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tariff_matrix_cache (
                market TEXT NOT NULL,
                hs_code TEXT NOT NULL,
                origin_code TEXT NOT NULL DEFAULT '',
                requested_year INTEGER NOT NULL,
                scanned_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(market, hs_code, origin_code, requested_year)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS supply_profile_cache (
                project_id INTEGER PRIMARY KEY,
                hs_code TEXT NOT NULL,
                origin_code TEXT NOT NULL,
                synced_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_response_cache (
                provider TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(provider, cache_key)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_usage_daily (
                provider TEXT NOT NULL,
                day TEXT NOT NULL,
                network_requests INTEGER NOT NULL DEFAULT 0,
                cache_hits INTEGER NOT NULL DEFAULT 0,
                stale_hits INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(provider, day)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_health (
                provider TEXT PRIMARY KEY,
                last_status TEXT NOT NULL DEFAULT 'unknown',
                last_success_at TEXT,
                last_failure_at TEXT,
                last_error TEXT,
                last_latency_ms INTEGER,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_evidence_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                market TEXT NOT NULL DEFAULT '',
                evidence_type TEXT NOT NULL,
                field_name TEXT NOT NULL,
                value_json TEXT NOT NULL,
                source_name TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT '',
                evidence_level TEXT NOT NULL DEFAULT '',
                retrieval_method TEXT NOT NULL DEFAULT 'ai',
                confidence TEXT NOT NULL DEFAULT '',
                observed_at TEXT,
                retrieved_at TEXT NOT NULL,
                excerpt TEXT NOT NULL DEFAULT '',
                source_hash TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(project_id, market, evidence_type, field_name, source_url)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hs_ranking_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL DEFAULT 0,
                query_text TEXT NOT NULL,
                selected_code TEXT NOT NULL,
                candidate_codes_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hs_ranking_feedback_created
            ON hs_ranking_feedback(created_at DESC)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_recovery_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                market TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                requested_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_type_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                origin TEXT NOT NULL DEFAULT '',
                hs_code TEXT NOT NULL,
                attributes_json TEXT NOT NULL DEFAULT '{}',
                markets_json TEXT NOT NULL DEFAULT '[]',
                assumptions_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                is_example INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def save_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    init_db()
    synced_at = payload.get("synced_at") or _now()
    payload = {**payload, "synced_at": synced_at}
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO market_snapshots (
                market, reporter_code, currency, hs_code, origin_code, origin_name, start_year, end_year, synced_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market, hs_code, origin_code, start_year, end_year)
            DO UPDATE SET
                reporter_code=excluded.reporter_code,
                currency=excluded.currency,
                origin_name=excluded.origin_name,
                synced_at=excluded.synced_at,
                payload_json=excluded.payload_json
            """,
            (
                payload["market"], payload["reporter_code"], payload["currency"], payload["hs_code"],
                str((payload.get("origin") or {}).get("code") or ""), str((payload.get("origin") or {}).get("name") or ""),
                int(payload["start_year"]), int(payload["end_year"]), synced_at,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    return payload


def list_snapshots(hs_code: str | None = None) -> list[dict[str, Any]]:
    init_db()
    query = "SELECT payload_json FROM market_snapshots"
    params: tuple[Any, ...] = ()
    if hs_code:
        query += " WHERE hs_code = ?"
        params = (hs_code,)
    query += " ORDER BY synced_at DESC"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    out = []
    for row in rows:
        try:
            out.append(json.loads(row["payload_json"]))
        except Exception:
            continue
    return out


def latest_snapshot(market: str, hs_code: str, origin_code: str | None = None) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        if origin_code is None:
            row = conn.execute(
                "SELECT payload_json FROM market_snapshots WHERE market=? AND hs_code=? ORDER BY synced_at DESC LIMIT 1",
                (market, hs_code),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT payload_json FROM market_snapshots WHERE market=? AND hs_code=? AND origin_code=? ORDER BY synced_at DESC LIMIT 1",
                (market, hs_code, str(origin_code)),
            ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return None


def save_listing_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    init_db()
    synced_at = payload.get("synced_at") or _now()
    payload = {**payload, "synced_at": synced_at}
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO listing_snapshots (project_id, market_code, environment, marketplace, query, synced_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, market_code, environment, marketplace, query)
            DO UPDATE SET synced_at=excluded.synced_at, payload_json=excluded.payload_json
            """,
            (
                int(payload.get("project_id") or 0),
                str(payload.get("market_code") or payload.get("market") or "").upper(),
                payload.get("environment", "unknown"),
                payload.get("marketplace", "unknown"),
                payload.get("query", ""),
                synced_at,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    return payload


def list_listing_snapshots() -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT payload_json FROM listing_snapshots ORDER BY synced_at DESC").fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            out.append(json.loads(row["payload_json"]))
        except Exception:
            continue
    return out


def save_tariff_override(*, market: str, hs_code: str, rate: float, reference_year: int | None = None, note: str | None = None) -> dict[str, Any]:
    init_db()
    updated_at = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO tariff_overrides (market, hs_code, rate, reference_year, note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(market, hs_code)
            DO UPDATE SET rate=excluded.rate, reference_year=excluded.reference_year, note=excluded.note, updated_at=excluded.updated_at
            """,
            (market.upper(), hs_code, float(rate), reference_year, note, updated_at),
        )
        conn.commit()
    return get_tariff_override(market, hs_code) or {}


def get_tariff_override(market: str, hs_code: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT market, hs_code, rate, reference_year, note, updated_at FROM tariff_overrides WHERE market=? AND hs_code=?",
            (market.upper(), hs_code),
        ).fetchone()
    return dict(row) if row else None


def delete_tariff_override(market: str, hs_code: str) -> bool:
    init_db()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM tariff_overrides WHERE market=? AND hs_code=?", (market.upper(), hs_code))
        conn.commit()
    return cur.rowcount > 0


def _decode_project(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for src, dest in [
        ("attributes_json", "attributes"),
        ("markets_json", "markets"),
        ("assumptions_json", "assumptions"),
    ]:
        try:
            data[dest] = json.loads(data.pop(src))
        except Exception:
            data[dest] = {} if dest != "markets" else []
            data.pop(src, None)
    data["is_example"] = bool(data.get("is_example"))
    return data


def create_project(payload: dict[str, Any]) -> dict[str, Any]:
    init_db()
    now = _now()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO projects (
                product_type_id, title, description, origin, hs_code,
                attributes_json, markets_json, assumptions_json,
                status, is_example, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["product_type_id"],
                payload["title"],
                payload.get("description", ""),
                payload.get("origin", ""),
                payload["hs_code"],
                json.dumps(payload.get("attributes", {}), ensure_ascii=False),
                json.dumps(payload.get("markets", []), ensure_ascii=False),
                json.dumps(payload.get("assumptions", {}), ensure_ascii=False),
                payload.get("status", "active"),
                1 if payload.get("is_example") else 0,
                now,
                now,
            ),
        )
        project_id = int(cur.lastrowid)
        conn.commit()
    return get_project(project_id) or {}


def list_projects() -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM projects WHERE is_example=0 ORDER BY updated_at DESC").fetchall()
    return [p for row in rows if (p := _decode_project(row)) is not None]


def get_project(project_id: int) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (int(project_id),)).fetchone()
    return _decode_project(row)


def update_project(project_id: int, changes: dict[str, Any]) -> dict[str, Any] | None:
    current = get_project(project_id)
    if current is None:
        return None

    merged = {**current, **{k: v for k, v in changes.items() if v is not None}}
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE projects SET
                product_type_id=?, title=?, description=?, origin=?, hs_code=?, attributes_json=?, markets_json=?,
                assumptions_json=?, status=?, updated_at=?
            WHERE id=?
            """,
            (
                merged.get("product_type_id", "generic"), merged["title"], merged.get("description", ""), merged.get("origin", ""), merged.get("hs_code", ""),
                json.dumps(merged.get("attributes", {}), ensure_ascii=False),
                json.dumps(merged.get("markets", []), ensure_ascii=False),
                json.dumps(merged.get("assumptions", {}), ensure_ascii=False),
                merged.get("status", "draft"), now, int(project_id),
            ),
        )
        conn.commit()
    return get_project(project_id)


def delete_project(project_id: int) -> bool:
    init_db()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM projects WHERE id=?", (int(project_id),))
        conn.commit()
    return cur.rowcount > 0



def save_market_scan(project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    init_db()
    scanned_at = payload.get("scanned_at") or _now()
    payload = {**payload, "scanned_at": scanned_at, "project_id": int(project_id)}
    origin = payload.get("origin") or {}
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO market_scan_cache (project_id, hs_code, origin_code, origin_name, scanned_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                hs_code=excluded.hs_code, origin_code=excluded.origin_code, origin_name=excluded.origin_name,
                scanned_at=excluded.scanned_at, payload_json=excluded.payload_json
            """,
            (int(project_id), str(payload.get("hs_code") or ""), str(origin.get("code") or ""),
             str(origin.get("name") or ""), scanned_at, json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
    return payload


def get_market_scan(project_id: int) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT payload_json FROM market_scan_cache WHERE project_id=?", (int(project_id),)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return None


def delete_market_scan(project_id: int) -> bool:
    init_db()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM market_scan_cache WHERE project_id=?", (int(project_id),))
        conn.commit()
    return cur.rowcount > 0


def save_tax_override(*, market: str, rate: float, reference_year: int | None = None, note: str | None = None) -> dict[str, Any]:
    init_db(); now=_now()
    with _connect() as conn:
        conn.execute("""INSERT INTO tax_overrides (market,rate,reference_year,note,updated_at) VALUES (?,?,?,?,?)
        ON CONFLICT(market) DO UPDATE SET rate=excluded.rate,reference_year=excluded.reference_year,note=excluded.note,updated_at=excluded.updated_at""",(market.upper(),float(rate),reference_year,note,now)); conn.commit()
    return get_tax_override(market) or {}

def get_tax_override(market: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row=conn.execute("SELECT market,rate,reference_year,note,updated_at FROM tax_overrides WHERE market=?",(market.upper(),)).fetchone()
    return dict(row) if row else None

def delete_tax_override(market: str) -> bool:
    init_db()
    with _connect() as conn:
        cur=conn.execute("DELETE FROM tax_overrides WHERE market=?",(market.upper(),)); conn.commit(); return cur.rowcount>0

def save_ai_brief(project_id: int, market: str, payload: dict[str, Any]) -> dict[str, Any]:
    init_db(); now=_now(); data={**payload,"generated_at":now}
    with _connect() as conn:
        conn.execute("""INSERT INTO ai_briefs(project_id,market,generated_at,payload_json) VALUES (?,?,?,?)
        ON CONFLICT(project_id,market) DO UPDATE SET generated_at=excluded.generated_at,payload_json=excluded.payload_json""",(int(project_id),market.upper(),now,json.dumps(data,ensure_ascii=False))); conn.commit()
    return data

def get_ai_brief(project_id: int, market: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row=conn.execute("SELECT payload_json FROM ai_briefs WHERE project_id=? AND market=?",(int(project_id),market.upper())).fetchone()
    return json.loads(row[0]) if row else None


# V5.3 global tariff and origin-supply research caches.
def save_tariff_matrix_row(payload: dict[str, Any]) -> dict[str, Any]:
    init_db()
    scanned_at = payload.get("scanned_at") or _now()
    row = {**payload, "scanned_at": scanned_at}
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO tariff_matrix_cache (market, hs_code, origin_code, requested_year, scanned_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(market, hs_code, origin_code, requested_year)
            DO UPDATE SET scanned_at=excluded.scanned_at, payload_json=excluded.payload_json
            """,
            (str(row.get("market") or "").upper(), str(row.get("hs_code") or ""), str(row.get("origin_code") or ""), int(row.get("requested_year") or 0), scanned_at, json.dumps(row, ensure_ascii=False)),
        )
        conn.commit()
    return row


def list_tariff_matrix(*, hs_code: str, origin_code: str = "", requested_year: int | None = None, markets: list[str] | None = None) -> list[dict[str, Any]]:
    init_db()
    query = "SELECT payload_json FROM tariff_matrix_cache WHERE hs_code=? AND origin_code=?"
    params: list[Any] = [str(hs_code), str(origin_code or "")]
    if requested_year is not None:
        query += " AND requested_year=?"
        params.append(int(requested_year))
    if markets:
        marks = [str(x).upper() for x in markets]
        query += " AND market IN (%s)" % ",".join("?" for _ in marks)
        params.extend(marks)
    query += " ORDER BY market"
    with _connect() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            out.append(json.loads(row["payload_json"]))
        except Exception:
            continue
    return out


def save_supply_profile(project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    init_db()
    synced_at = payload.get("synced_at") or _now()
    row = {**payload, "project_id": int(project_id), "synced_at": synced_at}
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO supply_profile_cache (project_id, hs_code, origin_code, synced_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                hs_code=excluded.hs_code, origin_code=excluded.origin_code,
                synced_at=excluded.synced_at, payload_json=excluded.payload_json
            """,
            (int(project_id), str(row.get("hs6") or row.get("hs_code") or ""), str((row.get("origin") or {}).get("code") or row.get("origin_code") or ""), synced_at, json.dumps(row, ensure_ascii=False)),
        )
        conn.commit()
    return row


def get_supply_profile(project_id: int) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT payload_json FROM supply_profile_cache WHERE project_id=?", (int(project_id),)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return None


# V5.3.8 source runtime cache and observability.
def source_cache_get(provider: str, cache_key: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT fetched_at, payload_json FROM source_response_cache WHERE provider=? AND cache_key=?",
            (str(provider), str(cache_key)),
        ).fetchone()
    if not row:
        return None
    try:
        return {"fetched_at": row["fetched_at"], "payload": json.loads(row["payload_json"])}
    except Exception:
        return None


def source_cache_put(provider: str, cache_key: str, payload: Any) -> dict[str, Any]:
    init_db()
    fetched_at = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO source_response_cache(provider, cache_key, fetched_at, payload_json) VALUES (?,?,?,?)
            ON CONFLICT(provider, cache_key) DO UPDATE SET fetched_at=excluded.fetched_at, payload_json=excluded.payload_json
            """,
            (str(provider), str(cache_key), fetched_at, json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
    return {"provider": provider, "cache_key": cache_key, "fetched_at": fetched_at}


def source_usage_increment(provider: str, metric: str) -> None:
    if metric not in {"network_requests", "cache_hits", "stale_hits", "failures"}:
        return
    init_db()
    day = datetime.now(timezone.utc).date().isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO source_usage_daily(provider, day) VALUES (?,?)",
            (str(provider), day),
        )
        conn.execute(
            f"UPDATE source_usage_daily SET {metric}={metric}+1 WHERE provider=? AND day=?",
            (str(provider), day),
        )
        conn.commit()


def source_health_record(provider: str, *, ok: bool, latency_ms: int | None = None, error: str | None = None, status: str | None = None) -> None:
    init_db()
    now = _now()
    final_status = status or ("ok" if ok else "error")
    with _connect() as conn:
        current = conn.execute("SELECT last_success_at,last_failure_at FROM source_health WHERE provider=?", (str(provider),)).fetchone()
        # Keep last_success_at tied to a successful live/provider call. Cache hits
        # update current status without making old evidence look newly fetched.
        live_success = ok and final_status not in {"cached", "stale-cache"}
        last_success = now if live_success else (current["last_success_at"] if current else None)
        last_failure = (current["last_failure_at"] if current else None) if ok else now
        conn.execute(
            """
            INSERT INTO source_health(provider,last_status,last_success_at,last_failure_at,last_error,last_latency_ms,updated_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(provider) DO UPDATE SET
                last_status=excluded.last_status,
                last_success_at=excluded.last_success_at,
                last_failure_at=excluded.last_failure_at,
                last_error=excluded.last_error,
                last_latency_ms=excluded.last_latency_ms,
                updated_at=excluded.updated_at
            """,
            (str(provider), final_status, last_success, last_failure, None if ok else str(error or ""), latency_ms, now),
        )
        conn.commit()


def source_runtime_summary() -> list[dict[str, Any]]:
    init_db()
    day = datetime.now(timezone.utc).date().isoformat()
    providers = ["UN Comtrade", "UNCTAD TRAINS / WITS", "ECB", "eBay", "Official Tariff"]
    out: list[dict[str, Any]] = []
    with _connect() as conn:
        for provider in providers:
            health = conn.execute("SELECT * FROM source_health WHERE provider=?", (provider,)).fetchone()
            usage = conn.execute("SELECT * FROM source_usage_daily WHERE provider=? AND day=?", (provider, day)).fetchone()
            cache_count = conn.execute("SELECT COUNT(*) AS n, MAX(fetched_at) AS latest FROM source_response_cache WHERE provider=?", (provider,)).fetchone()
            item = {
                "provider": provider,
                "status": health["last_status"] if health else "idle",
                "last_success_at": health["last_success_at"] if health else None,
                "last_failure_at": health["last_failure_at"] if health else None,
                "last_error": health["last_error"] if health else None,
                "last_latency_ms": health["last_latency_ms"] if health else None,
                "network_requests_today": usage["network_requests"] if usage else 0,
                "cache_hits_today": usage["cache_hits"] if usage else 0,
                "stale_hits_today": usage["stale_hits"] if usage else 0,
                "failures_today": usage["failures"] if usage else 0,
                "cache_entries": cache_count["n"] if cache_count else 0,
                "cache_latest_at": cache_count["latest"] if cache_count else None,
            }
            total = item["network_requests_today"] + item["cache_hits_today"] + item["stale_hits_today"]
            item["cache_hit_ratio"] = ((item["cache_hits_today"] + item["stale_hits_today"]) / total) if total else None
            out.append(item)
    return out


def source_cache_clear(provider: str | None = None) -> int:
    init_db()
    with _connect() as conn:
        if provider:
            cur = conn.execute("DELETE FROM source_response_cache WHERE provider=?", (str(provider),))
        else:
            cur = conn.execute("DELETE FROM source_response_cache")
        conn.commit()
    return int(cur.rowcount or 0)


def save_ai_evidence(record: dict[str, Any]) -> dict[str, Any]:
    init_db()
    retrieved_at = str(record.get("retrieved_at") or _now())
    payload = {**record, "retrieved_at": retrieved_at}
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO ai_evidence_records (
                project_id, market, evidence_type, field_name, value_json, source_name, source_url, source_type,
                evidence_level, retrieval_method, confidence, observed_at, retrieved_at, excerpt, source_hash, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, market, evidence_type, field_name, source_url) DO UPDATE SET
                value_json=excluded.value_json, source_name=excluded.source_name, source_type=excluded.source_type,
                evidence_level=excluded.evidence_level, retrieval_method=excluded.retrieval_method, confidence=excluded.confidence,
                observed_at=excluded.observed_at, retrieved_at=excluded.retrieved_at, excerpt=excluded.excerpt,
                source_hash=excluded.source_hash, metadata_json=excluded.metadata_json
            """,
            (
                int(payload.get("project_id") or 0), str(payload.get("market") or "").upper(),
                str(payload.get("evidence_type") or ""), str(payload.get("field_name") or ""),
                json.dumps(payload.get("value"), ensure_ascii=False), str(payload.get("source_name") or ""),
                str(payload.get("source_url") or ""), str(payload.get("source_type") or ""),
                str(payload.get("evidence_level") or ""), str(payload.get("retrieval_method") or "ai"),
                str(payload.get("confidence") or ""), payload.get("observed_at"), retrieved_at,
                str(payload.get("excerpt") or "")[:1000], str(payload.get("source_hash") or ""),
                json.dumps(payload.get("metadata") or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
    return payload


def list_ai_evidence(project_id: int, market: str | None = None, evidence_type: str | None = None) -> list[dict[str, Any]]:
    init_db()
    clauses=["project_id=?"]; params:[Any]=[int(project_id)]
    if market is not None:
        clauses.append("market=?"); params.append(str(market or "").upper())
    if evidence_type:
        clauses.append("evidence_type=?"); params.append(str(evidence_type))
    sql="SELECT * FROM ai_evidence_records WHERE "+" AND ".join(clauses)+" ORDER BY retrieved_at DESC, id DESC"
    with _connect() as conn:
        rows=conn.execute(sql, tuple(params)).fetchall()
    out=[]
    for row in rows:
        item=dict(row)
        try: item["value"]=json.loads(item.pop("value_json"))
        except Exception: item["value"]=None; item.pop("value_json",None)
        try: item["metadata"]=json.loads(item.pop("metadata_json"))
        except Exception: item["metadata"]={}; item.pop("metadata_json",None)
        out.append(item)
    return out


def latest_ai_evidence(project_id: int, market: str, field_name: str) -> dict[str, Any] | None:
    rows=list_ai_evidence(project_id, market)
    return next((r for r in rows if r.get("field_name")==field_name), None)


def start_ai_recovery_run(project_id: int, market: str, requested: dict[str, Any]) -> int:
    init_db()
    with _connect() as conn:
        cur=conn.execute(
            "INSERT INTO ai_recovery_runs(project_id,market,started_at,status,requested_json,result_json,error) VALUES(?,?,?,?,?,?,?)",
            (int(project_id),str(market or "").upper(),_now(),"running",json.dumps(requested or {},ensure_ascii=False),"{}","")
        )
        conn.commit(); return int(cur.lastrowid)


def finish_ai_recovery_run(run_id: int, *, status: str, result: dict[str, Any] | None = None, error: str = "") -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            "UPDATE ai_recovery_runs SET completed_at=?, status=?, result_json=?, error=? WHERE id=?",
            (_now(),str(status),json.dumps(result or {},ensure_ascii=False),str(error or "")[:2000],int(run_id))
        ); conn.commit()


def list_ai_recovery_runs(project_id: int, market: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    init_db(); params:[Any]=[int(project_id)]; where="project_id=?"
    if market is not None: where+=" AND market=?"; params.append(str(market or "").upper())
    params.append(max(1,min(int(limit),100)))
    with _connect() as conn:
        rows=conn.execute(f"SELECT * FROM ai_recovery_runs WHERE {where} ORDER BY id DESC LIMIT ?",tuple(params)).fetchall()
    out=[]
    for row in rows:
        item=dict(row)
        for k in ("requested_json","result_json"):
            try:item[k[:-5]]=json.loads(item.pop(k))
            except Exception:item[k[:-5]]={};item.pop(k,None)
        out.append(item)
    return out


def save_hs_ranking_feedback(*, project_id: int = 0, query_text: str, selected_code: str, candidate_codes: list[str]) -> dict[str, Any]:
    init_db(); now = _now()
    payload = {
        "project_id": int(project_id or 0), "query_text": str(query_text or "")[:2000],
        "selected_code": str(selected_code or "")[:20],
        "candidate_codes": [str(x)[:20] for x in (candidate_codes or [])[:30]], "created_at": now,
    }
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO hs_ranking_feedback(project_id,query_text,selected_code,candidate_codes_json,created_at) VALUES(?,?,?,?,?)",
            (payload["project_id"], payload["query_text"], payload["selected_code"], json.dumps(payload["candidate_codes"], ensure_ascii=False), now),
        )
        conn.commit(); payload["id"] = int(cur.lastrowid)
    return payload


def list_hs_ranking_feedback(limit: int = 200) -> list[dict[str, Any]]:
    init_db(); cap=max(1,min(int(limit or 200),1000))
    with _connect() as conn:
        rows=conn.execute("SELECT * FROM hs_ranking_feedback ORDER BY id DESC LIMIT ?", (cap,)).fetchall()
    out=[]
    for row in rows:
        item=dict(row)
        try:item["candidate_codes"]=json.loads(item.pop("candidate_codes_json"))
        except Exception:item["candidate_codes"]=[];item.pop("candidate_codes_json",None)
        out.append(item)
    return out
