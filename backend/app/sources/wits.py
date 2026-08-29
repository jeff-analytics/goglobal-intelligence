from __future__ import annotations

from typing import Any
from threading import Lock
from time import monotonic

import requests

from ..source_runtime import cache_key, cached_call
from ..storage import source_cache_get

WITS_BASE = "https://wits.worldbank.org/API/V1/SDMX/V21/datasource/TRN"
# WITS is a useful historical reference, but it is not reliable enough to block
# an interactive research flow. One bounded attempt is made when the user
# explicitly refreshes the WITS matrix. Repeated failures open a short circuit
# breaker so a global scan does not wait on the same unavailable host hundreds
# of times.
WITS_ATTEMPTS = 1
WITS_CONNECT_TIMEOUT = 2.5
WITS_READ_TIMEOUT = 5
WITS_BREAKER_THRESHOLD = 1
WITS_BREAKER_COOLDOWN_SECONDS = 10 * 60
_BREAKER_LOCK = Lock()
_NETWORK_LOCK = Lock()
_BREAKER_FAILURES = 0
_BREAKER_OPEN_UNTIL = 0.0


def _breaker_before_request() -> None:
    with _BREAKER_LOCK:
        if monotonic() < _BREAKER_OPEN_UNTIL:
            raise RuntimeError("WITS_NETWORK_PAUSED")


def _breaker_success() -> None:
    global _BREAKER_FAILURES, _BREAKER_OPEN_UNTIL
    with _BREAKER_LOCK:
        _BREAKER_FAILURES = 0
        _BREAKER_OPEN_UNTIL = 0.0


def _breaker_failure() -> None:
    global _BREAKER_FAILURES, _BREAKER_OPEN_UNTIL
    with _BREAKER_LOCK:
        _BREAKER_FAILURES += 1
        if _BREAKER_FAILURES >= WITS_BREAKER_THRESHOLD:
            _BREAKER_OPEN_UNTIL = monotonic() + WITS_BREAKER_COOLDOWN_SECONDS


def _request_identity(*, reporter_code: str, partner_code: str, hs_code: str, year: str, datatype: str):
    url = (
        f"{WITS_BASE}/reporter/{reporter_code}/partner/{partner_code}/"
        f"product/{hs_code}/year/{year}/datatype/{datatype}"
    )
    params = {"format": "JSON"}
    return url, params, cache_key(url, params)


def _cached_payload(*, reporter_code: str, partner_code: str, hs_code: str, year: str, datatype: str) -> Any | None:
    _, _, key = _request_identity(
        reporter_code=reporter_code, partner_code=partner_code, hs_code=hs_code, year=year, datatype=datatype
    )
    row = source_cache_get("UNCTAD TRAINS / WITS", key)
    return (row or {}).get("payload") if row else None


