from __future__ import annotations

import json

from src.ingestion.file_router import parse_document_file
from src.ir import build_json_ir, get_value
from src.normalization import (NormalizationConfig, SemanticNormalizationConfig,
                               normalize_document_file, normalize_ir, normalize_semantics)


def _annotations(ir, locator, finding_type):
    return [item for item in ir.annotations.get(locator, []) if item.finding_type == finding_type]


def _one(ir, locator, finding_type):
    return _annotations(ir, locator, finding_type)[0]


def _valid_aadhaar_like():
    # Purely synthetic test digits: choose a check digit satisfying Verhoeff.
    from src.normalization.semantic import _verhoeff_valid
    prefix = "23456789012"
    return next(prefix + str(digit) for digit in range(10)
                if _verhoeff_valid(prefix + str(digit)))


def test_field_synonyms_map_aliases_and_structural_names_without_forcing_generic_keys():
    source = {"patient": {"name": "Asha Devi", "birthDate": "2001-02-03"},
              "provider": {"name": "Dr. Ramesh"}, "payload": {"value": "opaque", "type": "unknown"}}
    source["clientFullName"] = "Asha Devi"
    ir = build_json_ir(source, document_id="doc-one")
    config = SemanticNormalizationConfig(field_synonyms={"patient_name": ("client full name",)})
    normalize_semantics(ir, config=config)
    assert _one(ir, "$.patient.name", "canonical_field").details["canonical_field"] == "patient_name"
    assert _one(ir, "$.patient.birthDate", "canonical_field").details["canonical_field"] == "date_of_birth"
    assert _one(ir, "$.provider.name", "canonical_field").details["canonical_field"] == "doctor_name"
    assert _one(ir, "$.clientFullName", "canonical_field").details["canonical_field"] == "patient_name"
    assert _one(ir, "$.payload.value", "canonical_field").details["status"] == "UNKNOWN"
    assert _one(ir, "$.payload.type", "canonical_field").details["canonical_field"] is None
    assert ir.document_id == "doc-one"
    conflicted = build_json_ir({"patient": {"provider": {"name": "Asha"}}}, document_id="conflict")
    normalize_semantics(conflicted)
    assert _one(conflicted, "$.patient.provider.name", "canonical_field").details["status"] == "AMBIGUOUS"


def test_name_normalization_preserves_original_honorifics_initials_and_script():
    original = {"patientName": "  श्री. A. K.  Kumar,  ", "providerName": "Dr. Ramesh"}
    ir = build_json_ir(original, document_id="names")
    normalize_semantics(ir)
    patient = _one(ir, "$.patientName", "normalized_name")
    assert patient.details["normalized_value"] == "A. K. Kumar"
    assert patient.details["honorifics"] == ["श्री"]
    assert patient.details["initials_expanded"] is False
    doctor = _one(ir, "$.providerName", "normalized_name")
    assert doctor.details["normalized_value"] == "Ramesh"
    assert get_value(ir, "$.patientName") == original["patientName"]
    assert _one(ir, "$.providerName", "person_role").details["role"] == "DOCTOR"
    assert _one(ir, "$.patientName", "person_role").details["role"] == "PATIENT"


def test_cross_script_name_representation_is_opt_in_and_does_not_link_people():
    source = {"patients": [{"patientName": "आशा"}, {"patientName": "आशा"}]}
    ir = build_json_ir(source, document_id="indic")
    config = SemanticNormalizationConfig(transliterate_names=True)
    normalize_semantics(ir, config=config)
    left = _one(ir, "$.patients[0].patientName", "normalized_name")
    right = _one(ir, "$.patients[1].patientName", "normalized_name")
    assert left.details["normalized_value"] == right.details["normalized_value"] == "आशा"
    translit = _one(ir, "$.patients[0].patientName", "transliterated_name")
    assert translit.details["identity_equivalence"] == "not_asserted"
    assert not ir.linkage.matched_records
    assert ir.structure.data == source


