"""Immutable, checksummed local datasets. No credentials or automatic uploads."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from urllib.parse import urlsplit, urlunsplit
from common.validation import canonical, iso, utc


def safe_source(url: str) -> str:
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError("source must be a credential-free HTTPS URL without query or fragment")
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def _slug(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", value) or value in {".", ".."}:
        raise ValueError("invalid dataset name")
    return value


def store(root: Path, *, provider: str, scope: str, source: str, raw: bytes,
          records: list[dict], received_utc: str, kind: str,
          provenance: str = "PROVIDER_RESPONSE", secrets: tuple[str, ...] = ()) -> Path:
    """Always create a new vintage. Receipt time is never a claimed original vintage."""
    provider, scope, kind = _slug(provider), _slug(scope), _slug(kind)
    source = safe_source(source)
    received = iso(received_utc)
    if not isinstance(raw, bytes) or not isinstance(records, list):
        raise ValueError("raw bytes and normalized record list required")
    normalized = canonical(records)
    for secret in secrets:
        if secret and any(secret.encode("utf-8") in payload for payload in (raw, normalized)):
            raise ValueError("credential appeared in response; refusing to save it")
    parent = Path(root) / provider
    parent.mkdir(parents=True, exist_ok=True)
    stamp = utc(received).strftime("%Y%m%dT%H%M%S%fZ")
    target = parent / f"{scope}__{stamp}__{uuid.uuid4().hex[:10]}"
    stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=parent))
    try:
        (stage / "raw.bin").write_bytes(raw)
        (stage / "records.json").write_bytes(normalized)
        manifest = {"schema": "moneyprinter.dataset.v1", "provider": provider,
                    "scope": scope, "kind": kind, "source": source,
                    "received_utc": received, "available_utc": received,
                    "provenance": provenance, "record_count": len(records),
                    "historical_availability_verified": False,
                    "files": {"raw.bin": hashlib.sha256(raw).hexdigest(),
                              "records.json": hashlib.sha256(normalized).hexdigest()}}
        (stage / "manifest.json").write_bytes(canonical(manifest))
        os.rename(stage, target)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def read_dataset(path: Path) -> tuple[dict, list[dict]]:
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text("utf-8"))
    if manifest.get("schema") != "moneyprinter.dataset.v1" or set(manifest.get("files", {})) != {"raw.bin", "records.json"}:
        raise ValueError("unsupported dataset manifest")
    for name, expected in manifest["files"].items():
        file = path / name
        if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise ValueError("dataset checksum mismatch")
    records = json.loads((path / "records.json").read_text("utf-8"))
    if not isinstance(records, list) or len(records) != manifest["record_count"]:
        raise ValueError("record count mismatch")
    utc(manifest["available_utc"])
    return manifest, records


def inventory(root: Path, *, cutoff_utc: str | None = None) -> dict:
    entries, errors = [], []
    for path in sorted(Path(root).glob("*/*/manifest.json")):
        if path.parent.name.startswith("."):
            continue
        try:
            manifest, _ = read_dataset(path.parent)
            if cutoff_utc is not None and utc(manifest["available_utc"]) > utc(cutoff_utc):
                continue
            entries.append({**manifest, "dataset_id": path.parent.name})
        except (ValueError, OSError, KeyError, TypeError):
            errors.append({"dataset_id": path.parent.name, "error": "INVALID_ARCHIVE"})
    return {"datasets": entries, "errors": errors}


def import_manual(root: Path, file: Path, *, now: str | None = None) -> Path:
    """Manual files cannot claim earlier availability merely by supplying a date."""
    raw = Path(file).read_bytes()
    if len(raw) > 20_000_000:
        raise ValueError("manual import exceeds 20 MB")
    doc = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(doc, dict) or doc.get("schema") != "moneyprinter.manual.v1" or not isinstance(doc.get("records"), list):
        raise ValueError("expected moneyprinter.manual.v1 JSON with a records array")
    forbidden = {"api_key", "apikey", "token", "authorization", "password", "secret", "secret_key"}
    def check(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if str(k).lower() in forbidden:
                    raise ValueError("manual import contains a credential-like field")
                check(v)
        elif isinstance(value, list):
            for v in value:
                check(v)
    check(doc)
    received = now or datetime.now(timezone.utc).isoformat()
    rows = [{"data": r, "available_utc": iso(received), "provenance": "MANUAL_UNVERIFIED"}
            for r in doc["records"]]
    return store(root, provider="manual", scope=doc.get("scope", "import"),
                 source=doc["source"], raw=raw, records=rows, received_utc=received,
                 kind="manual_context", provenance="MANUAL_UNVERIFIED")
