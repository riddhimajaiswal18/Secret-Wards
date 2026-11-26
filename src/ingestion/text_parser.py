"""Plain-text document representation."""
from __future__ import annotations

from src.ir import IntermediateRepresentation, build_json_ir


def parse_text_ir(text: str, *, document_id: str, filename: str,
                  encoding: str, bom: bool = False) -> IntermediateRepresentation:
    return build_json_ir(text, document_id=document_id, filename=filename, encoding=encoding,
                         source_format="text", arrangement="document",
                         original_layout={"bom": bom})
