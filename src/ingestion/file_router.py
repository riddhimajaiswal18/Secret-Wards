"""Format routing to the shared document IR; unsupported inputs are explicit parse errors."""
from __future__ import annotations

import json
import csv
from pathlib import Path
from typing import Any

from src.ir import (MAX_FILE_MB, IntermediateRepresentation, ProcessingStatus, SourceMetadata,
                    SourceStructure, ValidationResult)
from src.ingestion.csv_tsv import parse_delimited_ir
from src.ingestion.encoding import DecodeError, decode_bytes
from src.ingestion.fhir_parser import parse_fhir_ir
from src.ingestion.ir_json import json_layout, parse_json_ir
from src.ingestion.text_parser import parse_text_ir

_REASONS = {
    "non_finite_number": "non_finite_number",
    "depth_limit_exceeded": "depth_limit_exceeded",
    "malformed_json": "malformed_json",
    "malformed_fhir_json": "malformed_fhir_json",
    "invalid_fhir_bundle_structure": "invalid_fhir_bundle",
    "invalid_fhir_bundle_entry": "invalid_fhir_bundle",
    "not_fhir_bundle": "not_fhir_bundle",
    "xml_dtd_or_entity_forbidden": "xml_entity_forbidden",
    "malformed_xml": "malformed_xml",
    "malformed_delimited_file": "malformed_delimited_file",
}


def _reason(exc: Exception) -> str:
    """Pass a parser's own code through verbatim; unknown text becomes a generic bucket.

    `parse_status` is a parser-level fact (depth_limit_exceeded); the release vocabulary
    (excessive_depth) is applied later, in the report layer, by normalise_reason().
    """
    code = str(exc)
    return code if code in _REASONS else "malformed_or_unsupported_content"
from src.ingestion.xml_parser import parse_xml_ir


def _parse_error(document_id: str, filename: str, source_format: str,
                 reason: str) -> IntermediateRepresentation:
    return IntermediateRepresentation(
        document_id=document_id,
        source=SourceMetadata(format=source_format, original_filename=filename),
        structure=SourceStructure(root_type="null", original_layout={}, data=None),
        validation=ValidationResult(parse_status=f"ERROR:{reason}", privacy_validation="NOT_EVALUATED",
                                    serialization_status="NOT_STARTED"),
        processing_status=ProcessingStatus.QUARANTINED,
        errors=[reason],
    )


def parse_document_file(path: str | Path, *, document_id: str | None = None,
                        source_identity: str | None = None) -> IntermediateRepresentation:
    source_path = Path(path)
    suffix = source_path.suffix.lower()
    document_id = document_id or source_path.stem
    def finish(ir: IntermediateRepresentation) -> IntermediateRepresentation:
        ir.source.source_identity = source_identity
        return ir
    if suffix not in {".csv", ".tsv", ".json", ".txt", ".xml"}:
        return finish(_parse_error(document_id, source_path.name, suffix.lstrip(".") or "unknown",
                                   "unsupported_format"))
    try:
        raw = source_path.read_bytes()
        if len(raw) > MAX_FILE_MB * 1024 * 1024:
            return _parse_error(document_id, source_path.name, suffix[1:], "too-large")
        if not raw:
            return finish(_parse_error(document_id, source_path.name, suffix[1:], "empty_file"))
        text, encoding = decode_bytes(raw)
        bom = raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"))
    except FileNotFoundError:
        return finish(_parse_error(document_id, source_path.name, suffix[1:], "input_not_found"))
    except OSError:
        return finish(_parse_error(document_id, source_path.name, suffix[1:], "input_read_error"))
    except DecodeError:
        return finish(_parse_error(document_id, source_path.name, suffix[1:], "unsupported_encoding"))

    try:
        if suffix == ".csv":
            # The kit contains a JSON export mislabeled as CSV; content wins over suffix.
            if text.lstrip().startswith(("{", "[")):
                return finish(_json_or_fhir(text, document_id, source_path.name, encoding, bom=bom))
            delimiter = _sniff_delimiter(text)
            return finish(parse_delimited_ir(text, document_id=document_id, filename=source_path.name,
                                             encoding=encoding, delimiter=delimiter, bom=bom))
        if suffix == ".tsv":
            return finish(parse_delimited_ir(text, document_id=document_id, filename=source_path.name,
                                             encoding=encoding, delimiter="\t", bom=bom))
        if suffix == ".txt":
            return finish(parse_text_ir(text, document_id=document_id, filename=source_path.name,
                                        encoding=encoding, bom=bom))
        if suffix == ".xml":
            return finish(parse_xml_ir(text, document_id=document_id, filename=source_path.name,
                                       encoding=encoding, bom=bom))
        return finish(_json_or_fhir(text, document_id, source_path.name, encoding, bom=bom))
    except (ValueError, RecursionError) as exc:
        reason = _reason(exc)
        return finish(_parse_error(document_id, source_path.name, suffix[1:], reason))


def _check_nesting(text: str, limit: int = 512) -> None:
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > limit:
                raise ValueError("depth_limit_exceeded") from None
        elif char in "]}":
            depth = max(0, depth - 1)


def _sniff_delimiter(text: str) -> str:
    """Count candidate separators outside CSV-quoted cells, with stable tie-breaking."""
    counts = {candidate: 0 for candidate in (",", ";", "|", "\t")}
    sample = text[:65536]
    quoted = False
    i = 0
    while i < len(sample):
        char = sample[i]
        if quoted:
            if char == '"' and i + 1 < len(sample) and sample[i + 1] == '"':
                i += 2
                continue
            if char == '"':
                quoted = False
            i += 1
            continue
        if char == '"':
            quoted = True
        elif char in counts:
            counts[char] += 1
        i += 1
    best = max(counts, key=lambda candidate: (counts[candidate], candidate == ","))
    return best if counts[best] else ","


def _json_or_fhir(text: str, document_id: str, filename: str,
                  encoding: str, bom: bool = False) -> IntermediateRepresentation:
    try:
        _check_nesting(text)
        obj: Any = json.loads(text)
    except (ValueError, RecursionError):
        if _exceeds_json_depth(text):
            raise ValueError("depth_limit_exceeded") from None
        raise ValueError("malformed_json") from None
    if isinstance(obj, dict) and obj.get("resourceType") == "Bundle":
        return parse_fhir_ir(text, document_id=document_id, filename=filename, encoding=encoding, bom=bom)
    return parse_json_ir(text, document_id=document_id, filename=filename, encoding=encoding, bom=bom)


def _exceeds_json_depth(text: str, limit: int = 512) -> bool:
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > limit:
                return True
        elif char in "]}":
            depth = max(0, depth - 1)
    return False
