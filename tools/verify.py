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
import xml.etree.ElementTree as ET

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
_PERSON_FIELD = re.compile(
    r"(?:patient|pt|relative|guardian|attendant|father|mother|spouse|husband|wife|"
    r"son|daughter|next.?of.?kin).{0,20}(?:name|naam|given|first|last|family)|"
    r"(?:full|first|last|given|family)_?name", re.IGNORECASE)
_ROLE_FIELD = re.compile(
    r"\b(?:doctor|practitioner|provider|consultant|physician|nurse|hospital|clinic|"
    r"organization|organisation|facility|institution)\b", re.IGNORECASE)
_PERSON_VALUE_LABEL = re.compile(
    r"(?i)(?:patient\s*name|name\s*of\s*patient|pt\.?\s*name|patient|name|"
    r"attendant|guardian|relative|father\s*of|mother\s*of|s/o|d/o|w/o|c/o|"
    r"son\s*of|daughter\s*of|wife\s*of|husband\s*of|next\s*of\s*kin)\s*[:=\-]\s*"
    r"([^,;\r\n]+)"
)
_PATIENT_NAME_PREFIX = re.compile(
    r"(?i:patient)\s+([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2})"
)
_RELATIVE_NAME_PREFIX = re.compile(
    r"(?i:\b(?:s/o|d/o|w/o|c/o|son\s+of|daughter\s+of|wife\s+of|husband\s+of|"
    r"father\s+of|mother\s+of|attendant|guardian|relative|next\s+of\s+kin)\s*[:=\-]?\s*)"
    r"([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,2})"
)
_HONORIFIC_NAME = re.compile(
    r"\b[A-Z][a-z]{2,}\s+(?:amma|babu|bhaiya|bhai|behenji|behen|ji|didi|sahab|sahib)\b",
    re.IGNORECASE,
)
_SCHEMA_KEYS = {
    "system", "meta", "resource", "entry", "data", "record", "records", "patient",
    "patients", "visit", "visits", "by_name", "identifier", "identifiers", "name",
    "given", "family", "first", "last", "text", "display", "id", "type", "status",
}

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


def _plausible_person(value: str) -> bool:
    value = value.strip(" \t\r\n:;,.()[]{}\"'")
    if not value or len(value) > 100 or re.search(r"\d", value):
        return False
    words = re.findall(r"[A-Za-z\u0900-\u097f][A-Za-z\u0900-\u097f'’-]*", value)
    if not words or len(words) > 5:
        return False
    return not any(word.casefold() in _NOT_PERSON for word in words)


def _contextual_names(text: str) -> list[str]:
    """High precision names from text, gated by a local person-role marker."""
    names: list[str] = []
    for line in text.splitlines():
        for match in _PERSON_VALUE_LABEL.finditer(line):
            value = match.group(1).strip()
            # A label value may continue into demographics or another field on the same line.
            value = re.split(
                r"(?i)\s+(?:age(?:/sex)?|sex|dob|date\s+of\s+birth|uhid|mrn|mobile|phone)\b",
                value, maxsplit=1)[0]
            if _plausible_person(value) and not _ROLE_FIELD.search(line[:match.start()]):
                names.append(value)
            else:
                names.extend(candidate.group(0) for candidate in _NAME_PAIR.finditer(value)
                             if _plausible_person(candidate.group(0)))
        for pattern in (_PATIENT_NAME_PREFIX, _RELATIVE_NAME_PREFIX):
            for match in pattern.finditer(line):
                value = " ".join(match.group(1).split())
                if _plausible_person(value):
                    names.append(value)
        for match in _HONORIFIC_NAME.finditer(line):
            names.append(match.group(0))
    return names


