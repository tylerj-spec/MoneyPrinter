"""
EODHD adapter - historical EOD option chains.

CREDENTIAL HANDLING (non-negotiable, per the project's own rules):
The API token is read from the EODHD_API_TOKEN environment variable. It is never
written to a file, never logged, never passed as a function argument that could
land in a traceback, and never included in a manifest or report.

Set it once on Windows:
    setx EODHD_API_TOKEN "your-token-here"
then open a NEW terminal (setx only affects new sessions).

Verify without printing it:
    python -c "import os;print('set:', bool(os.environ.get('EODHD_API_TOKEN')))"

If a token ever appears in a chat window, a commit, a log line, or a screenshot,
treat it as compromised and rotate it. Rotation is free; a leaked key on a paid
account is not.

COVERAGE NOTE:
EODHD option history begins ~Q4 2023. That is roughly one market regime - no 2022
bear, no 2020 vol shock. Sufficient to BUILD and VALIDATE the pipeline. Not
sufficient to claim regime robustness. Any result from this window must be
labelled single-regime until tested against deeper history.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

TOKEN_ENV_VAR = "EODHD_API_TOKEN"
BASE_URL = "https://eodhd.com/api"

# EOD chain for date D is published after the close; treat as consumable next morning.
CHAIN_AVAILABILITY_LAG_HOURS = 17
ET_UTC_OFFSET_HOURS = 4


class MissingCredential(RuntimeError):
    pass


def _token() -> str:
    """Fetch the token from the environment. Never returns it to a caller that logs."""
    tok = os.environ.get(TOKEN_ENV_VAR)
    if not tok:
        raise MissingCredential(
            f"{TOKEN_ENV_VAR} is not set. Set it with:\n"
            f'    setx {TOKEN_ENV_VAR} "your-token"\n'
            f"then open a new terminal. Do not hardcode it and do not paste it into chat."
        )
    return tok


def redact(text: str) -> str:
    """Scrub the token from any string before it is logged or written anywhere."""
    tok = os.environ.get(TOKEN_ENV_VAR)
    if tok and tok in text:
        text = text.replace(tok, "***REDACTED***")
    # Also catch it if it appears as a URL query parameter under any name.
    import re
    return re.sub(r"([?&](?:api_token|token|apikey|key)=)[^&\s]+", r"\1***REDACTED***", text)


def chain_available_time(chain_date: str) -> datetime:
    y, m, d = (int(x) for x in chain_date.split("-"))
    close_utc = (datetime(y, m, d, 16, 0) + timedelta(hours=ET_UTC_OFFSET_HOURS)).replace(
        tzinfo=timezone.utc)
    return close_utc + timedelta(hours=CHAIN_AVAILABILITY_LAG_HOURS)


def normalize_contract(raw: dict[str, Any], chain_date: str, underlying: str) -> dict[str, Any]:
    """
    Shape one raw contract into the four-timestamp contract.

    Fails closed: a contract without a usable two-sided quote is marked UNKNOWN
    rather than being given a synthesized mid. A fabricated mid is indistinguishable
    from a real one downstream, and it silently inflates every backtest that uses it.
    """
    bid, ask = raw.get("bid"), raw.get("ask")
    usable = (
        isinstance(bid, (int, float)) and isinstance(ask, (int, float))
        and bid > 0 and ask > 0 and ask >= bid
    )
    rec = {
        "underlying": underlying,
        "chain_date": chain_date,
        "contract": raw.get("contract") or raw.get("symbol"),
        "type": raw.get("type"),
        "strike": raw.get("strike"),
        "expiration": raw.get("expirationDate") or raw.get("exp_date"),
        "bid": bid if usable else None,
        "ask": ask if usable else None,
        "mid": round((bid + ask) / 2, 4) if usable else None,
        "volume": raw.get("volume"),
        "open_interest": raw.get("openInterest") or raw.get("open_interest"),
        "implied_volatility": raw.get("impliedVolatility") or raw.get("volatility"),
        "delta": raw.get("delta"), "gamma": raw.get("gamma"),
        "theta": raw.get("theta"), "vega": raw.get("vega"),
        "available_time": chain_available_time(chain_date),
        "status": "OK" if usable else "UNKNOWN",
    }
    if not usable:
        rec["reason"] = "no usable two-sided quote (missing, non-positive, or crossed)"
    return rec


def fetch_eod_chain(underlying: str, chain_date: str) -> list[dict[str, Any]]:
    """
    Live fetch. Run on Tyler's machine (Codex). Requires network + `requests`.

    Any exception message is passed through redact() before it can propagate,
    because request libraries habitually include the full URL - token and all -
    in their error text.
    """
    import requests  # lazy import so this module loads without the dep

    url = f"{BASE_URL}/options/{underlying}.US"
    params = {"api_token": _token(), "from": chain_date, "to": chain_date, "fmt": "json"}
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        raise RuntimeError(redact(f"EODHD fetch failed for {underlying} {chain_date}: {e}")) from None

    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    out = []
    for expiry_block in (data or []):
        contracts = expiry_block.get("options", {}) if isinstance(expiry_block, dict) else {}
        for side in ("CALL", "PUT"):
            for c in contracts.get(side, []) or []:
                c.setdefault("type", side)
                out.append(normalize_contract(c, chain_date, underlying))
    return out
