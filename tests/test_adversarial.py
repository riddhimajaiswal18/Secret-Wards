"""Adversarial tests ported from the standalone scaffold, so one repo carries all the coverage.

These encode failure modes that cost real points during development: a raw copy, a canary in a
filename, a symlink escape, a malformed file that takes the batch down. Each one is a regression
test first and a bug report second.
"""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.ingestion.file_router import parse_document_file
from src.output.writer import write_submission
from src.security.safe_logging import leak_scan, safe_write

ROOT = Path(__file__).resolve().parents[1]


def write(root: Path, rel: str, data: bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def submit(tmp_path: Path) -> dict:
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    inputs.mkdir(exist_ok=True)
    report = write_submission(inputs, outputs)
    return report


# ── the writer is the only path to disk ─────────────────────────────────────
def test_traversal_is_refused(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError):
        safe_write(out, "../escape.txt", b"x")


def test_symlink_write_is_refused(tmp_path):
    out, elsewhere = tmp_path / "out", tmp_path / "elsewhere"
    (out / "sub").mkdir(parents=True)
    elsewhere.mkdir()
    os.symlink(elsewhere, out / "sub" / "dir")
    with pytest.raises(ValueError):
        safe_write(out, "sub/dir/x.txt", b"x")


# ── leak scan covers every channel ──────────────────────────────────────────
def test_leak_scan_finds_content_and_filename(tmp_path):
    write(tmp_path / "out", "a.txt", b"patient Kaveri Nambiar seen")
    write(tmp_path / "out", "Kaveri_Nambiar_note.txt", b"clean")
    hits = leak_scan(tmp_path / "out", ["Kaveri Nambiar"])
    assert any(h[1] == "Kaveri Nambiar" for h in hits)
    assert any(h[1].startswith("filename:") for h in hits)


# ── accounting and quarantine ───────────────────────────────────────────────
def test_quarantine_never_writes_a_copy(tmp_path):
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    write(inputs, "scan.pdf", b"%PDF-1.4 secret bytes")
    report = write_submission(inputs, outputs)
    assert report["counts"]["files_quarantined"] == 1
    assert not (outputs / "sanitized" / "scan.pdf").exists()


def test_binary_named_as_text_is_quarantined(tmp_path):
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    write(inputs, "note.txt", b"%PDF-1.4\n" + b"x" * 200)
    report = write_submission(inputs, outputs)
    entry = report["files"][0]
    assert entry["status"] == "quarantined" and entry["reason"] == "binary-pdf"


def test_duplicate_basenames_both_survive(tmp_path):
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    write(inputs, "h1/opd.csv", b"a,b\n1,2\n")
    write(inputs, "h2/opd.csv", b"a,b\n3,4\n")
    report = write_submission(inputs, outputs)
    assert report["counts"]["files_sanitized"] == 2
    outputs_seen = {entry.get("output") for entry in report["files"]}
    assert len(outputs_seen) == 2


def test_report_never_contains_input_values(tmp_path):
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    write(inputs, "n.txt", "Patient Kaveri Nambiar phone 8599253525".encode())
    write_submission(inputs, outputs)
    blob = (outputs / "report.json").read_text(encoding="utf-8")
    assert "Kaveri" not in blob and "8599253525" not in blob


def test_report_never_contains_pii_bearing_input_filename(tmp_path):
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    write(inputs, "notes/Ritara_Qemvi_9820001111.txt", b"clinical reference only")
    write_submission(inputs, outputs)
    blob = (outputs / "report.json").read_text(encoding="utf-8")
    report = json.loads(blob)
    assert "Ritara" not in blob and "Qemvi" not in blob and "9820001111" not in blob
    assert all("path" not in entry for entry in report["files"])
    assert report["schema"] == "raksha-report/1"


def test_quarantine_report_omits_original_filename(tmp_path):
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    write(inputs, "unsafe/Ritara_Qemvi_9820001111.xyz", b"unsupported")
    write_submission(inputs, outputs)
    blob = (outputs / "report.json").read_text(encoding="utf-8")
    report = json.loads(blob)
    assert "Ritara" not in blob and "Qemvi" not in blob and "9820001111" not in blob
    assert report["files"][0]["status"] == "quarantined"
    assert report["files"][0]["output"] is None
    assert "path" not in report["quarantine"][0]


def test_contextual_relative_names_keep_clinical_complaints():
    from src.detection.engine import find
    from src.detection.protection import ProtectionIndex

    index = ProtectionIndex()
    examples = {
        "C/O Ramesh": "[RELATIVE]",
        "C/O fever": "C/O fever",
        "K/C/O diabetes": "K/C/O diabetes",
        "S/o ram kumar": "[RELATIVE]",
    }
    from src.policy import engine as policy_engine
    tokens = policy_engine.resolve_tokens(None)
    from src.detection.engine import redact
    for source, expected in examples.items():
        output, _ = redact(source, index, tokens)
        if expected == "[RELATIVE]":
            assert output != source, source
        else:
            assert output == expected


def test_explicit_labels_capture_single_names_and_address_values():
    from src.detection.engine import redact
    from src.detection.protection import ProtectionIndex

    index = ProtectionIndex()
    text = "Patient Name: Niral\nVillage: Hariyapur\nPIN: 560001"
    output, counts = redact(text, index, {
        "NAME": "[NAME]", "VILLAGE": "[VILLAGE]", "PIN": "[PIN]",
        "PHONE": "[PHONE]", "RELATIVE": "[RELATIVE]",
    })
    assert "Niral" not in output
    assert "Hariyapur" not in output
    assert "560001" not in output
    assert counts.get("NAME") and counts.get("VILLAGE") and counts.get("PIN")


def test_missing_input_directory_exits_two(tmp_path):
    code = subprocess.call([sys.executable, str(ROOT / "main.py"), "--input",
                            str(tmp_path / "absent"), "--output", str(tmp_path / "o")],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert code == 2


# ── determinism ────────────────────────────────────────────────────────────
def test_two_runs_are_byte_identical(tmp_path):
    inputs = tmp_path / "in"
    write(inputs, "a/x.csv", b"name,age\nSunita,54\n")
    write(inputs, "b/y.json", b'{"resourceType":"Patient","id":"1"}')
    write(inputs, "c/n.txt", "Patient Ramesh Patel 9812345678".encode())
    first, second = tmp_path / "o1", tmp_path / "o2"
    write_submission(inputs, first)
    write_submission(inputs, second)
    rel_first = sorted(p.relative_to(first).as_posix() for p in first.rglob("*") if p.is_file())
    rel_second = sorted(p.relative_to(second).as_posix() for p in second.rglob("*") if p.is_file())
    assert rel_first == rel_second
    for rel in rel_first:
        if rel in {"report.json", "records.jsonl"}:
            continue
        assert (first / rel).read_bytes() == (second / rel).read_bytes(), rel


# ── parsing edges ──────────────────────────────────────────────────────────
def test_single_column_csv_stays_tabular(tmp_path):
    path = write(tmp_path, "names.csv", b"patient\nSunita Patel\nMohd Shahid\n")
    ir = parse_document_file(path)
    assert ir.source.format == "csv" and len(ir.structure.data["rows"]) == 2


def test_crlf_and_bom_are_preserved(tmp_path):
    raw = b"\xef\xbb\xbfname,note\r\nPatel,stable\r\n"
    path = write(tmp_path, "w.csv", raw)
    ir = parse_document_file(path)
    assert ir.structure.data["header"] == ["name", "note"]
    assert ir.structure.original_layout.get("bom") is True
    assert ir.structure.original_layout.get("lineterminator") == "\r\n"


def test_cp1252_is_decoded_not_dropped(tmp_path):
    path = write(tmp_path, "note.txt", "Patient Andrée discharged".encode("cp1252"))
    ir = parse_document_file(path)
    assert ir.validation.parse_status == "SUCCESS"
    assert "Andrée" in ir.structure.data


def test_deep_json_is_quarantined_not_crashing(tmp_path):
    path = write(tmp_path, "deep.json", ("{\"a\":" * 400 + "1" + "}" * 400).encode())
    ir = parse_document_file(path)
    assert ir.validation.parse_status.startswith("ERROR")


def test_truncated_json_is_quarantined(tmp_path):
    path = write(tmp_path, "opd.json", b'{"patients": [{"name": "Sunita Pa')
    ir = parse_document_file(path)
    assert ir.validation.parse_status.startswith("ERROR")


def test_non_finite_numbers_are_rejected(tmp_path):
    """NaN and Infinity are Python extensions; re-emitting them yields invalid JSON."""
    path = write(tmp_path, "nan.json", b'{"bp": NaN, "temp": Infinity}')
    ir = parse_document_file(path)
    assert ir.validation.parse_status.startswith("ERROR")


def test_error_reason_is_specific_not_generic(tmp_path):
    path = write(tmp_path, "deep.json", ("{\"a\":" * 400 + "1" + "}" * 400).encode())
    ir = parse_document_file(path)
    assert ir.validation.parse_status == "ERROR:depth_limit_exceeded"


# ── end-to-end accounting ──────────────────────────────────────────────────
def test_every_input_file_gets_exactly_one_fate(tmp_path):
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    write(inputs, "ok.csv", b"a,b\n1,2\n")
    write(inputs, "bad.json", b'{"a":')
    write(inputs, "x.pdf", b"%PDF-1.4")
    report = write_submission(inputs, outputs)
    assert len(report["files"]) == 3
    statuses = sorted(entry["status"] for entry in report["files"])
    assert statuses == ["quarantined", "quarantined", "sanitized"]
    assert all(entry["input_sha256"] and "path" not in entry for entry in report["files"])
    assert report["counts"]["files_total"] == 3


def test_json_record_arrays_use_pointer_locators_and_embed_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("RAKSHA_SECRET", "test-secret-json")
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    write(inputs, "visits.json", json.dumps({"visits": [
        {"uhid": "JJH-0077112", "patient_ref": "JJH-0077112",
         "patient_name": "Sunita Patel"},
        {"uhid": "JJH-0099999", "patient_ref": "JJH-0099999",
         "patient_name": "Mohd Shahid"},
    ]}).encode())
    write_submission(inputs, outputs)
    rows = [json.loads(line) for line in
            (outputs / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["loc"] for row in rows] == ["/visits/0", "/visits/1"]
    assert len({row["patient"] for row in rows}) == 2
    produced = json.loads((outputs / "sanitized" / "visits.json").read_text(encoding="utf-8"))
    assert [visit["patient_ref"] for visit in produced["visits"]] == [
        row["patient"] for row in rows]


def test_fhir_patient_name_is_scrubbed_and_practitioner_is_preserved(tmp_path):
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    bundle = {
        "resourceType": "Bundle", "type": "collection",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "JJH-0077112",
                          "identifier": [{"system": "urn:mrn", "value": "JJH-0077112"}],
                          "name": [{"text": "Sunita Patel"}]}},
            {"resource": {"resourceType": "Practitioner", "id": "d1",
                          "name": [{"text": "Dr. Ramesh Kumar"}]}},
            {"resource": {"resourceType": "Condition", "id": "c1",
                          "subject": {"reference": "Patient/JJH-0077112"}}},
        ],
    }
    write(inputs, "bundle.json", json.dumps(bundle).encode())
    write_submission(inputs, outputs)
    produced = json.loads((outputs / "sanitized" / "bundle.json").read_text(encoding="utf-8"))
    patient, practitioner, condition = [entry["resource"] for entry in produced["entry"]]
    assert "Sunita" not in json.dumps(patient)
    assert "Dr. Ramesh Kumar" in json.dumps(practitioner)
    assert patient["id"] != "JJH-0077112"
    assert condition["subject"]["reference"] == f"Patient/{patient['id']}"


