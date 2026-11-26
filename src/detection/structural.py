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
from src.detection.engine import find
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

    # ── JSON/FHIR keys and attachments ───────────────────────────────────────
    if fmt in {"json", "fhir"}:
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key in list(node.keys()):
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
                    # Index-by-patient objects: the key itself is the identity, and it may be a
                    # single capitalised token ("Anita_Sharma") or a bare numeric MRN ("010565").
                    if isinstance(key, str) and len(key) >= 4 and not classify(key):
                        findings = (find(key, index)
                                    or find(key.replace("_", " ").replace("-", " "), index)
                                    or _index_key_findings(key, child, index))
                        if findings:
                            new_key = tokens.get(findings[0].kind, "[REDACTED]").strip("[]")
                            new_key = new_key.lower() or "redacted"
                            counter = 1
                            candidate = new_key
                            while candidate in node:      # never collapse two keys into one
                                counter += 1
                                candidate = f"{new_key}_{counter}"
                            node[candidate] = node.pop(key)
                            bump(findings[0].kind)
                    stack.append(child)
            elif isinstance(node, list):
                stack.extend(node)

    return counts
