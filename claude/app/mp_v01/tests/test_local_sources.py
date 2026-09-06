"""Offline collector, archive and secret-hygiene regressions; discovered by run_all."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from unittest.mock import Mock
from localdata.archive import store, read_dataset, inventory, import_manual
from localdata.providers import collect, normalize, Transport, DataError

NOW = "2026-09-04T20:00:00Z"


def test_archives_are_immutable_checked_and_cutoff_filtered():
    with TemporaryDirectory() as tmp:
        kw = dict(provider="fed", scope="x", source="https://www.federalreserve.gov/feeds/x", raw=b"x", records=[{"a": 1}], received_utc=NOW, kind="context")
        first = store(Path(tmp), **kw)
        second = store(Path(tmp), **kw)
        assert first != second and len(inventory(Path(tmp))["datasets"]) == 2
        assert not inventory(Path(tmp), cutoff_utc="2020-01-01T00:00:00Z")["datasets"]
        (first / "raw.bin").write_bytes(b"corruption")
        assert len(inventory(Path(tmp))["errors"]) == 1
        assert read_dataset(second)[1] == [{"a": 1}]


def test_secret_in_response_is_rejected_before_disk_write():
    with TemporaryDirectory() as tmp:
        try:
            store(Path(tmp), provider="x", scope="x", kind="x", source="https://x.test/data", raw=b"SECRET", records=[], received_utc=NOW, secrets=("SECRET",))
        except ValueError:
            pass
        else:
            assert False
        assert not list(Path(tmp).rglob("raw.bin"))


def test_manual_import_cannot_backdate_availability():
    with TemporaryDirectory() as tmp:
        file = Path(tmp) / "manual.json"
        file.write_text(json.dumps({"schema": "moneyprinter.manual.v1", "source": "https://example.com/report", "records": [{"available_utc": "2000-01-01T00:00:00Z"}]}))
        path = import_manual(Path(tmp) / "archive", file, now=NOW)
        manifest, rows = read_dataset(path)
        assert rows[0]["available_utc"].startswith("2026-09-04")
        assert manifest["provenance"] == "MANUAL_UNVERIFIED"


def test_calendar_and_feed_preserve_publication_not_fake_availability():
    raw = b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:1\nDTSTART;TZID=America/New_York:20260904T083000\nSUMMARY:Jobs\nEND:VEVENT\nEND:VCALENDAR"
    rows = normalize("bls_calendar", raw, NOW, vintage="2026-09-04")
    assert rows[0]["event_utc"].startswith("2026-09-04T12:30")
    assert rows[0]["available_utc"].startswith("2026-09-04T20:00")
    rss = b"<rss><channel><item><title>Release</title><pubDate>Fri, 04 Sep 2026 12:00:00 GMT</pubDate></item></channel></rss>"
    assert normalize("fed", rss, NOW, vintage="2026-09-04")[0]["usage"] == "CONTEXT_ONLY"


def test_fred_explicit_vintage_missing_key_and_no_key_in_archive():
    transport = Mock()
    transport.get.return_value = b'{"count":1,"observations":[{"date":"2025-01-01","value":"4.1"}]}'
    with TemporaryDirectory() as tmp:
        path = collect(Path(tmp), "fred", scope="DGS10", vintage="2025-01-02", env={"FRED_API_KEY": "PRIVATE"}, transport=transport, now=NOW)
        assert transport.get.call_args.args[1]["realtime_end"] == "2025-01-02"
        assert b"PRIVATE" not in (path / "manifest.json").read_bytes()
        assert "?" not in read_dataset(path)[0]["source"]
        try:
            collect(Path(tmp), "fred", env={}, transport=transport)
        except DataError:
            pass
        else:
            assert False
        assert transport.get.call_count == 1


def test_free_alpaca_is_forced_indicative_and_never_executable():
    transport = Mock()
    transport.get.return_value = b'{"snapshots":{"SPY261016C00600000":{"latestQuote":{"bp":1,"ap":2}}}}'
    with TemporaryDirectory() as tmp:
        path = collect(Path(tmp), "alpaca", env={"APCA_API_KEY_ID": "KEY1", "APCA_API_SECRET_KEY": "KEY2"}, transport=transport, now=NOW)
        assert transport.get.call_args.args[1]["feed"] == "indicative"
        assert read_dataset(path)[1][0]["executable_verified"] is False


def test_transport_rejects_order_hosts_and_credential_urls():
    transport = Transport(opener=Mock(), pause_seconds=0)
    for url in ("http://data.sec.gov/submissions/a", "https://api.tradier.com/v1/accounts/orders", "https://evil.test/data", "https://data.sec.gov/submissions/a?apikey=x"):
        try:
            transport.get(url)
        except DataError:
            pass
        else:
            assert False, url
    assert not transport.opener.open.called


def test_sec_bls_and_tradier_shapes_are_explicit():
    sec = {"filings": {"recent": {"accessionNumber": ["1"], "form": ["8-K"], "filingDate": ["2026-09-04"], "acceptanceDateTime": ["2026-09-04T19:00:00Z"], "primaryDocument": ["x.htm"]}}}
    assert normalize("sec", json.dumps(sec).encode(), NOW, vintage="2026-09-04")[0]["coverage"] == "RECENT_SUBMISSIONS_ONLY"
    bls = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [{"seriesID": "CPI", "data": [{"year": "2026", "period": "M08", "value": "123"}]}]}}
    assert normalize("bls", json.dumps(bls).encode(), NOW, vintage="2026-09-04")[0]["usage"] == "LATEST_VINTAGE_CONTEXT"
    tradier = b'{"quotes":{"quote":{"symbol":"SPY","bid":100,"ask":101,"bidsize":10,"asksize":10}}}'
    q = normalize("tradier", tradier, NOW, vintage="2026-09-04")[0]
    assert q["feed_type"] == "DELAYED_SANDBOX" and q["executable_verified"] is False


def test_manual_credentials_and_path_escape_are_rejected():
    with TemporaryDirectory() as tmp:
        file = Path(tmp) / "bad.json"
        file.write_text(json.dumps({"schema": "moneyprinter.manual.v1", "source": "https://example.com", "records": [{"api_key": "PRIVATE"}]}))
        try:
            import_manual(Path(tmp), file, now=NOW)
        except ValueError:
            pass
        else:
            assert False
        try:
            store(Path(tmp), provider="..", scope="x", kind="x", source="https://example.com", raw=b"x", records=[], received_utc=NOW)
        except ValueError:
            pass
        else:
            assert False
