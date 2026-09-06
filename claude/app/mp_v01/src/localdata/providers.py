"""Bounded read-only collectors. Public data is context, not proof of tradeability.

A current download becomes available to this app now, even when observations
refer to older periods. Historical availability is never inferred from a date.
"""
from __future__ import annotations
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
import re
import time
from urllib import request, parse, error
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
from common.validation import iso
from localdata.archive import store

PROVIDERS = {
    "bls_calendar": {"credentials": (), "scope": "calendar", "description": "BLS release calendar; no key"},
    "fed": {"credentials": (), "scope": "monetary", "description": "Federal Reserve monetary-policy RSS; no key"},
    "bls": {"credentials": (), "scope": "CUUR0000SA0", "description": "BLS latest-vintage time series; no key"},
    "sec": {"credentials": ("SEC_USER_AGENT",), "scope": "0000320193", "description": "SEC recent submissions; contact User-Agent, not a key"},
    "fred": {"credentials": ("FRED_API_KEY",), "scope": "DGS10", "description": "FRED/ALFRED explicit vintage query; registered free key"},
    "tradier": {"credentials": ("TRADIER_API_KEY",), "scope": "SPY", "description": "Tradier delayed sandbox quotes by default"},
    "alpaca": {"credentials": ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY"), "scope": "SPY", "description": "Free indicative options snapshot; not executable quotes"},
}
HOSTS = {"www.bls.gov", "api.bls.gov", "www.federalreserve.gov", "data.sec.gov",
         "api.stlouisfed.org", "sandbox.tradier.com", "api.tradier.com", "data.alpaca.markets"}


class DataError(RuntimeError):
    """Safe messages only: no response bodies, query strings or credentials."""


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise DataError("REDIRECT_REFUSED")


class Transport:
    def __init__(self, *, opener=None, pause_seconds=1.0):
        self.opener = opener or request.build_opener(NoRedirect())
        self.pause = pause_seconds
        self.last = None

    def get(self, url: str, params=None, headers=None) -> bytes:
        parts = parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in HOSTS or parts.query or parts.fragment or parts.username or parts.port not in (None, 443):
            raise DataError("UNAPPROVED_ENDPOINT")
        if not parts.path.startswith(("/schedule/", "/feeds/", "/submissions/", "/fred/", "/publicAPI/", "/v1/markets/", "/v1beta1/options/")):
            raise DataError("UNAPPROVED_ENDPOINT")
        if self.last is not None:
            time.sleep(max(0, self.pause - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        query = parse.urlencode(params or {})
        req = request.Request(url + ("?" + query if query else ""), headers={
            "User-Agent": "MoneyPrinter-local-research/0.6", "Accept": "application/json, text/calendar, application/rss+xml", **(headers or {})})
        try:
            with self.opener.open(req, timeout=25) as response:
                body = response.read(20_000_001)
            if len(body) > 20_000_000:
                raise DataError("RESPONSE_TOO_LARGE")
            return body
        except error.HTTPError as exc:
            kind = {401: "AUTH_FAILED", 403: "ACCESS_DENIED", 429: "RATE_LIMITED"}.get(exc.code, "HTTP_ERROR")
            raise DataError(f"{kind} (HTTP {exc.code})") from None
        except (error.URLError, TimeoutError, OSError):
            raise DataError("UNREACHABLE (network, DNS, TLS, proxy or timeout)") from None


def parse_calendar(raw: bytes, received: str) -> list[dict]:
    text = raw.decode("utf-8-sig")
    if "BEGIN:VCALENDAR" not in text:
        raise DataError("INVALID_CALENDAR")
    text = re.sub(r"\r?\n[ \t]", "", text)
    rows = []
    for block in text.split("BEGIN:VEVENT")[1:]:
        block = block.split("END:VEVENT")[0]
        fields = {}
        for line in block.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fields[k] = v
        if any(k.startswith("RRULE") for k in fields):
            raise DataError("UNSUPPORTED_RECURRING_CALENDAR")
        start = next(((k, v) for k, v in fields.items() if k.startswith("DTSTART")), None)
        if not start:
            continue
        key, value = start
        event = None
        if "T" in value:
            zone = ZoneInfo(key.split("TZID=", 1)[1].split(";", 1)[0].strip('"')) if "TZID=" in key else ZoneInfo("America/New_York")
            if value.endswith("Z"):
                zone, value = timezone.utc, value[:-1]
            event = iso(datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=zone))
        rows.append({"event_id": fields.get("UID"), "title": fields.get("SUMMARY", ""),
                     "event_utc": event, "event_date": value[:8] if event is None else None,
                     "status": fields.get("STATUS", "CONFIRMED"), "available_utc": iso(received),
                     "calendar_complete": False})
    return rows


def parse_feed(raw: bytes, received: str) -> list[dict]:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise DataError("UNSAFE_XML")
    root = ET.fromstring(raw)
    if root.tag != "rss":
        raise DataError("INVALID_FEED")
    rows = []
    for item in root.findall("./channel/item"):
        published = item.findtext("pubDate")
        rows.append({"title": item.findtext("title"), "url": item.findtext("link"),
                     "published_utc": iso(parsedate_to_datetime(published)) if published else None,
                     "available_utc": iso(received), "usage": "CONTEXT_ONLY"})
    return rows


def normalize(provider: str, raw: bytes, received: str, *, vintage: str, production: bool = False) -> list[dict]:
    if provider == "bls_calendar":
        return parse_calendar(raw, received)
    if provider == "fed":
        return parse_feed(raw, received)
    doc = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(doc, dict):
        raise DataError("INVALID_JSON_OBJECT")
    if provider == "sec":
        recent = doc.get("filings", {}).get("recent")
        if not isinstance(recent, dict) or not isinstance(recent.get("accessionNumber"), list):
            raise DataError("INVALID_SEC_RESPONSE")
        keys = ("accessionNumber", "form", "filingDate", "acceptanceDateTime", "primaryDocument")
        n = len(recent["accessionNumber"])
        if any(not isinstance(recent.get(k), list) or len(recent[k]) != n for k in keys):
            raise DataError("INCONSISTENT_SEC_ARRAYS")
        return [{**{k: recent[k][i] for k in keys}, "available_utc": iso(received),
                 "coverage": "RECENT_SUBMISSIONS_ONLY", "usage": "CONTEXT_ONLY"} for i in range(n)]
    if provider == "fred":
        observations = doc.get("observations")
        if not isinstance(observations, list) or doc.get("count", len(observations)) > len(observations):
            raise DataError("INCOMPLETE_FRED_RESPONSE")
        return [{"date": r["date"], "value": r["value"],
                 "requested_vintage": vintage, "realtime_start": r.get("realtime_start"),
                 "realtime_end": r.get("realtime_end"), "available_utc": iso(received),
                 "usage": "VINTAGE_CONTEXT_NOT_INTRADAY_PROOF"} for r in observations]
    if provider == "bls":
        if doc.get("status") != "REQUEST_SUCCEEDED":
            raise DataError("BLS_REQUEST_FAILED")
        return [{"series_id": s["seriesID"], **r, "available_utc": iso(received),
                 "usage": "LATEST_VINTAGE_CONTEXT"} for s in doc["Results"]["series"] for r in s["data"]]
    if provider == "tradier":
        quotes = doc.get("quotes", {}).get("quote") if isinstance(doc.get("quotes"), dict) else None
        if quotes is None:
            return []
        quotes = quotes if isinstance(quotes, list) else [quotes]
        if not all(isinstance(q, dict) for q in quotes):
            raise DataError("INVALID_TRADIER_RESPONSE")
        return [{"symbol": q.get("symbol"), "bid": q.get("bid"), "ask": q.get("ask"),
                 "vendor_bid_date_ms": q.get("bid_date"), "vendor_ask_date_ms": q.get("ask_date"),
                 "vendor_bid_size": q.get("bidsize"), "vendor_ask_size": q.get("asksize"),
                 "feed_type": "CONSOLIDATED" if production else "DELAYED_SANDBOX",
                 "size_units": "UNVERIFIED_VENDOR_UNITS", "available_utc": iso(received),
                 "executable_verified": False, "usage": "QUOTE_ARCHIVE_ONLY"} for q in quotes]
    if provider == "alpaca":
        snapshots = doc.get("snapshots")
        if not isinstance(snapshots, dict):
            raise DataError("INVALID_ALPACA_RESPONSE")
        return [{"contract_id": symbol, "snapshot": value, "feed_type": "INDICATIVE",
                 "executable_verified": False, "coverage": "BOUNDED_FIRST_PAGE",
                 "more_pages_available": bool(doc.get("next_page_token")),
                 "available_utc": iso(received)} for symbol, value in snapshots.items()]
    raise DataError("UNKNOWN_PROVIDER")


def collect(root, provider: str, *, scope: str | None = None, vintage: str | None = None,
            production: bool = False, transport=None, env=None, now=None):
    if provider not in PROVIDERS:
        raise DataError("UNKNOWN_PROVIDER")
    env = os.environ if env is None else env
    config = PROVIDERS[provider]
    missing = [k for k in config["credentials"] if not env.get(k, "").strip()]
    if missing:
        raise DataError("MISSING_CREDENTIAL: " + ", ".join(missing))
    secrets = tuple(env[k] for k in config["credentials"])
    scope = scope or config["scope"]
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,40}", scope):
        raise DataError("INVALID_SCOPE")
    vintage = vintage or datetime.now(timezone.utc).date().isoformat()
    datetime.strptime(vintage, "%Y-%m-%d")
    headers, params = {}, {}
    if provider == "bls_calendar":
        url = "https://www.bls.gov/schedule/news_release/bls.ics"
    elif provider == "fed":
        url = "https://www.federalreserve.gov/feeds/press_monetary.xml"
    elif provider == "bls":
        url = "https://api.bls.gov/publicAPI/v1/timeseries/data/" + parse.quote(scope, safe="")
    elif provider == "sec":
        if not scope.isdigit() or len(scope) > 10 or "@" not in env["SEC_USER_AGENT"] or "\n" in env["SEC_USER_AGENT"] or "\r" in env["SEC_USER_AGENT"]:
            raise DataError("SEC_REQUIRES_NUMERIC_CIK_AND_CONTACT_USER_AGENT")
        url = "https://data.sec.gov/submissions/CIK" + scope.zfill(10) + ".json"
        headers["User-Agent"] = env["SEC_USER_AGENT"]
    elif provider == "fred":
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {"api_key": env["FRED_API_KEY"], "series_id": scope, "file_type": "json",
                  "realtime_start": vintage, "realtime_end": vintage, "limit": 100000}
    elif provider == "tradier":
        host = "api.tradier.com" if production else "sandbox.tradier.com"
        url = f"https://{host}/v1/markets/quotes"
        params = {"symbols": scope, "greeks": "false"}
        headers["Authorization"] = "Bearer " + env["TRADIER_API_KEY"]
    else:
        url = "https://data.alpaca.markets/v1beta1/options/snapshots/" + parse.quote(scope, safe="")
        params = {"feed": "indicative", "limit": 100}
        headers = {"APCA-API-KEY-ID": env["APCA_API_KEY_ID"], "APCA-API-SECRET-KEY": env["APCA_API_SECRET_KEY"]}
    raw = (transport or Transport()).get(url, params, headers)
    received = now or datetime.now(timezone.utc).isoformat()
    try:
        rows = normalize(provider, raw, received, vintage=vintage, production=production)
        return store(root, provider=provider, scope=scope.replace(":", "_"), source=url, raw=raw,
                     records=rows, received_utc=received, kind="context", secrets=secrets)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, ET.ParseError, UnicodeError):
        raise DataError("INVALID_PROVIDER_RESPONSE (nothing saved)") from None