def _pick_ci(row: dict[str, Any], *keys: str):
    lowered = {str(k).lower().lstrip("@"): v for k, v in row.items()}
    for key in keys:
        normalized = key.lower().lstrip("@")
        if normalized in lowered:
            return lowered[normalized]
    return None


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _collect_observations(node: Any, inherited: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Collect WITS observations while retaining scalar dimensions from parents.

    WITS SDMX JSON can place dimensions on a Series object and OBS_VALUE on a
    nested Obs object. A plain recursive walk loses that context, so we carry it
    down the tree.
    """
    inherited = dict(inherited or {})
    found: list[dict[str, Any]] = []

    if isinstance(node, dict):
        current = dict(inherited)
        for key, value in node.items():
            if not isinstance(value, (dict, list)):
                current[str(key)] = value

        obs_value = _pick_ci(current, "OBS_VALUE", "obs_value", "value")
        if obs_value is not None and _num(obs_value) is not None:
            found.append(current)

        for value in node.values():
            if isinstance(value, (dict, list)):
                found.extend(_collect_observations(value, current))

    elif isinstance(node, list):
        for value in node:
            found.extend(_collect_observations(value, inherited))

    return found


def _request_tariff(*, reporter_code: str, partner_code: str, hs_code: str, year: str, datatype: str, force_refresh: bool = False) -> Any:
    url, params, key = _request_identity(
        reporter_code=reporter_code, partner_code=partner_code, hs_code=hs_code, year=year, datatype=datatype
    )

    def network_fetch():
        # Serialize live WITS traffic. If the host times out once, the circuit
        # opens before queued tariff-matrix workers can create a request storm.
        with _NETWORK_LOCK:
            _breaker_before_request()
            last_exc: Exception | None = None
            attempts = max(1, int(WITS_ATTEMPTS))
            for attempt in range(attempts):
                try:
                    response = requests.get(url, params=params, timeout=(WITS_CONNECT_TIMEOUT, WITS_READ_TIMEOUT))
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < attempts - 1:
                        last_exc = requests.HTTPError(f"WITS HTTP {response.status_code}")
                        continue
                    response.raise_for_status()
                    try:
                        payload = response.json()
                        _breaker_success()
                        return payload
                    except ValueError as exc:
                        raise ValueError("WITS returned a non-JSON response") from exc
                except Exception as exc:
                    last_exc = exc
                    if attempt >= attempts - 1:
                        break
            assert last_exc is not None
            _breaker_failure()
            if isinstance(last_exc, requests.Timeout):
                raise RuntimeError(f"WITS request timed out after {attempts} attempt(s)") from last_exc
            if isinstance(last_exc, requests.ConnectionError):
                raise RuntimeError(f"WITS connection failed after {attempts} attempt(s)") from last_exc
            raise last_exc

    payload, _meta = cached_call(
        provider="UNCTAD TRAINS / WITS",
        key=key,
        fetcher=network_fetch,
        ttl_seconds=7 * 24 * 60 * 60,
        stale_ttl_seconds=90 * 24 * 60 * 60,
        force_refresh=force_refresh,
    )
    return payload


def _candidate_year(row: dict[str, Any]) -> int | None:
    value = _pick_ci(row, "YEAR", "TIME_PERIOD", "time_period", "year")
    try:
        return int(str(value)[:4]) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _select_candidate(candidates: list[dict[str, Any]], requested_year: int) -> dict[str, Any] | None:
    numeric = [row for row in candidates if _num(_pick_ci(row, "OBS_VALUE", "obs_value", "value")) is not None]
    if not numeric:
        return None

    dated = [(row, _candidate_year(row)) for row in numeric]
    at_or_before = [(row, yr) for row, yr in dated if yr is not None and yr <= requested_year]
    if at_or_before:
        at_or_before.sort(key=lambda pair: pair[1])
        return at_or_before[-1][0]

    dated_valid = [(row, yr) for row, yr in dated if yr is not None]
    if dated_valid:
        dated_valid.sort(key=lambda pair: pair[1])
        return dated_valid[-1][0]
    return numeric[0]


def fetch_tariff_cached(
    *, reporter_code: str, partner_code: str, hs_code: str, year: str, datatype: str = "reported"
) -> dict[str, Any] | None:
    """Read any previously observed WITS tariff without making a network call.

    Interactive market refreshes use this path so WITS cannot hold the page open.
    The explicit tariff-matrix scan remains the place that refreshes WITS live.
    """
    requested_year = int(year)
    for candidate_year in (str(year), "all"):
        payload = _cached_payload(
            reporter_code=reporter_code, partner_code=partner_code, hs_code=hs_code, year=candidate_year, datatype=datatype
        )
        if payload is None:
            continue
        row = _select_candidate(_collect_observations(payload), requested_year)
        if row is None:
            continue
        actual_year = _candidate_year(row)
        return {
            "reporter_code": reporter_code,
            "partner_code": partner_code,
            "hs_code": hs_code,
            "requested_year": year,
            "year": actual_year,
            "datatype": datatype,
            "rate": _num(_pick_ci(row, "OBS_VALUE", "obs_value", "value")),
            "tariff_type": _pick_ci(row, "TARIFFTYPE", "tarifftype", "tariff_type"),
            "min_rate": _num(_pick_ci(row, "MIN_RATE", "min_rate")),
            "max_rate": _num(_pick_ci(row, "MAX_RATE", "max_rate")),
            "nomenclature": _pick_ci(row, "NOMENCODE", "nomencode"),
            "fallback_used": bool(candidate_year == "all" or (actual_year is not None and actual_year != requested_year)),
            "source": "UNCTAD TRAINS / WITS",
            "source_type": "cached-historical-reference",
            "note": None,
        }
    return None


def fetch_tariff(*, reporter_code: str, partner_code: str, hs_code: str, year: str, datatype: str = "reported") -> dict[str, Any]:
    requested_year = int(year)
    exact_payload = _request_tariff(
        reporter_code=reporter_code,
        partner_code=partner_code,
        hs_code=hs_code,
        year=year,
        datatype=datatype,
    )
    candidates = _collect_observations(exact_payload)
    row = _select_candidate(candidates, requested_year)
    fallback_used = False

    # TRAINS coverage often lags current trade data. If the requested year has
    # no observation, ask for all available years and use the closest year not
    # later than the requested year.
    if row is None:
        all_payload = _request_tariff(
            reporter_code=reporter_code,
            partner_code=partner_code,
            hs_code=hs_code,
            year="all",
            datatype=datatype,
        )
        candidates = _collect_observations(all_payload)
        row = _select_candidate(candidates, requested_year)
        fallback_used = row is not None
    else:
        all_payload = None

    if row is None:
        return {
            "reporter_code": reporter_code,
            "partner_code": partner_code,
            "hs_code": hs_code,
            "requested_year": year,
            "year": None,
            "rate": None,
            "tariff_type": None,
            "min_rate": None,
            "max_rate": None,
            "nomenclature": None,
            "fallback_used": False,
            "source": "UNCTAD TRAINS / WITS",
            "note": "No numeric tariff observation was returned for this reporter-product request.",
        }

    actual_year = _candidate_year(row)
    return {
        "reporter_code": reporter_code,
        "partner_code": partner_code,
        "hs_code": hs_code,
        "requested_year": year,
        "year": actual_year,
        "datatype": datatype,
        "rate": _num(_pick_ci(row, "OBS_VALUE", "obs_value", "value")),
        "tariff_type": _pick_ci(row, "TARIFFTYPE", "tarifftype", "tariff_type"),
        "min_rate": _num(_pick_ci(row, "MIN_RATE", "min_rate")),
        "max_rate": _num(_pick_ci(row, "MAX_RATE", "max_rate")),
        "nomenclature": _pick_ci(row, "NOMENCODE", "nomencode"),
        "fallback_used": bool(fallback_used or (actual_year is not None and actual_year != requested_year)),
        "source": "UNCTAD TRAINS / WITS",
        "note": None,
    }
