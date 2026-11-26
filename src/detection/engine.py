"""Detection engine: find personal data in text, table cells and JSON leaves.

The whole design rests on one rule: **a detector proposes, a protection index vetoes**. Every
candidate span is tested against clinical shapes (``12.6 g/dL``, ``1-0-1``, ``x 5 days``) and the
run-time drug/analyte lexicon before it is allowed to become an edit. That is what keeps a
de-identifier from deleting medicine while chasing names.

Findings carry a *role* (patient, relative, clinician, institution) because the transform differs:
a clinician's name is not the patient's identity, and deleting it costs clinical meaning for no
privacy gain.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from src.detection.columns import classify, key_from_locator
from src.detection.protection import ProtectionIndex, is_institution
from src.ir import (Annotation, DetectionStatus, IntermediateRepresentation, PendingEdit)
from src.detection import identifiers as ids

# ── kinds ────────────────────────────────────────────────────────────────────
PHONE, EMAIL, AADHAAR, PAN, ABHA, UHID, PIN, NAME, RELATIVE = (
    "PHONE", "EMAIL", "AADHAAR", "PAN", "ABHA", "UHID", "PIN", "NAME", "RELATIVE")

_ANCHOR_NAME = re.compile(
    r"(?:Patient\s*Name|Name\s*of\s*Patient|Pt\.?\s*Name|Patient|Name|नाम|मरीज़)\s*[:\-–]?\s*")
_ANCHOR_RELATIVE = re.compile(
    r"(?:S/o|D/o|W/o|C/o|Son\s+of|Daughter\s+of|Wife\s+of|Husband\s+of|Father\s+of|माता|पिता)\s*[:\-–]?\s*",
    re.IGNORECASE)
_ANCHOR_CLINICIAN = re.compile(
    r"(?:Dr\.?|Doctor|Consultant|RMO|MO|Physician|Surgeon)\s*[:\-–]?\s*", re.IGNORECASE)
# Romanised Hindi and Devanagari name anchors. The captured run may be lowercase (Hinglish) or a
# single Devanagari token, which the capitalised-run rule could never match.
_ANCHOR_LOCAL = re.compile(
    r"(?:patient\s*ka\s*naam|patient\s*ka\s*name|naam|नाम|मरीज़\s*का\s*नाम|रोगी\s*का\s*नाम)"
    r"\s*[:\-–]?\s*(?:hai\s+|है\s+)?", re.IGNORECASE)
_LOCAL_TOKEN = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}|[\u0900-\u0963\u0970-\u097F]{2,}")
_HINGLISH_STOP = {
    "hai", "hain", "ka", "ki", "ke", "ko", "se", "aur", "mein", "me", "koi", "nahi", "tha",
    "the", "patient", "mobile", "number", "phone", "address", "pata", "umar", "age", "ward",
    "doctor", "dr", "hospital", "admit", "discharge", "fever", "bukhar", "dard", "khansi",
    "dawa", "goli", "din", "report", "test", "opd", "ipd", "mrn", "uhid",
}

_ANCHOR_ADDRESS = re.compile(
    r"(?:Address|Addr|पता|Residence)\s*[:\-–]\s*", re.IGNORECASE)

# A name-shaped run: 2–4 capitalised tokens, or Devanagari words of 3+ characters.
# Hinglish names carry a lowercase kinship suffix: "Kamal bhaiya", "Asha ji", "Mahesh bhai".
_NAME_KIN = re.compile(r"\b[A-Z][a-z]{2,}\s+(?:bhaiya|bhai|behenji|behen|ji|didi|sahab|sahib|ben)\b",
                       re.IGNORECASE)

_NAME_RUN = re.compile(r"(?:[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,3}"
                       r"|[\u0900-\u0963\u0970-\u097F]{3,}"
                       r"(?:\s+[\u0900-\u0963\u0970-\u097F]{3,}){1,3})")
_ADDRESS_RUN = re.compile(r"[A-Za-z0-9][^,;\n]{8,90}")

# A roster line is often prefixed by a time or a bullet ("18:40 - Name", "3. Name"). The clinical
# veto reads that prefix as a vitals reading and suppresses the name that follows it, so the
# prefix is excluded from the veto decision — the name is not inside a clinical neighbourhood.
_LABEL_PREFIX = re.compile(r"(?:\d{1,2}[:.]\d{2}(?:\s*(?:am|pm))?|\d{1,2}(?:st|nd|rd|th)?"
                           r"|[-\u2022*])\s*[-\u2013\u2014:)]?\s*$", re.IGNORECASE)

_NOT_NAMES = {
    "patient", "hospital", "discharge", "summary", "admission", "department", "address",
    "mobile", "phone", "clinic", "college", "district", "village", "tehsil", "tablet",
    "capsule", "injection", "doctor", "consultant", "reference", "range", "result", "report",
    "diagnosis", "medicine", "male", "female", "years", "year", "days", "date", "opd", "ipd",
}
# Devanagari function words and complaint vocabulary: "6 दिन से बुखार" is a clinical sentence,
# not a name. Word-level, general, and independent of any patient identity.
_NOT_NAMES_DEVA = {
    "दिन", "से", "और", "के", "में", "है", "को", "का", "की", "पर", "लिए", "बुखार", "खांसी",
    "दर्द", "उल्टी", "दस्त", "सांस", "हफ्ते", "महीने", "साल", "वर्ष", "रोगी", "मरीज", "नाम",
    "पता", "जांच", "दवा", "गोली", "इंजेक्शन", "अस्पताल", "डॉक्टर", "स्थिति", "इलाज",
}


@dataclass
class Finding:
    kind: str
    start: int
    end: int
    role: str = "patient"
    confidence: float = 1.0

    def overlaps(self, spans: Iterable[tuple[int, int]]) -> bool:
        return any(self.start < end and start < self.end for start, end in spans)


def _identifier_patterns() -> list[tuple[str, re.Pattern, float]]:
    return [(EMAIL, ids._EMAIL, 1.0), (PAN, ids._PAN, 1.0), (ABHA, ids._ABHA, 0.9),
            (AADHAAR, ids._AADHAAR, 0.9), (PHONE, ids._PHONE, 0.95),
            (UHID, ids._UHID, 0.8), (PIN, ids._PINCODE, 0.7)]


_CLINICIAN_PREFIX = re.compile(r"(?:Dr\.?|Doctor|Consultant|RMO|MO)\s*", re.IGNORECASE)


def _clinician_spans(text: str) -> list[tuple[int, int]]:
    """Roles marked on the page win: a clinician is not the patient and must not be scrubbed."""
    spans: list[tuple[int, int]] = []
    for match in _CLINICIAN_PREFIX.finditer(text):
        run = _NAME_RUN.search(text[match.end():match.end() + 60])
        if run:
            spans.append((match.start(), match.end() + run.end()))
    return spans


def find(text: str, index: ProtectionIndex, *, names: bool = True) -> list[Finding]:
    """All personal spans in one string, clinical and contextual content excluded."""
    protected = index.protected_spans(text) + _clinician_spans(text)
    # Devanagari digits are the same value as ASCII digits and folding is one character for one,
    # so spans computed on the folded copy still address the original text.
    folded = ids.fold_digits(text)
    found: list[Finding] = []

    for kind, pattern, confidence in _identifier_patterns():
        for match in pattern.finditer(folded):
            start, end = match.span()
            candidate = Finding(kind, start, end, "patient", confidence)
            if candidate.overlaps(protected) or index.is_clinical_text(folded, start, end):
                continue
            # A 6-digit PIN and a 6-digit value are the same shape; require a locality word nearby.
            if kind == PIN and not re.search(r"(?:pin|pincode|post|zip)\W{0,3}$",
                                             text[max(0, start - 16):start], re.IGNORECASE):
                continue
            found.append(candidate)

    if names:
        found.extend(_anchored(text, _ANCHOR_RELATIVE, RELATIVE, 0.9, protected, index))
        found.extend(_anchored(text, _ANCHOR_NAME, NAME, 0.9, protected, index))
        found.extend(_bare_runs(text, protected, index))
        found.extend(_anchored_local(text, protected, index))
        for match in _NAME_KIN.finditer(text):
            candidate = Finding(NAME, match.start(), match.end(), "patient", 0.8)
            if not candidate.overlaps(protected) and \
                    not index.is_clinical_text(text, match.start(), match.end()):
                found.append(candidate)
    return _dedupe(found)


def _anchored(text: str, anchor: re.Pattern, kind: str, confidence: float,
              protected: list[tuple[int, int]], index: ProtectionIndex) -> list[Finding]:
    out: list[Finding] = []
    for anchor_match in anchor.finditer(text):
        window = text[anchor_match.end():anchor_match.end() + 60]
        run = _NAME_RUN.search(window)
        if not run:
            continue
        start = anchor_match.end() + run.start()
        end = anchor_match.end() + run.end()
        tokens = {token.lower() for token in text[start:end].split()}
        if tokens & (_NOT_NAMES | _NOT_NAMES_DEVA) or len(tokens) < 2:
            continue
        candidate = Finding(kind, start, end, "relative" if kind == RELATIVE else "patient",
                            confidence)
        if candidate.overlaps(protected) or index.is_clinical_text(text, start, end):
            continue
        out.append(candidate)
    return out


def _anchored_local(text: str, protected: list[tuple[int, int]],
                    index: ProtectionIndex) -> list[Finding]:
    """Names after a Hinglish or Devanagari anchor: lowercase runs and single tokens allowed.

    "Patient ka naam krishna chaitanya hai" and "नाम: सुनीता" are the two shapes that leaked at
    100% and 21% respectively because they do not look like English names.
    """
    out: list[Finding] = []
    for anchor in _ANCHOR_LOCAL.finditer(text):
        cursor = anchor.end()
        run: list[tuple[int, int]] = []
        for token in _LOCAL_TOKEN.finditer(text, cursor, cursor + 80):
            value = token.group(0)
            if len(run) >= 3:
                break
            if value.lower() in _HINGLISH_STOP or value.lower() in _NOT_NAMES:
                break
            if index.word_is_clinical(value) or index.is_place(value):
                break
            run.append(token.span())
        if not run:
            continue
        left, right = run[0][0], run[-1][1]
        candidate = Finding(NAME, left, right, "patient", 0.75)
        if candidate.overlaps(protected) or index.is_clinical_text(text, left, right):
            continue
        out.append(candidate)
    return out


def _bare_runs(text: str, protected: list[tuple[int, int]],
               index: ProtectionIndex) -> list[Finding]:
    """Unanchored names: lower confidence, never inside a clinical neighbourhood.

    Stopwords are trimmed rather than treated as a veto, otherwise a label such as
    "Discharge Summary Anita Deshmukh" would protect the name it happens to sit next to.
    """
    out: list[Finding] = []
    for match in _NAME_RUN.finditer(text):
        run = match.group(0)
        if is_institution(run) or index.is_place(run):
            continue
        group: list[tuple[int, int]] = []
        tokens = [(token.start(), token.end(), token.group(0))
                  for token in re.finditer(r"\S+", run)] + [(None, None, None)]
        for start, end, token in tokens:
            keep = (token is not None
                    and len(token) >= 3
                    and token.lower() not in _NOT_NAMES
                    and token.lower() not in _NOT_NAMES_DEVA
                    and not index.word_is_clinical(token))
            if keep:
                group.append((start, end))
                continue
            if len(group) >= 2 or (len(group) == 1 and _devanagari_word(run)):
                left = match.start() + group[0][0]
                right = match.start() + group[-1][1]
                candidate = Finding(NAME, left, right, "patient", 0.6)
                prefixed = bool(_LABEL_PREFIX.search(text[max(0, left - 12):left]))
                if not candidate.overlaps(protected) and (
                        prefixed or not index.is_clinical_text(text, left, right)):
                    out.append(candidate)
            group = []
    return out


def _devanagari_word(run: str) -> bool:
    """A single Devanagari word of 4+ characters is name-shaped; Latin single words are not."""
    return bool(re.fullmatch(r"[\u0900-\u0963\u0970-\u097F]{4,}", run.strip()))


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """Keep the highest-confidence finding per overlapping group; deterministic order."""
    ordered = sorted(findings, key=lambda f: (-f.confidence, f.start, -(f.end - f.start)))
    kept: list[Finding] = []
    for candidate in ordered:
        if any(candidate.start < other.end and other.start < candidate.end for other in kept):
            continue
        kept.append(candidate)
    return sorted(kept, key=lambda f: f.start)


# ── edit construction ────────────────────────────────────────────────────────
def redact(text: str, index: ProtectionIndex, tokens: dict[str, str]) -> tuple[str, dict[str, int]]:
    """Apply every finding to one string, returning the new string and per-kind counts."""
    counts: dict[str, int] = {}
    out = text
    for finding in reversed(find(text, index)):
        token = tokens.get(finding.kind)
        if not token:
            continue
        out = out[:finding.start] + token + out[finding.end:]
        counts[finding.kind] = counts.get(finding.kind, 0) + 1
    return out, counts


def _walk_json(value: Any, path: str, emit) -> None:
    from src.ir import json_path
    stack: list[tuple[Any, str]] = [(value, path)]
    while stack:
        node, current = stack.pop()
        if isinstance(node, dict):
            for key, child in node.items():
                stack.append((child, json_path(current, key)))
        elif isinstance(node, list):
            for position, child in enumerate(node):
                stack.append((child, json_path(current, position)))
        elif isinstance(node, str) and len(node) >= 4:
            emit(current, node)


def build_edits(ir: IntermediateRepresentation, index: ProtectionIndex,
                tokens: dict[str, str]) -> tuple[dict[str, list[PendingEdit]], dict[str, int]]:
    """Turn findings into locator-addressed edits, one technique per kind.

    Text keeps span-level edits (surgical). Tables and JSON replace the whole cell or value, which
    is safer than splicing inside a serialised field and keeps locators stable.
    """
    edits: dict[str, list[PendingEdit]] = {}
    counts: dict[str, int] = {}
    counter = 0

    def add(locator: str, replacement: str, kind: str, expected: Any) -> None:
        nonlocal counter
        counter += 1
        edits.setdefault(locator, []).append(PendingEdit(
            edit_id=f"e{counter:05d}", locator=locator, replacement=replacement,
            expected_value=expected, technique=f"replace_{kind.lower()}"))

    fmt = ir.source.format
    data = ir.structure.data

    if fmt == "text" and isinstance(data, str):
        for finding in find(data, index):
            token = tokens.get(finding.kind)
            if not token:
                continue
            add(f"span:{finding.start}:{finding.end}", token, finding.kind,
                data[finding.start:finding.end])
            counts[finding.kind] = counts.get(finding.kind, 0) + 1
        return edits, counts

    if fmt in {"csv", "tsv"} and isinstance(data, dict):
        # A label such as MRN or DOB settles what a column holds even when the value looks
        # anonymous, which is exactly the case value-shape rules cannot decide.
        column_kinds = [classify(label) for label in data.get("header", [])]
        for row_index, row in enumerate(data.get("rows", [])):
            for column_index, cell in enumerate(row):
                if not isinstance(cell, str) or not cell.strip():
                    continue
                column_kind = column_kinds[column_index] if column_index < len(column_kinds) else None
                if column_kind:
                    token = tokens.get(column_kind, "[REDACTED]")
                    if cell.strip() == token:
                        continue
                    add(f"row:{row_index},col:{column_index}", token, column_kind, cell)
                    counts[column_kind] = counts.get(column_kind, 0) + 1
                    continue
                if len(cell) < 4:
                    continue
                new_cell, cell_counts = redact(cell, index, tokens)
                if new_cell == cell:
                    continue
                add(f"row:{row_index},col:{column_index}", new_cell,
                    next(iter(cell_counts)), cell)
                for kind, value in cell_counts.items():
                    counts[kind] = counts.get(kind, 0) + value
        return edits, counts

    if fmt in {"json", "fhir"}:
        pending: list[tuple[str, str, str, str]] = []

        def collect(locator: str, value: str) -> None:
            key_kind = classify(key_from_locator(locator))
            if key_kind and is_institution(value):
                key_kind = None          # Organization.name is context, not a person
            if key_kind:
                token = tokens.get(key_kind, "[REDACTED]")
                if value.strip() != token:
                    pending.append((locator, token, key_kind, value))
                    counts[key_kind] = counts.get(key_kind, 0) + 1
                return
            new_value, value_counts = redact(value, index, tokens)
            if new_value == value:
                return
            pending.append((locator, new_value, next(iter(value_counts)), value))
            for kind, number in value_counts.items():
                counts[kind] = counts.get(kind, 0) + number

        _walk_json(data, "$", collect)
        for locator, new_value, kind, expected in pending:
            add(locator, new_value, kind, expected)
    return edits, counts


def annotate(ir: IntermediateRepresentation, index: ProtectionIndex) -> dict[str, list[Annotation]]:
    """Value-free annotation record for the report and the audit trail."""
    annotations: dict[str, list[Annotation]] = {}
    edits, _ = build_edits(ir, index, {kind: "" for kind in
                                       (PHONE, EMAIL, AADHAAR, PAN, ABHA, UHID, PIN, NAME, RELATIVE)})
    for locator, items in edits.items():
        annotations[locator] = [
            Annotation(annotation_id=item.edit_id, finding_type=item.technique,
                       locator=locator, detection_status=DetectionStatus.DETECTED,
                       detection_method="tier0+tier1")
            for item in items
        ]
    return annotations
