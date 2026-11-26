"""Quarantine policy: every file has exactly one fate, and every reason is a stable enum."""
from __future__ import annotations

from enum import Enum


class QuarantineReason(str, Enum):
    UNSUPPORTED_FORMAT = "unsupported_format"
    BINARY_PDF = "binary-pdf"
    BINARY_IMAGE = "binary-image"
    BINARY_ARCHIVE = "binary-archive"
    NOT_TEXT = "not-text"
    EMPTY = "empty"
    TOO_LARGE = "too-large"
    EXCESSIVE_DEPTH = "excessive_depth"
    MALFORMED_JSON = "malformed_json"
    NON_FINITE_NUMBER = "non_finite_number"
    DUPLICATE_KEYS = "duplicate_keys"
    MALFORMED_XML = "malformed_xml"
    XML_ENTITY_FORBIDDEN = "xml_entity_forbidden"
    MALFORMED_DELIMITED = "malformed_delimited_file"
    UNSUPPORTED_ENCODING = "unsupported_encoding"
    EDIT_FAILED = "transformation_failed"
    UNREADABLE = "unreadable"
    UNPARSED = "unparsed"


_MAGIC = ((b"%PDF", QuarantineReason.BINARY_PDF),
          (b"\x89PNG", QuarantineReason.BINARY_IMAGE),
          (b"\xff\xd8\xff", QuarantineReason.BINARY_IMAGE),
          (b"PK\x03\x04", QuarantineReason.BINARY_ARCHIVE),
          (b"\x1f\x8b", QuarantineReason.BINARY_ARCHIVE),
          (b"II*\x00", QuarantineReason.BINARY_IMAGE),
          (b"MM\x00*", QuarantineReason.BINARY_IMAGE),
          (b"\xd0\xcf\x11\xe0", QuarantineReason.BINARY_ARCHIVE))


def binary_reason(raw: bytes) -> QuarantineReason | None:
    """Magic-byte detection: a binary container is quarantined whatever its extension says."""
    head = raw[:512]
    for magic, reason in _MAGIC:
        if head.startswith(magic):
            return reason
    if len(raw) > 132 and raw[128:132] == b"DICM":
        return QuarantineReason.BINARY_IMAGE
    return None


_ALIASES = {
    "empty_file": "empty",
    "not_text": "not-text",
    "too_large": "too-large",
    "input_not_found": "unreadable",
    "input_read_error": "unreadable",
    "depth_limit_exceeded": "excessive_depth",
    "xml_depth_limit_exceeded": "excessive_depth",
    "malformed_or_unsupported_content": "unparsed",
    "not_fhir_bundle": "unsupported_format",
    "invalid_fhir_bundle": "malformed_json",
    "xml_entity_forbidden": "xml_entity_forbidden",
    "unsupported_encoding": "unsupported_encoding",
}


def normalise_reason(raw: str) -> str:
    """Fold parser text into the enum vocabulary; unknown values become `unparsed`."""
    cleaned = raw.replace("ERROR:", "").strip().lower().replace(" ", "_")
    if cleaned in _ALIASES:
        return _ALIASES[cleaned]
    return cleaned if cleaned in {r.value for r in QuarantineReason} else QuarantineReason.UNPARSED.value
