"""Clinical protection: the veto that keeps a de-identifier from destroying medicine.

Two sources, both derived at run time so nothing is hard-coded to one dataset:

* **lexicon** — drug names, analyte names and units are read from whatever reference files the
  input ships (formulary, lab ranges, ward census, protocol text). A different hospital with
  different drugs is handled by reading *its* files, not by editing code.
* **shape** — numeric-with-unit, ratios, frequency codes, dose courses and eponyms are clinical by
  form alone, so they are protected even when the lexicon is empty.

`ProtectionIndex.covers(start, end)` answers one question: may a detector edit inside this span?
The answer is never "yes" for a value that a clinician needs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Units that make a neighbouring number clinical rather than personal.
_UNITS = (r"mg|mcg|µg|g|gm|kg|ml|l|dL|dl|mmol|mol|mEq|IU|iu|mmHg|mm Hg|bpm|/min|/µL|/uL|/mm3|"
          r"°C|C|F|%|cm|mm|m|hour|hours|hr|hrs|day|days|week|weeks|dose|doses|tablet|tablets|"
          r"tab|tabs|capsule|capsules|cap|drops|puffs|units|U|g/dL|mg/dL|ng/mL|pg/mL|mIU/L")

_NUMBER = r"\d+(?:[.,]\d+)?"
_VALUE_UNIT = re.compile(rf"(?<![\w.]){_NUMBER}\s*(?:{_UNITS})(?![\w])", re.IGNORECASE)
_RATIO = re.compile(rf"(?<![\w.]){_NUMBER}\s*/\s*{_NUMBER}(?![\w.])")
# A ratio is only clinical when a vital-sign word introduces it: "BP 117/82" is a reading,
# "IP/26/00130" is an identifier that happens to contain a slash.
_VITALS = re.compile(r"(?:\bBP\b|B\.P|blood\s*pressure|pulse|\bPR\b|\bRR\b|"
                     r"resp(?:iration)?|SpO2|pressure)\W{0,6}$", re.IGNORECASE)
_FREQUENCY = re.compile(r"\b(?:OD|BD|BID|TDS|TID|QID|QDS|HS|SOS|STAT|PRN|Q\d+H|"
                        r"[0-9]-[0-9]-[0-9]|[01]\s*-\s*[01]\s*-\s*[01])\b")
_COURSE = re.compile(rf"(?:x|×|for)\s*{_NUMBER}\s*(?:days?|weeks?|doses?|months?)", re.IGNORECASE)
_EPONYM = re.compile(r"\b[A-Z][a-z]{2,}'s\s+(?:disease|syndrome|sign|phenomenon|triad|ulcer|"
                     r"lymphoma|anemia|anaemia|palsy|contracture)\b")
_DRUG_FORM = re.compile(r"\b(?:Tab|Tabs|Inj|Cap|Caps|Syp|Susp|Oint|Drops|Sos|Stat)\.?\b")
_TIME = re.compile(r"\b\d{1,2}[:.]\d{2}\s*(?:am|pm|hrs|hours)?\b", re.IGNORECASE)
_DURATION_WORDS = re.compile(r"\b(?:days?|weeks?|months?|hours?)\b", re.IGNORECASE)

_LEXICON_SPLIT = re.compile(r"[^A-Za-z\u0900-\u097F]+")
_STOP = {"id", "name", "code", "type", "unit", "value", "range", "low", "high", "normal",
         "male", "female", "hospital", "district", "state", "village", "text", "date", "yes", "no"}


@dataclass
class ProtectionIndex:
    """Spans that must survive byte-for-byte, plus the vocabulary that generates them."""

    lexicon: set[str] = field(default_factory=set)
    places: set[str] = field(default_factory=set)
    columns: set[str] = field(default_factory=set)
    sources: list[str] = field(default_factory=list)

    @classmethod
    def from_reference_documents(cls, paths: list[Path]) -> "ProtectionIndex":
        index = cls()
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            index.sources.append(path.name)
            for token in _LEXICON_SPLIT.split(text):
                lowered = token.lower()
                if len(lowered) >= 4 and lowered not in _STOP and not lowered.isdigit():
                    index.lexicon.add(lowered)
        return index

    @classmethod
    def from_input_tree(cls, root: str | Path) -> "ProtectionIndex":
        """Prefer files whose names say they are reference data; fall back to nothing."""
        base = Path(root)
        wanted = []
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            lowered = path.name.lower()
            if any(marker in lowered for marker in ("formulary", "reference", "census", "protocol")):
                wanted.append(path)
        index = cls.from_reference_documents(wanted)
        index.places = harvest_places(root)
        return index

    # ── span tests ───────────────────────────────────────────────────────────
    def is_clinical_text(self, text: str, start: int, end: int) -> bool:
        """True when the span, or its immediate neighbourhood, is clinical."""
        window_start = max(0, start - 24)
        window_end = min(len(text), end + 24)
        window = text[window_start:window_end]
        if any(pattern.search(window) for pattern in
               (_VALUE_UNIT, _FREQUENCY, _COURSE, _EPONYM, _DRUG_FORM)):
            return True
        if _RATIO.search(window) and _VITALS.search(text[max(0, start - 18):start]):
            return True
            return True
        if _TIME.search(window) or _DURATION_WORDS.search(window):
            return True
        tokens = _LEXICON_SPLIT.split(text[start:end])
        return any(token.lower() in self.lexicon for token in tokens if len(token) >= 4)

    def is_place(self, text: str) -> bool:
        """A district or state is demographic context: coarsening it is fine, deleting it is not."""
        candidate = re.sub(r"\s+", " ", text.strip()).lower()
        if not candidate:
            return False
        if candidate in self.places:
            return True
        tokens = candidate.split()
        return bool(tokens) and all(token in self.places for token in tokens)

    def word_is_clinical(self, word: str) -> bool:
        return word.lower() in self.lexicon or word.lower() in _STOP

    def protected_spans(self, text: str) -> list[tuple[int, int]]:
        """All spans a detector must not touch, in one pass."""
        spans: list[tuple[int, int]] = []
        for pattern in (_VALUE_UNIT, _COURSE, _FREQUENCY, _EPONYM, _TIME):
            spans.extend(match.span() for match in pattern.finditer(text))
        for match in _RATIO.finditer(text):
            if _VITALS.search(text[max(0, match.start() - 18):match.start()]):
                spans.append(match.span())
        return spans


# ── place harvesting ─────────────────────────────────────────────────────────
_GEO_LABEL = re.compile(r"(district|state|region)\b", re.IGNORECASE)
_INSTITUTION = re.compile(r"\b(hospital|clinic|centre|center|institute|nursing\s*home|"
                          r"medical\s*college|pharmacy|laborator(y|ies)|labs?)\b", re.IGNORECASE)


def is_institution(text: str) -> bool:
    """An organisation name is context, not a person."""
    return bool(_INSTITUTION.search(text))


def harvest_places(root: str | Path, budget_bytes: int = 8_000_000) -> set[str]:
    """Read district/state columns from the input itself; no shipped gazetteer needed.

    The label is generic (`District`, `State`), so the same code works on an unseen hospital
    export: whatever *its* district column holds becomes the protected place vocabulary.
    """
    import csv
    import io
    import json

    places: set[str] = set()
    spent = 0
    base = Path(root)
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".csv", ".tsv", ".json"}:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if spent + size > budget_bytes:
            continue
        spent += size
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lstrip("\ufeff")
        except OSError:
            continue
        if path.suffix.lower() in {".csv", ".tsv"}:
            delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
            try:
                rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
            except csv.Error:
                continue
            if not rows:
                continue
            columns = [index for index, label in enumerate(rows[0]) if _GEO_LABEL.search(label or "")]
            for row in rows[1:]:
                for index in columns:
                    if index < len(row):
                        value = row[index].strip()
                        if 2 <= len(value) <= 40:
                            places.add(value.lower())
        else:
            try:
                payload = json.loads(text)
            except Exception:
                continue
            stack = [payload]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    for key, child in node.items():
                        if isinstance(child, str) and _GEO_LABEL.search(str(key)):
                            if 2 <= len(child) <= 40:
                                places.add(child.strip().lower())
                        stack.append(child)
                elif isinstance(node, list):
                    stack.extend(node)
    return places
