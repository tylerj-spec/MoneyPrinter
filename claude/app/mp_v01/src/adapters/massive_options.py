"""
Massive (formerly Polygon.io) adapter - HISTORICAL option contracts and bars.

WHY THIS FILE EXISTS
adapters/yahoo_daily.py has said since it was written that Yahoo serves only
CURRENT option chains, and named historical chains the project's top open risk:
there is no way to ask Yahoo what the SPY chain looked like on 2024-03-05. That
constraint is why backtest.py measures the signal layer and refuses to draw an
options equity curve - the numbers for one would have to be invented.

Massive sells exactly that history. If the account's entitlement covers it, the
options layer becomes testable against the past rather than only forward.

WHAT WAS VERIFIED, AND HOW
Every path, parameter and field name below was read out of the vendor's own
Python client (github.com/massive-com/client-python), not inferred from their
marketing pages or from Polygon documentation remembered from before the
2025-10-30 rebrand. What has NOT been verified is what a given account is
entitled to, because this repository's build environment cannot reach
api.massive.com at all. Hence probe() - see below.

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

THE POINT-IN-TIME SHAPE, WHICH IS NOT THE OBVIOUS ONE
There is a snapshot endpoint that returns a chain WITH vendor Greeks, but it is
a snapshot of NOW - it cannot be asked about a past date, so it is no better
than Yahoo for history. Historical work goes through two calls instead:

  1. /v3/reference/options/contracts?as_of=D&expired=true
     the contracts that EXISTED on date D. `as_of` is what makes this
     point-in-time rather than a survivorship-biased list of what still trades.
  2. /v2/aggs/ticker/O:SPY240315C00500000/range/1/day/FROM/TO
     that contract's daily bars.

So the vendor supplies historical PRICES, and the Greeks are solved here, from
the quote, by options/greeks.py. That is the better arrangement anyway: a
vendor's Greeks carry their volatility model and their dividend assumption,
neither of which is stated, whereas a solved IV is reproducible from numbers
that are in the file.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from common.timezones import US_EASTERN as NY

TOKEN_ENV_VAR = "MASSIVE_API_KEY"
BASE_URL = "https://api.massive.com"

# Verbatim from massive/rest/reference.py and massive/rest/aggs.py in the
# vendor's client. Kept together so a rebrand or version bump is one edit.
CONTRACTS_PATH = "/v3/reference/options/contracts"
AGGS_PATH = "/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_}/{to}"
CHAIN_SNAPSHOT_PATH = "/v3/snapshot/options/{underlying}"

# A daily bar for session D is final after the 16:00 ET close and published with
# a lag. Same conservative convention as yahoo_daily: consumable next morning,
# never on its own date. Tighten only with measured evidence of real latency.
BAR_AVAILABILITY_LAG_HOURS = 17


class MissingCredential(RuntimeError):
    pass


class MassiveError(RuntimeError):
    """A call that came back wrong. Carries no key: see redact().

    `kind` is set where the error is RAISED, not sniffed out of the message
    afterwards. Sniffing got this wrong immediately: an HTTPS proxy refusing to
    open a tunnel says "403 Forbidden", and a classifier looking for "403" in
    the text reported NOT_ENTITLED - sending the reader to check a subscription
    when the real problem was that the host was unreachable. The two need
    completely different responses, so the distinction is recorded at the only
    point that actually knows it.
    """

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
    """Scrub the key from any string before it is logged or written anywhere."""
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


# ---------------------------------------------------------------------------
# Normalisation - pure, and therefore the part that is actually tested
# ---------------------------------------------------------------------------
# The chain-NaN bug that emptied four tickers existed because this logic lived
# inline in a network call where no test could reach it. It does not happen
# twice: nothing below touches the network.

def _finite(value: Any) -> float | None:
    """A real number, or None. NaN, infinities and non-numerics become None."""
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
    """One row of /v3/reference/options/contracts.

    `as_of` is carried onto the record because it is the entire reason the row
    is trustworthy: it says the contract existed on that date, rather than that
    it exists now and might have been listed later.
    """
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
    """One daily bar from /v2/aggs. Keys are single letters; see models/aggs.py.

    `t` is epoch MILLISECONDS at the start of the aggregate window. Reading it
    as seconds would place every bar in 1970, and reading the date in UTC rather
    than ET would move any late-session bar onto the following day - the same
    off-by-one the walk-forward calendar had to be taught.
    """
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
    """OCC-style symbol as Massive spells it: O:SPY240315C00500000.

    Strike is in thousandths, zero-padded to eight digits. Built here rather
    than assembled at call sites so there is one place to be wrong.
    """
    k = kind.strip().upper()
    if k not in ("CALL", "PUT"):
        raise ValueError(f"kind must be CALL or PUT, got {kind!r}")
    y, m, d = expiration.split("-")
    thousandths = int(round(float(strike) * 1000))
    if thousandths <= 0:
        raise ValueError(f"strike must be positive, got {strike!r}")
    return f"O:{underlying.strip().upper()}{y[2:]}{m}{d}{k[0]}{thousandths:08d}"


# ---------------------------------------------------------------------------
# The network layer - deliberately thin, and never trusted without a probe
# ---------------------------------------------------------------------------

def _get(path: str, params: dict[str, Any] | None = None,
         *, timeout: int = 30) -> dict[str, Any]:
    """One GET. Raises MassiveError with the key scrubbed from the message."""
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
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        # 401/403 is an entitlement answer, not a crash: the free tier is sold
        # per asset class, so "your key works but not for options" is a real and
        # likely outcome that the caller needs to be able to read.
        kind = "NOT_ENTITLED" if e.code in (401, 402, 403) else "HTTP_ERROR"
        raise MassiveError(redact(f"HTTP {e.code} on {path}: {body}"), kind) from None
    except urllib.error.URLError as e:
        # URLError means the request never got an HTTP answer at all - DNS,
        # TLS, a refused connection, or a proxy declining the tunnel. Whatever
        # digits appear in the reason, this is not an entitlement verdict.
        raise MassiveError(redact(f"cannot reach {BASE_URL}: {e.reason}"),
                           "UNREACHABLE") from None


def _paginate(path: str, params: dict[str, Any], *, max_pages: int = 20) -> Iterator[dict]:
    """Follow next_url. Bounded, because an unbounded loop against a metered
    API is how a free tier becomes a surprise bill on a paid one."""
    page = _get(path, params)
    for _ in range(max_pages):
        for row in page.get("results") or []:
            yield row
        nxt = page.get("next_url")
        if not nxt:
            return
        page = _get(nxt[len(BASE_URL):] if nxt.startswith(BASE_URL) else nxt)


def list_contracts_as_of(underlying: str, as_of: str, *, expired: bool = True,
                         limit: int = 1000, max_pages: int = 20) -> list[dict[str, Any]]:
    """The contracts that existed on `as_of`. This is the point-in-time call."""
    rows = _paginate(CONTRACTS_PATH, {
        "underlying_ticker": underlying.strip().upper(),
        "as_of": as_of, "expired": str(bool(expired)).lower(), "limit": limit,
    }, max_pages=max_pages)
    return [normalize_contract(r, as_of=as_of) for r in rows]


def contract_daily_bars(symbol: str, start: str, end: str,
                        *, adjusted: bool = True) -> list[dict[str, Any]]:
    """Daily bars for one option contract."""
    path = AGGS_PATH.format(ticker=urllib.parse.quote(symbol, safe=""),
                            multiplier=1, timespan="day", from_=start, to=end)
    doc = _get(path, {"adjusted": str(bool(adjusted)).lower(), "limit": 50000})
    return [normalize_agg(r, contract_symbol=symbol) for r in (doc.get("results") or [])]


def probe(underlying: str = "SPY", as_of: str | None = None) -> dict[str, Any]:
    """Spend ONE call to find out what this account can actually do.

    The build environment for this repository cannot reach api.massive.com, so
    nothing above has been executed against the live service. Rather than let a
    backfill discover that at scale, this makes a single cheap request and
    reports exactly what came back - entitlement, shape, and whether `as_of`
    is honoured. Run it before anything else.
    """
    as_of = as_of or (datetime.now(NY).date() - timedelta(days=400)).isoformat()
    out: dict[str, Any] = {"as_of": as_of, "underlying": underlying,
                           "endpoint": CONTRACTS_PATH}
    try:
        doc = _get(CONTRACTS_PATH, {"underlying_ticker": underlying.upper(),
                                    "as_of": as_of, "expired": "true", "limit": 5})
    except MissingCredential as e:
        out.update(ok=False, reason="NO_KEY", detail=str(e))
        return out
    except MassiveError as e:
        out.update(ok=False, detail=str(e), reason=e.kind)
        return out

    rows = doc.get("results") or []
    out.update(ok=True, status=doc.get("status"), returned=len(rows),
               has_next_page=bool(doc.get("next_url")),
               sample=[normalize_contract(r, as_of=as_of) for r in rows[:3]],
               unexpected_keys=sorted(set(rows[0]) - {
                   "cfi", "contract_type", "exercise_style", "expiration_date",
                   "primary_exchange", "shares_per_contract", "strike_price",
                   "ticker", "underlying_ticker", "correction",
                   "additional_underlyings"}) if rows else [])
    return out
