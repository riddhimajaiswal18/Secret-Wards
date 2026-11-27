"""Typed, deterministic privacy transformations applied after identity assignment.

Dates use one secret-derived offset per pseudonym, so intervals and stay lengths survive while
the original calendar date does not. Age and locality values are generalized only inside records
that carry patient evidence. This module queues locator-guarded edits; it never edits the input
files or their authoritative parsed source values in place.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from src.detection.columns import classify
from src.ir import IntermediateRepresentation, PendingEdit, json_path
from src.normalization.dates import normalize_date
from src.privacy.linkage import _evidence, _record_at, _walk

_AGE_KEYS = {"age", "agesex", "patientage", "ageyears", "ageyrs", "ageyear"}
_AGE_VALUE = re.compile(
    r"^\s*(\d{1,3})(\s*(?:years?|yrs?|y/o|वर्ष|साल))?"
    r"(\s*(?:/|\s)\s*(?:m|f|male|female|other))?\s*$", re.IGNORECASE
)
_DATE_FIELDS = {
    "date", "visitdate", "admissiondate", "dischargedate", "encounterdate",
    "registrationdate", "regdate", "collectiondate", "recordeddate",
    "effectivedatetime", "performeddatetime", "authoredon", "timestamp",
    "lastupdated", "onsetdate", "issued",
}
_NON_PATIENT_CONTEXT = {
    "doctor", "practitioner", "provider", "consultant", "physician", "surgeon", "nurse",
    "hospital", "clinic", "organization", "organisation", "facility", "institution",
}
_DATE_TOKEN = re.compile(
    r"(?<!\d)(?:\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
    r"|\d{1,2}[./-]\d{1,2}[./-]\d{4})(?!\d)"
)
_EVENT_CONTEXT = re.compile(
    r"\b(?:date|admission|admitted|discharge|discharged|visit|encounter|consultation|"
    r"collected|collection|sampled|follow[- ]?up|reviewed|recorded|performed|issued)\b",
    re.IGNORECASE,
)
_BIRTH_CONTEXT = re.compile(r"\b(?:dob|birth|born)\b", re.IGNORECASE)
_PIN = re.compile(r"^\s*([0-9०-९]{3})[0-9०-९ -]{3,8}\s*$")
_LOCATION_KEYS = {"village", "village/mohalla", "mohalla", "locality"}
_DISTRICT_KEYS = {"district", "districtname", "jila", "zila"}


def _key_name(value: Any) -> str:
    return re.sub(r"[^a-z]", "", str(value).casefold())


def _age_band(value: Any, width: int, minor_policy: str, oldest_policy: str) -> str | None:
    if isinstance(value, bool):
        return None
    raw = str(value)
    match = _AGE_VALUE.fullmatch(raw)
    if not match:
        return None
    age = int(match.group(1))
    if age > 120:
        return None
    suffix = (match.group(2) or "") + (match.group(3) or "")
    if age < 18 and minor_policy == "0-17":
        band = "0-17"
    elif age >= 85 and oldest_policy == "85+":
        band = "85+"
    else:
        low = (age // max(1, width)) * max(1, width)
        band = f"{low}-{low + max(1, width) - 1}"
    if isinstance(value, str) and suffix:
        units = (match.group(2) or "").strip()
        gender = (match.group(3) or "").strip()
        band += (f" {units}" if units else "") + (f"/{gender.lstrip('/')}" if gender else "")
    return band


def _date_offset(secret: str, identity: str, max_days: int) -> int:
    span = max(1, int(max_days))
    digest = hmac.new(
        secret.encode("utf-8"), f"secret-wards/date-shift/v1|{identity}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    value = int.from_bytes(digest[:8], "big") % (2 * span)
    return value - span if value < span else value - span + 1


def _shift_date(value: str, offset: int, date_order: str) -> str | None:
    """Shift complete dates only and preserve the source's date/time suffix and style."""
    raw = value.strip()
    if not raw:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ].*)?", raw):
        normalized, status, _ = normalize_date(raw, date_order=date_order)
        if status != "success" or normalized is None:
            return None
        try:
            if "T" in normalized or re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:.*", normalized):
                parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
                shifted = parsed + timedelta(days=offset)
                result = shifted.isoformat().replace("+00:00", "Z")
                return result.replace("+00:00", "Z") if raw.endswith("Z") else result
            return (date.fromisoformat(normalized) + timedelta(days=offset)).isoformat()
        except ValueError:
            return None
    match = re.fullmatch(r"(\d{1,2})([./-])(\d{1,2})\2(\d{4})", raw)
    if not match:
        return None
    normalized, status, _ = normalize_date(raw, date_order=date_order)
    if status != "success" or normalized is None:
        return None
    try:
        shifted = date.fromisoformat(normalized) + timedelta(days=offset)
    except ValueError:
        return None
    return f"{shifted.day:02d}{match.group(2)}{shifted.month:02d}{match.group(2)}{shifted.year:04d}"


