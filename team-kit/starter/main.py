#!/usr/bin/env python3
"""Secret Wards starter: a correct *skeleton*, not a solution.

It already does the boring, contract-critical parts right:
  * walks every input file in a fixed order (deterministic output),
  * decodes UTF-8 / UTF-8-BOM / UTF-16 / cp1252 and writes UTF-8,
  * keeps CSV as CSV (same delimiter, same header), JSON as JSON (same structure),
  * quarantines anything it cannot parse instead of copying it,
  * writes report.json (SHA-256 per input file, honest counts, timing, memory),
  * writes records.jsonl with the right locators (row:N, /json/pointer, doc),
  * gives you keyed HMAC pseudonyms and per-patient date shifting helpers,
  * never prints, logs or stores personal data or RAKSHA_SECRET.

What it does NOT do is the actual challenge. Search for "TODO(team)".
As shipped it is roughly the "naive regex" level: it passes CONTRACT OK and scores low.

Usage: python main.py --input <input dir> --output <empty output dir>
Standard library only, Python 3.10+.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------- policy
def load_policy(path: Path) -> dict:
    """Tiny `key: value` reader for config/policy.yaml (no PyYAML needed)."""
    policy = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" in line:
                k, v = (x.strip() for x in line.split(":", 1))
                policy[k] = int(v) if v.lstrip("-").isdigit() else v
    return policy


HERE = Path(__file__).resolve().parent
POLICY = load_policy(HERE / "config" / "policy.yaml")
SECRET = os.environ.get("RAKSHA_SECRET", "").encode()  # never print or write this


# --------------------------------------------------------------------------- pseudonyms & dates
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U


def pseudonym(patient_key: str) -> str:
    """Stable, non-reversible ID: HMAC-SHA256 keyed with RAKSHA_SECRET (never a plain hash).

    Same key + same secret -> same ID in every file. A different secret -> a different ID.
    patient_key should be YOUR canonical identity for a cluster of records (see link_records).
    """
    digest = hmac.new(SECRET, patient_key.encode("utf-8"), hashlib.sha256).digest()
    n = int.from_bytes(digest[:5], "big")
    code = "".join(_ALPHABET[(n >> (5 * i)) & 31] for i in range(6))
    return f"PSN-{code}"


def date_shift_days(patient_key: str) -> int:
    """Per-patient shift in [-max, +max], never 0. Shift every date of one patient by the
    SAME amount and a 9-day stay stays 9 days."""
    m = int(POLICY.get("date_shift_max_days", 180))
    d = hmac.new(SECRET, b"shift|" + patient_key.encode("utf-8"), hashlib.sha256).digest()
    v = int.from_bytes(d[:4], "big") % (2 * m) - m
    return v if v != 0 else 1


def shift_date(value: dt.date, patient_key: str) -> dt.date:
    return value + dt.timedelta(days=date_shift_days(patient_key))


def age_band(age: int) -> str:
    """5-year bands by default; the band must CONTAIN the true age."""
    w = int(POLICY.get("age_band_years", 5))
    lo = (age // w) * w
    return f"{lo}-{lo + w - 1}"


# --------------------------------------------------------------------------- detection
# TODO(team): this is the part that wins or loses the event. Ideas, in rough order of value:
#   * column-aware rules: a column named like a name/phone/address is PII whatever it contains
#     (but expect renamed columns on hidden data: "Patient's Name", "Gram/Mohalla", ...);
#   * a name gazetteer in Latin AND Devanagari, transliteration (Mohammad/Mohd/Md./मोहम्मद),
#     honorifics (ji, sahab, didi, श्री), relatives (S/o, D/o, W/o, C/O <name>);
#   * the meaning traps: "C/O fever" is a complaint, "Dr. Ramesh" stays, "Dolo 650", "5 mg",
#     "1-0-1" are doses, "Parkinson's disease" is not a person;
#   * JSON keys, CSV headers, file names and base64 attachments can all hold PII.
PATTERNS = [
    ("PHONE", re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
    ("AADHAAR", re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("NAME", re.compile(r"(?i)(?<=name:)\s*[^\n,;|]+")),
]


class Stats:
    identifiers = 0
    records = 0
    linked = 0
    generalized = 0
    suppressed = 0


def clean_text(text: str) -> str:
    """Replace detected identifiers with typed placeholders. TODO(team): much more than regex."""
    for kind, rx in PATTERNS:
        text, n = rx.subn(f"[{kind}]" if kind != "NAME" else " [NAME]", text)
        Stats.identifiers += n
    return text


def clean_value(v):
    if isinstance(v, str):
        return clean_text(v)
    if isinstance(v, list):
        return [clean_value(x) for x in v]
    if isinstance(v, dict):
        # JSON keys can be PII too (for example a dict keyed by patient name)
        return {clean_text(k): clean_value(x) for k, x in v.items()}
    return v  # numbers, booleans, null keep their type


# --------------------------------------------------------------------------- linkage
def link_records(_record_text: str):
    """Return a canonical patient key for a record, or None when the evidence is too weak.

    TODO(team): blocking + fuzzy/phonetic + cross-script matching across ALL files, then cluster
    without transitive over-merging. Two different people with the same name must stay apart.
    A wrong link costs more than no link, so the starter links nothing.
    """
    return None


# --------------------------------------------------------------------------- I/O
def decode(raw: bytes) -> str | None:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="strict")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def process_csv(text: str, delimiter: str, rel: str, records: list) -> str:
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    if not rows:
        return ""
    header, body = rows[0], rows[1:]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    w.writerow(header)  # TODO(team): rename a header only if it contains PII
    for i, row in enumerate(body):
        key = link_records(delimiter.join(row))
        pid = pseudonym(key) if key else None
        # TODO(team): write pid into the row's patient column so it appears INSIDE the record
        w.writerow([clean_text(c) for c in row])
        records.append({"file": f"sanitized/{rel}", "loc": f"row:{i}", "patient": pid})
        Stats.records += 1
        Stats.linked += pid is not None
    return buf.getvalue()


def process_json(text: str, rel: str, records: list) -> str:
    data = json.loads(text)
    is_doc = not isinstance(data, dict) or data.get("resourceType") == "Bundle" or not any(
        isinstance(v, list) and v and all(isinstance(x, dict) for x in v) for v in data.values())
    if is_doc:  # FHIR Bundle or single object: one record for the whole file
        records.append({"file": f"sanitized/{rel}", "loc": "doc", "patient": None})
        Stats.records += 1
    else:
        for k, v in data.items():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                for i, _ in enumerate(v):
                    pointer_key = k.replace("~", "~0").replace("/", "~1")
                    records.append({"file": f"sanitized/{rel}", "loc": f"/{pointer_key}/{i}", "patient": None})
                    Stats.records += 1
    # TODO(team): FHIR must stay a valid R4 Bundle whose references resolve
    return json.dumps(clean_value(data), ensure_ascii=False, indent=2) + "\n"


def process_text(text: str, rel: str, records: list) -> str:
    records.append({"file": f"sanitized/{rel}", "loc": "doc", "patient": None})
    Stats.records += 1
    return clean_text(text)


def peak_rss_mb() -> float:
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(r / 1024 if sys.platform != "darwin" else r / 1048576, 1)
    except Exception:  # noqa: BLE001 - not available on every OS
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description="Secret Wards starter pipeline")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    t0 = time.monotonic()
    inp, out = Path(a.input), Path(a.output)
    san = out / "sanitized"
    san.mkdir(parents=True, exist_ok=True)
    files, records = [], []
    sys.setrecursionlimit(5000)

    for path in sorted(p for p in inp.rglob("*") if p.is_file()):
        rel = path.relative_to(inp).as_posix()
        raw = path.read_bytes()
        entry = {"input_sha256": hashlib.sha256(raw).hexdigest()}
        ext = path.suffix.lower()
        try:
            if ext not in (".csv", ".tsv", ".json", ".txt"):
                raise ValueError("unsupported_format")
            if not raw.strip():
                raise ValueError("empty_file")
            text = decode(raw)
            if text is None:
                raise ValueError("undecodable_text")
            # TODO(team): a file NAME can contain PII: rename it and report the new path
            if ext in (".csv", ".tsv"):
                result = process_csv(text, "\t" if ext == ".tsv" else ",", rel, records)
            elif ext == ".json":
                result = process_json(text, rel, records)
            else:
                result = process_text(text, rel, records)
            dest = san / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(result, encoding="utf-8", newline="")
            entry.update(output=f"sanitized/{rel}", status="sanitized")
        except (ValueError, RecursionError, UnicodeError, csv.Error) as exc:
            # Fail safe: never copy what we could not clean. The reason holds no file content.
            reason = str(exc) if isinstance(exc, ValueError) and str(exc).isidentifier() else type(exc).__name__
            entry.update(output=None, status="quarantined", reason=reason)
        files.append(entry)

    # Records whose file ended up quarantined must not be listed
    exported = {e["output"] for e in files if e["output"]}
    records = [r for r in records if r["file"] in exported]

    with open(out / "records.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    n_san = sum(e["status"] == "sanitized" for e in files)
    report = {
        "schema": "raksha-report/1",
        "files": files,
        "counts": {
            "files_total": len(files), "files_sanitized": n_san, "files_quarantined": len(files) - n_san,
            "records_processed": len(records), "identifiers_detected": Stats.identifiers,
            "records_linked": sum(r["patient"] is not None for r in records),
            "records_generalized": Stats.generalized, "records_suppressed": Stats.suppressed,
            "records_quarantined": 0,
        },
        "timing": {"seconds": round(time.monotonic() - t0, 2)},
        "resources": {"peak_rss_mb": peak_rss_mb()},
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # Only counts go to stdout: stdout and stderr are scanned for PII.
    print(f"files {len(files)} sanitized {n_san} quarantined {len(files) - n_san} records {len(records)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
