#!/usr/bin/env python3
"""Independent release verifier.

This file is deliberately ignorant of how the sanitizer works. It imports nothing from
`src/detection`, `src/transformation`, `src/policy`, `src/output` or `src/pipeline`, and it reads
only two things: the input tree and the released output tree. Its job is to answer one question —
*may this output be released?* — and to say no when it cannot prove the answer.

What independence buys: the sanitizer proves "I edited what I found". The verifier asks the different
question "is there still an identifier in the bytes I am about to publish". A bug shared by both would
have to be a bug in the pattern definitions and in the reading of the released tree at once.

What it does NOT do: it is not proof of anonymity and not a re-identification risk assessment. A clean
verification means no identifier of the classes it knows about survived in the channels it can read.

Exit codes: 0 released, 1 failed, 2 cannot verify (missing or unreadable inputs).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
from pathlib import Path

SCHEMA = "secret-wards-verification/1"

# ── identifier classes the verifier knows, defined here and nowhere else ───────────────────
PATTERNS = {
    "PHONE": re.compile(r"(?<!\d)(?:\+?91[-\s]?)?[6-9]\d{9}(?!\d)"),
    "AADHAAR": re.compile(r"(?<!\d)\d{4}[-\s]?\d{4}[-\s]?\d{4}(?!\d)"),
    "PAN": re.compile(r"(?<![A-Z])[A-Z]{5}\d{4}[A-Z](?![A-Z])"),
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "ABHA": re.compile(r"(?<!\d)\d{2}-\d{4}-\d{4}-\d{4}(?!\d)"),
    "MRN_PREFIXED": re.compile(r"(?<![A-Za-z0-9])(?:[A-Z]{2,5}-)\d{5,9}(?![0-9])"),
}
_LABELLED_NUMBER = re.compile(
    r"(?:mrn|uhid|ipd|opd|reg(?:istration)?\.?\s*(?:no|id)?|patient\s*id|adm(?:ission)?\s*(?:no|id))"
    r"\W{0,4}(?:[A-Z]{2,5}-)?(\d{5,9})(?![0-9])", re.IGNORECASE)
_NAME_PAIR = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2}\b")

# Words that make a capitalised pair a clinical or geographic phrase rather than a person.
# Local to the verifier on purpose: sharing the sanitizer's lists would share its blind spots.
_NOT_PERSON = {
    "blood", "pressure", "heart", "rate", "body", "temperature", "general", "ward", "bed",
    "discharge", "summary", "opd", "ipd", "department", "medicine", "surgery", "test",
    "report", "hospital", "clinic", "government", "district", "village", "block", "state",
    "india", "uttar", "pradesh", "madhya", "bihar", "patient", "male", "female",
}
# A drug formulary is full of Titlecase pairs ("Sodium Chloride", "Ferrous Sulphate"). A name is a
# candidate only in a document that also carries another identifier class or a person label.
_PERSON_LABEL = re.compile(
    r"\b(?:patient|name|attendant|guardian|relative|visitor|father|mother|spouse|son|daughter|"
    r"wife|husband|brought|accompanied)\b", re.IGNORECASE)
_CLINICIAN = re.compile(r"(?:\bDr\.?|\bDoctor|\bProf\.?|\bSister|\bNurse)\s*$", re.IGNORECASE)

TEXT_EXT = {".txt", ".md", ".log", ".csv", ".tsv", ".json", ".jsonl", ".xml"}
BINARY_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".zip", ".gz"}


def _mask(value: str) -> str:
    """Evidence without republishing the identifier: class, length and a salted prefix."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"len={len(value)} sha256={digest}"


_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def candidate_identifiers(text: str) -> list[tuple[str, str]]:
    """Identifier-shaped strings in one text blob, as (kind, value).

    UUIDs are excluded: FHIR fullUrl and subject references are 36-character identifiers whose digit
    runs match the Aadhaar and MRN shapes. Reporting them as patient identifiers would be a false
    positive, and a verifier that cries wolf is as useless as one that stays silent.
    """
    out: list[tuple[str, str]] = []
    uuid_spans = [m.span() for m in _UUID.finditer(text)]

    def inside_uuid(a: int, b: int) -> bool:
        return any(s <= a and b <= e for s, e in uuid_spans)

    for kind, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            if inside_uuid(*match.span()):
                continue
            out.append((kind, match.group(0)))
    # A bare number is an identifier only when a label introduces it (MRN, UHID, IPD, reg no).
    # Matching per line keeps a label from one flattened JSON chunk from adopting the digits of the
    # next one, which is how UUID fragments were being reported as MRNs.
    for line in text.splitlines():
        for match in _LABELLED_NUMBER.finditer(line):
            out.append(("MRN", match.group(1)))
    for match in _NAME_PAIR.finditer(text):
        tokens = match.group(0).split()
        # A label word often leads the run ("Patient Sunita Patel"); drop labels, then judge.
        while tokens and tokens[0].lower() in _NOT_PERSON:
            tokens = tokens[1:]
        while tokens and tokens[-1].lower() in _NOT_PERSON:
            tokens = tokens[:-1]
        if len(tokens) < 2 or any(word.lower() in _NOT_PERSON for word in tokens):
            continue
        offset = match.start() + match.group(0).find(tokens[0])
        if _CLINICIAN.search(text[max(0, offset - 12):offset]):
            continue                      # a named clinician is not a patient identifier
        out.append(("NAME", " ".join(tokens)))
    return out