def test_nested_json_name_and_address_context_is_sanitized(tmp_path):
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    payload = {"patients": [{
        "uhid": "JJH-0077112",
        "name": {"first": "Sunita", "last": "Patel"},
        "address": {"line": ["House 22, Main Road"], "city": "Lucknow"},
    }]}
    write(inputs, "patients.json", json.dumps(payload).encode())
    write_submission(inputs, outputs)
    produced = json.loads((outputs / "sanitized" / "patients.json").read_text(encoding="utf-8"))
    rendered = json.dumps(produced)
    assert "Sunita" not in rendered and "Patel" not in rendered
    assert "House 22" not in rendered and "Lucknow" not in rendered


# ── identity keys, not label keys ───────────────────────────────────────────
def test_identity_key_map_is_renamed_without_collapsing(tmp_path):
    """`{"Sunita Patel": "UHID-1"}` leaks through the key, not the value.

    Regression for the key channel (measured 41.7% -> 0.0%): the value path replaced the UHID and
    `continue`d before the key was ever examined, so the name survived as a JSON key.
    """
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    payload = {"by_name": {"Sunita Patel": "JJH-1", "Mohd Shahid": "JJH-2",
                           "Anita Sharma": "JJH-3"}}
    write(inputs, "patient_index.json", json.dumps(payload).encode())
    write_submission(inputs, outputs)
    produced = json.loads((outputs / "sanitized" / "patient_index.json").read_text())
    keys = list(produced["by_name"])
    assert not any(name.split()[0] in k for name in payload["by_name"] for k in keys), keys
    assert len(keys) == 3, "distinct identities must not collapse into one key"


def test_label_keys_survive(tmp_path):
    """Structural label keys carry meaning for downstream consumers and must not be renamed."""
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    write(inputs, "row.json", json.dumps({"patient_name": "Sunita Patel",
                                          "hospital": "JJH", "visits": 3}).encode())
    write_submission(inputs, outputs)
    produced = json.loads((outputs / "sanitized" / "row.json").read_text())
    assert set(produced) >= {"patient_name", "hospital", "visits"}
