"""Typed, lossless intermediate representation for source documents."""
from __future__ import annotations

from enum import Enum
import json
import re
from typing import Any, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# pydantic_core refuses to serialise beyond ~400 nesting levels; a document that parses but
# cannot be written is worse than one rejected early, so the cap sits well below that limit.
MAX_DEPTH = 96
MAX_FILE_MB = 64


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="allow", validate_assignment=True)


class PresenceStatus(str, Enum):
    PRESENT = "present"
    NOT_FOUND = "not_found"
    NULL = "null"
    PARSE_ERROR = "parse_error"
    NOT_APPLICABLE = "not_applicable"


class DetectionStatus(str, Enum):
    DETECTED = "detected"
    NOT_DETECTED = "not_detected"
    UNCERTAIN = "uncertain"
    NOT_EVALUATED = "not_evaluated"


class LinkageStatus(str, Enum):
    MATCH = "MATCH"
    NON_MATCH = "NON_MATCH"
    UNCERTAIN = "UNCERTAIN"
    NOT_EVALUATED = "NOT_EVALUATED"


class SourceMetadata(StrictModel):
    format: str
    # Optional upstream/source-system identity is distinct from document_id.
    source_identity: str | None = None
    encoding: str | None = None
    detected_arrangement: str | None = None
    original_filename: str | None = None
    schema_detected: bool | None = None


class SourceStructure(StrictModel):
    root_type: Literal["object", "array", "string", "number", "boolean", "null"]
    original_layout: Any
    data: Any


class FieldMetadata(StrictModel):
    """Derived, value-free metadata for one location in a format core."""
    locator: str
    field_name: str
    parent_locator: str | None = None
    field_kind: Literal["object", "array", "leaf"]
    expected_dtype: str | None = None
    actual_dtype: str | None = None
    presence_status: PresenceStatus

    @model_validator(mode="after")
    def consistent_kind(self) -> "FieldMetadata":
        if self.field_kind == "object" and self.actual_dtype not in (None, "object"):
            raise ValueError("object metadata must have object actual_dtype")
        if self.field_kind == "array" and self.actual_dtype not in (None, "array"):
            raise ValueError("array metadata must have array actual_dtype")
        return self


class EntityLocation(StrictModel):
    start: int
    end: int
    unit: str = "character"

    @model_validator(mode="after")
    def valid_range(self) -> "EntityLocation":
        if self.start < 0 or self.end < self.start:
            raise ValueError("entity location must be a non-negative, increasing range")
        return self


class EntityRecord(StrictModel):
    entity_id: str
    entity_type: str
    field_path: str
    location: EntityLocation
    confidence: float = Field(ge=0, le=1)
    detection_method: str
    masking_technique: str | None = None
    status: str


class LinkageResult(StrictModel):
    status: LinkageStatus = LinkageStatus.NOT_EVALUATED
    canonical_patient_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    matched_records: list[str] = Field(default_factory=list)
    matching_attributes: list[str] = Field(default_factory=list)


class TransformationRecord(StrictModel):
    transformation_id: str
    field_path: str
    entity_id: str | None = None
    technique: str
    status: str
    reversible: bool


class NormalizationStatus(str, Enum):
    SUCCESS = "success"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"
    NOT_APPLICABLE = "not_applicable"


class NormalizationResult(StrictModel):
    """Sparse derived value; ``locator`` references the untouched source value."""
    locator: str
    normalization_type: str
    normalized_value: Any = None
    status: NormalizationStatus
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(StrictModel):
    parse_status: str
    structure_preserved: bool | None = None
    clinical_utility_preserved: bool | None = None
    privacy_validation: str
    serialization_status: str


class ProcessingStatus(str, Enum):
    PARSED = "PARSED"
    ANNOTATED = "ANNOTATED"
    EDITED = "EDITED"
    SERIALIZED = "SERIALIZED"
    QUARANTINED = "QUARANTINED"


class Annotation(StrictModel):
    annotation_id: str
    finding_type: str
    locator: str
    entity_type: str | None = None
    pii_classification: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    detection_method: str | None = None
    detection_status: DetectionStatus = DetectionStatus.NOT_EVALUATED
    actual_dtype: str | None = None
    expected_dtype: str | None = None
    validation_result: str | None = None
    uncertain: bool = False
    review_required: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class PendingEdit(StrictModel):
    edit_id: str
    locator: str
    operation: Literal["replace"] = "replace"
    replacement: Any
    expected_value: Any = None
    technique: str
    entity_id: str | None = None


class EditAudit(StrictModel):
    edit_id: str
    locator: str
    status: Literal["SUCCESS", "FAILED"]
    technique: str
    error_code: str | None = None


