"""Safe JSON decoding and IR construction; exceptions never include source text."""
from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path
from typing import Any

from src.ir import IntermediateRepresentation, build_json_ir


class JSONIRParseError(ValueError):
    """Sanitized parse failure that does not carry raw patient content."""


def _check_depth(text: str, limit: int = 512) -> None:
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
                raise JSONIRParseError("JSON input exceeds supported nesting depth") from None
        elif char in "]}":
            depth = max(0, depth - 1)


def parse_json_ir(text: str, *, document_id: str, filename: str | None = None,
                  encoding: str = "utf-8", bom: bool = False) -> IntermediateRepresentation:
    _check_depth(text)
    try:
        value: Any = json.loads(text)
    except (json.JSONDecodeError, RecursionError, ValueError):
        raise JSONIRParseError("JSON input could not be parsed safely") from None
    try:
        return build_json_ir(value, document_id=document_id, filename=filename, encoding=encoding,
                             original_layout={"bom": bom})
    except (RecursionError, TypeError, ValueError):
        raise JSONIRParseError("JSON structure could not be represented safely") from None


def _decode_json_bytes(raw: bytes) -> tuple[str, str]:
    """Strictly decode common JSON encodings without leaking content in errors."""
    candidates = ("utf-8-sig", "utf-16", "cp1252")
    for encoding in candidates:
        try:
            return raw.decode(encoding, errors="strict"), encoding
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise JSONIRParseError("Input encoding is unsupported") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert a JSON document into Secret Wards IR")
    parser.add_argument("--input", required=True, help="path to a JSON input file")
    parser.add_argument("--output", required=True, help="path for the IR JSON output")
    parser.add_argument("--document-id", default=None, help="optional IR document identifier")
    args = parser.parse_args(argv)
    source_path = Path(args.input)
    output_path = Path(args.output)
    try:
        raw = source_path.read_bytes()
        text, encoding = _decode_json_bytes(raw)
        ir = parse_json_ir(text, document_id=args.document_id or source_path.stem,
                           filename=source_path.name, encoding=encoding,
                           bom=raw.startswith(b"\xef\xbb\xbf"))
        serialized = ir.model_dump_json(indent=2) + "\n"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized, encoding="utf-8")
    except (OSError, JSONIRParseError):
        print("Could not convert JSON input safely.", file=sys.stderr)
        return 2
    print("IR written successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
