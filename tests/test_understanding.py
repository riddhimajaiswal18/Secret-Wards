from __future__ import annotations

import json

from src.ir import build_json_ir
from src.normalization import normalize_document_file, normalize_ir
from src.understanding import UnderstandingConfig, understand_ir


def _find(ir, locator, kind):
    return [item for item in ir.annotations.get(locator, []) if item.finding_type == kind]


def _one(ir, locator, kind):
    return _find(ir, locator, kind)[0]


def test_json_hierarchy_sections_and_normalize_evidence_produce_contextual_findings():
    source = {
        "Patient Details": {"Name": "Asha Devi"},
        "Medical History": {"description": "Diagnosed with Parkinson's disease"},
        "Prescription": {"medication": "Ramipril 5 mg prescribed by Dr. Ramesh"},
    }
    ir = build_json_ir(source, document_id="understand-json")
    normalize_ir(ir)
    normalize_before = {
        locator: [item.model_dump(mode="json") for item in items]
        for locator, items in ir.annotations.items()
    }
    understand_ir(ir)

    patient_name = "$['Patient Details'].Name"
    history = "$['Medical History'].description"
    prescription = "$.Prescription.medication"
    assert any(item.details["canonical_section"] == "PATIENT_DETAILS"
               for item in _find(ir, patient_name, "section_context"))
    assert _one(ir, patient_name, "contextual_person_role").details["role"] == "PATIENT"
    assert "Parkinson's disease" in [item.details.get("canonical_term")
                                      for item in ir.annotations[history]
                                      if item.finding_type == "clinical_term"]
    diagnosis = _one(ir, history, "relationship")
    assert diagnosis.details["predicate"] == "DIAGNOSED_WITH"
    assert diagnosis.details["status"] == "RESOLVED"
    prescription_relation = _one(ir, prescription, "relationship")
    assert prescription_relation.details["predicate"] == "PRESCRIBED_BY"
    assert prescription_relation.details["object_role"] == "DOCTOR"
    assert all(any(a.annotation_id == original["annotation_id"]
                   for a in ir.annotations.get(locator, []))
               for locator, items in normalize_before.items() for original in items)
    assert ir.structure.data == source
    assert ir.pending_edits == {}


def test_text_headings_labels_and_relationship_spans_use_doc_locator(tmp_path):
    path = tmp_path / "note.txt"
    content = ("Patient Details:\nName: Asha Devi\n\n"
               "Medical History:\nDiagnosed with Parkinson's disease\n"
               "C/O fever\nC/O Ramesh\n\n"
               "Prescription:\nRamipril 5 mg prescribed by Dr. Ramesh\n")
    path.write_text(content, encoding="utf-8")
    ir = normalize_document_file(str(path))
    original = ir.structure.data
    document_text = ir.structure.data
    understand_ir(ir)

    headings = _find(ir, "doc", "section_context")
    assert {item.details["canonical_section"] for item in headings} >= {
        "PATIENT_DETAILS", "MEDICAL_HISTORY", "PRESCRIPTION"}
    classifications = _find(ir, "doc", "contextual_semantic_classification")
    patient_line = next(item for item in classifications
                        if item.details.get("source_field") == "Name")
    assert patient_line.details["canonical_field"] == "patient_name"
    assert "PATIENT_DETAILS" in patient_line.details["section_context"]
    patient_role = next(item for item in _find(ir, "doc", "contextual_person_role")
                        if item.details.get("role") == "PATIENT")
    assert document_text[slice(*patient_role.details["source_span"])] == "Asha Devi"

    relations = _find(ir, "doc", "relationship")
    complaint = next(item for item in relations if item.details["predicate"] == "COMPLAINS_OF")
    ambiguous = next(item for item in relations
                     if item.details["predicate"] == "RELATIONSHIP_UNRESOLVED")
    prescribed = next(item for item in relations if item.details["predicate"] == "PRESCRIBED_BY")
    assert document_text[slice(*complaint.details["object_span"])] == "fever"
    assert complaint.details["status"] == "RESOLVED"
    assert document_text[slice(*ambiguous.details["object_span"])] == "Ramesh"
    assert ambiguous.details["status"] == "AMBIGUOUS"
    assert document_text[slice(*prescribed.details["object_span"])] == "Dr. Ramesh"
    assert ir.structure.data == original


