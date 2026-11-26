import pytest
from pydantic import ValidationError

from src.ingestion.ir_json import JSONIRParseError, parse_json_ir
from src.ir import (
    FieldMetadata,
    IntermediateRepresentation,
    PresenceStatus,
    build_json_ir,
    get_value,
    iter_field_metadata,
)


def test_nested_json_preserves_order_types_and_unknown_fields():
    source = {"patient": {"name": "Asha", "age": 0, "active": False}, "unknown": [None, 2]}
    ir = build_json_ir(source, document_id="d1", filename="records.json")
    assert ir.structure.data == source
    assert list(ir.structure.data) == ["patient", "unknown"]
    assert ir.structure.data["patient"]["age"] == 0
    assert ir.structure.data["patient"]["active"] is False
    metadata = list(iter_field_metadata(ir))
    assert {field.locator for field in metadata} >= {
        "$.patient.name", "$.patient.age", "$.unknown[0]", "$.unknown[1]"
    }
    assert ir.model_dump(mode="json")["structure"]["data"] == source
    assert "fields" not in ir.model_dump(mode="json")
    name_field = next(f for f in metadata if f.locator == "$.patient.name")
    assert name_field.parent_locator == "$.patient"
    assert name_field.field_kind == "leaf"
    assert get_value(ir, name_field.locator) == "Asha"
    assert "value" not in name_field.model_dump()


def test_null_and_not_found_are_distinct():
    ir = build_json_ir({"patient": {"name": None}}, document_id="d2")
    null_field = next(f for f in iter_field_metadata(ir) if f.locator == "$.patient.name")
    assert null_field.presence_status is PresenceStatus.NULL
    empty = build_json_ir({"patient": {"middle_name": ""}}, document_id="d2-empty")
    empty_field = next(f for f in iter_field_metadata(empty) if f.locator == "$.patient.middle_name")
    assert empty_field.presence_status is PresenceStatus.PRESENT
    assert empty_field.actual_dtype == "string"


def test_wrong_top_level_field_types_are_rejected():
    with pytest.raises(ValidationError):
        IntermediateRepresentation.model_validate({"document_id": 3})
    with pytest.raises(ValidationError):
        FieldMetadata(locator="$.x", field_name="x", field_kind="object",
                      actual_dtype="array", presence_status="present")


def test_arrays_and_quoted_property_paths():
    ir = build_json_ir([{"a.b": "x"}, {"n": [1, 2]}], document_id="d3")
    paths = {field.locator for field in iter_field_metadata(ir)}
    assert "$[0]['a.b']" in paths
    assert "$[1].n[1]" in paths
    assert ir.structure.root_type == "array"


def test_unknown_fields_survive_ir_validation():
    raw = build_json_ir({"opaque": {"vendor": 7}}, document_id="d4").model_dump()
    raw["source"]["vendor_metadata"] = {"x": [1, 2]}
    restored = IntermediateRepresentation.model_validate(raw)
    assert restored.source.model_extra["vendor_metadata"] == {"x": [1, 2]}
    assert restored.structure.data["opaque"]["vendor"] == 7


def test_malformed_json_has_no_raw_value_in_error():
    secret_text = '{"patient":"private value",'
    with pytest.raises(JSONIRParseError) as exc:
        parse_json_ir(secret_text, document_id="d5")
    assert "private value" not in str(exc.value)


def test_model_rejects_invalid_confidence_and_entity_path():
    with pytest.raises(ValidationError):
        from src.ir import EntityRecord, EntityLocation
        EntityRecord(entity_id="e", entity_type="name", field_path="$.missing",
                     location=EntityLocation(start=0, end=1), confidence=1.1,
                     detection_method="rule", status="DETECTED")
