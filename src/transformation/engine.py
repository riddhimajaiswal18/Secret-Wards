"""Deterministic, locator-based edits and serialization for parsed document cores."""
from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from src.ir import (EditAudit, IntermediateRepresentation, PendingEdit, ProcessingStatus,
                    TransformationRecord)


class EditFailure(ValueError):
    """A locator or precondition did not identify the expected target."""


_TOKEN = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]|\['((?:\\.|[^'])*)'\]")


def _path_tokens(path: str) -> list[str | int]:
    if not path.startswith("$"):
        raise EditFailure("invalid_locator")
    pos, tokens = 1, []
    while pos < len(path):
        match = _TOKEN.match(path, pos)
        if not match:
            raise EditFailure("invalid_locator")
        if match.group(1) is not None:
            tokens.append(match.group(1))
        elif match.group(2) is not None:
            tokens.append(int(match.group(2)))
        else:
            token = match.group(3).replace("\\'", "'").replace("\\\\", "\\")
            tokens.append(token)
        pos = match.end()
    return tokens


def _parent_and_key(root: Any, tokens: list[str | int]) -> tuple[Any, str | int]:
    if not tokens:
        raise EditFailure("root_replacement_not_supported")
    parent = root
    try:
        for token in tokens[:-1]:
            parent = parent[token]
        key = tokens[-1]
        if isinstance(parent, list) and not isinstance(key, int):
            raise EditFailure("array_index_required")
        if isinstance(parent, dict) and not isinstance(key, str):
            raise EditFailure("object_key_required")
        _ = parent[key]
        return parent, key
    except (KeyError, IndexError, TypeError):
        raise EditFailure("locator_not_found") from None


def _target(ir: IntermediateRepresentation, locator: str) -> tuple[Any, Any]:
    fmt = ir.source.format
    if fmt == "text":
        match = re.fullmatch(r"span:(\d+):(\d+)", locator)
        if not match or not isinstance(ir.structure.data, str):
            raise EditFailure("invalid_text_locator")
        start, end = map(int, match.groups())
        if end > len(ir.structure.data) or end < start:
            raise EditFailure("locator_not_found")
        return ir.structure, (start, end)
    if fmt in {"csv", "tsv"}:
        match = re.fullmatch(r"row:(\d+),col:(\d+)", locator)
        if not match:
            raise EditFailure("invalid_cell_locator")
        row, col = map(int, match.groups())
        rows = ir.structure.data["rows"]
        if row >= len(rows) or col >= len(rows[row]):
            raise EditFailure("locator_not_found")
        return rows[row], col
    if fmt == "xml":
        tokens = _path_tokens(locator)
        parent, key = _parent_and_key(ir.structure.data, tokens)
        return parent, key
    if fmt in {"json", "fhir"}:
        parent, key = _parent_and_key(ir.structure.data, _path_tokens(locator))
        return parent, key
    raise EditFailure("format_not_editable")


def apply_edit(ir: IntermediateRepresentation, locator: str, edit: PendingEdit) -> None:
    """Apply one guarded edit to the format-specific core, never by value search."""
    if edit.locator != locator:
        raise EditFailure("locator_mismatch")
    fhir_refs: list[tuple[Any, str | int, str]] = []
    if ir.source.format == "fhir":
        tokens = _path_tokens(locator)
        if len(tokens) >= 3 and tokens[0] == "entry" and isinstance(tokens[1], int):
            entry = ir.structure.data.get("entry", [])[tokens[1]]
            if tokens[2] == "fullUrl":
                old = entry.get("fullUrl")
                new = edit.replacement
                if old is not None and isinstance(new, str):
                    for item in ir.structure.data.get("entry", []):
                        resource = item.get("resource", {})
                        _collect_fhir_references(resource, old, new, fhir_refs)
            elif tokens[2:4] == ["resource", "id"]:
                resource = entry.get("resource", {})
                old_id = resource.get("id")
                resource_type = resource.get("resourceType")
                if old_id is not None and resource_type and isinstance(edit.replacement, str):
                    _collect_fhir_references(ir.structure.data, f"{resource_type}/{old_id}",
                                             f"{resource_type}/{edit.replacement}", fhir_refs)
    parent, key = _target(ir, locator)
    if ir.source.format == "text":
        start, end = key
        current = parent.data[start:end]
        if edit.expected_value is not None and current != edit.expected_value:
            raise EditFailure("precondition_failed")
        parent.data = parent.data[:start] + str(edit.replacement) + parent.data[end:]
        return
    current = parent[key]
    if edit.expected_value is not None and current != edit.expected_value:
        raise EditFailure("precondition_failed")
    if isinstance(parent, list):
        if not isinstance(edit.replacement, str) and ir.source.format in {"csv", "tsv"}:
            raise EditFailure("cell_replacement_must_be_string")
    parent[key] = edit.replacement
    for ref_parent, ref_key, ref_value in fhir_refs:
        ref_parent[ref_key] = ref_value