def test_hindi_field_and_clinical_terms_and_custom_terminology_are_supported():
    source = {"मरीज का नाम": "आशा", "नोट": "बुखार", "customDiagnosis": "RareTerm"}
    ir = build_json_ir(source, document_id="hindi")
    config = SemanticNormalizationConfig(clinical_terms={
        "RareTerm": {"canonical_term": "Configured term", "category": "diagnosis", "concept_id": "LOCAL:1"}
    })
    normalize_semantics(ir, config=config)
    assert _one(ir, "$['मरीज का नाम']", "canonical_field").details["canonical_field"] == "patient_name"
    fever = _one(ir, "$['नोट']", "clinical_term")
    assert fever.details["canonical_term"] == "fever"
    custom = _one(ir, "$.customDiagnosis", "clinical_term")
    assert custom.details["concept_id"] == "LOCAL:1"


def test_phone_identifier_uses_phone_parser_and_configured_region():
    ir = build_json_ir({"phoneNumber": "98765 43210"}, document_id="phone-id")
    normalize_ir(ir, config=NormalizationConfig(default_phone_region="IN"))
    annotations = _annotations(ir, "$.phoneNumber", "identifier_classification")
    assert len(annotations) == 1
    try:
        import phonenumbers  # noqa: F401
    except ImportError:
        assert annotations[0].details["status"] == "UNKNOWN"
    else:
        assert annotations[0].details["status"] in {"RESOLVED", "INVALID"}
        if annotations[0].details["status"] == "RESOLVED":
            assert annotations[0].details["normalized_value"].startswith("+91")


def test_identifier_classification_requires_context_and_validation():
    valid = _valid_aadhaar_like()
    ir = build_json_ir({"aadhaarNumber": valid, "panNumber": "ABCPK1234D",
                        "abhaId": "12345678901234", "mrn": "MRN-AB12-0042",
                        "insuranceId": "POL-ABC-123", "patientName": "123456789012"},
                       document_id="ids")
    normalize_semantics(ir)
    aadhaar = _one(ir, "$.aadhaarNumber", "identifier_classification")
    assert aadhaar.pii_classification == "aadhaar"
    assert aadhaar.details["status"] == "RESOLVED"
    assert _one(ir, "$.panNumber", "identifier_classification").details["status"] == "RESOLVED"
    assert _one(ir, "$.abhaId", "identifier_classification").details["status"] == "LOW_CONFIDENCE"
    assert _one(ir, "$.mrn", "identifier_classification").details["status"] == "LOW_CONFIDENCE"
    assert _one(ir, "$.insuranceId", "identifier_classification").details["status"] == "LOW_CONFIDENCE"
    assert not _annotations(ir, "$.patientName", "identifier_classification")

    bad = build_json_ir({"aadhaarNumber": valid[:-1] + ("0" if valid[-1] != "0" else "1"),
                         "panNumber": "ABCDE1234F"}, document_id="bad-ids")
    normalize_semantics(bad)
    assert _one(bad, "$.aadhaarNumber", "identifier_classification").details["status"] == "INVALID"
    assert _one(bad, "$.panNumber", "identifier_classification").details["status"] == "INVALID"


def test_clinical_terms_doses_and_units_are_annotated_without_changing_values():
    text = "Parkinson's disease. Ramipril 5 mg; Dolo 650 BD x 5 days; 245 mg/dL; 1-0-1."
    ir = build_json_ir({"clinicalNote": text}, document_id="clinical")
    normalize_semantics(ir)
    findings = ir.annotations["$.clinicalNote"]
    canonical_terms = [item.details.get("canonical_term") for item in findings
                       if item.finding_type == "clinical_term"]
    assert "Parkinson's disease" in canonical_terms
    assert "ramipril" in canonical_terms
    assert "Dolo" in canonical_terms
    abbreviations = [item for item in findings if item.finding_type == "clinical_abbreviation"]
    assert next(item for item in abbreviations if item.details["abbreviation"] == "BD").details["expansion"] == "twice_daily"
    measures = [item.details["value"] for item in findings if item.finding_type == "clinical_measurement"]
    assert {"5 mg", "245 mg/dL", "1-0-1"}.issubset(set(measures))
    assert get_value(ir, "$.clinicalNote") == text