def _date_key(value: str, date_order: str) -> str | None:
    normalized, status, _ = normalize_date(value.strip(), date_order=date_order)
    return normalized[:10] if status == "success" and normalized else None


def prepare_date_offsets(
    input_root: str | Path,
    patient_by_file_locator: dict[tuple[str, str], str | None],
    secret: str | None,
    policy: dict[str, Any] | None = None,
) -> dict[str, int | None]:
    """Prepare one per-identity offset while avoiding collisions with any source DOB.

    The source values are read only into memory. This prevents a shifted visit date from
    accidentally becoming another patient's exact date of birth in the release.
    """
    if not secret:
        return {}
    config = policy or {}
    date_config = config.get("date_shifting") or {}
    max_days = int(date_config.get("max_days", 180))
    date_order = str(date_config.get("date_order", "DMY")).upper()
    if max_days <= 0:
        return {}

    from src.ingestion.file_router import parse_document_file
    from src.output.writer import iter_inputs, record_locators

    birth_dates: set[str] = set()
    events_by_identity: dict[str, set[str]] = defaultdict(set)

    for path, relative in iter_inputs(input_root):
        try:
            ir = parse_document_file(path)
        except Exception:
            continue
        if ir.validation.parse_status != "SUCCESS":
            continue
        fmt = ir.source.format
        for locator in record_locators(ir):
            node = _record_at(ir.structure.data, locator)
            token = patient_by_file_locator.get((relative, locator))
            evidence = _evidence(ir, locator)
            if not (token or any(evidence[name] for name in ("name", "phone", "dob"))):
                continue
            identity = token or f"record|{relative}|{locator}"
            if isinstance(node, str):
                for line in node.splitlines():
                    is_birth = bool(_BIRTH_CONTEXT.search(line))
                    if is_birth:
                        for match in _DATE_TOKEN.finditer(line):
                            key = _date_key(match.group(0), date_order)
                            if key:
                                birth_dates.add(key)
                    elif _EVENT_CONTEXT.search(line):
                        for match in _DATE_TOKEN.finditer(line):
                            key = _date_key(match.group(0), date_order)
                            if key:
                                events_by_identity[identity].add(key)
                continue
            for field_path, value in _walk(node):
                if not field_path or not isinstance(value, str):
                    continue
                context = {_key_name(part) for part in field_path}
                if context & {_key_name(part) for part in _NON_PATIENT_CONTEXT}:
                    continue
                key = field_path[-1]
                key_norm = _key_name(key)
                parsed = _date_key(value, date_order)
                if not parsed:
                    continue
                if classify(key) == "DOB" or "dob" in key_norm or "birth" in key_norm:
                    birth_dates.add(parsed)
                elif key_norm in _DATE_FIELDS:
                    events_by_identity[identity].add(parsed)

    offsets: dict[str, int | None] = {}
    for identity, event_dates in events_by_identity.items():
        initial = _date_offset(secret, identity, max_days)
        candidates = list(range(-max_days, max_days + 1))
        candidates.remove(0)
        candidates.sort(key=lambda value: (abs(value - initial), value))
        selected = None
        for offset in candidates:
            if all((date.fromisoformat(value) + timedelta(days=offset)).isoformat()
                   not in birth_dates for value in event_dates):
                selected = offset
                break
        if selected is not None:
            offsets[identity] = selected
        else:
            # An unusually dense birth-date calendar leaves no safe shift in the policy window.
            # The caller must suppress those exact dates instead of falling back to a collision.
            offsets[identity] = None
    return offsets


def _json_pointer(parent: str, key: str | int) -> str:
    escaped = str(key).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}"


def _existing(ir: IntermediateRepresentation, locator: str) -> list[PendingEdit]:
    return ir.pending_edits.setdefault(locator, [])


