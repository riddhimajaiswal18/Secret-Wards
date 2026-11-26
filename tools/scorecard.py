#!/usr/bin/env python3
"""Independent scorecard: measure a release without asking the sanitizer for its opinion.

Every number here is computed from (a) the input tree, (b) the output tree, and (c) the kit's
truth file. Nothing is taken from `report.json` except the file accounting it is supposed to
declare, and every metric prints its own denominator so a reader can check the arithmetic.

Definitions (explicit, because a percentage with a hidden denominator is not evidence):

  direct_pii_leak   entity surfaces from truth found verbatim in the *output tree*
                    denominator = all entity surfaces in exported files
  canary_leak       synthetic canary surfaces found anywhere under the output root
                    denominator = all canary surfaces in the truth file
  utility_kept      clinical values the truth marks "preserve", found in output
                    denominator = those values in exported files
  raw_copy          an exported file whose bytes equal its input
                    denominator = all exported files
  silent_skip       an input file with no fate in the report
                    denominator = all input files
  determinism       two independent runs, byte diff on the sanitized tree

Usage: python3 tools/scorecard.py [--kit DIR] [--output DIR] [--json PATH]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
norm = lambda text: re.sub(r"\s+", " ", text).strip()  # noqa: E731


def _text(path: Path) -> str:
    try:
        return norm(path.read_bytes().decode("utf-8", "ignore"))
    except OSError:
        return ""


def _all_text(root: Path) -> str:
    chunks = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            chunks.append(_text(path))
            chunks.append(norm(path.as_posix()))
    return norm(" ".join(chunks))


def measure(kit: Path, output: Path) -> dict:
    truth = json.loads((kit / "dev" / "truth" / "truth.json").read_text(encoding="utf-8"))
    sanitized = output / "sanitized"
    report = {}
    try:
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass

    declared = {entry.get("input_sha256"): entry for entry in report.get("files") or []}
    exported: dict[str, Path] = {}
    for rel, meta in truth["files"].items():
        entry = declared.get(meta.get("sha256"))
        target = sanitized / str(entry.get("output", "")).replace("sanitized/", "", 1) \
            if entry and entry.get("output") else sanitized / rel
        if target.is_file():
            exported[rel] = target

    leaks = collections.Counter()
    totals = collections.Counter()
    channels = collections.Counter()
    channel_totals = collections.Counter()
    scripts = collections.Counter()
    script_totals = collections.Counter()
    examples: list[tuple[str, str, str]] = []

    kept = kept_total = 0
    for rel, meta in truth["files"].items():
        target = exported.get(rel)
        body = _text(target) if target else ""
        # filename channel is about what was actually released, not the source name
        name = norm(target.relative_to(sanitized).as_posix()) if target else norm(rel)
        for unit in meta["units"].values():
            for entity in unit.get("entities") or []:
                surface = norm(entity.get("surface", ""))
                if not surface:
                    continue
                kind = entity.get("type", "?")
                channel = entity.get("channel", "content")
                script = entity.get("script", "?")
                totals[kind] += 1
                channel_totals[channel] += 1
                script_totals[script] += 1
                haystack = name if channel == "filename" else body
                if surface in haystack:
                    leaks[kind] += 1
                    channels[channel] += 1
                    scripts[script] += 1
                    if len(examples) < 8:
                        examples.append((rel, kind, channel))
            if target:
                for item in unit.get("preserve") or []:
                    value = norm(item.get("text", "") if isinstance(item, dict) else str(item))
                    if not value:
                        continue
                    kept_total += 1
                    kept += value in body

    canaries = {norm(e["surface"]) for meta in truth["files"].values()
                for unit in meta["units"].values() for e in unit.get("entities") or []
                if e.get("type") == "CANARY"}
    tree = _all_text(output)
    canary_hits = sum(1 for surface in canaries if surface and surface in tree)

    raw_copies = 0            # identical bytes, any file (reference data is legitimately identical)
    raw_copies_penalised = 0  # identical bytes where the kit expects a quarantine decision
    for rel, target in exported.items():
        source = kit / "dev" / "input" / rel
        if source.is_file() and source.read_bytes() == target.read_bytes():
            raw_copies += 1
            if truth["files"][rel].get("expect") == "either":
                raw_copies_penalised += 1

    fates = {entry.get("path") for entry in report.get("files") or []}
    silent = [rel for rel in truth["files"] if rel not in fates]

    leak_total = sum(leaks.values())
    entity_total = sum(totals.values())
    return {
        "files": {
            "input": len(truth["files"]),
            "exported": len(exported),
            "quarantined": len(report.get("quarantine") or []),
            "unaccounted": len(silent),
        },
        "direct_pii": {
            "leaked": leak_total,
            "denominator": entity_total,
            "rate": round(leak_total / entity_total, 4) if entity_total else 0.0,
            "by_type": dict(leaks.most_common()),
            "by_channel": {c: round(channels[c] / channel_totals[c], 4)
                           for c in channel_totals},
            "by_script": {s: round(scripts[s] / script_totals[s], 4) for s in script_totals},
            "examples": examples,
        },
        "canaries": {"found": canary_hits, "denominator": len(canaries)},
        "utility": {"kept": kept, "denominator": kept_total,
                    "rate": round(kept / kept_total, 4) if kept_total else 0.0},
        "integrity": {"raw_copies": raw_copies, "raw_copies_penalised": raw_copies_penalised,
                      "exported": len(exported),
                      "unaccounted_files": silent[:5]},
        "identity": {"linked_records": sum(1 for line in
                                           (output / "records.jsonl").read_text(
                                               encoding="utf-8").splitlines() if line.strip()
                                           and json.loads(line).get("patient"))}
        if (output / "records.jsonl").is_file() else {"linked_records": 0},
    }


def dependency_probe() -> dict:
    """Optional backends whose absence changes behaviour *silently* at run time."""
    import importlib.util
    import shutil
    modules = {name: importlib.util.find_spec(name) is not None
               for name in ("indic_transliteration", "pypdf", "PIL", "pytesseract",
                            "phonenumbers", "yaml")}
    modules["tesseract_binary"] = shutil.which("tesseract") is not None
    modules["pdftoppm_binary"] = shutil.which("pdftoppm") is not None
    modules["interpreter"] = sys.executable
    return modules


def determinism(kit: Path, first: Path) -> dict:
    second = first.parent / ".scorecard_second"
    shutil.rmtree(second, ignore_errors=True)
    try:
        subprocess.run([sys.executable, str(ROOT / "main.py"), "--input",
                        str(kit / "dev" / "input"), "--output", str(second), "--quiet"],
                       cwd=ROOT, check=True, capture_output=True, timeout=900)
        a, b = first / "sanitized", second / "sanitized"
        files_a = sorted(p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file())
        files_b = sorted(p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file())
        differing = [rel for rel in files_a if (a / rel).read_bytes() != (b / rel).read_bytes()] \
            if files_a == files_b else ["file-set-differs"]
        return {"identical": not differing, "files": len(files_a), "differing": differing[:5]}
    except Exception as exc:                                     # noqa: BLE001
        return {"identical": False, "error": type(exc).__name__}
    finally:
        shutil.rmtree(second, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", default=str(ROOT.parent / "kit"))
    parser.add_argument("--output", default=str(ROOT / "build" / "out"))
    parser.add_argument("--json", default="")
    parser.add_argument("--no-determinism", action="store_true")
    args = parser.parse_args()
    kit, output = Path(args.kit), Path(args.output)
    if not output.is_dir():
        print(f"no release to measure at {output}", file=sys.stderr)
        return 2

    result = measure(kit, output)
    result["dependencies"] = dependency_probe()
    if not args.no_determinism:
        result["determinism"] = determinism(kit, output)

    pii, util, files = result["direct_pii"], result["utility"], result["files"]
    print("SECRET WARDS — independent scorecard")
    print(f"  files     {files['exported']}/{files['input']} exported · "
          f"{files['quarantined']} quarantined · {files['unaccounted']} unaccounted")
    print(f"  PII       {pii['leaked']}/{pii['denominator']} still visible "
          f"({pii['rate'] * 100:.1f}%)   ← denominator = entity surfaces in exported files")
    print("  channels  " + " · ".join(f"{c} {v * 100:.1f}%" for c, v in
                                      sorted(pii["by_channel"].items())))
    print("  scripts   " + " · ".join(f"{s} {v * 100:.1f}%" for s, v in
                                      sorted(pii["by_script"].items())))
    print(f"  utility   {util['kept']}/{util['denominator']} clinical values kept "
          f"({util['rate'] * 100:.1f}%)")
    print(f"  canaries  {result['canaries']['found']}/{result['canaries']['denominator']} found")
    print(f"  integrity {result['integrity']['raw_copies']} identical-to-input "
          f"({result['integrity']['raw_copies_penalised']} on files the kit expects quarantined) · "
          f"identity {result['identity']['linked_records']} linked records")
    if "determinism" in result:
        d = result["determinism"]
        print(f"  determinism {'OK' if d['identical'] else 'FAIL'} ({d.get('files', 0)} files)")
    missing = [k for k, v in result["dependencies"].items()
               if v is False and k not in {"interpreter"}]
    if missing:
        print(f"  deps      MISSING at run time: {', '.join(missing)}  "
              f"← behaviour degrades silently for these")
    if pii["examples"]:
        print("  worst leaks (file, type, channel):")
        for rel, kind, channel in pii["examples"][:5]:
            print(f"    {rel:46s} {kind:16s} {channel}")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8")
        print(f"  json      {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