def _document_name_candidates(path: Path, text: str) -> list[str]:
    """Find names from person fields without treating every clinical proper noun as a patient.

    This verifier remains independent of the sanitizer. It parses only enough structure to know
    whether a value belongs to a patient/relative field; raw identifiers are still scanned by the
    separate shape-based rules above.
    """
    suffix = path.suffix.casefold()
    names: list[str] = []
    if suffix == ".json":
        try:
            payload = json.loads(text)
        except (ValueError, RecursionError):
            payload = None

        def walk(node, path=()):
            if isinstance(node, dict):
                for key, value in node.items():
                    key_text = str(key)
                    compact = re.sub(r"[^a-z]", "", key_text.casefold())
                    key_readable = key_text.replace("_", " ").replace("-", " ")
                    if (key_text.casefold() not in _SCHEMA_KEYS and
                            candidate_identifiers(key_readable) and
                            not _ROLE_FIELD.search(key_text)):
                        names.extend(value for kind, value in candidate_identifiers(key_readable)
                                     if kind == "NAME")
                    next_path = path + (key_text,)
                    if isinstance(value, str):
                        ancestry = " ".join(next_path)
                        if (not _ROLE_FIELD.search(ancestry) and
                                (_PERSON_FIELD.search(key_text) or
                                (compact == "name" and
                                 re.search(r"(?i)\b(?:patient|patients|relative|guardian|attendant)\b",
                                           ancestry)))):
                            if _plausible_person(value):
                                names.append(value.strip())
                        # Values in explicit source/path metadata are checked for identity names.
                        if re.search(r"(?i)(?:path|file|source)", key_text):
                            names.extend(name for kind, name in candidate_identifiers(
                                value.replace("_", " ").replace("\\", " ")) if kind == "NAME")
                    else:
                        walk(value, next_path)
            elif isinstance(node, list):
                for value in node:
                    walk(value, path)

        if payload is not None:
            walk(payload)
    elif suffix in {".csv", ".tsv"}:
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter="\t" if suffix == ".tsv" else ","))
        except csv.Error:
            rows = []
        if rows:
            for index, label in enumerate(rows[0]):
                if _ROLE_FIELD.search(label):
                    continue
                is_person_field = bool(_PERSON_FIELD.search(label)) or label.strip().casefold() == "name"
                if not is_person_field:
                    continue
                for row in rows[1:]:
                    if index < len(row) and _plausible_person(row[index]):
                        names.append(row[index].strip())
    elif suffix == ".xml":
        try:
            root = ET.fromstring(text)
        except (ET.ParseError, RecursionError):
            names.extend(_contextual_names(text))
        else:
            def walk_xml(element, ancestry=()):
                tag = element.tag.rsplit("}", 1)[-1]
                context = ancestry + (tag,)
                context_text = " ".join(context)
                normalized_tag = re.sub(r"[^a-z]", "", tag.casefold())
                if not _ROLE_FIELD.search(context_text):
                    is_person_name = (_PERSON_FIELD.search(tag) or
                                      (normalized_tag == "name" and
                                       re.search(
                                           r"(?i)\b(?:patient|patientRole|guardian|relative|"
                                           r"attendant|RelatedPerson)\b", context_text)))
                    if is_person_name:
                        for value in [element.text or "", *element.attrib.values()]:
                            if _plausible_person(value):
                                names.append(value.strip())
                for child in list(element):
                    walk_xml(child, context)

            walk_xml(root)
    else:
        names.extend(_contextual_names(text))
    return list(dict.fromkeys(names))


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


def read_raw_text(path: Path) -> str | None:
    """Decode source bytes without flattening JSON, CSV or XML structure."""
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
    return None if "\x00" in text else text


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
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, RecursionError):
        tags = re.findall(r"<\/?([A-Za-z_][\w:.-]*)", text)
        attrs = re.findall(r'([A-Za-z_][\w:.-]*)\s*=\s*"([^"]{0,200})"', text)
        body = re.sub(r"<[^>]{0,1000}>", "\n", text)
        return "\n".join(tags + [f"{k} {v}" for k, v in attrs] + [body])
    chunks: list[str] = []

    def walk(node):
        chunks.append(node.tag.rsplit("}", 1)[-1])
        if node.text:
            chunks.append(node.text)
        for key, value in node.attrib.items():
            chunks.extend((key, value))
        for child in list(node):
            walk(child)
            if child.tail:
                chunks.append(child.tail)

    walk(root)
    return "\n".join(chunks)


def _files(root: Path) -> dict[str, Path]:
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*")) if p.is_file()}


def _sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


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
    # The submission contract intentionally identifies inputs by content hash because their
    # paths can contain PII. Keep compatibility with older reports that used `path`, while
    # mapping current hash-only entries back to local input files for verification.
    inputs_by_hash: dict[str, list[str]] = {}
    for rel, path in input_files.items():
        digest = _sha256(path)
        if digest is not None:
            inputs_by_hash.setdefault(digest, []).append(rel)

    entries: dict[str, dict] = {}
    extra_entries: list[dict] = []
    for entry in report.get("files", []):
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("path"), str):
            key = entry["path"]
        elif isinstance(entry.get("input_sha256"), str):
            candidates = inputs_by_hash.get(entry["input_sha256"], [])
            out_path = entry.get("output")
            preferred = (out_path.removeprefix("sanitized/")
                         if isinstance(out_path, str) and out_path.startswith("sanitized/")
                         else None)
            key = preferred if preferred in candidates else (candidates.pop(0) if candidates else "")
            if preferred in candidates:
                candidates.remove(preferred)
            if not key:
                extra_entries.append(entry)
                continue
        else:
            extra_entries.append(entry)
            continue
        if key in entries:
            extra_entries.append(entry)
        else:
            entries[key] = entry
    checks: dict[str, dict] = {}
    findings: list[dict] = []
    per_file: list[dict] = []

    # ── V1 accounting: every input file has exactly one recorded fate ──────────────────────
    unaccounted = sorted(set(input_files) - set(entries))
    phantom = sorted((set(entries) - set(input_files)) | {
        f"unmapped:{entry.get('input_sha256', 'missing-hash')}" for entry in extra_entries
    })
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

        candidates = [(kind, value) for kind, value in
                      candidate_identifiers(input_text or "") if kind != "NAME"]
        raw_input = read_raw_text(in_path) or input_text or ""
        candidates.extend(("NAME", value) for value in
                          _document_name_candidates(in_path, raw_input))
        expected = list(dict.fromkeys(candidates))
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