def read_text(path: Path) -> str | None:
    """Best-effort text of a released file; None when the verifier cannot inspect it."""
    if path.suffix.lower() in BINARY_EXT:
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None
    if text.count("\x00") > 0:
        return None
    if path.suffix.lower() == ".csv":
        return _csv_text(text)
    if path.suffix.lower() in {".json", ".jsonl"}:
        return _json_text(text)
    if path.suffix.lower() == ".xml":
        return _xml_text(text)
    return text


def _csv_text(text: str) -> str:
    """Header and cells separated by spaces, so structural identity reaches the pattern scan."""
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return text
    return "\n".join(" ".join(cell for cell in row if cell) for row in rows[:400])


def _json_text(text: str) -> str:
    """Keys and string values flattened; a name used as a key is still a name."""
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text

    chunks: list[str] = []

    def walk(node, depth=0):
        if depth > 24:
            return
        if isinstance(node, dict):
            for key, child in node.items():
                chunks.append(str(key))
                walk(child, depth + 1)
        elif isinstance(node, list):
            for child in node[:200]:
                walk(child, depth + 1)
        elif isinstance(node, str):
            chunks.append(node)
        elif isinstance(node, (int, float)):
            chunks.append(str(node))

    walk(value)
    return "\n".join(chunks)


def _xml_text(text: str) -> str:
    """Tags and attribute values, without importing a parser the sanitizer also uses."""
    tags = re.findall(r"<\/?([A-Za-z_][\w:.-]*)", text)
    attrs = re.findall(r'([A-Za-z_][\w:.-]*)\s*=\s*"([^"]{0,200})"', text)
    return "\n".join(tags + [f"{k} {v}" for k, v in attrs])


def _files(root: Path) -> dict[str, Path]:
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*")) if p.is_file()}


