"""FHIR JSON Bundle detection and conservative structural validation."""
from __future__ import annotations

import json
from typing import Any

from src.ir import IntermediateRepresentation, build_json_ir
from src.ingestion.ir_json import json_layout


def parse_fhir_ir(text: str, *, document_id: str, filename: str,
                  encoding: str, bom: bool = False) -> IntermediateRepresentation:
    try:
        value: Any = json.loads(text)
    except (ValueError, RecursionError):
        raise ValueError("malformed_fhir_json") from None
    if not isinstance(value, dict) or value.get("resourceType") != "Bundle":
        raise ValueError("not_fhir_bundle") from None
    if not isinstance(value.get("type"), str) or not isinstance(value.get("entry", []), list):
        raise ValueError("invalid_fhir_bundle_structure") from None
    for entry in value.get("entry", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict):
            raise ValueError("invalid_fhir_bundle_entry") from None
    return build_json_ir(value, document_id=document_id, filename=filename, encoding=encoding,
                         source_format="fhir", arrangement="FHIR_R4_bundle",
                         original_layout=json_layout(text, bom))
