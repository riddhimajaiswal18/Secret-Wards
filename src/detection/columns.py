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
    ("RELATIVE", re.compile(r"(relative|guardian|father|mother|spouse|husband|wife|pita|pati|mata|maa|"
                            r"attendant|next\s*of\s*kin|kin|पिता|माता|पति|पत्नी|"
                            r"अभिभावक|रिश्तेदार|परिजन)\b", re.I)),
    ("AADHAAR", re.compile(r"(aadhaa?r|adhar|uidai|आधार)", re.I)),
    ("ABHA", re.compile(r"\babha\b", re.I)),
    ("PAN", re.compile(r"\bpan\b|pan\s*(no|number)", re.I)),
    ("INSURANCE", re.compile(r"(insurance|policy|tpa|claim|scheme|esi|esic|pmjay)", re.I)),
    ("UHID", re.compile(r"(uhid|mrn|patient\s*id|pid|reg(istration)?\s*(no|num|id)|"
                        r"\bipd\b|\bopd\b|admission\s*(no|num|id)|hospital\s*id|"
                        r"\bcr\s*no\b|visit\s*(no|id)|encounter|पंजीकरण|अस्पताल\s*आईडी)", re.I)),
    ("DOB", re.compile(r"(\bdob\b|date\s*of\s*birth|birth\s*date|year\s*of\s*birth|"
                       r"janm\s*(?:tithi|tarikh|date)|जन्म\s*(?:तिथि|तारीख))", re.I)),
    ("PHONE", re.compile(r"\b(?:phone|mobile|contact|cell|telephone|tel|whatsapp)\b|मोबाइल|फोन|संपर्क|दूरभाष", re.I)),
    ("EMAIL", re.compile(r"(e[-_]?mail|email\s*id|ईमेल)", re.I)),
    ("PIN", re.compile(r"(\bpin\b|pincode|pin\s*code|zip|postal|पिन\s*(?:कोड)?)", re.I)),
    ("VILLAGE", re.compile(r"(village|gram|gaon|gaav|panchayat|गांव|गाँव|ग्राम|पंचायत)", re.I)),
    ("HOUSE", re.compile(r"(house|h\.?\s*no|door|flat|building|street|gali|mohalla|"
                         r"locality|colony|area\b|घर|मकान|गली|मोहल्ला)", re.I)),
    ("LANDMARK", re.compile(r"(landmark|near\s*by|nearby|पहचान\s*चिह्न|निशान)", re.I)),
    ("ADDRESS", re.compile(r"(address|addr|residence|residing|pata|city|tehsil|tahsil|jila|zila|"
                            r"(?<![\u0900-\u097F])पता(?![\u0900-\u097F])|"
                            r"(?<![\u0900-\u097F])निवास(?![\u0900-\u097F])|तहसील|जिला)", re.I)),
    ("NAME", re.compile(r"(patient\s*name|full\s*name|(?:first|last|given|family|middle)_?name|"
                        r"\bname\b|pname|pt\s*name|"
                        r"\bnaam\b|रोगी\s*का\s*नाम|मरीज़?\s*का\s*नाम|\bनाम\b)", re.I)),
]

# Columns that must never be treated as personal: clinical content and demographics we keep.
_KEEP = re.compile(r"\b(?:district|state|country|region|town|age|sex|gender|ward|bed|"
                   r"medicine|drug|dose|dosage|frequency|route|test|investigation|value|unit|"
                   r"result|reference|range|department|doctor|consultant|hospital|clinic|"
                   r"institution|facility|amount|bill|total|status|type|remarks|notes?|"
                   r"complaint|history|procedure|outcome)\b|"
                   r"\bdiagnos\w*\b|\bdate\s*of\s*(?:admission|discharge)\b|"
                   r"\b(?:admission|discharge)\s*date\b|\b(?:ling|umar|tehsil|tahsil|jila|zila)\b|"
                   r"अस्पताल|चिकित्सालय|डॉक्टर|चिकित्सक", re.I)

_LABEL_CLEAN = re.compile(r"[^a-z0-9\u0900-\u097f]+", re.I)


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
    # Explicit identity/identifier fields take precedence over a generic context word. For
    # example, `hospital_uhid` is an identifier field even though it contains `hospital`; the
    # `_KEEP` guard is for ambiguous labels such as `hospital_name` and `doctor_name`.
    direct_kinds = {"RELATIVE", "AADHAAR", "ABHA", "PAN", "INSURANCE", "UHID", "DOB",
                    "PHONE", "EMAIL", "PIN", "VILLAGE", "HOUSE", "LANDMARK"}
    for kind, pattern in _COLUMN_RULES:
        if kind in direct_kinds and pattern.search(normalised):
            return kind
    if (_KEEP.search(normalised)
            and not re.search(r"\b(?:address|addr|residence|pata)\b", normalised)):
        return None
    for kind, pattern in _COLUMN_RULES:
        if kind not in direct_kinds and pattern.search(normalised):
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