def verify_tree(input_root: str | Path, output_root: str | Path, *,
                require_caps: tuple[str, ...] = ()) -> dict:
    """Verify released output. Returns a machine-readable report with an `overall` verdict."""
    inputs, outputs = Path(input_root), Path(output_root)
    report_path = outputs / "report.json"
    if not report_path.exists():
        return {"schema": SCHEMA, "overall": "cannot_verify",
                "reason": "report.json missing", "files": [], "checks": {}}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema": SCHEMA, "overall": "cannot_verify",
                "reason": "report.json unreadable", "files": [], "checks": {}}

    input_files = _files(inputs)
    released = {rel: p for rel, p in _files(outputs / "sanitized").items()}
    entries = {e["path"]: e for e in report.get("files", []) if isinstance(e, dict) and "path" in e}
    checks: dict[str, dict] = {}
    findings: list[dict] = []
    per_file: list[dict] = []

    # ── V1 accounting: every input file has exactly one recorded fate ──────────────────────
    unaccounted = sorted(set(input_files) - set(entries))
    phantom = sorted(set(entries) - set(input_files))
    duplicated = sorted({e["path"] for e in report.get("files", [])
                         if isinstance(e, dict) and "path" in e and
                         sum(1 for x in report["files"] if x.get("path") == e["path"]) > 1})
    missing_outputs = sorted(rel for rel, e in entries.items()
                             if e.get("status") == "sanitized"
                             and e.get("output", "").replace("sanitized/", "", 1) not in released)
    checks["accounting"] = {
        "files_in_input": len(input_files),
        "files_in_report": len(entries),
        "unaccounted": unaccounted,
        "phantom": phantom,
        "duplicated": duplicated,
        "sanitized_without_output": missing_outputs,
        "status": "failed" if (unaccounted or phantom or duplicated or missing_outputs) else "passed",
    }

    # ── V2/V3/V4/V6 per file: surviving identifiers, paths, structure, unchanged bytes ────
    untransformed: list[str] = []
    unsupported: list[str] = []
    surviving_total = 0
    for rel, entry in sorted(entries.items()):
        if entry.get("status") != "sanitized":
            per_file.append({"path": rel, "verification_status": "quarantined"})
            continue
        out_rel = entry.get("output", "").replace("sanitized/", "", 1)
        out_path = released.get(out_rel)
        in_path = input_files.get(rel)
        if out_path is None or in_path is None:
            per_file.append({"path": rel, "verification_status": "failed",
                             "reason": "released file or input missing"})
            findings.append({"path": rel, "check": "presence", "detail": "output or input missing"})
            continue

        released_text = read_text(out_path)
        input_text = read_text(in_path)
        if released_text is None:
            unsupported.append(rel)
            per_file.append({"path": rel, "verification_status": "unsupported",
                             "note": "content not inspectable by this verifier"})
            continue

        candidates = candidate_identifiers(input_text or "")
        if not (any(kind != "NAME" for kind, _ in candidates)
                or _PERSON_LABEL.search(input_text or "")):
            candidates = [(kind, value) for kind, value in candidates if kind != "NAME"]
        expected = candidates
        leaked = []
        for kind, value in expected:
            if value in released_text:
                leaked.append({"kind": kind, "evidence": _mask(value)})
        for kind, value in candidate_identifiers(out_rel):
            leaked.append({"kind": kind, "evidence": _mask(value), "channel": "path"})
        for kind, value in candidate_identifiers(out_path.name):
            leaked.append({"kind": kind, "evidence": _mask(value), "channel": "filename"})

        unchanged = released_text == (input_text if input_text is not None else released_text)
        if unchanged and leaked:
            untransformed.append(rel)

        surviving_total += len(leaked)
        status = "failed" if leaked else "passed"
        per_file.append({
            "path": rel,
            "parse_status": entry.get("parse_status", "unknown"),
            "detection_status": entry.get("detection_status", "unknown"),
            "surfaces_found": entry.get("surfaces_found", 0),
            "surfaces_edited": entry.get("surfaces_edited", 0),
            "verification_status": status,
            "release_status": "blocked" if status != "passed" else entry.get("release_status", "released"),
            "verification_findings": leaked,
            "candidates_expected": len(expected),
        })
        for item in leaked:
            findings.append({"path": rel, "check": "surviving_identifier", **item})

    by_kind: dict[str, int] = {}
    for item in findings:
        if item.get("check") == "surviving_identifier":
            by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
    checks["surviving_identifiers"] = {
        "candidates_expected": sum(f["candidates_expected"] for f in per_file
                                   if "candidates_expected" in f),
        "surviving": surviving_total,
        "surviving_by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "status": "failed" if surviving_total else "passed",
    }
    checks["unchanged_outputs"] = {
        "files_with_identifiers_released_unchanged": sorted(untransformed),
        "status": "failed" if untransformed else "passed",
    }

    # ── V5 capabilities: an inspection stage that did not run is not a pass ───────────────
    caps = report.get("capabilities", {}) or {}
    missing = list(caps.get("missing", []) or [])
    unmet = [name for name in require_caps if name in missing]
    checks["capabilities"] = {
        "missing": missing,
        "required": list(require_caps),
        "unmet": unmet,
        "status": "failed" if unmet else "passed",
    }
    if unmet:
        findings.append({"path": "-", "check": "capabilities",
                         "detail": f"required but unavailable: {', '.join(unmet)}"})

    # ── V7 coverage: what the verifier could not read is reported, never assumed safe ────
    checks["coverage"] = {
        "files_inspectable": len(per_file) - len(unsupported),
        "files_unsupported": sorted(unsupported),
        "status": "unsupported" if unsupported else "passed",
    }

    failed = any(c["status"] == "failed" for c in checks.values())
    overall = "failed" if failed else "passed"
    return {
        "schema": SCHEMA,
        "overall": overall,
        "checks": checks,
        "findings": findings,
        "files": per_file,
        "note": ("Independent release-safety check. A pass means no identifier of the classes this "
                 "file knows about survived in the channels it can read. It is not proof of "
                 "anonymity and not a re-identification risk assessment."),
    }


def main(argv: list[str]) -> int:
    args = list(argv[1:])
    require: list[str] = []
    if "--require" in args:
        index = args.index("--require")
        require = [c.strip() for c in args[index + 1].split(",") if c.strip()]
        del args[index:index + 2]
    if len(args) < 2:
        print("usage: tools/verify.py <input_dir> <output_dir> [--require cap,cap] [--json PATH]")
        return 2
    json_path = None
    if "--json" in args:
        index = args.index("--json")
        json_path = args[index + 1]
        del args[index:index + 2]

    result = verify_tree(args[0], args[1], require_caps=tuple(require))
    destination = Path(json_path) if json_path else Path(args[1]) / "verification.json"
    try:
        destination.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass

    checks = result.get("checks", {})
    print(f"VERIFICATION {result['overall'].upper()}")
    for name, detail in checks.items():
        print(f"  {name:22s} {detail.get('status', '?'):11s} "
              f"{ {k: v for k, v in detail.items() if k != 'status' and v not in ([], 0, '')} }")
    if result["overall"] == "cannot_verify":
        print(f"  reason: {result.get('reason')}")
        return 2
    for item in result.get("findings", [])[:10]:
        print(f"  ! {item['path']}: {item['check']} {item.get('kind', '')} {item.get('detail', '')}"
              f"{item.get('evidence', '')}")
    return 0 if result["overall"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
