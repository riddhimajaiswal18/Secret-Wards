"""Tier-0 detection: identifiers with a structural check, plus a conservative name-shape rule.

Deliberately narrow. This module exists so scanned/derived text can be released safely before the
full detector lands: it removes things that are provably identifiers even without context, and it
over-redacts name-shaped token runs rather than risk publishing a patient's name.

Every replacement is a fixed token, so output is deterministic and the clinical text around the
redaction stays byte-identical.
"""
from __future__ import annotations

import re

_TOKEN = "[REDACTED]"

_DIGITS_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")

# Aadhaar-like: 12 digits in 4-4-4 groups (verhoeff-validated downstream when confidence matters).
_AADHAAR = re.compile(r"(?<!\d)(\d{4})[ -]?(\d{4})[ -]?(\d{4})(?!\d)")
# Indian mobile / landline with optional country code and separators.
_PHONE = re.compile(r"(?<!\d)(?:\+?91[ -]?)?([6-9]\d{9})(?!\d)")
# PAN: five letters, four digits, one letter, with a valid holder-type character.
_PAN = re.compile(r"(?<![A-Z0-9])([A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z])(?![A-Z0-9])")
# ABHA / health id: 14 digits, optionally dashed after 2.
_ABHA = re.compile(r"(?<!\d)(\d{2}-?\d{4}-?\d{4}-?\d{4})(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Hospital identifiers: a mandatory letter prefix, then a separator, then digits.
# The letter prefix is required and a bare space is not a separator, so a vital sign such as
# "BP 117/82" or a ratio such as "117/82" can never be read as an identifier.
_UHID = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2,6}[-/](?:[A-Za-z]{1,6}[-/])?\d{2,10}(?:[-/]\d{1,10})?)(?![0-9])")
_PINCODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")

# Name shape: 2–4 capitalised tokens, not a unit, not a drug form, not an organisation suffix.
_NAME_RUN = re.compile(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,3})\b")

_STOPWORDS = {
    "patient", "hospital", "discharge", "summary", "admission", "department", "address",
    "mobile", "clinic", "college", "district", "village", "tablet", "capsule", "injection",
    "doctor", "consultant", "reference", "range", "result", "report", "diagnosis", "medicine",
}
_UNIT_WORDS = {
    "mg", "ml", "gm", "kg", "mmhg", "mmol", "iu", "mcg", "drops", "tablet", "capsule",
    "days", "weeks", "hours", "times", "daily", "twice", "thrice",
}

# Dosage-form markers: a capitalised word sitting next to one of these is a drug, not a person.
_FORM_WORDS = {"tab", "tabs", "inj", "cap", "caps", "syp", "susp", "oint", "drops", "sos", "stat"}


def fold_digits(text: str) -> str:
    """Devanagari digits become ASCII so one pattern serves both scripts."""
    return text.translate(_DIGITS_DEVANAGARI)


def scrub(text: str) -> tuple[str, dict[str, int]]:
    """Return (redacted_text, counts by category). Deterministic; never reorders text."""
    counts: dict[str, int] = {}

    def mark(kind: str) -> None:
        counts[kind] = counts.get(kind, 0) + 1

    text = fold_digits(text)

    def sub(pattern: re.Pattern, kind: str, source: str) -> str:
        def replace(match: re.Match) -> str:
            mark(kind)
            return _TOKEN
        return pattern.sub(replace, source)

    text = sub(_EMAIL, "EMAIL", text)
    text = sub(_PAN, "PAN", text)
    text = sub(_ABHA, "ABHA", text)
    text = sub(_AADHAAR, "AADHAAR", text)
    text = sub(_PHONE, "PHONE", text)
    text = sub(_UHID, "UHID", text)
    text = sub(_PINCODE, "PIN", text)

    def name_repl(match: re.Match) -> str:
        tokens = match.group(1).split()
        # Redact the name tokens and keep the surrounding vocabulary: "Patient Farhan Qureshi"
        # must not survive because "Patient" happened to sit in front of it.
        clinical = _STOPWORDS | _UNIT_WORDS | _FORM_WORDS
        candidates = [token for token in tokens if token.lower() not in clinical]
        if len(candidates) < 2 or any(len(token) < 3 for token in candidates):
            return match.group(0)
        out, previous = [], None
        for token in tokens:
            if token.lower() in clinical:
                out.append(token)
                previous = None
                continue
            if previous != _TOKEN:
                out.append(_TOKEN)
                previous = _TOKEN
        mark("NAME")
        return " ".join(out)

    text = _NAME_RUN.sub(name_repl, text)
    return text, counts