def test_ambiguous_abbreviations_are_not_blindly_expanded():
    cases = {"complaint": "C/O fever", "relativeName": "C/O Ramesh", "c_o_text": "C/O Ramesh", "pt": "PT follow up",
             "dc": "DC", "plain": "BD"}
    ir = build_json_ir(cases, document_id="abbreviations")
    normalize_semantics(ir)
    assert not _annotations(ir, "$.complaint", "person_role")
    assert _one(ir, "$.complaint", "clinical_abbreviation").details["expansion"] == "complaint_of"
    assert _one(ir, "$.relativeName", "clinical_abbreviation").details["expansion"] == "care_of_relative"
    assert _one(ir, "$.relativeName", "person_role").details["role"] == "RELATIVE"
    assert _one(ir, "$.c_o_text", "person_role").details["status"] == "AMBIGUOUS"
    assert _one(ir, "$.pt", "clinical_abbreviation").details["expansion"] is None
    assert _one(ir, "$.dc", "clinical_abbreviation").details["expansion"] is None
    assert _one(ir, "$.plain", "clinical_abbreviation").details["expansion"] is None
    ir2 = build_json_ir({"lab": "PT 14 sec"}, document_id="pt")
    normalize_semantics(ir2)
    assert _one(ir2, "$.lab", "clinical_abbreviation").details["expansion"] == "prothrombin_time"


def test_roles_require_context_markers_and_conflicts_remain_ambiguous():
    source = {"patientName": "Ramesh", "doctorName": "Ramesh", "relativeName": "S/o Ramesh",
              "emergencyContactName": "Asha", "name": "Ramesh", "doctorNamedPatient": "Dr. Ramesh"}
    ir = build_json_ir(source, document_id="roles")
    normalize_semantics(ir)
    assert _one(ir, "$.patientName", "person_role").details["role"] == "PATIENT"
    assert _one(ir, "$.doctorName", "person_role").details["role"] == "DOCTOR"
    assert _one(ir, "$.relativeName", "person_role").details["role"] == "RELATIVE"
    assert _one(ir, "$.emergencyContactName", "person_role").details["role"] == "EMERGENCY_CONTACT"
    assert not _annotations(ir, "$.name", "person_role")
    assert _one(ir, "$.doctorNamedPatient", "person_role").details["status"] == "AMBIGUOUS"
    assert not ir.linkage.matched_records  # Same names never form a match.

    composite = build_json_ir({"patientName": "Asha C/O Ramesh"}, document_id="composite")
    normalize_semantics(composite)
    names = _annotations(composite, "$.patientName", "normalized_name")
    assert [(item.details["canonical_field"], item.details["normalized_value"]) for item in names] == [
        ("patient_name", "Asha"), ("relative_name", "Ramesh")]
    roles = _annotations(composite, "$.patientName", "person_role")
    assert [item.details["role"] for item in roles] == ["PATIENT", "RELATIVE"]


def test_semantic_annotations_are_deterministic_and_do_not_touch_pending_edits():
    ir = build_json_ir({"patientName": " Asha  Devi ", "note": "C/O fever"}, document_id="repeat")
    from src.ir import Annotation, DetectionStatus
    ir.add_annotation(Annotation(annotation_id="DET-1", finding_type="other_detection", locator="$.note",
                                 detection_status=DetectionStatus.DETECTED, details={"kept": True}))
    normalize_ir(ir)
    first = ir.to_deterministic_json()
    pending = dict(ir.pending_edits)
    normalize_ir(ir)
    assert ir.to_deterministic_json() == first
    assert ir.pending_edits == pending == {}
    assert any(item.annotation_id == "DET-1" for item in ir.annotations["$.note"])
    assert ir.structure.data == {"patientName": " Asha  Devi ", "note": "C/O fever"}


