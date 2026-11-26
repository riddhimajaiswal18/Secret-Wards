"""Typed, lossless intermediate representation for source documents."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    encoding: str | None = None
    detected_arrangement: str | None = None
    original_filename: str | None = None
    schema_detected: bool | None = None


class SourceStructure(StrictModel):
    root_type: Literal["object", "array", "string", "number", "boolean", "null"]
    original_layout: Any
    data: Any


class FieldRecord(StrictModel):
    field_id: str
    field_name: str
    field_path: str
    parent_field_id: str | None = None
    field_kind: Literal["object", "array", "leaf"]
    expected_dtype: str | None = None
    actual_dtype: str | None = None
    presence_status: PresenceStatus
    sensitivity: str | None = None
    detection_status: DetectionStatus = DetectionStatus.NOT_EVALUATED
    expected_masking_technique: str | None = None

    @model_validator(mode="after")
    def consistent_presence_value(self) -> "FieldRecord":
        if self.field_kind == "object" and self.actual_dtype not in (None, "object"):
            raise ValueError("object fields must have object actual_dtype")
        if self.field_kind == "array" and self.actual_dtype not in (None, "array"):
            raise ValueError("array fields must have array actual_dtype")
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


class ValidationResult(StrictModel):
    parse_status: str
    structure_preserved: bool | None = None
    clinical_utility_preserved: bool | None = None
    privacy_validation: str
    serialization_status: str


class IntermediateRepresentation(StrictModel):
    ir_version: str = "1.0"
    document_id: str
    source: SourceMetadata
    structure: SourceStructure
    fields: list[FieldRecord] = Field(default_factory=list)
    entities: list[EntityRecord] = Field(default_factory=list)
    linkage: LinkageResult = Field(default_factory=LinkageResult)
    transformations: list[TransformationRecord] = Field(default_factory=list)
    validation: ValidationResult

    @model_validator(mode="after")
    def validate_references(self) -> "IntermediateRepresentation":
        field_paths = {f.field_path for f in self.fields}
        fields_by_id = {f.field_id: f for f in self.fields}
        if len(fields_by_id) != len(self.fields):
            raise ValueError("field_id values must be unique")
        for field in self.fields:
            if field.parent_field_id is not None:
                parent = fields_by_id.get(field.parent_field_id)
                if parent is None:
                    raise ValueError("parent_field_id must reference an existing field")
                if parent.field_kind not in ("object", "array"):
                    raise ValueError("a field parent must be an object or array")
                if not field.field_path.startswith(parent.field_path):
                    raise ValueError("field_path must be nested under its parent path")
        if self.fields and not any(f.field_path == "$" and f.parent_field_id is None for f in self.fields):
            raise ValueError("field tree must contain a root field at '$'")
        entity_ids = {e.entity_id for e in self.entities}
        for entity in self.entities:
            if entity.field_path not in field_paths:
                raise ValueError("entity field_path must reference a field record")
        for transform in self.transformations:
            if transform.field_path not in field_paths:
                raise ValueError("transformation field_path must reference a field record")
            if transform.entity_id is not None and transform.entity_id not in entity_ids:
                raise ValueError("transformation entity_id must reference an entity")
        return self


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
    if key.isidentifier():
        return f"{parent}.{key}"
    escaped = key.replace("\\", "\\\\").replace("'", "\\'")
    return f"{parent}['{escaped}']"


def build_json_ir(data: Any, *, document_id: str, filename: str | None = None,
                  encoding: str = "utf-8") -> IntermediateRepresentation:
    """Create a path/parent index for JSON nodes; original values live only in structure.data."""
    fields: list[FieldRecord] = []

    def walk(value: Any, path: str, name: str, parent_id: str | None) -> None:
        dtype = json_dtype(value)
        kind = "object" if dtype == "object" else "array" if dtype == "array" else "leaf"
        field_id = f"f_{len(fields) + 1:06d}"
        fields.append(FieldRecord(
            field_id=field_id, field_name=name, field_path=path, parent_field_id=parent_id,
            field_kind=kind,
            expected_dtype=dtype, actual_dtype=dtype,
            presence_status=PresenceStatus.NULL if value is None else PresenceStatus.PRESENT,
        ))
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, json_path(path, key), key, field_id)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, json_path(path, index), str(index), field_id)

    walk(data, "$", "root", None)
    root_type = json_dtype(data)
    return IntermediateRepresentation(
        document_id=document_id,
        source=SourceMetadata(format="json", encoding=encoding,
                              detected_arrangement="nested_object" if root_type == "object" else root_type,
                              original_filename=filename, schema_detected=False),
        structure=SourceStructure(root_type=root_type, original_layout={}, data=data),
        fields=fields,
        validation=ValidationResult(parse_status="SUCCESS", privacy_validation="NOT_EVALUATED",
                                    serialization_status="PENDING"),
    )