def apply_privacy_transforms(
    ir: IntermediateRepresentation,
    *,
    file_relative: str,
    patient_by_locator: dict[str, str | None],
    secret: str | None,
    policy: dict[str, Any] | None = None,
    date_offsets: dict[str, int | None] | None = None,
) -> dict[str, int]:
    """Queue age, date, village and PIN generalizations. Return value-free counts."""
    if ir.validation.parse_status != "SUCCESS":
        return {"records_generalized": 0, "fields_generalized": 0, "dates_shifted": 0}
    config = policy or {}
    age_config = config.get("age_bands") or {}
    loc_config = config.get("location_generalization") or {}
    date_config = config.get("date_shifting") or {}
    width = int(age_config.get("width_years", 5))
    minor_policy = str(age_config.get("minor_policy", "0-17"))
    oldest_policy = str(age_config.get("oldest_age_policy", "85+"))
    target_level = str(loc_config.get("default_level", "district")).casefold()
    max_days = int(date_config.get("max_days", 180))
    date_order = str(date_config.get("date_order", "DMY")).upper()

    edits_by_record: dict[str, int] = defaultdict(int)
    evidence_by_record: dict[str, dict[str, Any]] = {}
    fields_generalized = 0
    dates_shifted = 0
    edit_counter = 0

    def queue(locator: str, expected: Any, replacement: Any, technique: str,
              record_locator: str) -> None:
        nonlocal edit_counter, fields_generalized
        if expected == replacement:
            return
        existing = _existing(ir, locator)
        if existing:
            # The detector may already have proposed a token for a village or PIN. The more
            # informative privacy transform safely supersedes that edit at the same locator.
            edit = existing[0]
            edit.replacement = replacement
            edit.technique = technique
        else:
            edit_counter += 1
            edit = PendingEdit(edit_id=f"p{edit_counter:05d}", locator=locator,
                               replacement=replacement, expected_value=expected,
                               technique=technique)
            ir.pending_edits.setdefault(locator, []).append(edit)
        edits_by_record[record_locator] += 1
        fields_generalized += 1

    def transform_value(
        *, value: Any, key: str, locator: str, sibling: dict[str, Any],
        record_locator: str, patient_token: str | None, text_context: str = "",
        text_span: tuple[int, int] | None = None, context: tuple[str, ...] = (),
    ) -> None:
        nonlocal dates_shifted
        key_norm = _key_name(key)
        if record_locator not in evidence_by_record:
            evidence_by_record[record_locator] = _evidence(ir, record_locator)
        evidence = evidence_by_record[record_locator]
        direct = bool(patient_token)
        has_patient = direct or any(evidence[name] for name in ("name", "phone", "dob"))
        if (not has_patient or
                any(_key_name(part) in _NON_PATIENT_CONTEXT for part in context)):
            return

        if key_norm in _AGE_KEYS:
            band = _age_band(value, width, minor_policy, oldest_policy)
            if band is not None:
                queue(locator, value, band, "generalize_age", record_locator)

        if target_level == "district" and (
                key.casefold() in _LOCATION_KEYS or classify(key) == "VILLAGE"):
            district = next((candidate for name, candidate in sibling.items()
                             if _key_name(name) in _DISTRICT_KEYS and isinstance(candidate, str)
                             and candidate.strip()), None)
            replacement = district.strip() if district else "[LOCATION]"
            if value != replacement:
                queue(locator, value, replacement, "generalize_to_district", record_locator)

        if classify(key) == "PIN" and isinstance(value, str):
            pin = _PIN.fullmatch(value)
            if pin:
                replacement = f"{pin.group(1)}***"
                if replacement != value:
                    queue(locator, value, replacement, "generalize_pin_prefix", record_locator)

        if (key_norm not in _DATE_FIELDS or "dob" in key_norm or "birth" in key_norm
                or not isinstance(value, str) or secret is None or max_days <= 0):
            return
        identity = patient_token or f"record|{file_relative}|{record_locator}"
        if date_offsets is not None and identity in date_offsets:
            offset = date_offsets[identity]
            shifted = ("[DATE]" if offset is None else _shift_date(value, offset, date_order))
        else:
            offset = _date_offset(secret, identity, max_days)
            shifted = _shift_date(value, offset, date_order)
        if shifted is not None and shifted != value:
            queue(locator, value, shifted, "date_shift_per_patient", record_locator)
            dates_shifted += 1

    fmt = ir.source.format
    data = ir.structure.data
    if fmt in {"csv", "tsv"} and isinstance(data, dict):
        headers = data.get("header") or []
        for row_index, row in enumerate(data.get("rows") or []):
            record_locator = f"row:{row_index}"
            token = patient_by_locator.get(record_locator)
            siblings = {str(name): value for name, value in zip(headers, row)}
            for column, value in enumerate(row):
                if not isinstance(value, str):
                    continue
                header = str(headers[column]) if column < len(headers) else ""
                transform_value(value=value, key=header,
                                locator=f"row:{row_index},col:{column}", sibling=siblings,
                                record_locator=record_locator, patient_token=token,
                                context=(header,))

    elif fmt in {"json", "fhir"} and isinstance(data, (dict, list)):
        from src.output.writer import record_locators
        tokens = {locator: patient_by_locator.get(locator) for locator in record_locators(ir)}
        token_by_pointer = {
            locator: tokens.get(locator)
            for locator in tokens if locator.startswith("/")
        }
        if "doc" in tokens:
            token_by_pointer[""] = tokens["doc"]

        def walk(node: Any, path: str, pointer: str, ancestors: tuple[str, ...],
                 record_locator: str, patient_token: str | None) -> None:
            if pointer in token_by_pointer:
                record_locator = pointer
                patient_token = token_by_pointer[pointer]
            if record_locator == "doc":
                record_locator = "doc"
            if isinstance(node, dict):
                for key, value in node.items():
                    child_path = json_path(path, str(key))
                    child_pointer = _json_pointer(pointer, str(key))
                    child_context = ancestors + (str(key),)
                    transform_value(value=value, key=str(key), locator=child_path,
                                    sibling=node, record_locator=record_locator,
                                    patient_token=patient_token, context=child_context)
                    walk(value, child_path, child_pointer, child_context,
                         record_locator, patient_token)
            elif isinstance(node, list):
                for position, value in enumerate(node):
                    walk(value, json_path(path, position), _json_pointer(pointer, position),
                         ancestors, record_locator, patient_token)

        walk(data, "$", "", (), "doc", patient_by_locator.get("doc"))

    elif fmt == "text" and isinstance(data, str):
        record_locator = next(iter(patient_by_locator), "span:0:0")
        patient_token = patient_by_locator.get(record_locator)
        evidence = _evidence(ir, record_locator)
        if patient_token or any(evidence[name] for name in ("name", "phone", "dob")):
            for line_match in re.finditer(r"(?m)^.*$", data):
                line = line_match.group(0)
                if _EVENT_CONTEXT.search(line) and not _BIRTH_CONTEXT.search(line):
                    for match in _DATE_TOKEN.finditer(line):
                        start = line_match.start() + match.start()
                        end = line_match.start() + match.end()
                        identity = patient_token or f"record|{file_relative}|{record_locator}"
                        if secret is None or max_days <= 0:
                            continue
                        if date_offsets is not None and identity in date_offsets:
                            offset = date_offsets[identity]
                            shifted = ("[DATE]" if offset is None else
                                       _shift_date(match.group(0), offset, date_order))
                        else:
                            offset = _date_offset(secret, identity, max_days)
                            shifted = _shift_date(match.group(0), offset, date_order)
                        if shifted is not None and shifted != match.group(0):
                            queue(f"span:{start}:{end}", match.group(0), shifted,
                                  "date_shift_per_patient", record_locator)
                            dates_shifted += 1
                age_match = re.search(
                    r"(?i)\b(?:age(?:/sex)?|umar)\s*[:=\-]?\s*"
                    r"(\d{1,3}(?:\s*(?:years?|yrs?|y/o|वर्ष|साल))?"
                    r"(?:\s*(?:/|\s)\s*(?:m|f|male|female|other))?)", line)
                if age_match:
                    original = age_match.group(1)
                    band = _age_band(original, width, minor_policy, oldest_policy)
                    if band is not None:
                        start = line_match.start() + age_match.start(1)
                        end = line_match.start() + age_match.end(1)
                        queue(f"span:{start}:{end}", original, band,
                              "generalize_age", record_locator)

    return {
        "records_generalized": len(edits_by_record),
        "fields_generalized": fields_generalized,
        "dates_shifted": dates_shifted,
    }
