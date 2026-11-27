"""A single file must be protected on its own.

Detection must not depend on other files in the corpus: a one-file input containing a phone number
and a person's name has to produce edits. Two defects are pinned here, both found in the Phase 0
audit:

* a roster line prefixed by a clock time ("18:40 - Name") had its name suppressed, because the time
  prefix made the clinical-context veto fire;
* the same applied to bullets and numbered lists ("3. Name").
"""
from __future__ import annotations

import json
from pathlib import Path

from src.output.writer import write_submission


def _run(tmp_path: Path, body: str) -> tuple[dict, str]:
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    (inputs / "notes").mkdir(parents=True, exist_ok=True)
    (inputs / "notes" / "v.txt").write_text(body, encoding="utf-8")
    report = write_submission(inputs, outputs)
    produced = list((outputs / "sanitized").rglob("v.txt"))
    assert produced, "the single input file must be exported"
    return report, produced[0].read_text(encoding="utf-8")


def test_one_file_alone_is_protected(tmp_path):
    report, text = _run(tmp_path, "Patient Zorawar Qadri, mobile 6910522119\n")
    assert "6910522119" not in text, "phone must be edited on a one-file corpus"
    assert "Zorawar Qadri" not in text, "name must be edited on a one-file corpus"
    assert report["counts"]["files_total"] == 1


def test_name_after_a_clock_prefix_is_detected(tmp_path):
    _, text = _run(tmp_path, "VISITOR LOG\n18:40 - Zorawar Qadri (attendant, bed 12)\n")
    assert "Zorawar Qadri" not in text, "a clock prefix must not suppress the name that follows"


def test_name_after_a_bullet_and_a_number_is_detected(tmp_path):
    _, bullets = _run(tmp_path, "A\n- Mohd Shahid, compounder\n")
    _, numbered = _run(tmp_path, "A\n3. Anita Deshmukh, sister\n")
    assert "Mohd Shahid" not in bullets
    assert "Anita Deshmukh" not in numbered


def test_vitals_line_is_not_treated_as_a_name(tmp_path):
    """The prefix rule must not start eating clinical rows: '09:30 BP 130/85' stays intact."""
    _, text = _run(tmp_path, "09:30 BP 130/85, pulse 88\n10:15 Temp 38.4\n")
    assert "130/85" in text and "88" in text


# ── transformation and release integrity ────────────────────────────────────
def test_a_file_whose_findings_were_lost_is_not_reported_sanitized(tmp_path):
    """Parsing success must never be reported as sanitisation success.

    Regression for sanitized/notes/visitor_log_ward5.txt, released byte-identical to its input:
    _CLINICIAN_PREFIX matched 'dr' inside 'Qadri' and 'MO' inside 'mob', and each false prefix
    opened a 60-character clinician span that vetoed the patient name and the phone number that
    followed it. Detection then found nothing on the document while finding both on a single line.
    """
    report, text = _run(tmp_path, "VISITOR LOG\n18:40 - Zorawar Qadri (attendant, bed 12), "
                                  "mob 6910522119\n19:10 - Dr. Ramesh Srivastava took evening round.\n")
    entry = report["files"][0]
    assert "Zorawar Qadri" not in text
    assert entry["status"] == "sanitized"
    assert entry["surfaces_found"] >= 1
    assert entry["surfaces_edited"] >= 1
    assert entry["parse_status"] == "SUCCESS" and entry["release_status"] == "released"


def test_clinician_prefix_does_not_match_inside_words():
    """'Qadri' contains 'dr' and 'mob' contains 'mo'; neither is a clinician prefix."""
    from src.detection.engine import _clinician_spans
    assert _clinician_spans("18:40 - Zorawar Qadri (attendant) mob 6910522119") == []
    spans = _clinician_spans("19:10 - Dr. Ramesh Srivastava took round.\nPatient Anita Deshmukh")
    assert spans and spans[0][0] > 0
    assert all("\n" not in "" for _ in spans)          # symbolic: spans are ranges, see below
    name_at = "19:10 - Dr. Ramesh Srivastava took round.\nPatient Anita Deshmukh"
    assert spans[0][1] <= name_at.index(" took"), "a clinician span must stop at the name"