class IntermediateRepresentation(StrictModel):
    ir_version: str = "1.0"
    document_id: str
    source: SourceMetadata
    structure: SourceStructure
    entities: list[EntityRecord] = Field(default_factory=list)
    linkage: LinkageResult = Field(default_factory=LinkageResult)
    transformations: list[TransformationRecord] = Field(default_factory=list)
    annotations: dict[str, list[Annotation]] = Field(default_factory=dict)
    # Sparse derived values only; the original remains in structure.data.
    normalizations: dict[str, list[NormalizationResult]] = Field(default_factory=dict)
    pending_edits: dict[str, list[PendingEdit]] = Field(default_factory=dict)
    edit_audit: list[EditAudit] = Field(default_factory=list)
    processing_status: ProcessingStatus = ProcessingStatus.PARSED
    errors: list[str] = Field(default_factory=list)
    validation: ValidationResult

    @model_validator(mode="after")
    def validate_references(self) -> "IntermediateRepresentation":
        if self.entities:
            available = {item.locator for item in iter_field_metadata(self)}
            if any(entity.field_path not in available for entity in self.entities):
                raise ValueError("entity field_path must resolve in the format core")
        entity_ids = {e.entity_id for e in self.entities}
        for transform in self.transformations:
            if not transform.field_path:
                raise ValueError("transformation field_path/locator cannot be empty")
            if transform.entity_id is not None and transform.entity_id not in entity_ids:
                raise ValueError("transformation entity_id must reference an entity")
        for locator, annotations in self.annotations.items():
            if any(annotation.locator != locator for annotation in annotations):
                raise ValueError("annotation locator must match its locator index")
        for locator, edits in self.pending_edits.items():
            if any(edit.locator != locator for edit in edits):
                raise ValueError("pending edit locator must match its locator index")
        for locator, results in self.normalizations.items():
            if any(result.locator != locator for result in results):
                raise ValueError("normalization locator must match its locator index")
        if self.normalizations:
            available = {item.locator for item in iter_field_metadata(self)}
            if any(locator not in available for locator in self.normalizations):
                raise ValueError("normalization locator must resolve in the format core")
            for results in self.normalizations.values():
                kinds = [item.normalization_type for item in results]
                if len(kinds) != len(set(kinds)):
                    raise ValueError("normalization types must be unique per locator")
        return self

    def add_annotation(self, annotation: Annotation) -> None:
        self.annotations.setdefault(annotation.locator, []).append(annotation)
        self.processing_status = ProcessingStatus.ANNOTATED

    def add_pending_edit(self, edit: PendingEdit) -> None:
        self.pending_edits.setdefault(edit.locator, []).append(edit)

    def to_deterministic_json(self) -> str:
        """Serialize the IR envelope deterministically without reordering source data."""
        payload = self.model_dump(mode="json")
        payload["annotations"] = {
            locator: sorted((item.model_dump(mode="json") for item in items),
                            key=lambda item: item["annotation_id"])
            for locator, items in sorted(self.annotations.items())
        }
        payload["pending_edits"] = {
            locator: sorted((item.model_dump(mode="json") for item in items),
                            key=lambda item: item["edit_id"])
            for locator, items in sorted(self.pending_edits.items())
        }
        payload["normalizations"] = {
            locator: sorted((item.model_dump(mode="json") for item in items),
                            key=lambda item: item["normalization_type"])
            for locator, items in sorted(self.normalizations.items())
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def json_dtype(value: Any) -> str:
    """Return the JSON type without coercing Python bools to integers."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError("unsupported JSON value type")


def json_path(parent: str, key: str | int) -> str:
    """Build a JSONPath, escaping property tokens without changing source keys."""
    if isinstance(key, int):
        return f"{parent}[{key}]"
    # The locator parser's dotted-name grammar is intentionally ASCII. Quote
    # non-ASCII keys so the same locator always resolves losslessly.
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return f"{parent}.{key}"
    escaped = key.replace("\\", "\\\\").replace("'", "\\'")
    return f"{parent}['{escaped}']"


def build_json_ir(data: Any, *, document_id: str, filename: str | None = None,
                  encoding: str = "utf-8", source_format: str = "json",
                  arrangement: str | None = None,
                  original_layout: dict[str, Any] | None = None,
                  max_depth: int = MAX_DEPTH) -> IntermediateRepresentation:
    """Build the envelope around one authoritative format-native data core."""
    stack = [(data, 0)]
    seen_containers: set[int] = set()
    while stack:
        value, depth = stack.pop()
        if depth > max_depth:
            raise ValueError("depth_limit_exceeded")
        if isinstance(value, (dict, list)):
            identity = id(value)
            if identity in seen_containers:
                raise ValueError("cyclic_structure_unsupported")
            seen_containers.add(identity)
            children = value.values() if isinstance(value, dict) else value
            stack.extend((child, depth + 1) for child in children)
    root_type = json_dtype(data)
    return IntermediateRepresentation(
        document_id=document_id,
        source=SourceMetadata(format=source_format, encoding=encoding,
                              detected_arrangement=arrangement or ("nested_object" if root_type == "object" else root_type),
                              original_filename=filename, schema_detected=False),
        structure=SourceStructure(root_type=root_type, original_layout=original_layout or {}, data=data),
        validation=ValidationResult(parse_status="SUCCESS", privacy_validation="NOT_EVALUATED",
                                    serialization_status="PENDING"),
    )


def iter_field_metadata(ir: IntermediateRepresentation) -> Iterator[FieldMetadata]:
    """Derive value-free locator metadata on demand from the authoritative document core."""
    if ir.processing_status == ProcessingStatus.QUARANTINED:
        yield FieldMetadata(locator="$", field_name="root", field_kind="leaf",
                            presence_status=PresenceStatus.PARSE_ERROR)
        return
    data, fmt = ir.structure.data, ir.source.format
    if fmt == "text":
        yield FieldMetadata(locator="doc", field_name="document", field_kind="leaf",
                            actual_dtype="string", presence_status=PresenceStatus.PRESENT)
        return
    if fmt in {"csv", "tsv"}:
        header, rows = data.get("header", []), data.get("rows", [])
        yield FieldMetadata(locator="doc", field_name="table", field_kind="object",
                            actual_dtype="object", presence_status=PresenceStatus.PRESENT)
        for column, name in enumerate(header):
            yield FieldMetadata(locator=f"header:col:{column}", field_name=name,
                                parent_locator="doc", field_kind="leaf", actual_dtype="string",
                                presence_status=PresenceStatus.PRESENT)
        for row_index, row in enumerate(rows):
            yield FieldMetadata(locator=f"row:{row_index}", field_name="row",
                                parent_locator="doc", field_kind="array", actual_dtype="array",
                                presence_status=PresenceStatus.PRESENT)
            for column in range(max(len(header), len(row))):
                exists = column < len(row)
                name = header[column] if column < len(header) else str(column)
                yield FieldMetadata(locator=f"row:{row_index},col:{column}", field_name=name,
                                    parent_locator=f"row:{row_index}", field_kind="leaf",
                                    actual_dtype="string" if exists else None,
                                    presence_status=PresenceStatus.PRESENT if exists else PresenceStatus.NOT_FOUND)
        return

    stack: list[tuple[Any, str, str, str | None, int]] = [(data, "$", "root", None, 0)]
    while stack:
        value, locator, name, parent, depth = stack.pop()
        if depth > 512:
            raise ValueError("field_metadata_depth_exceeded")
        dtype = json_dtype(value)
        kind = "object" if dtype == "object" else "array" if dtype == "array" else "leaf"
        yield FieldMetadata(locator=locator, field_name=name, parent_locator=parent,
                            field_kind=kind, actual_dtype=dtype,
                            presence_status=PresenceStatus.NULL if value is None else PresenceStatus.PRESENT)
        if isinstance(value, dict):
            children = [(child, json_path(locator, key), key, locator, depth + 1)
                        for key, child in value.items()]
            stack.extend(reversed(children))
        elif isinstance(value, list):
            children = [(child, json_path(locator, index), str(index), locator, depth + 1)
                        for index, child in enumerate(value)]
            stack.extend(reversed(children))


_PATH_TOKEN = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]|\['((?:\\.|[^'])*)'\]")


class LocatorResolutionError(ValueError):
    """A source locator does not resolve in the document's format core."""


def get_value(ir: IntermediateRepresentation, locator: str) -> Any:
    """Read a value by its format-specific locator without copying it into metadata."""
    if ir.processing_status == ProcessingStatus.QUARANTINED:
        raise LocatorResolutionError("document has no parsed source core")
    data, fmt = ir.structure.data, ir.source.format
    try:
        if fmt == "text":
            if locator == "doc":
                return data
            match = re.fullmatch(r"span:(\d+):(\d+)", locator)
            if not match:
                raise LocatorResolutionError("invalid text locator")
            start, end = map(int, match.groups())
            if end < start or end > len(data):
                raise LocatorResolutionError("text locator is out of bounds")
            return data[start:end]
        if fmt in {"csv", "tsv"}:
            if locator == "doc":
                return data
            match = re.fullmatch(r"header:col:(\d+)", locator)
            if match:
                return data["header"][int(match.group(1))]
            match = re.fullmatch(r"row:(\d+),col:(\d+)", locator)
            if match:
                row, col = map(int, match.groups())
                return data["rows"][row][col]
            match = re.fullmatch(r"row:(\d+)", locator)
            if match:
                return data["rows"][int(match.group(1))]
            raise LocatorResolutionError("invalid table locator")
        if not locator.startswith("$"):
            raise LocatorResolutionError("invalid structured-data locator")
        tokens: list[str | int] = []
        position = 1
        while position < len(locator):
            match = _PATH_TOKEN.match(locator, position)
            if not match:
                raise LocatorResolutionError("invalid structured-data locator")
            if match.group(1) is not None:
                tokens.append(match.group(1))
            elif match.group(2) is not None:
                tokens.append(int(match.group(2)))
            else:
                tokens.append(match.group(3).replace("\\'", "'").replace("\\\\", "\\"))
            position = match.end()
        value = data
        for token in tokens:
            value = value[token]
        return value
    except (KeyError, IndexError, TypeError):
        raise LocatorResolutionError("locator does not resolve in the source core") from None
