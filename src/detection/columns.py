"""Structural detection: decide what a column or JSON key *means*, not what a value looks like.

A medical record number is often just `000123`; a house number is often just `22`; a date of birth
is often just `12/03/1968`. No value-shape rule can tell those from blood pressure or a dose. The
header can: `MRN`, `H.No`, `DOB` are unambiguous, and they generalise across hospitals because the
meaning of the label is the same even when the wording changes.

Rules are ordered: the first match wins, so a specific label (`relative_name`) beats a generic one
(`name`). Anything clinical is deliberately **not** mapped, and an unmapped column is left to the
value detectors.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# (kind, pattern) — order matters, first match wins.
_COLUMN_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("RELATIVE", re.compile(r"(relative|guardian|father|mother|spouse|husband|wife|"
                            r"attendant|next\s*of\s*kin|kin)\b", re.I)),
    ("AADHAAR", re.compile(r"(aadhaa?r|adhar|uidai)", re.I)),
    ("ABHA", re.compile(r"\babha\b", re.I)),
    ("PAN", re.compile(r"\bpan\b|pan\s*(no|number)", re.I)),
    ("INSURANCE", re.compile(r"(insurance|policy|tpa|claim|scheme|esi|esic|pmjay)", re.I)),
    ("UHID", re.compile(r"(uhid|mrn|patient\s*id|pid|reg(istration)?\s*(no|num|id)|"
                        r"\bipd\b|\bopd\b|admission\s*(no|num|id)|hospital\s*id|"
                        r"\bcr\s*no\b|visit\s*(no|id)|encounter)", re.I)),
    ("DOB", re.compile(r"(\bdob\b|date\s*of\s*birth|birth\s*date|year\s*of\s*birth)", re.I)),
    ("PHONE", re.compile(r"(phone|mobile|contact|cell|tel(ephone)?|whatsapp)", re.I)),
    ("EMAIL", re.compile(r"(e[-_]?mail|email\s*id)", re.I)),
    ("PIN", re.compile(r"(\bpin\b|pincode|pin\s*code|zip|postal)", re.I)),
    ("HOUSE", re.compile(r"(house|h\.?\s*no|door|flat|building|street|gali|mohalla|"
                         r"locality|colony|area\b)", re.I)),
    ("VILLAGE", re.compile(r"(village|gram|panchayat)", re.I)),
    ("LANDMARK", re.compile(r"(landmark|near\s*by|nearby)", re.I)),
    ("ADDRESS", re.compile(r"(address|addr|residence|residing)", re.I)),
    ("NAME", re.compile(r"(patient\s*name|full\s*name|\bname\b|pname|pt\s*name)", re.I)),
]

# Columns that must never be treated as personal: clinical content and demographics we keep.
_KEEP = re.compile(r"(district|state|country|region|city|town|age|sex|gender|diagnos|medicine|drug|dose|dosage|frequency|route|"
                   r"test|investigation|value|unit|result|reference|range|ward|bed|"
                   r"department|doctor|consultant|date\s*of\s*(admission|discharge)|"
                   r"admission\s*date|discharge\s*date|amount|bill|total|status|type|"
                   r"remarks|notes?|complaint|history|procedure|outcome)", re.I)

_LABEL_CLEAN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ColumnKind:
    kind: str
    label: str


def classify(label: str | None) -> str | None:
    """Return the personal-data kind a column/key label implies, or None."""
    if not label:
        return None
    normalised = _LABEL_CLEAN.sub(" ", str(label).lower()).strip()
    if not normalised:
        return None
    if _KEEP.search(normalised):
        return None
    for kind, pattern in _COLUMN_RULES:
        if pattern.search(normalised):
            return kind
    return None


def classify_all(labels: list[str]) -> list[str | None]:
    return [classify(label) for label in labels]


def key_from_locator(locator: str) -> str | None:
    """Last meaningful segment of a JSONPath: `$.patient.dob` -> `dob`."""
    tail = locator.rsplit(".", 1)[-1]
    tail = tail.split("[", 1)[0]
    tail = tail.strip("'\"")
    return tail or None