def test_xml_section_titles_scope_descendants_without_format_conversion(tmp_path):
    path = tmp_path / "history.xml"
    source = "<record><section><title>Medical History</title><diagnosis>Parkinson's disease</diagnosis></section></record>"
    path.write_text(source, encoding="utf-8")
    ir = normalize_document_file(str(path))
    original = json.dumps(ir.structure.data, ensure_ascii=False)
    understand_ir(ir)
    diagnosis_locator = "$.children[0].children[1].text"
    section = _one(ir, diagnosis_locator, "section_context")
    assert section.details["canonical_section"] == "MEDICAL_HISTORY"
    assert section.details["section_locator"] == "$.children[0]"
    assert _one(ir, diagnosis_locator, "contextual_semantic_classification").details["clinical_concepts"] == [
        "Parkinson's disease"]
    assert json.dumps(ir.structure.data, ensure_ascii=False) == original


def test_fhir_section_sibling_heading_scopes_entries(tmp_path):
    source = {"resourceType": "Bundle", "type": "document", "entry": [
        {"resource": {"resourceType": "Composition", "section": [
            {"title": "Medical History", "text": {"status": "generated",
             "div": "Diagnosed with Parkinson's disease"}}
        ]}}
    ]}
    path = tmp_path / "composition.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    ir = normalize_document_file(str(path))
    understand_ir(ir)
    value_locator = "$.entry[0].resource.section[0].text.div"
    section = _one(ir, value_locator, "section_context")
    assert section.details["canonical_section"] == "MEDICAL_HISTORY"
    assert section.details["section_locator"] == "$.entry[0].resource.section[0]"
    assert _one(ir, value_locator, "contextual_semantic_classification").details["clinical_concepts"] == [
        "Parkinson's disease"]


def test_delimited_header_section_context_and_relationships_keep_existing_locators(tmp_path):
    path = tmp_path / "data.tsv"
    path.write_text("Medical History\tPrescription\nDiagnosed with fever\tDrug prescribed by Dr. Rao\n", encoding="utf-8")
    ir = normalize_document_file(str(path))
    understand_ir(ir)
    history_cell = "row:0,col:0"
    prescription_cell = "row:0,col:1"
    assert _one(ir, history_cell, "section_context").details["canonical_section"] == "MEDICAL_HISTORY"
    assert _one(ir, prescription_cell, "section_context").details["canonical_section"] == "PRESCRIPTION"
    relation = _one(ir, prescription_cell, "relationship")
    assert relation.details["predicate"] == "PRESCRIBED_BY"
    assert relation.details["status"] == "RESOLVED"


def test_ambiguous_context_and_deterministic_rerun_preserve_other_stages():
    source = {"name": "Ramesh", "note": "C/O Ramesh"}
    ir = build_json_ir(source, document_id="uncertain")
    normalize_ir(ir)
    understand_ir(ir, config=UnderstandingConfig())
    first = ir.to_deterministic_json()
    relation = _one(ir, "$.note", "relationship")
    assert relation.details["status"] == "AMBIGUOUS"
    assert relation.details["predicate"] == "RELATIONSHIP_UNRESOLVED"
    assert not _find(ir, "$.name", "contextual_person_role")
    normalize_annotations = {loc: [a.annotation_id for a in items if a.annotation_id.startswith("SEM-")]
                            for loc, items in ir.annotations.items()}
    understand_ir(ir)
    assert ir.to_deterministic_json() == first
    assert {loc: [a.annotation_id for a in items if a.annotation_id.startswith("SEM-")]
            for loc, items in ir.annotations.items()} == normalize_annotations
    assert ir.structure.data == source
    assert ir.pending_edits == {}


def test_understanding_does_not_resolve_conflicting_normalize_role_evidence():
    ir = build_json_ir({"patientName": "Dr. Ramesh"}, document_id="role-conflict")
    normalize_ir(ir)
    understand_ir(ir)
    role = _one(ir, "$.patientName", "contextual_person_role")
    assert role.details["status"] == "AMBIGUOUS"
    assert role.details["role"] == "UNKNOWN"
    assert set(role.details["candidate_roles"]) == {"DOCTOR", "PATIENT"}