def test_clinical_protection_spans_have_original_offsets():
    from src.detection.clinical_protection import protected_spans
    text = "é Ramipril 5 mg, Parkinson’s disease, 1-0-1"
    spans = protected_spans(text)
    assert any(text[item["start"]:item["end"]] == "Ramipril" for item in spans)
    assert any(text[item["start"]:item["end"]] == "5 mg" for item in spans)
    assert any(text[item["start"]:item["end"]] == "Parkinson’s disease" for item in spans)
    assert any(text[item["start"]:item["end"]] == "1-0-1" for item in spans)


def test_csv_header_mapping_and_ragged_missing_cells_use_existing_locators(tmp_path):
    path = tmp_path / "semantic.csv"
    path.write_text("Patient Name,MRN\nAsha,AB12-42\nRavi\n", encoding="utf-8")
    ir = normalize_document_file(str(path), document_id="doc-id", source_identity="hospital-a")
    assert ir.document_id == "doc-id"
    assert ir.source.source_identity == "hospital-a"
    assert _one(ir, "header:col:0", "canonical_field").details["canonical_field"] == "patient_name"
    assert _one(ir, "row:0,col:1", "identifier_classification").details["status"] == "LOW_CONFIDENCE"
    assert _one(ir, "row:1,col:1", "canonical_field").details["canonical_field"] == "mrn"


def test_repeated_generic_columns_use_consensus_and_mark_conflicts_ambiguous(tmp_path):
    consistent = tmp_path / "repeated.csv"
    consistent.write_text("type,value\nemail,a@example.org\nemail,b@example.org\nemail,\n", encoding="utf-8")
    ir = normalize_document_file(str(consistent))
    assert _one(ir, "header:col:1", "canonical_field").details["canonical_field"] == "email"
    assert _one(ir, "row:2,col:1", "canonical_field").details["canonical_field"] == "email"

    mixed = tmp_path / "mixed.csv"
    mixed.write_text("value\na@example.org\n2001-02-03\n", encoding="utf-8")
    mixed_ir = normalize_document_file(str(mixed))
    assert _one(mixed_ir, "header:col:0", "canonical_field").details["status"] == "AMBIGUOUS"
    assert _one(mixed_ir, "row:0,col:0", "canonical_field").details["status"] == "AMBIGUOUS"


def test_fhir_and_xml_contextual_names_and_canonical_locators(tmp_path):
    fhir = {"resourceType": "Bundle", "type": "document", "entry": [
        {"resource": {"resourceType": "Patient", "name": [{"given": ["Asha"], "family": "Devi"}]}}
    ]}
    fhir_path = tmp_path / "bundle.json"
    fhir_path.write_text(json.dumps(fhir), encoding="utf-8")
    ir = normalize_document_file(str(fhir_path))
    given_locator = "$.entry[0].resource.name[0].given[0]"
    assert _one(ir, given_locator, "canonical_field").details["canonical_field"] == "patient_name"
    assert _one(ir, given_locator, "person_role").details["role"] == "PATIENT"

    fhir["entry"].append({"resource": {"resourceType": "Practitioner", "name": [
        {"given": ["Ramesh"], "family": "Doctor"}]}})
    fhir_path.write_text(json.dumps(fhir), encoding="utf-8")
    provider_ir = normalize_document_file(str(fhir_path))
    provider_name = "$.entry[1].resource.name[0].given[0]"
    assert _one(provider_ir, provider_name, "canonical_field").details["canonical_field"] == "doctor_name"
    assert _one(provider_ir, provider_name, "person_role").details["role"] == "DOCTOR"

    xml_path = tmp_path / "people.xml"
    xml_path.write_text("<record><doctorName>Dr. Ramesh</doctorName></record>", encoding="utf-8")
    xml_ir = normalize_document_file(str(xml_path))
    assert any(item.finding_type == "person_role" and item.details["role"] == "DOCTOR"
               for items in xml_ir.annotations.values() for item in items)