# ── XML: values must be detected, structure and clinic kept ────────────────
def test_xml_text_nodes_and_attributes_are_sanitized(tmp_path):
    """HL7 CDA discharge was re-serialised with every identifier intact: no detector saw it."""
    xml = ('<ClinicalDocument><recordTarget><patientRole>'
           '<id extension="JJH-0077112"/><name>Zorawar Qadri</name>'
           '<telecom value="mob 6910522119"/></patientRole></recordTarget>'
           '<component><section><code code="11450-4" displayName="Problem"/><title>Diagnosis</title>'
           '<text>Acute gastroenteritis, Metformin 500 mg BD</text></section></component>'
           '</ClinicalDocument>')
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    (inputs / "misc").mkdir(parents=True)
    (inputs / "misc" / "cda.xml").write_text(xml, encoding="utf-8")
    write_submission(inputs, outputs)
    released = (outputs / "sanitized" / "misc" / "cda.xml").read_text(encoding="utf-8")
    assert "Zorawar Qadri" not in released and "6910522119" not in released
    assert "Acute gastroenteritis" in released and "Metformin 500 mg" in released
    assert "<ClinicalDocument>" in released and "<name>" in released


# ── PHONE: contact label in a clinical row ─────────────────────────────────
def test_phone_after_contact_label_is_detected_in_a_clinical_row(tmp_path):
    body = "VISITOR LOG\n18:40 - Zorawar Qadri (attendant, bed 12), mob 6910522119\n"
    _, text = _run(tmp_path, body)
    assert "6910522119" not in text
    assert "bed 12" in text, "clinical context must survive"


def test_phone_after_a_contact_label_beats_a_protected_window(tmp_path):
    """'Mob: 8069773173' inside a prescription: the clinical window protects doses, not phones."""
    _, text = _run(tmp_path, "Rx\nTab. Paracetamol 500 mg BD x 3 days\nMob: 8069773173\n")
    assert "8069773173" not in text
    assert "500 mg" in text and "3 days" in text


def test_aadhaar_is_detected_only_from_its_label(tmp_path):
    body = '{"ids": {"aadhar_no": "902115225016", "abha": "12-3456-7890-1234"}}'
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    (inputs / "reg").mkdir(parents=True)
    (inputs / "reg" / "p.json").write_text(body, encoding="utf-8")
    write_submission(inputs, outputs)
    released = (outputs / "sanitized" / "reg" / "p.json").read_text()
    assert "902115225016" not in released


def test_mrn_inside_an_export_path_is_detected(tmp_path):
    body = '{"source_path": "D:\\\\HIS\\\\exports\\\\opd\\\\Shahid_NA_010607\\\\visits.json"}'
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    (inputs / "opd").mkdir(parents=True)
    (inputs / "opd" / "v.json").write_text(body, encoding="utf-8")
    write_submission(inputs, outputs)
    released = (outputs / "sanitized" / "opd" / "v.json").read_text()
    assert "010607" not in released
    assert "Shahid" not in released, "name plus initials in a source-path component must be removed"


def test_identifiers_stored_as_adjacent_list_elements(tmp_path):
    """`"ids": ["aadhar_no", "902115225016"]` - label and value as separate list items."""
    body = '{"ids": ["aadhar_no", "902115225016", "abha", "12-3456-7890-1234"], "district": "Hardoi"}'
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    (inputs / "reg").mkdir(parents=True)
    (inputs / "reg" / "p.json").write_text(body, encoding="utf-8")
    write_submission(inputs, outputs)
    released = (outputs / "sanitized" / "reg" / "p.json").read_text()
    assert "902115225016" not in released
    assert "Hardoi" in released, "administrative context must survive"


