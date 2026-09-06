"""
Massive (formerly Polygon.io) adapter - HISTORICAL option contracts and bars.

WHY THIS FILE EXISTS
adapters/yahoo_daily.py has said since it was written that Yahoo serves only
CURRENT option chains, and named historical chains the project's top open risk:
there is no way to ask Yahoo what the SPY chain looked like on 2024-03-05. That
constraint is why backtest.py measures the signal layer and refuses to draw an
options equity curve - the numbers for one would have to be invented.

Massive sells historical option reference and price data. If the account's
entitlement covers it, the options layer can be tested against the past rather
than only forward. The adapter still fails closed: an HTTP 200 is not treated as
proof that a point-in-time filter was honoured.

WHAT WAS VERIFIED, AND HOW
Every path, parameter and field name below was read out of the vendor's own
Python client and current REST documentation. What has NOT been verified in this
repository is what a particular account is entitled to, because the build
environment cannot reach api.massive.com. Hence diagnose_access() below.

CREDENTIAL HANDLING (same rules as adapters/eodhd_options.py)
The key is read from MASSIVE_API_KEY, which is the vendor client's own default
variable name. It is never written to a file, never logged, never passed as an
argument that could surface in a traceback.

    setx MASSIVE_API_KEY "your-key-here"        (Windows; open a NEW terminal)

Two properties make this safer than the EODHD path, and both are the vendor's
doing rather than ours:
  - authentication is an Authorization: Bearer header, so the key never appears
    in a URL, and URLs are what request libraries put into exception messages
  - redact() still scrubs it from any text, because "never" is a property worth
    enforcing twice

THE POINT-IN-TIME SHAPE
There is a snapshot endpoint that returns a chain WITH vendor Greeks, but it is
a snapshot of NOW. Historical work instead combines contract reference queries
with historical option bars/quotes. Massive documents `as_of` as a point-in-time
parameter and expiration_date range filters separately. This adapter therefore
keeps both: explicit expiration bounds are mechanically verifiable, while
`as_of` is diagnosed independently before a historical backfill is trusted.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator

from common.timezones import US_EASTERN as NY

TOKEN_ENV_VAR = "MASSIVE_API_KEY"
BASE_URL = "https://api.massive.com"

CONTRACTS_PATH = "/v3/reference/options/contracts"
AGGS_PATH = "/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_}/{to}"
CHAIN_SNAPSHOT_PATH = "/v3/snapshot/options/{underlying}"

BAR_AVAILABILITY_LAG_HOURS = 17


class MissingCredential(RuntimeError):
    pass


class MassiveError(RuntimeError):
    """A call that came back wrong. Carries no key: see redact()."""

    def __init__(self, message: str, kind: str = "ERROR"):
        super().__init__(message)
        self.kind = kind


def _token() -> str:
    tok = os.environ.get(TOKEN_ENV_VAR)
    if not tok:
        raise MissingCredential(
            f"{TOKEN_ENV_VAR} is not set. Set it with:\n"
            f'    setx {TOKEN_ENV_VAR} "your-key"\n'
            f"then open a new terminal. Or paste it into the app's key box, which\n"
            f"passes it to this process without writing it anywhere.\n"
            f"Do not hardcode it and do not paste it into chat."
        )
    return tok


def redact(text: str) -> str:
    tok = os.environ.get(TOKEN_ENV_VAR)
    if tok and tok in text:
        text = text.replace(tok, "***REDACTED***")
    return text


def bar_event_time(bar_date: str) -> datetime:
    y, m, d = (int(x) for x in bar_date.split("-"))
    return datetime(y, m, d, 16, 0, tzinfo=NY).astimezone(timezone.utc)


def bar_available_time(bar_date: str) -> datetime:
    y, m, d = (int(x) for x in bar_date.split("-"))
    close_et = datetime(y, m, d, 16, 0, tzinfo=NY)
    return (close_et + timedelta(hours=BAR_AVAILABILITY_LAG_HOURS)).astimezone(timezone.utc)


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _count(value: Any) -> int | None:
    f = _finite(value)
    return int(f) if f is not None and f >= 0 else None


def normalize_contract(row: dict[str, Any], *, as_of: str) -> dict[str, Any]:
    strike = _finite(row.get("strike_price"))
    kind = (row.get("contract_type") or "").upper() or None
    return {
        "contract_symbol": row.get("ticker") or None,
        "underlying": row.get("underlying_ticker") or None,
        "type": kind if kind in ("CALL", "PUT") else None,
        "strike": strike,
        "expiration": row.get("expiration_date") or None,
        "exercise_style": row.get("exercise_style") or None,
        "shares_per_contract": _count(row.get("shares_per_contract")),
        "as_of": as_of,
        "status": "OK" if (strike is not None and kind in ("CALL", "PUT")
                           and row.get("ticker") and row.get("expiration_date"))
                  else "UNKNOWN",
    }


def normalize_agg(row: dict[str, Any], *, contract_symbol: str) -> dict[str, Any]:
    ts = _finite(row.get("t"))
    day = (datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).astimezone(NY).date().isoformat()
           if ts is not None else None)
    close = _finite(row.get("c"))
    return {
        "contract_symbol": contract_symbol,
        "date": day,
        "open": _finite(row.get("o")), "high": _finite(row.get("h")),
        "low": _finite(row.get("l")), "close": close,
        "vwap": _finite(row.get("vw")),
        "volume": _count(row.get("v")),
        "transactions": _count(row.get("n")),
        "event_time": bar_event_time(day) if day else None,
        "available_time": bar_available_time(day) if day else None,
        "status": "OK" if (day and close is not None and close > 0) else "UNKNOWN",
    }


def contract_symbol(underlying: str, expiration: str, kind: str, strike: float) -> str:
    k = kind.strip().upper()
    if k not in ("CALL", "PUT"):
        raise ValueError(f"kind must be CALL or PUT, got {kind!r}")
    y, m, d = expiration.split("-")
    thousandths = int(round(float(strike) * 1000))
    if thousandths <= 0:
        raise ValueError(f"strike must be positive, got {strike!r}")
    return f"O:{underlying.strip().upper()}{y[2:]}{m}{d}{k[0]}{thousandths:08d}"


def _get(path: str, params: dict[str, Any] | None = None,
         *, timeout: int = 30) -> dict[str, Any]:
    url = BASE_URL + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + _token(),
        "Accept": "application/json",
        "User-Agent": "moneyprinter/0.1",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
            if not isinstance(doc, dict) or doc.get("status") not in ("OK", "DELAYED"):
                raise MassiveError("Response did not report an OK/DELAYED data status",
                                   "INVALID_RESPONSE")
            return doc
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        kind = "NOT_ENTITLED" if e.code in (401, 402, 403) else "HTTP_ERROR"
        raise MassiveError(redact(f"HTTP {e.code} on {path}: {body}"), kind) from None
    except urllib.error.URLError as e:
        raise MassiveError(redact(f"cannot reach {BASE_URL}: {e.reason}"),
                           "UNREACHABLE") from None


def _paginate(path: str, params: dict[str, Any], *, max_pages: int = 20) -> Iterator[dict]:
    page = _get(path, params)
    for page_index in range(max_pages):
        for row in page.get("results") or []:
            yield row
        nxt = page.get("next_url")
        if not nxt:
            return
        if page_index + 1 == max_pages:
            raise MassiveError(f"Response exceeds max_pages={max_pages}; incomplete history rejected",
                               "INCOMPLETE_RESPONSE")
        if not nxt.startswith(BASE_URL + "/"):
            raise MassiveError("Unexpected pagination URL", "INVALID_RESPONSE")
        page = _get(nxt[len(BASE_URL):] if nxt.startswith(BASE_URL) else nxt)


def _validate_contracts(rows, underlying: str, as_of: str) -> list[dict[str, Any]]:
    """An HTTP success is insufficient: verify explicit scope before saving."""
    expected = underlying.strip().upper()
    day = date.fromisoformat(as_of)
    normalized = []
    for row in rows:
        contract = normalize_contract(row, as_of=as_of)
        try:
            valid = (contract["status"] == "OK" and contract["underlying"] == expected
                     and contract["strike"] > 0
                     and date.fromisoformat(contract["expiration"]) >= day)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise MassiveError(
                f"Contract response does not match {expected} on {as_of}: "
                f"{contract['contract_symbol']} (underlying={contract['underlying']}, "
                f"expiration={contract['expiration']}). History rejected.",
                "INVALID_CONTRACT_RESPONSE")
        normalized.append(contract)
    return normalized


def list_contracts_as_of(underlying: str, as_of: str, *, expired: bool = True,
                         limit: int = 1000, max_pages: int = 20) -> list[dict[str, Any]]:
    """Request contracts as of `as_of`, with an independently checkable expiry floor."""
    rows = _paginate(CONTRACTS_PATH, {
        "underlying_ticker": underlying.strip().upper(),
        "as_of": as_of, "expired": str(bool(expired)).lower(), "limit": limit,
        "expiration_date.gte": as_of,
    }, max_pages=max_pages)
    return _validate_contracts(rows, underlying, as_of)


def contract_daily_bars(symbol: str, start: str, end: str,
                        *, adjusted: bool = True) -> list[dict[str, Any]]:
    path = AGGS_PATH.format(ticker=urllib.parse.quote(symbol, safe=""),
                            multiplier=1, timespan="day", from_=start, to=end)
    doc = _get(path, {"adjusted": str(bool(adjusted)).lower(), "limit": 50000})
    return [normalize_agg(r, contract_symbol=symbol) for r in (doc.get("results") or [])]


def _row_scope(rows: list[dict[str, Any]]) -> tuple[set[str], list[str], set[str]]:
    underlyings = {str(r.get("underlying_ticker") or "?") for r in rows}
    expirations = sorted({str(r.get("expiration_date") or "?") for r in rows})
    tickers = {str(r.get("ticker") or "?") for r in rows}
    return underlyings, expirations, tickers


def diagnose_access(underlying: str = "SPY", as_of: str | None = None,
                    pause_seconds: float = 13.0) -> list[dict[str, Any]]:
    """Five-rung, fail-closed access diagnostic.

    Constant sort/order parameters make the three-row samples deterministic.
    Each rung then adds one capability-bearing query parameter:
      1 bare control
      2 underlying_ticker
      3 expired=true
      4 expiration_date.gte=<as_of>
      5 as_of=<as_of>

    `OK` means the response directly proves the parameter did what can be
    mechanically checked. `CONSISTENT` means the final point-in-time response
    changed in a way consistent with `as_of`; it is stronger than a blind 200
    but deliberately not called proof of the vendor's full historical semantics.
    `UNVERIFIED` means the sample did not contradict the request but also did not
    demonstrate the capability. Historical backfills should not proceed on an
    UNVERIFIED final rung.
    """
    as_of = as_of or (datetime.now(NY).date() - timedelta(days=400)).isoformat()
    date.fromisoformat(as_of)  # reject malformed dates before spending a call
    want = underlying.strip().upper()
    base = {"sort": "expiration_date", "order": "asc", "limit": 3}
    rungs = [
        ("bare", dict(base), "does the endpoint answer this key at all?"),
        ("underlying filter", {**base, "underlying_ticker": want},
         "is underlying_ticker honoured?"),
        ("expired access", {**base, "underlying_ticker": want, "expired": "true"},
         "can this key return expired contracts?"),
        ("expiration floor", {**base, "underlying_ticker": want, "expired": "true",
                              "expiration_date.gte": as_of},
         "is the explicit historical expiration bound honoured?"),
        ("point in time", {**base, "underlying_ticker": want, "expired": "true",
                           "expiration_date.gte": as_of, "as_of": as_of},
         "does adding as_of have an observable point-in-time effect?"),
    ]

    out: list[dict[str, Any]] = []
    previous_tickers: set[str] | None = None
    today = datetime.now(NY).date().isoformat()

    for i, (name, params, asks) in enumerate(rungs):
        if i:
            time.sleep(pause_seconds)
        step: dict[str, Any] = {
            "step": name,
            "asks": asks,
            "params": {k: v for k, v in params.items()
                       if k not in ("limit", "sort", "order")},
        }
        try:
            doc = _get(CONTRACTS_PATH, params)
        except MassiveError as e:
            step.update(verdict=e.kind, detail=str(e))
            out.append(step)
            break

        rows = doc.get("results") or []
        step["returned"] = len(rows)
        if not rows:
            step["verdict"] = "EMPTY"
            out.append(step)
            previous_tickers = set()
            continue

        underlyings, expirations, tickers = _row_scope(rows)
        step["underlyings_returned"] = sorted(underlyings)[:5]
        step["expirations_returned"] = expirations[:5]

        if "underlying_ticker" in params and underlyings != {want}:
            step["verdict"] = "IGNORED"
            step["detail"] = (f"asked for {want}, got {', '.join(sorted(underlyings))} - "
                              "underlying_ticker is not being applied")
        elif "expiration_date.gte" in params and any(
                exp == "?" or exp < as_of for exp in expirations):
            step["verdict"] = "IGNORED"
            step["detail"] = (f"asked for expiration_date.gte={as_of}, got "
                              f"{', '.join(expirations[:5])}")
        elif name == "expired access":
            if any(exp != "?" and exp < today for exp in expirations):
                step["verdict"] = "OK"
                step["detail"] = "sample includes at least one contract already expired today"
            else:
                step["verdict"] = "UNVERIFIED"
                step["detail"] = ("expired=true returned rows, but this three-row sample "
                                  "contains no contract expired today; do not infer history access")
        elif name == "point in time":
            if previous_tickers is not None and tickers != previous_tickers:
                step["verdict"] = "CONSISTENT"
                step["detail"] = ("adding as_of changed the deterministic contract sample while "
                                  "all explicit scope checks still passed")
            else:
                step["verdict"] = "UNVERIFIED"
                step["detail"] = ("adding as_of did not change this deterministic sample. That is "
                                  "not proof it was ignored, but it also is not evidence that the "
                                  "point-in-time filter affected the response")
        else:
            step["verdict"] = "OK"

        out.append(step)
        previous_tickers = tickers

    return out


def probe(underlying: str = "SPY", as_of: str | None = None) -> dict[str, Any]:
    """Legacy one-call smoke test. Prefer diagnose_access for capability boundaries."""
    as_of = as_of or (datetime.now(NY).date() - timedelta(days=400)).isoformat()
    out: dict[str, Any] = {"as_of": as_of, "underlying": underlying,
                           "endpoint": CONTRACTS_PATH}
    try:
        doc = _get(CONTRACTS_PATH, {"underlying_ticker": underlying.upper(),
                                    "as_of": as_of, "expired": "true", "limit": 5,
                                    "expiration_date.gte": as_of})
        contracts = _validate_contracts(doc.get("results") or [], underlying, as_of)
    except MissingCredential as e:
        out.update(ok=False, reason="NO_KEY", detail=str(e))
        return out
    except MassiveError as e:
        out.update(ok=False, detail=str(e), reason=e.kind)
        return out

    rows = doc.get("results") or []
    if not rows:
        out.update(ok=False, reason="NO_MATCHING_CONTRACTS",
                   detail="No matching reference contracts returned; access is inconclusive.")
        return out
    out.update(ok=True, status=doc.get("status"), returned=len(rows),
               capability="CONTRACT_REFERENCE_ONLY",
               price_history_verified=False,
               has_next_page=bool(doc.get("next_url")),
               sample=contracts[:3],
               unexpected_keys=sorted(set(rows[0]) - {
                   "cfi", "contract_type", "exercise_style", "expiration_date",
                   "primary_exchange", "shares_per_contract", "strike_price",
                   "ticker", "underlying_ticker", "correction",
                   "additional_underlyings"}) if rows else [])
    return out
