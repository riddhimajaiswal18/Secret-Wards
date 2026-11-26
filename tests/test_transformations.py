import csv
import io
import json

import pytest

from src.ingestion.file_router import parse_document_file
from src.ir import Annotation, PendingEdit, ProcessingStatus
from src.transformation.engine import EditFailure, apply_pending_edits, serialize_ir


def test_ragged_csv_cell_locator_does_not_change_neighbors(tmp_path):
    path = tmp_path / "ragged.csv"
    path.write_text('a;b;c\n1;"two;parts";3\n4;5\n', encoding="utf-8")
    ir = parse_document_file(path)
    ir.structure.original_layout.update({"delimiter": ";", "quotechar": '"',
                                         "lineterminator": "\n", "bom": False})
    ir.add_pending_edit(PendingEdit(edit_id="e1", locator="row:0,col:1", replacement="masked",
                                    expected_value="two;parts", technique="test"))
    apply_pending_edits(ir)
    output = serialize_ir(ir).decode("utf-8")
    parsed = list(csv.reader(io.StringIO(output), delimiter=";"))
    assert parsed == [["a", "b", "c"], ["1", "masked", "3"], ["4", "5"]]


def test_text_span_changes_only_selected_repeated_occurrence(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("Asha met Asha", encoding="utf-8")
    ir = parse_document_file(path)
    ir.add_annotation(Annotation(annotation_id="a1", finding_type="pii", locator="span:9:13"))
    ir.add_pending_edit(PendingEdit(edit_id="e1", locator="span:9:13", replacement="[NAME]",
                                    expected_value="Asha", technique="test"))
    apply_pending_edits(ir)
    assert ir.structure.data == "Asha met [NAME]"


def test_fhir_fullurl_edit_updates_only_reference_properties(tmp_path):
    path = tmp_path / "bundle.json"
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": [
        {"fullUrl": "urn:uuid:patient-a", "resource": {"resourceType": "Patient", "id": "a"}},
        {"fullUrl": "urn:uuid:obs", "resource": {"resourceType": "Observation", "id": "o",
         "subject": {"reference": "urn:uuid:patient-a"}, "note": [{"text": "urn:uuid:patient-a"}]}}
    ]}
    path.write_text(json.dumps(bundle), encoding="utf-8")
    ir = parse_document_file(path)
    locator = "$.entry[0].fullUrl"
    ir.add_pending_edit(PendingEdit(edit_id="e1", locator=locator, replacement="urn:uuid:new-patient",
                                    expected_value="urn:uuid:patient-a", technique="test"))
    apply_pending_edits(ir)
    assert ir.structure.data["entry"][1]["resource"]["subject"]["reference"] == "urn:uuid:new-patient"
    assert ir.structure.data["entry"][1]["resource"]["note"][0]["text"] == "urn:uuid:patient-a"
    result = json.loads(serialize_ir(ir))
    assert result["entry"][1]["resource"]["subject"]["reference"] == "urn:uuid:new-patient"


def test_csv_semicolon_dialect_round_trips_with_quote_and_bom(tmp_path):
    path = tmp_path / "quoted.csv"
    path.write_bytes(b'\xef\xbb\xbfname;note\r\nAsha;"hello; world"\r\n')
    ir = parse_document_file(path)
    assert ir.structure.original_layout["delimiter"] == ";"
    serialized = serialize_ir(ir)
    assert serialized.startswith(b"\xef\xbb\xbf")
    assert b'"hello; world"' in serialized
    assert serialized.endswith(b"\r\n")


def test_serialization_independent_of_annotation_insertion_order(tmp_path):
    path = tmp_path / "obj.json"
    path.write_text('{"a":"x","b":"y"}', encoding="utf-8")
    first = parse_document_file(path)
    second = parse_document_file(path)
    annotations = [Annotation(annotation_id="a", finding_type="test", locator="$.a"),
                   Annotation(annotation_id="b", finding_type="test", locator="$.b")]
    for item in annotations:
        first.add_annotation(item)
    for item in reversed(annotations):
        second.add_annotation(item)
    assert serialize_ir(first) == serialize_ir(second)
    assert first.to_deterministic_json() == second.to_deterministic_json()


def test_deep_json_is_rejected_with_controlled_depth_error(tmp_path):
    path = tmp_path / "deep.json"
    path.write_text("{" + '"x":{' * 1200 + '"end":1' + "}" * 1200 + "}", encoding="utf-8")
    ir = parse_document_file(path)
    assert ir.validation.parse_status == "ERROR:depth_limit_exceeded"
    assert ir.processing_status is ProcessingStatus.QUARANTINED


def test_failed_edit_quarantines_and_cannot_be_serialized(tmp_path):
    path = tmp_path / "obj.json"
    path.write_text('{"a":"original"}', encoding="utf-8")
    ir = parse_document_file(path)
    ir.add_pending_edit(PendingEdit(edit_id="e1", locator="$.a", replacement="masked",
                                    expected_value="wrong", technique="test"))
    with pytest.raises(EditFailure):
        apply_pending_edits(ir)
    assert ir.processing_status is ProcessingStatus.QUARANTINED
    with pytest.raises(EditFailure):
        serialize_ir(ir)


def test_overlapping_text_edits_quarantine(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("abcdef", encoding="utf-8")
    ir = parse_document_file(path)
    for eid, locator in (("e1", "span:1:4"), ("e2", "span:3:5")):
        ir.add_pending_edit(PendingEdit(edit_id=eid, locator=locator, replacement="X",
                                        technique="test"))
    with pytest.raises(EditFailure):
        apply_pending_edits(ir)
    assert ir.processing_status is ProcessingStatus.QUARANTINED


def test_resource_id_edit_updates_typed_fhir_references(tmp_path):
    path = tmp_path / "bundle.json"
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": [
        {"fullUrl": "urn:uuid:p", "resource": {"resourceType": "Patient", "id": "p1"}},
        {"fullUrl": "urn:uuid:o", "resource": {"resourceType": "Observation", "id": "o1",
         "subject": {"reference": "Patient/p1"}, "note": [{"text": "Patient/p1"}]}}
    ]}
    path.write_text(json.dumps(bundle), encoding="utf-8")
    ir = parse_document_file(path)
    locator = "$.entry[0].resource.id"
    ir.add_pending_edit(PendingEdit(edit_id="e1", locator=locator, replacement="p2",
                                    expected_value="p1", technique="test"))
    apply_pending_edits(ir)
    resource = ir.structure.data["entry"][1]["resource"]
    assert resource["subject"]["reference"] == "Patient/p2"
    assert resource["note"][0]["text"] == "Patient/p1"
