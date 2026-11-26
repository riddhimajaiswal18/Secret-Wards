"""CSV/TSV parsing into the shared IR without coercing cell values."""
from __future__ import annotations

import csv
import io
import re
from typing import Any

from src.ir import IntermediateRepresentation, SourceMetadata, SourceStructure, ValidationResult


def parse_delimited_ir(text: str, *, document_id: str, filename: str,
                       encoding: str, delimiter: str,
                       bom: bool = False) -> IntermediateRepresentation:
    try:
        try:
            dialect = csv.Sniffer().sniff(text[:65536], delimiters=delimiter)
        except csv.Error:
            dialect = csv.excel_tab if delimiter == "\t" else csv.excel
        rows = list(csv.reader(io.StringIO(text, newline=""), dialect=dialect, strict=True))
    except (csv.Error, UnicodeError):
        raise ValueError("malformed_delimited_file") from None
    header = rows[0] if rows else []
    body = rows[1:] if rows else []
    # Array storage preserves duplicate headers, original order, ragged rows and strings.
    data: dict[str, Any] = {"header": header, "rows": body}
    source_format = "tsv" if delimiter == "\t" else "csv"
    line_ending = "\r\n" if "\r\n" in text else "\n" if "\n" in text else "\r"
    quotechar = dialect.quotechar or '"'
    doublequote, escapechar, quoting = dialect.doublequote, dialect.escapechar, dialect.quoting
    layout = {"delimiter": delimiter, "quotechar": quotechar, "doublequote": doublequote,
              "escapechar": escapechar, "quoting": quoting,
              "lineterminator": line_ending, "bom": bom, "encoding": encoding,
              "header_order": header, "row_count": len(body)}
    return IntermediateRepresentation(
        document_id=document_id,
        source=SourceMetadata(format=source_format, encoding=encoding,
                              detected_arrangement="header_rows", original_filename=filename,
                              schema_detected=False),
        structure=SourceStructure(root_type="object", original_layout=layout, data=data),
        validation=ValidationResult(parse_status="SUCCESS", privacy_validation="NOT_EVALUATED",
                                    serialization_status="PENDING"),
    )
