#!/usr/bin/env python3
"""Secret Wards practice self-check (standard library only).

Compares YOUR output on the practice data with the answers in dev/truth/truth.json and
tells you, in plain words, what you leaked, what medical values you lost and how well
you linked patients.

    python3 check_dev.py --output my_output/            # summary
    python3 check_dev.py --output my_output/ --show 20  # also list 20 example leaks

This is a ROUGH guide for practice. The official score uses hidden datasets, the full
evaluator and the attacker (docs/SCORING.md). A clean self-check here is a good sign,
not a guarantee: hidden data has names, labels and formats you have never seen.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import itertools
import re
import json
import os
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


_B64 = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


def with_b64(text: str) -> str:
    """Attachments hide PII in base64: decode every long base64 run and append it."""
    extra = []
    for m in _B64.finditer(text):
        tok = m.group(0)
        try:
            extra.append(base64.b64decode(tok + "=" * (-len(tok) % 4)).decode("utf-8", errors="ignore"))
        except (binascii.Error, ValueError):
            pass
    return text + "\n" + "\n".join(extra) if extra else text


def read_text(p: Path) -> str:
    try:
        raw = p.read_bytes()[: 50 * 1024 * 1024]
    except OSError:
        return ""
    return with_b64(raw.decode("utf-8", errors="replace"))


def all_text_under(root: Path) -> str:
    parts = []
    for dp, _, fn in os.walk(root):
        for n in fn:
            parts.append(n)
            parts.append(read_text(Path(dp) / n))
    return norm("\n".join(parts))


def record_for(loc: str, recs: dict):
    """Longest reported locator that covers this record: exact, JSON-pointer ancestor, or doc."""
    if loc in recs:
        return recs[loc]
    if loc.startswith("/"):
        parts = loc.split("/")
        for i in range(len(parts) - 1, 1, -1):
            anc = "/".join(parts[:i])
            if anc in recs:
                return recs[anc]
    return recs.get("doc")


def pct(a: int, b: int) -> str:
    return "  n/a" if b == 0 else f"{100 * a / b:5.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--output", required=True, help="the folder your system wrote")
    ap.add_argument("--truth", default=str(HERE / "dev" / "truth" / "truth.json"))
    ap.add_argument("--show", type=int, default=0, help="print this many example leaks")
    a = ap.parse_args()
    out = Path(a.output)
    truth = json.loads(Path(a.truth).read_text(encoding="utf-8"))
    san = out / "sanitized"

    try:
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        report = {"files": []}
    renamed = {e.get("input_sha256"): e.get("output") for e in report.get("files") or []}

    recs = defaultdict(dict)
    try:
        for line in (out / "records.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                recs[str(r["file"]).replace("sanitized/", "", 1)][r["loc"]] = r.get("patient")
    except (OSError, ValueError, KeyError):
        pass

    leaks, kept = Counter(), Counter()
    leak_examples = []
    by_script, by_channel = Counter(), Counter()
    tot_script, tot_channel = Counter(), Counter()
    pres_ok = pres_all = 0
    unit_patient = {}  # (file, loc) -> (true patient, your pseudonym)
    copied_raw = 0

    for rel, f in truth["files"].items():
        out_rel = rel
        declared = renamed.get(f["sha256"])
        if declared:
            out_rel = str(declared).replace("sanitized/", "", 1)
        p = san / out_rel
        exists = p.is_file()
        text = norm(read_text(p)) if exists else ""
        src = Path(a.truth).resolve().parents[1] / "input" / rel
        # officially: a broken or unsupported file with PII exported byte-for-byte as "sanitized"
        has_pii = any(u["entities"] for u in f["units"].values())
        if has_pii and exists and f.get("expect") == "either" and src.is_file() and p.read_bytes() == src.read_bytes():
            copied_raw += 1
        fname = norm(out_rel)
        for loc, u in f["units"].items():
            for e in u["entities"]:
                if e.get("type") == "CANARY":
                    continue
                tot_script[e["script"]] += 1
                tot_channel[e["channel"]] += 1
                surface = norm(e["surface"])
                hay = fname if e["channel"] == "filename" else text
                if exists or e["channel"] == "filename":
                    hit = bool(surface) and surface in hay
                else:
                    hit = False  # file not exported: nothing leaked from it
                if hit:
                    leaks[e["type"]] += 1
                    by_script[e["script"]] += 1
                    by_channel[e["channel"]] += 1
                    if len(leak_examples) < a.show:
                        leak_examples.append((e["type"], e["script"], e["channel"], rel, e["surface"]))
                else:
                    kept[e["type"]] += 1
            if exists:
                for pv in u.get("preserve") or []:
                    pres_all += 1
                    pres_ok += norm(pv["text"]) in text
            if u.get("link") == "required" and u.get("patient"):
                unit_patient[(rel, loc)] = (u["patient"], record_for(loc, recs.get(out_rel, {})))

    # canaries: anywhere in the output folder, including logs and report
    everything = all_text_under(out)
    canary_surfaces = {norm(e["surface"]) for f in truth["files"].values() for u in f["units"].values()
                       for e in u["entities"] if e.get("type") == "CANARY"}
    canary_hits = sum(1 for s in canary_surfaces if s and s in everything)

    # linkage: pairwise precision / recall over records that should be linked
    units = list(unit_patient.values())
    tp = fp = fn = 0
    by_true = defaultdict(list)
    for i, (t, y) in enumerate(units):
        by_true[t].append(i)
    yours = defaultdict(list)
    for i, (t, y) in enumerate(units):
        if y:
            yours[y].append(i)
    true_pairs = sum(len(v) * (len(v) - 1) // 2 for v in by_true.values())
    for members in yours.values():
        for i, j in itertools.combinations(members, 2):
            if units[i][0] == units[j][0]:
                tp += 1
            else:
                fp += 1
    fn = true_pairs - tp
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f05 = (1.25 * prec * rec / (0.25 * prec + rec)) if prec + rec else 0.0
    merged_people = sum(1 for m in yours.values() if len({units[i][0] for i in m}) > 1)

    total_ent = sum(leaks.values()) + sum(kept.values())
    print("=" * 64)
    print(" SECRET WARDS practice self-check (rough guide, not the official score)")
    print("=" * 64)
    print(f"\n1) PERSONAL DATA: {sum(leaks.values())} of {total_ent} pieces still visible "
          f"({pct(sum(leaks.values()), total_ent)} leaked; lower is better)")
    for t in sorted(set(leaks) | set(kept), key=lambda x: -leaks[x]):
        n = leaks[t] + kept[t]
        print(f"   {t:<16} leaked {leaks[t]:>4} / {n:<4} {pct(leaks[t], n)}")
    print("   by language: " + ", ".join(f"{s} {pct(by_script[s], tot_script[s]).strip()}" for s in tot_script))
    print("   by hiding place: " + ", ".join(f"{c} {pct(by_channel[c], tot_channel[c]).strip()}" for c in tot_channel))
    print(f"\n2) CANARIES: {canary_hits} of {len(canary_surfaces)} planted canaries found in your output folder "
          "(each one costs -3 officially)")
    print(f"\n3) MEDICAL DATA KEPT: {pres_ok} of {pres_all} medical values survived ({pct(pres_ok, pres_all)}; higher is better)")
    print(f"\n4) PATIENT LINKING: precision {prec:.2f}, recall {rec:.2f}, F0.5 {f05:.2f}"
          f"  (pseudonyms that wrongly merge different people: {merged_people})")
    if not any(y for _, y in units):
        print("   you linked nothing yet: write your pseudonym into records.jsonl \"patient\"")
    print(f"\n5) RAW COPIES: {copied_raw} broken/unsupported files were copied out unchanged instead of quarantined (each costs -5 officially)")
    if leak_examples:
        print("\nExample leaks (type, language, place, file, text):")
        for ex in leak_examples:
            print("   ", " | ".join(ex))
    print("\nNext: fix the biggest leak rows first, keep the medical values, then link patients.")
    print("Also run: python3 validate_output.py --input dev/input --output", a.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