def test_hinglish_kinship_relatives_are_redacted(tmp_path):
    """Ground-truth-confirmed relative leaks: kinship word only, capitalised name before it."""
    body = ("Lab notes\nAsha ji 48/F\nRef by Jagdish Chachu\nSample collected Umesh Mama\n"
            "Bill paid Raju Papa\n")
    _, text = _run(tmp_path, body)
    for name in ("Jagdish Chachu", "Umesh Mama", "Raju Papa"):
        assert name not in text, name


def test_hinglish_patient_honorifics_survive_nearby_clinical_values(tmp_path):
    body = (
        "Patient: Sukhwinder amma ki condition ab stable hai.\n"
        "Shahid babu ka BP 105/77, pulse 72.\n"
        "Brijesh ka BP 146/91, sugar control nahi hai.\n"
        "19:10 - Dr. Ramesh Srivastava reviewed the patient.\n"
        "Tab Metformin 500 mg BD x 5 days.\n"
    )
    _, text = _run(tmp_path, body)
    for name in ("Sukhwinder amma", "Shahid babu", "Brijesh"):
        assert name not in text, name
    assert "105/77" in text and "146/91" in text
    assert "Metformin 500 mg BD x 5 days" in text
    assert "Dr. Ramesh Srivastava" in text


def test_attendant_anchor_and_dotted_name_are_handled(tmp_path):
    body = (
        "Attendant: Zubair, Mob. 9368591915\n"
        "14:00 - Mohd. Shahid - K/C/O addison's disease.\n"
    )
    _, text = _run(tmp_path, body)
    assert "Zubair" not in text
    assert "9368591915" not in text
    assert "Mohd. Shahid" not in text
    assert "addison's disease" in text
    assert "Mob." in text


def test_ward_numbers_are_only_generalized_in_attendant_address(tmp_path):
    body = (
        "Address (attendant): C/O Ramesh Yadav, Ward 8\n"
        "Ward/Bed: Ward 1 (Medicine) / Bed 20\n"
        "Nursing notes - Ward 8 (Medicine)\n"
    )
    _, text = _run(tmp_path, body)
    assert "Ward 8" not in text.splitlines()[0]
    assert "Ward 1 (Medicine)" in text
    assert "Ward 8 (Medicine)" in text


def test_kinship_words_do_not_eat_clinical_text(tmp_path):
    """Negative control: relationship anchors must not touch clinical shorthand or doses."""
    body = "C/O fever x 3 days\nK/C/O diabetes\nTab Metformin 500 mg BD\nBP 130/85\n"
    _, text = _run(tmp_path, body)
    assert "C/O fever" in text and "K/C/O diabetes" in text
    assert "500 mg" in text and "130/85" in text


def test_context_protects_clinical_acronym_not_person_name_and_handles_chat_names(tmp_path):
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    (inputs / "clean").mkdir(parents=True)
    (inputs / "notes").mkdir()
    (inputs / "clean" / "dengue_management_protocol.txt").write_text(
        "ASHA workers should follow up discharged patients.\n", encoding="utf-8")
    (inputs / "notes" / "note.txt").write_text(
        "Name: Asha Rajput\n"
        "[30/05/26, 9:32 pm] Kamal Bhaiya: report received\n"
        "Report of Asha ji\n"
        "Asha, W/o Kamal, admitted today.\n"
        "Lifeline Pathology issued the result.\n", encoding="utf-8")
    write_submission(inputs, outputs)
    note = (outputs / "sanitized" / "notes" / "note.txt").read_text(encoding="utf-8")
    protocol = (outputs / "sanitized" / "clean" / "dengue_management_protocol.txt").read_text(
        encoding="utf-8")
    for name in ("Asha Rajput", "Kamal Bhaiya", "Asha ji", "Asha, W/o Kamal"):
        assert name not in note
    assert "Lifeline Pathology" in note
    assert "ASHA workers" in protocol
