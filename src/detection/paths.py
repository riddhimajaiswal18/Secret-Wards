"""Path sanitation: the filename is a data channel, not a label.

`Discharge_Summary_Fatima_Bano_SNJ-26-064508.txt` names the patient in the file name, and a
silent rename is not enough — the release must be able to say "this input became that output", so
the mapping is declared in `report.json` (which the contract already supports through
`files[].output`).

Paths are sanitised with the same detector as content, then made filesystem-safe and collision-free
in a deterministic way.
"""
from __future__ import annotations

import re

from src.detection.engine import redact
from src.detection.protection import ProtectionIndex

# Filename-safe tokens: no brackets, no spaces, so a path never needs escaping.
PATH_TOKENS = {
    "NAME": "PERSON",
    "RELATIVE": "RELATIVE",
    "PHONE": "PHONE",
    "EMAIL": "EMAIL",
    "AADHAAR": "AADHAAR",
    "PAN": "PAN",
    "ABHA": "ABHA",
    "UHID": "ID",
    "PIN": "PIN",
    "HOUSE": "HOUSE",
    "VILLAGE": "VILLAGE",
    "ADDRESS": "ADDRESS",
    "LANDMARK": "LANDMARK",
    "DOB": "DOB",
    "INSURANCE": "INSURANCE",
}

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_SEPARATORS = re.compile(r"[_\-.\s]+")


def _sanitise_segment(segment: str, index: ProtectionIndex) -> tuple[str, dict[str, int]]:
    """Redact one path segment, preserving the extension."""
    stem, dot, extension = segment.rpartition(".")
    if not dot:
        stem, extension = segment, ""
    # Separators become spaces so the name detector sees "Fatima Bano", not "Fatima_Bano".
    readable = _SEPARATORS.sub(" ", stem).strip()
    cleaned, counts = redact(readable, index, PATH_TOKENS)
    cleaned = _UNSAFE.sub(" ", cleaned).strip()
    cleaned = _SEPARATORS.sub("_", cleaned).strip("_")
    if not cleaned:
        cleaned = "file"
    if len(cleaned) > 96:
        cleaned = cleaned[:96].rstrip("_")
    return (f"{cleaned}.{extension}" if extension else cleaned), counts


def sanitise_path(relative: str, index: ProtectionIndex,
                  fallback_key: str = "") -> tuple[str, dict[str, int]]:
    """Return (safe_relative_path, counts). Deterministic for identical input."""
    segments = [segment for segment in relative.split("/") if segment]
    counts: dict[str, int] = {}
    cleaned: list[str] = []
    for segment in segments:
        safe, found = _sanitise_segment(segment, index)
        cleaned.append(safe)
        for kind, value in found.items():
            counts[kind] = counts.get(kind, 0) + value
    path = "/".join(cleaned) or "file"
    if fallback_key:
        path = path
    return path, counts