def _collect_fhir_references(value: Any, old: str, new: str,
                             result: list[tuple[Any, str | int, str]]) -> None:
    """Rewrite only FHIR `reference` properties exactly matching the old target."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "reference" and child == old:
                result.append((value, key, new))
            else:
                _collect_fhir_references(child, old, new, result)
    elif isinstance(value, list):
        for child in value:
            _collect_fhir_references(child, old, new, result)


def apply_pending_edits(ir: IntermediateRepresentation) -> IntermediateRepresentation:
    """Apply edits in deterministic order; on any failure quarantine the document."""
    edits = [(locator, edit) for locator in sorted(ir.pending_edits)
             for edit in sorted(ir.pending_edits[locator], key=lambda item: item.edit_id)]
    if ir.source.format == "text":
        # For spans, descending offsets keep earlier coordinates valid.
        def text_order(item: tuple[str, PendingEdit]) -> tuple[int, str]:
            match = re.fullmatch(r"span:(\d+):(\d+)", item[0])
            return (-int(match.group(1)), item[0]) if match else (0, item[0])
        edits.sort(key=text_order)
    locator = ""
    edit: PendingEdit | None = None
    try:
        if ir.source.format == "text":
            spans = []
            for locator, _edit in edits:
                match = re.fullmatch(r"span:(\d+):(\d+)", locator)
                if not match:
                    raise EditFailure("invalid_text_locator")
                spans.append(tuple(map(int, match.groups())))
            ascending = sorted(spans)
            if any(left[1] > right[0] for left, right in zip(ascending, ascending[1:])):
                raise EditFailure("overlapping_text_edits")
        for locator, edit in edits:
            apply_edit(ir, locator, edit)
            ir.edit_audit.append(EditAudit(edit_id=edit.edit_id, locator=locator,
                                           status="SUCCESS", technique=edit.technique))
            ir.transformations.append(TransformationRecord(
                transformation_id=edit.edit_id, field_path=locator, entity_id=edit.entity_id,
                technique=edit.technique, status="SUCCESS", reversible=False))
    except Exception as exc:
        reason = str(exc) if isinstance(exc, EditFailure) else "edit_failed"
        ir.processing_status = ProcessingStatus.QUARANTINED
        ir.validation.parse_status = "ERROR:transformation_failed"
        ir.validation.serialization_status = "NOT_STARTED"
        ir.errors.append(reason)
        ir.edit_audit.append(EditAudit(edit_id=edit.edit_id if edit else "batch",
                                       locator=locator or "batch",
                                       status="FAILED", technique=edit.technique if edit else "unknown",
                                       error_code=reason))
        raise EditFailure(reason) from None
    if edits:
        ir.processing_status = ProcessingStatus.EDITED
    return ir


def _xml_element(node: dict[str, Any]) -> ET.Element:
    element = ET.Element(node["tag"])
    element.attrib.update(dict(node["attributes"]))
    element.text = node.get("text")
    for child in node.get("children", []):
        element.append(_xml_element(child))
    element.tail = node.get("tail")
    return element


def serialize_ir(ir: IntermediateRepresentation) -> bytes:
    """Serialize current core using captured format metadata and deterministic ordering."""
    if ir.processing_status == ProcessingStatus.QUARANTINED:
        raise EditFailure("quarantined_document_cannot_be_serialized")
    fmt, data = ir.source.format, ir.structure.data
    layout = ir.structure.original_layout or {}
    if fmt in {"json", "fhir"}:
        indent = layout.get("indent", 2)
        if indent is None:
            text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        else:
            text = json.dumps(data, ensure_ascii=False, indent=int(indent))
        if layout.get("trailing_newline", True):
            text += "\n"
    elif fmt in {"csv", "tsv"}:
        layout = ir.structure.original_layout
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, delimiter=layout.get("delimiter", "," if fmt == "csv" else "\t"),
                            quotechar=layout.get("quotechar", '"'),
                            doublequote=layout.get("doublequote", True),
                            escapechar=layout.get("escapechar"),
                            quoting=layout.get("quoting", csv.QUOTE_MINIMAL),
                            lineterminator=layout.get("lineterminator", "\n"))
        writer.writerow(data["header"])
        writer.writerows(data["rows"])
        text = buffer.getvalue()
    elif fmt == "text":
        text = data
    elif fmt == "xml":
        for prefix, uri in (layout.get("namespaces") or []):
            try:
                ET.register_namespace(prefix, uri)
            except ValueError:
                pass
        text = ET.tostring(_xml_element(data), encoding="unicode")
        declaration = ir.structure.original_layout.get("xml_declaration")
        if isinstance(declaration, str) and declaration:
            text = declaration + "\n" + text
    else:
        raise EditFailure("format_not_serializable")
    encoding = ir.source.encoding or "utf-8"
    has_bom = bool(ir.structure.original_layout.get("bom", False))
    if encoding == "utf-8-sig":
        encoding = "utf-8"
        has_bom = True
    encoded = text.encode(encoding)
    if has_bom and encoding == "utf-8":
        encoded = b"\xef\xbb\xbf" + encoded
    ir.processing_status = ProcessingStatus.SERIALIZED
    ir.validation.serialization_status = "SUCCESS"
    return encoded
