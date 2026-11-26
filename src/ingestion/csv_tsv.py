"""CSV/TSV parsing into the shared IR without coercing cell values."""
from __future__ import annotations

import csv
import io
from typing import Any

from src.ir import IntermediateRepresentation, build_json_ir


def parse_delimited_ir(text: str, *, document_id: str, filename: str,
                       encoding: str, delimiter: str) -> IntermediateRepresentation:
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True))
    except (csv.Error, UnicodeError):
        raise ValueError("malformed_delimited_file") from None
    header = rows[0] if rows else []
    body = rows[1:] if rows else []
    # Array storage preserves duplicate headers, original order, ragged rows and strings.
    data: dict[str, Any] = {"header": header, "rows": body}
    return build_json_ir(data, document_id=document_id, filename=filename, encoding=encoding,
                         source_format="tsv" if delimiter == "\t" else "csv",
                         arrangement="header_rows")
