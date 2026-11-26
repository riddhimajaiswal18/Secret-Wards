"""Format routing to the shared document IR; unsupported inputs are explicit parse errors."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from src.ir import (FieldRecord, IntermediateRepresentation, PresenceStatus,
                    SourceMetadata, SourceStructure, ValidationResult, build_json_ir)
from src.ingestion.csv_tsv import parse_delimited_ir
from src.ingestion.encoding import DecodeError, decode_bytes
from src.ingestion.fhir_parser import parse_fhir_ir
from src.ingestion.ir_json import parse_json_ir
from src.ingestion.text_parser import parse_text_ir


def _xml_node(element: ET.Element) -> dict[str, Any]:
    """Represent XML without collapsing repeated child tags or their order."""
    return {
        "tag": element.tag,
        "attributes": [[key, value] for key, value in element.attrib.items()],
        "text": element.text,
        "children": [_xml_node(child) for child in list(element)],
        "tail": element.tail,
    }


def _parse_xml(text: str, *, document_id: str, filename: str,
               encoding: str) -> IntermediateRepresentation:
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("xml_dtd_or_entity_forbidden") from None
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, RecursionError, ValueError):
        raise ValueError("malformed_xml") from None
    data = _xml_node(root)
    ir = build_json_ir(data, document_id=document_id, filename=filename, encoding=encoding,
                       source_format="xml", arrangement="ordered_xml_tree")
    return ir


def _parse_error(document_id: str, filename: str, source_format: str,
                 reason: str) -> IntermediateRepresentation:
    return IntermediateRepresentation(
        document_id=document_id,
        source=SourceMetadata(format=source_format, original_filename=filename),
        structure=SourceStructure(root_type="null", original_layout={}, data=None),
        fields=[FieldRecord(field_id="f_000001", field_name="root", field_path="$",
                            field_kind="leaf", expected_dtype=None, actual_dtype=None,
                            presence_status=PresenceStatus.PARSE_ERROR)],
        validation=ValidationResult(parse_status=f"ERROR:{reason}", privacy_validation="NOT_EVALUATED",
                                    serialization_status="NOT_STARTED"),
    )


def parse_document_file(path: str | Path) -> IntermediateRepresentation:
    source_path = Path(path)
    suffix = source_path.suffix.lower()
    document_id = source_path.stem
    if suffix not in {".csv", ".tsv", ".json", ".txt", ".xml"}:
        return _parse_error(document_id, source_path.name, suffix.lstrip(".") or "unknown",
                            "unsupported_format")
    try:
        raw = source_path.read_bytes()
        if not raw:
            return _parse_error(document_id, source_path.name, suffix[1:], "empty_file")
        text, encoding = decode_bytes(raw)
    except FileNotFoundError:
        return _parse_error(document_id, source_path.name, suffix[1:], "input_not_found")
    except OSError:
        return _parse_error(document_id, source_path.name, suffix[1:], "input_read_error")
    except DecodeError:
        return _parse_error(document_id, source_path.name, suffix[1:], "unsupported_encoding")

    try:
        if suffix == ".csv":
            # The kit contains a JSON export mislabeled as CSV; content wins over suffix.
            if text.lstrip().startswith(("{", "[")):
                return _json_or_fhir(text, document_id, source_path.name, encoding)
            return parse_delimited_ir(text, document_id=document_id, filename=source_path.name,
                                      encoding=encoding, delimiter=",")
        if suffix == ".tsv":
            return parse_delimited_ir(text, document_id=document_id, filename=source_path.name,
                                      encoding=encoding, delimiter="\t")
        if suffix == ".txt":
            return parse_text_ir(text, document_id=document_id, filename=source_path.name,
                                 encoding=encoding)
        if suffix == ".xml":
            return _parse_xml(text, document_id=document_id, filename=source_path.name,
                              encoding=encoding)
        return _json_or_fhir(text, document_id, source_path.name, encoding)
    except (ValueError, RecursionError):
        return _parse_error(document_id, source_path.name, suffix[1:], "malformed_or_unsupported_content")


def _json_or_fhir(text: str, document_id: str, filename: str,
                  encoding: str) -> IntermediateRepresentation:
    try:
        obj: Any = json.loads(text)
    except (ValueError, RecursionError):
        raise ValueError("malformed_json") from None
    if isinstance(obj, dict) and obj.get("resourceType") == "Bundle":
        return parse_fhir_ir(text, document_id=document_id, filename=filename, encoding=encoding)
    return build_json_ir(obj, document_id=document_id, filename=filename, encoding=encoding,
                         source_format="json")
