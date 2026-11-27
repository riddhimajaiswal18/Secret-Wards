"""Conservative, deterministic record linkage for one release run.

Strong record identifiers remain the primary signal. When different facilities issue different
identifiers, an exact patient-name and phone pair can connect records if the available sex and
date-of-birth evidence does not conflict. Name-only and phone-only matching are intentionally
unsupported. Candidate values stay in process memory and only keyed pseudonyms leave this module.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.detection.columns import classify
from src.detection import identifiers as ids
from src.ingestion.file_router import parse_document_file
from src.privacy.pseudonyms import pseudonym_for, pseudonym_for_locator, secret_from_environment

_PERSON_CONTEXT = {
    "doctor", "practitioner", "provider", "consultant", "physician", "hospital", "clinic",
    "organization", "organisation", "facility", "institution", "relative", "guardian",
    "attendant", "father", "mother", "spouse", "husband", "wife", "son", "daughter",
    "nextofkin",
}
_NAME_PARTS = {"first", "last", "given", "family", "middle"}
_HONORIFICS = {
    "amma", "babu", "bhai", "bhaiya", "ben", "behen", "behenji", "didi", "ji",
    "sahab", "sahib",
}
_TEXT_PATIENT_NAME = re.compile(
    r"(?im)^\s*(?:patient\s*name|name\s*of\s*patient|pt\.?\s*name|patient|name|"
    r"patient\s*ka\s*(?:naam|name)|naam)\s*[:=\-]\s*([^\r\n;]+)"
)
_TEXT_DOB = re.compile(
    r"(?i)(?:\bdob\b|date\s+of\s+birth|birth\s+date)\s*[:=\-]\s*"
    r"(\d{1,4}[./-]\d{1,2}[./-]\d{1,4})"
)


def _normal_name(value: str) -> str | None:
    value = value.strip().casefold()
    tokens = re.findall(r"[a-z\u0900-\u097f]+", value)
    while tokens and tokens[0] in {"patient", "name", "mr", "mrs", "ms", "श्री", "श्रीमती"}:
        tokens.pop(0)
    while tokens and tokens[-1] in _HONORIFICS:
        tokens.pop()
    if len(tokens) < 2 or any(len(token) < 2 for token in tokens):
        return None
    return " ".join(tokens[:4])


def _normal_phone(value: str) -> set[str]:
    values: set[str] = set()
    for match in ids._PHONE.finditer(ids.fold_digits(value)):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) >= 10:
            values.add(digits[-10:])
    return values


def _normal_date(value: str) -> str | None:
    match = re.fullmatch(r"\s*(\d{1,4})[./-](\d{1,2})[./-](\d{1,4})\s*", value)
    if not match:
        return None
    a, b, c = (int(part) for part in match.groups())
    if a > 31:  # ISO year first
        year, month, day = a, b, c
    else:
        day, month, year = a, b, c
    if not (1 <= day <= 31 and 1 <= month <= 12 and 1 <= year <= 9999):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _record_at(data: Any, locator: str) -> Any:
    if locator.startswith("row:") and isinstance(data, dict):
        try:
            index = int(locator.split(":", 1)[1])
            header, rows = data.get("header") or [], data.get("rows") or []
            row = rows[index]
            return {str(name): value for name, value in zip(header, row)}
        except (IndexError, TypeError, ValueError):
            return None
    if locator.startswith("/") and isinstance(data, (dict, list)):
        node = data
        try:
            for part in locator.split("/")[1:]:
                part = part.replace("~1", "/").replace("~0", "~")
                node = node[int(part)] if isinstance(node, list) else node[part]
            return node
        except (KeyError, IndexError, TypeError, ValueError):
            return None
    return data


def _walk(node: Any, path: tuple[str, ...] = ()):
    if isinstance(node, dict):
        for key, child in node.items():
            yield from _walk(child, path + (str(key),))
    elif isinstance(node, list):
        for child in node:
            yield from _walk(child, path)
    elif isinstance(node, str):
        yield path, node


def _evidence(ir: Any, locator: str) -> dict[str, Any]:
    """Extract record-scoped, value-minimized evidence from the common IR."""
    node = _record_at(ir.structure.data, locator)
    result: dict[str, Any] = {
        "name": set(), "phone": set(), "dob": set(), "sex": set(),
    }
    if isinstance(node, str):
        for match in _TEXT_PATIENT_NAME.finditer(node):
            value = match.group(1)
            value = re.split(
                r"(?i)\s+(?:age(?:/sex)?|sex|dob|date\s+of\s+birth|uhid|mrn|mobile|phone)\b"
                r"|\s*,\s*(?:age|sex|dob|uhid|mrn|mobile|phone)\b", value, maxsplit=1)[0]
            normalized = _normal_name(value)
            if normalized:
                result["name"].add(normalized)
        for match in _TEXT_DOB.finditer(node):
            normalized = _normal_date(match.group(1))
            if normalized:
                result["dob"].add(normalized)
        # Only explicitly labelled contact numbers participate; arbitrary clinical digits do not.
        for line in node.splitlines():
            if (re.search(r"(?i)\b(?:mobile|mob|phone|contact|telephone|tel)\b", line)
                    and not re.search(r"(?i)\b(?:attendant|guardian|relative|father|mother|spouse)\b",
                                      line)):
                result["phone"].update(_normal_phone(line))
        return result

    # Capture full names by person-role context. Split given/family names are composed only inside
    # the same parent object, never across sibling people or records.
    fragments: dict[str, dict[str, str]] = defaultdict(dict)
    for path, value in _walk(node):
        if not path or not value.strip():
            continue
        key = path[-1]
        context = {part.casefold().replace("_", "") for part in path}
        kind = classify(key)
        if kind == "NAME" and not context & _PERSON_CONTEXT:
            normalized = _normal_name(value)
            if normalized:
                result["name"].add(normalized)
        elif key.casefold().replace("_", "") in _NAME_PARTS:
            if not context & _PERSON_CONTEXT:
                fragments["/".join(path[:-1])][key.casefold().replace("_", "")] = value
        elif kind == "PHONE" and not context & _PERSON_CONTEXT:
            result["phone"].update(_normal_phone(value))
        elif kind == "DOB":
            normalized = _normal_date(value)
            if normalized:
                result["dob"].add(normalized)
        elif key.casefold() in {"sex", "gender"}:
            normalized = value.strip().casefold()
            if normalized in {"m", "male", "f", "female", "other", "unknown"}:
                result["sex"].add(normalized[0])
    for pieces in fragments.values():
        given = pieces.get("first") or pieces.get("given")
        family = pieces.get("last") or pieces.get("family")
        if given and family:
            normalized = _normal_name(f"{given} {family}")
            if normalized:
                result["name"].add(normalized)
    return result


def build_assignments(input_root: str | Path, secret: str | None = None) -> dict[tuple[str, str], str | None]:
    """Return release-run pseudonyms indexed by (input relative path, record locator).

    Records with the same direct identifier retain their current token. A unique exact
    name-and-phone pair may connect different identifier tokens, subject to conflict checks.
    """
    secret = secret or secret_from_environment()
    if not secret:
        return {}

    # Imported lazily to avoid the writer/linkage dependency cycle at module import time.
    from src.output.writer import iter_inputs, record_locators

    records: list[dict[str, Any]] = []
    for path, relative in iter_inputs(input_root):
        try:
            ir = parse_document_file(path)
        except Exception:
            continue
        if ir.validation.parse_status != "SUCCESS":
            continue
        for locator in record_locators(ir):
            records.append({
                "key": (relative, locator),
                "direct": pseudonym_for_locator(ir, locator, secret),
                "evidence": _evidence(ir, locator),
            })

    parent = list(range(len(records)))
    component_members: list[set[int]] = [{index} for index in range(len(records))]

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def compatible(left: int, right: int) -> bool:
        a, b = records[left]["evidence"], records[right]["evidence"]
        for field in ("sex", "dob"):
            av, bv = a[field], b[field]
            if av and bv and av.isdisjoint(bv):
                return False
        return True

    def union(left: int, right: int) -> bool:
        a, b = find(left), find(right)
        if a == b:
            return True
        if any(not compatible(i, j) for i in component_members[a]
               for j in component_members[b]):
            return False
        if len(component_members[a]) < len(component_members[b]):
            a, b = b, a
        parent[b] = a
        component_members[a].update(component_members[b])
        component_members[b].clear()
        return True

    by_direct: dict[str, list[int]] = defaultdict(list)
    by_composite: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        if record["direct"]:
            by_direct[record["direct"]].append(index)
        evidence = record["evidence"]
        # More than one candidate means the record cannot safely identify which pair is its owner.
        if len(evidence["name"]) == 1 and len(evidence["phone"]) == 1:
            by_composite[(next(iter(evidence["name"])),
                          next(iter(evidence["phone"])))].append(index)

    for members in by_direct.values():
        for index in members[1:]:
            union(members[0], index)
    for members in by_composite.values():
        for left_position, left in enumerate(members):
            for right in members[left_position + 1:]:
                union(left, right)

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        groups[find(index)].append(index)
    assignments: dict[tuple[str, str], str | None] = {}
    for members in groups.values():
        direct_tokens = sorted({records[i]["direct"] for i in members if records[i]["direct"]})
        composite_keys = sorted({
            (next(iter(records[i]["evidence"]["name"])),
             next(iter(records[i]["evidence"]["phone"])))
            for i in members
            if len(records[i]["evidence"]["name"]) == 1
            and len(records[i]["evidence"]["phone"]) == 1
        })
        if len(direct_tokens) == 1:
            token = direct_tokens[0]
        elif composite_keys:
            name, phone = composite_keys[0]
            token = pseudonym_for(secret, f"linkage|name-phone|{name}|{phone}")
        else:
            token = None
        for index in members:
            assignments[records[index]["key"]] = token
    return assignments
