"""Structural sanitation: the three channels that are not values.

* **header** — a column label can itself be personal data (`<phone>.csv`, a name used as a column).
* **key** — a JSON object key can carry an identifier, and renaming it changes every child locator,
  so it must happen *before* edits are built.
* **base64** — an attachment can hide the whole record. Decoded, rescanned, and replaced as a unit.

All three are structural mutations rather than locator edits, so they run once, deterministically,
before the value detectors, and report counts only — never content.
"""
from __future__ import annotations

import base64
import binascii
import re

from src.detection.columns import classify
from src.detection.engine import find, redact
from src.detection.protection import ProtectionIndex
from src.ir import IntermediateRepresentation

_B64 = re.compile(r"^[A-Za-z0-9+/=\s]{32,}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _looks_like_base64(value: str) -> bool:
    if len(value) < 32 or not _B64.match(value):
        return False
    compact = re.sub(r"\s+", "", value)
    return len(compact) % 4 == 0


def _decode(value: str, limit: int = 65536) -> bytes | None:
    try:
        blob = base64.b64decode(re.sub(r"\s+", "", value)[:limit], validate=False)
    except (binascii.Error, ValueError):
        return None
    if not blob:
        return None
    printable = sum(1 for byte in blob if 32 <= byte < 127 or byte in (9, 10, 13))
    if printable / len(blob) < 0.85 or _CONTROL.search(blob.decode("latin-1", "ignore")):
        return None
    return blob


_GENERIC_KEY = {"system", "hospital", "exported_by", "generated_at", "source_path", "visits",
                "meta", "resource", "entry", "patients", "records", "items", "data", "rows",
                "header", "columns", "fields", "type", "id", "name", "status", "date"}


def _index_key_findings(key: str, value, index) -> list:
    """Keys that are identities: a bare MRN, or a Titlecase token indexing an object/array."""
    lowered = key.strip().lower()
    if lowered in _GENERIC_KEY or len(lowered) < 3:
        return []
    from src.detection.engine import Finding, UHID, NAME
    if re.fullmatch(r"\d{4,12}", lowered):
        return [Finding(UHID, 0, len(key), "patient", 0.8)]
    parts = [part for part in re.split(r"[_\-\s]+", key) if part]
    if parts and all(
            part[:1].isupper() and len(part) >= 3 and part.lower() not in _GENERIC_KEY
            for part in parts) and len(parts) <= 3:
        return [Finding(NAME, 0, len(key), "patient", 0.7)]
    return []


def _index_key_is_identity(key: str, value, index) -> bool:
    return bool(_index_key_findings(key, value, index))


# A 12-digit number is an Aadhaar only when the field says so; likewise an MRN inside an export path.
_AADHAAR_KEY = re.compile(r"(?:aadhar|aadhaar|abha|uid|ration)", re.IGNORECASE)
_PATH_KEY = re.compile(r"(?:path|file|dir|folder|source)", re.IGNORECASE)
_PATH_MRN = re.compile(r"(?<![0-9])\d{5,9}(?![0-9])")

_IDENTITY_KINDS = {"NAME", "RELATIVE", "UHID", "AADHAAR", "ABHA", "PAN", "PHONE"}


def _identity_key_replacement(key, node, index, tokens):
    """A key that *is* the identity, e.g. `{"Sunita Patel": "UHID-1"}`.

    Titlecase or MRN-shaped keys are renamed; label keys ("patient_name", "by_name") are not,
    because classify() resolves those to a schema field and the key must stay meaningful.
    Returns (new_key, kind) or None.
    """
    if not isinstance(key, str) or len(key) < 4 or classify(key):
        return None
    findings = (find(key, index)
                or find(key.replace("_", " ").replace("-", " "), index)
                or _index_key_findings(key, None, index))
    if not findings:
        return None
    kind = findings[0].kind
    if kind not in _IDENTITY_KINDS:
        return None
    stem = (tokens.get(kind, "[REDACTED]").strip("[]").lower() or "redacted")
    candidate, counter = stem, 1
    while candidate in node and candidate != key:   # never collapse two identities into one key
        counter += 1
        candidate = f"{stem}_{counter}"
    return candidate, kind


def sanitise_structure(ir: IntermediateRepresentation, index: ProtectionIndex,
                       tokens: dict[str, str]) -> dict[str, int]:
    """Sanitise headers, keys and embedded attachments in place; return per-kind counts."""
    counts: dict[str, int] = {}
    fmt = ir.source.format
    data = ir.structure.data

    def bump(kind: str) -> None:
        counts[kind] = counts.get(kind, 0) + 1

    # ── table headers ────────────────────────────────────────────────────────
    if fmt in {"csv", "tsv"} and isinstance(data, dict):
        header = data.get("header") or []
        for position, label in enumerate(header):
            if not isinstance(label, str) or not label.strip():
                continue
            if classify(label):
                continue                      # a legitimate label such as "MRN" stays readable
            findings = find(label, index) or find(label.replace("_", " ").replace("-", " "), index)
            if not findings:
                continue
            replacement = tokens.get(findings[0].kind, "[REDACTED]")
            header[position] = replacement
            bump(findings[0].kind)

    # ── XML text nodes and attributes ────────────────────────────────────────
    # Without this branch no detector ever sees an XML value: the IR walker only knew json/fhir,
    # so an HL7 CDA discharge summary was re-serialised with every identifier intact and still
    # reported as sanitized.
    if fmt == "xml":
        def walk(node) -> None:
            if not isinstance(node, dict):
                return
            for field in ("text", "tail"):
                value = node.get(field)
                if isinstance(value, str) and value.strip():
                    cleaned, kinds = redact(value, index, tokens)
                    if kinds:
                        node[field] = cleaned
                        for kind, count in kinds.items():
                            for _ in range(count):
                                bump(kind)
            # The XML IR stores attributes as [name, value] pairs, not as a mapping.
            attributes = node.get("attributes")
            pairs = (list(attributes.items()) if isinstance(attributes, dict)
                     else [tuple(pair) for pair in attributes or []])
            for index_of, (name, value) in enumerate(pairs):
                if not isinstance(value, str) or not value.strip():
                    continue
                cleaned, kinds = redact(value, index, tokens)
                if not kinds:
                    continue
                if isinstance(attributes, dict):
                    attributes[name] = cleaned
                else:
                    attributes[index_of] = [name, cleaned]
                for kind, count in kinds.items():
                    for _ in range(count):
                        bump(kind)
            for child in node.get("children") or []:
                walk(child)

        if isinstance(data, dict):
            walk(data)

    # ── JSON/FHIR keys and attachments ───────────────────────────────────────
    if fmt in {"json", "fhir"}:
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key in list(node.keys()):
                    child = node.get(key)
                    # Note: no `continue` here. Skipping the rest of the loop body also skips
                    # stack.append(child), which silently stopped every descendant of a matched
                    # field from being sanitised (metadata leakage 12.5% -> 52.5% when that happened).
                    if isinstance(key, str) and isinstance(child, (str, int)):
                        # The value may be a JSON number, not a string: "aadhar_no": 902115225016.
                        text_value = str(child).strip()
                        if _AADHAAR_KEY.search(key) and re.fullmatch(r"[\d\s-]{12}", text_value):
                            node[key] = tokens.get("AADHAAR", "[AADHAAR]")
                            bump("AADHAAR")
                            continue


                            node[key] = tokens.get("AADHAAR", "[AADHAAR]")
                            child = node[key]
                            bump("AADHAAR")
                        elif (_PATH_KEY.search(key) and ("\\" in child or "_" in child)
                              and _PATH_MRN.search(child)):
                            cleaned = _PATH_MRN.sub(tokens.get("MRN", "[MRN]"), child)
                            if cleaned != child:
                                node[key] = cleaned
                                child = cleaned
                                bump("MRN")
                    renamed = _identity_key_replacement(key, node, index, tokens)
                    if renamed is not None:
                        new_key, kind = renamed
                        node[new_key] = node.pop(key)
                        key = new_key
                        bump(kind)
                    child = node[key]
                    if isinstance(child, str) and not _looks_like_base64(child) and (
                            "_" in child or "-" in child) and 4 <= len(child) <= 400:
                        # Export metadata embeds identity in path-shaped strings:
                        # "D:\\HIS\\exports\\opd\\Anita_Sharma_010565\\visits.json". Scan the
                        # separated form and replace the whole value, since it is one atomic field.
                        separated = child.replace("_", " ").replace("\\", " ")
                        findings = find(separated, index)
                        if findings and findings[0].kind in {"NAME", "RELATIVE", "UHID",
                                                             "AADHAAR", "ABHA", "PAN", "PHONE"}:
                            node[key] = tokens.get(findings[0].kind, "[REDACTED]")
                            bump("METADATA")
                            continue
                    if isinstance(child, str) and _looks_like_base64(child):
                        blob = _decode(child)
                        if blob is not None:
                            text = blob.decode("latin-1", "ignore")
                            findings = find(text, index)
                            if findings:
                                node[key] = tokens.get(findings[0].kind, "[REDACTED]")
                                bump("BASE64")
                                continue
                    stack.append(child)
            elif isinstance(node, list):
                # Labels and values also travel as adjacent list elements:
                # "ids": ["aadhar_no", "902115225016", "abha", "12-3456-..."].
                for position, item in enumerate(node):
                    if not isinstance(item, str):
                        continue
                    previous = node[position - 1] if position else None
                    if not isinstance(previous, str):
                        continue
                    if _AADHAAR_KEY.search(previous) and re.fullmatch(r"[\d\s-]{12}", item.strip()):
                        node[position] = tokens.get("AADHAAR", "[AADHAAR]")
                        bump("AADHAAR")
                    elif (_PATH_KEY.search(previous) and ("\\" in item or "_" in item)
                          and _PATH_MRN.search(item)):
                        cleaned = _PATH_MRN.sub(tokens.get("MRN", "[MRN]"), item)
                        if cleaned != item:
                            node[position] = cleaned
                            bump("MRN")
                stack.extend(node)

    return counts
