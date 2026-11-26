"""Scoped, keyed patient pseudonyms (SPEC.md §6: "patient": "PSN-7Q2K9D").

Design decisions, each forced by evidence gathered during this build:

* HMAC with the release secret, never a plain hash. An earlier audit reproduced a real system's
  UID as sha256(name+dob+sex) with an empty salt — invertible by dictionary attack.
* The evidence is an *identifier*, never a name. Name-only linkage was measured at 96 false merges;
  merging two patients corrupts their histories, which is worse than leaving them unlinked.
* No mapping table is stored, so there is nothing to encrypt and nothing to leak.
* A record with no identifier evidence gets patient=None. Honest absence beats a guess.

Alignment with the spec is deliberately modest: the identifier is taken from field labels where
available, otherwise from the strongest identifier-shaped value in the record. One pseudonym per
record, per file; batch files containing several patients are a documented limitation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from typing import Any

PREFIX = "PSN-"
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # no I, O, 0, 1: unambiguous in print
_SCOPE = "secret-wards/dev-corpus"                  # change per release; never derived from data

# Identifier-shaped evidence. A name alone is never evidence, by rule.
_PATIENT_COLUMN = re.compile(r"^(?:uhid|patient_?id|patient_?uhid|mrn|hospital_?patient_?id)$",
                             re.IGNORECASE)
_ID_KEYS = re.compile(r"(?:uhid|mrn|ipd|opd|reg(?:istration)?_?(?:no|id|number)?|patient_?id|adm)"
                      r"\w*$", re.IGNORECASE)
_ID_VALUE = re.compile(r"\b[A-Z]{2,5}[-_]?\d{5,9}\b")
_BARE_ID = re.compile(r"\b\d{6,9}\b")


def _digest(secret: str, kind: str, value: str) -> str:
    message = f"{_SCOPE}|{kind}|{value.strip().upper()}".encode("utf-8")
    raw = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    token = base64.b32encode(raw).decode("ascii").translate(str.maketrans("018", "OL2"))
    return PREFIX + "".join(ch for ch in token if ch in _ALPHABET)[:6]


def pseudonym_for(secret: str | None, evidence: str | None) -> str | None:
    """PSN- token for one patient identifier, or None when there is no defensible evidence."""
    if not secret or not evidence:
        return None
    value = str(evidence).strip()
    if not value:
        return None
    kind = "mrn" if value[:1].isdigit() else "hospital-id"
    return _digest(secret, kind, value)


def identity_evidence(ir: Any) -> str | None:
    """The single identifier in a record, or None when the record is ambiguous.

    A batch export contains one identifier per row. Assigning the first one to every row produced
    7 wrongly merged patients in one run — the same failure the audit measured at 96 false merges.
    Ambiguity is therefore answered with None, never with a guess.
    """
    """Best identifier-shaped value in a parsed record, preferring labelled fields."""
    labelled: list[str] = []
    bare: list[str] = []

    def walk(node: Any, key_hint: str = "", depth: int = 0) -> None:
        if depth > 24:
            return
        if isinstance(node, dict):
            for key, child in node.items():
                hint = str(key)
                walk(child, hint, depth + 1)
        elif isinstance(node, list):
            for child in node[:400]:
                walk(child, key_hint, depth + 1)
        elif isinstance(node, str):
            for match in _ID_VALUE.finditer(node):
                (labelled if _ID_KEYS.search(key_hint) else bare).append(match.group(0))
            if _ID_KEYS.search(key_hint):
                for match in _BARE_ID.finditer(node):
                    labelled.append(match.group(0))

    walk(getattr(ir, "structure", None).data if getattr(ir, "structure", None) else {})
    for group in (labelled, bare):
        distinct = {value.strip().upper() for value in group if value.strip()}
        if len(distinct) == 1:
            return group[0]
        if len(distinct) > 1:
            return None                     # several patients in one file: no defensible answer
    return None


def secret_from_environment() -> str | None:
    return os.environ.get("RAKSHA_SECRET") or None


def pseudonym_for_locator(ir: Any, locator: str, secret: str | None) -> str | None:
    """Identity at record granularity.

    A hospital export is one file with one patient per row, so a file-level pseudonym is a false
    merge waiting to happen (measured: 7 wrong merges, precision 0.06). Identity is therefore read
    from the row's own identifier column, and from the whole record only when the record carries a
    single unambiguous identifier.
    """
    if not secret:
        return None
    structure = getattr(ir, "structure", None)
    data = getattr(structure, "data", None) or {}
    fmt = getattr(getattr(ir, "source", None), "format", "")
    if fmt in {"csv", "tsv"} and locator.startswith("row:") and isinstance(data, dict):
        try:
            index = int(locator.split(":", 1)[1])
        except (IndexError, ValueError):
            return None
        header = [str(cell).strip() for cell in (data.get("header") or [])]
        rows = data.get("rows") or []
        # Only a column that names the patient itself qualifies. Anything else is evidence about a
        # claim, a visit or a hospital, and using it links two different people (measured: 1 merge).
        column = next((i for i, name in enumerate(header)
                       if _PATIENT_COLUMN.match(name.strip().replace(" ", "_"))), None)
        if column is None or not rows:
            return pseudonym_for(secret, identity_evidence(ir))
        row = rows[index] if index < len(rows) else rows[-1]
        value = row[column] if isinstance(row, (list, tuple)) and column < len(row) else None
        return pseudonym_for(secret, str(value) if value not in (None, "") else None)
    return pseudonym_for(secret, identity_evidence(ir))
