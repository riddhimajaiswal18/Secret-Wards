"""Tests for the detection → policy → structural chain.

These encode the traps that cost medical points during development, so a later change cannot
silently reintroduce them.
"""
from __future__ import annotations

import pytest

from src.detection import columns
from src.detection.engine import build_edits, find, redact
from src.detection.identifiers import scrub
from src.detection.paths import sanitise_path
from src.detection.protection import ProtectionIndex, is_institution
from src.detection.structural import sanitise_structure
from src.ingestion.file_router import parse_document_file
from src.policy.engine import DEFAULT_TOKENS, evaluate


@pytest.fixture()
def index() -> ProtectionIndex:
    idx = ProtectionIndex()
    idx.lexicon.update({"paracetamol", "metformin", "dengue", "ceftriaxone", "platelets"})
    idx.places.update({"rae bareli", "hardoi", "lucknow", "sitapur"})
    return idx


def kinds(text: str, idx: ProtectionIndex) -> list[str]:
    return [finding.kind for finding in find(text, idx)]


# ── identifiers ─────────────────────────────────────────────────────────────
def test_identifier_shapes(index):
    assert "UHID" in kinds("UHID-010610 seen", index)
    assert "UHID" in kinds("JJH-0077112 Zainab", index)          # 7 digits must not be trunc
    assert "UHID" in kinds("IP/26/00130", index)
    assert "PHONE" in kinds("Mob 9812345678", index)
    assert "AADHAAR" in kinds("uid 1234 5678 9012", index)


def test_vitals_are_not_identifiers(index):
    for clinical in ("BP 117/82", "PR 88/min", "Hb 10.2 g/dL", "Platelets 84,000/µL",
                     "Temp 37.6 C", "Weight 68 kg"):
        assert find(clinical, index) == [], clinical


def test_devanagari_digits_are_folded(index):
    assert "PHONE" in kinds("मोबाइल ९८१२३४५६७८", index)


# ── clinical protection ─────────────────────────────────────────────────────
def test_protection_keeps_doses_and_durations(index):
    text = "Tab. Paracetamol 650 mg TDS x 3 days"
    assert redact(text, index, DEFAULT_TOKENS)[0] == text


def test_devanagari_complaint_is_not_a_name(index):
    text = "6 दिन से बुखार और उल्टी"
    assert redact(text, index, DEFAULT_TOKENS)[0] == text


def test_institutions_and_places_survive(index):
    assert is_institution("Jeevan Jyoti Charitable Hospital")
    assert redact("Jeevan Jyoti Charitable Hospital", index, DEFAULT_TOKENS)[0] == \
        "Jeevan Jyoti Charitable Hospital"
    assert redact("Rae Bareli", index, DEFAULT_TOKENS)[0] == "Rae Bareli"


def test_clinician_role_is_kept(index):
    text = "Dr. Vandana Kulshrestha reviewed the case"
    assert redact(text, index, DEFAULT_TOKENS)[0] == text


# ── names ───────────────────────────────────────────────────────────────────
def test_anchored_and_bare_names_are_redacted(index):
    assert redact("Name: Sunita Patel", index, DEFAULT_TOKENS)[0] == "Name: [NAME]"
    assert redact("S/o Ramesh Patel", index, DEFAULT_TOKENS)[0] == "S/o [RELATIVE]"
    assert "[NAME]" in redact("admitted; Anita Deshmukh stable", index, DEFAULT_TOKENS)[0]


# ── structural ──────────────────────────────────────────────────────────────
def test_column_labels_map_and_clinical_columns_do_not():
    assert columns.classify("Patient Name") == "NAME"
    assert columns.classify("Relative Name") == "RELATIVE"
    assert columns.classify("MRN") == "UHID"
    assert columns.classify("DOB") == "DOB"
    assert columns.classify("District") is None          # utility, kept
    assert columns.classify("Diagnosis") is None
    assert columns.classify("Dose") is None


def test_paths_lose_identity_but_keep_shape(index, tmp_path):
    safe, counts = sanitise_path("discharge/Discharge_Summary_Anita_Deshmukh_SNJ-26-064508.txt",
                                 index)
    assert "Anita" not in safe and "Deshmukh" not in safe
    assert safe.endswith(".txt")
    assert counts


def test_headers_and_keys_are_sanitised(index, tmp_path):
    source = tmp_path / "vitals.csv"
    source.write_text("time,JJH-0077112 Zainab\n06:00,108/92\n", encoding="utf-8")
    ir = parse_document_file(source, document_id="d1")
    counts = sanitise_structure(ir, index, DEFAULT_TOKENS)
    assert ir.structure.data["header"][1] == "[UHID]"
    assert counts

    payload = tmp_path / "index.json"
    payload.write_text('{"Anita_Sharma": {"mrn": "010565"}}', encoding="utf-8")
    ir2 = parse_document_file(payload, document_id="d2")
    sanitise_structure(ir2, index, DEFAULT_TOKENS)
    assert all("Anita" not in key for key in ir2.structure.data)


# ── contract of the edit layer ──────────────────────────────────────────────
def test_edits_are_locator_addressed_and_preconditioned(index, tmp_path):
    source = tmp_path / "reg.csv"
    source.write_text("MRN,Patient Name\n010565,Anita Sharma\n", encoding="utf-8")
    ir = parse_document_file(source, document_id="d3")
    evaluate(ir, index)
    assert set(ir.pending_edits) == {"row:0,col:0", "row:0,col:1"}
    for edits in ir.pending_edits.values():
        for edit in edits:
            assert edit.expected_value                     # guards against editing the wrong cell


def test_text_edits_do_not_overlap(index):
    text = "Name: Sunita Patel, S/o Ramesh Patel"
    findings = find(text, index)
    assert all(not (a.start < b.end and b.start < a.end)
               for a, b in zip(findings, findings[1:]))


def test_scrubber_matches_engine_vocabulary():
    cleaned, counts = scrub("Mob 9812345678 UHID-010610")
    assert "9812345678" not in cleaned and "010610" not in cleaned
    assert counts
