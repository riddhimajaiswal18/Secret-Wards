#!/usr/bin/env python3
"""RAKSHA output-contract checker for teams (standard library only).

Usage:  python3 validate_output.py --input dev/input --output my_output/

It checks the *format* of your output against docs/SPEC.md. It does not score.
Scoring happens on hidden datasets with the organisers' evaluator.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

STATUSES = {"sanitized", "quarantined", "suppressed"}
COUNTS = ["files_total", "files_sanitized", "files_quarantined", "records_processed", "identifiers_detected",
          "records_linked", "records_generalized", "records_suppressed", "records_quarantined"]


def files(root: Path):
    for dp, dn, fn in os.walk(root):
        dn.sort()
        for n in sorted(fn):
            yield Path(dp) / n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    inp, out = Path(a.input), Path(a.output)
    errors, warns = [], []
    shas = {}
    for p in files(inp):
        shas.setdefault(hashlib.sha256(p.read_bytes()).hexdigest(), []).append(p.relative_to(inp).as_posix())
    san = out / "sanitized"
    if not san.is_dir():
        errors.append("missing output/sanitized/")
    exported = {p.relative_to(san).as_posix() for p in files(san)} if san.is_dir() else set()
    report = None
    try:
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append("missing output/report.json")
    except ValueError as exc:
        errors.append(f"report.json is not valid JSON: {exc}")
    declared = {}
    if isinstance(report, dict):
        for ent in report.get("files") or []:
            sha = str(ent.get("input_sha256", "")).lower()
            if sha not in shas:
                warns.append("report.files entry whose input_sha256 matches no input file")
                continue
            if ent.get("status") not in STATUSES:
                errors.append(f"report.files status must be one of {sorted(STATUSES)}")
            declared.setdefault(sha, []).append(ent)
            o = ent.get("output")
            if ent.get("status") == "sanitized":
                if not o:
                    errors.append("a sanitized entry has no output path")
                elif str(o).replace("sanitized/", "", 1) not in exported:
                    errors.append(f"declared output does not exist: {o}")
        counts = report.get("counts") or {}
        missing = [k for k in COUNTS if not isinstance(counts.get(k), (int, float))]
        if missing:
            warns.append(f"report.counts missing: {', '.join(missing)}")
        if not isinstance((report.get("timing") or {}).get("seconds"), (int, float)):
            warns.append("report.timing.seconds missing")
        if not isinstance((report.get("resources") or {}).get("peak_rss_mb"), (int, float)):
            warns.append("report.resources.peak_rss_mb missing")
    silent = 0
    for sha, paths in shas.items():
        for path in paths:
            if path in exported:
                continue
            if sha not in declared:
                silent += 1
    if silent:
        errors.append(f"{silent} input files are neither exported (same path) nor declared in report.files")
    bad = 0
    for rel in exported:
        data = (san / rel).read_bytes()
        try:
            (data[3:] if data.startswith(b"\xef\xbb\xbf") else data).decode("utf-8")
        except UnicodeDecodeError:
            bad += 1
    if bad:
        errors.append(f"{bad} sanitized files are not UTF-8")
    rj = out / "records.jsonl"
    if not rj.exists():
        warns.append("missing records.jsonl: identity resolution cannot be credited")
    else:
        for i, line in enumerate(rj.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                errors.append(f"records.jsonl line {i} is not JSON")
                break
            if not isinstance(r, dict) or "file" not in r or "loc" not in r or "patient" not in r:
                errors.append(f"records.jsonl line {i} needs file, loc, patient")
                break
            f = str(r["file"]).replace("sanitized/", "", 1)
            if f not in exported:
                errors.append(f"records.jsonl line {i} points to a file that was not exported: {r['file']}")
                break
    for w in warns:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    print("CONTRACT OK" if not errors else "CONTRACT PROBLEMS FOUND")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
