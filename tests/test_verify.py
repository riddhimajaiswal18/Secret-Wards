"""Adversarial tests for the independent release verifier.

Both directions are measured on purpose: a verifier that never fails is useless, and a verifier that
fails on clinical values would destroy utility. Each positive case has a matching negative case.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.verify import candidate_identifiers, verify_tree


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def build(tmp_path: Path, *, inputs: dict[str, str], released: dict[str, str],
          entries: list[dict] | None = None, missing: list[str] | None = None):
    inp, out = tmp_path / "in", tmp_path / "out"
    for rel, body in inputs.items():
        _write(inp, rel, body)
    for rel, body in released.items():
        _write(out / "sanitized", rel, body)
    if entries is None:
        entries = [{"path": rel, "status": "sanitized", "output": f"sanitized/{rel}",
                    "parse_status": "SUCCESS", "detection_status": "completed",
                    "surfaces_found": 1, "surfaces_edited": 1, "release_status": "released"}
                   for rel in released]
    report = {"files": entries, "quarantine": [], "counts": {},
              "capabilities": {"missing": missing or [], "available": []}}
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return inp, out


# ── negatives: clean output passes ──────────────────────────────────────────
def test_clean_output_passes(tmp_path):
    inp, out = build(tmp_path,
                     inputs={"notes/a.txt": "Patient Sunita Patel, mob 6910522119"},
                     released={"notes/a.txt": "Patient [NAME], mob [PHONE]"})
    result = verify_tree(inp, out)
    assert result["overall"] == "passed", result["checks"]


def test_clinical_values_are_not_treated_as_identifiers(tmp_path):
    """False-positive guard: a verdict that eats vitals or doses would be unusable."""
    body = "BP 130/85, pulse 88, Temp 38.4, Metformin 500 mg BD for 5 days"
    inp, out = build(tmp_path, inputs={"notes/b.txt": body}, released={"notes/b.txt": body})
    result = verify_tree(inp, out)
    assert result["overall"] == "passed", result["checks"]
    assert candidate_identifiers(body) == [] or all(
        kind != "NAME" for kind, _ in candidate_identifiers(body))


def test_clinician_names_are_not_reported_as_patient_leaks(tmp_path):
    body = "19:10 - Dr. Ramesh Srivastava took evening round."
    inp, out = build(tmp_path, inputs={"notes/c.txt": body}, released={"notes/c.txt": body})
    assert verify_tree(inp, out)["overall"] == "passed"


# ── positives: each leak class must fail ───────────────────────────────────
def test_reintroduced_name_fails(tmp_path):
    inp, out = build(tmp_path, inputs={"notes/a.txt": "Patient Sunita Patel"},
                     released={"notes/a.txt": "Patient Sunita Patel"})
    result = verify_tree(inp, out)
    assert result["overall"] == "failed"
    assert result["checks"]["surviving_identifiers"]["status"] == "failed"


def test_reintroduced_phone_fails(tmp_path):
    inp, out = build(tmp_path, inputs={"notes/a.txt": "mob 6910522119"},
                     released={"notes/a.txt": "mob 6910522119"})
    assert verify_tree(inp, out)["overall"] == "failed"


def test_identifier_in_filename_fails(tmp_path):
    inp, out = build(tmp_path, inputs={"notes/Sunita Patel.txt": "clean line"},
                     released={"notes/Sunita Patel.txt": "clean line"})
    result = verify_tree(inp, out)
    assert result["overall"] == "failed"


def test_identifier_in_json_key_fails(tmp_path):
    payload = '{"by_name": {"Sunita Patel": "JJH-0077112"}}'
    inp, out = build(tmp_path, inputs={"misc/index.json": payload},
                     released={"misc/index.json": payload})
    assert verify_tree(inp, out)["overall"] == "failed"


def test_unaccounted_input_file_fails(tmp_path):
    inp, out = build(tmp_path, inputs={"a.txt": "x", "b.txt": "y"}, released={"a.txt": "x"},
                     entries=[{"path": "a.txt", "status": "sanitized", "output": "sanitized/a.txt"}])
    result = verify_tree(inp, out)
    assert result["overall"] == "failed"
    assert result["checks"]["accounting"]["unaccounted"] == ["b.txt"]


def test_phantom_reported_file_fails(tmp_path):
    inp, out = build(tmp_path, inputs={"a.txt": "x"}, released={"a.txt": "x"},
                     entries=[{"path": "a.txt", "status": "sanitized", "output": "sanitized/a.txt"},
                              {"path": "ghost.txt", "status": "sanitized",
                               "output": "sanitized/ghost.txt"}])
    assert verify_tree(inp, out)["overall"] == "failed"


def test_unchanged_output_carrying_identifiers_fails(tmp_path):
    body = "Patient Sunita Patel, Aadhaar 1234 5678 9012"
    inp, out = build(tmp_path, inputs={"a.txt": body}, released={"a.txt": body})
    result = verify_tree(inp, out)
    assert result["overall"] == "failed"
    assert result["checks"]["unchanged_outputs"]["status"] == "failed"


def test_verifier_does_not_trust_the_sanitizer_report(tmp_path):
    """The entry claims nothing was found; the bytes say otherwise. Bytes win."""
    inp, out = build(tmp_path, inputs={"a.txt": "Patient Sunita Patel"},
                     released={"a.txt": "Patient Sunita Patel"},
                     entries=[{"path": "a.txt", "status": "sanitized", "output": "sanitized/a.txt",
                               "surfaces_found": 0, "surfaces_edited": 0}])
    assert verify_tree(inp, out)["overall"] == "failed"


def test_required_capability_missing_fails(tmp_path):
    inp, out = build(tmp_path, inputs={"a.txt": "x"}, released={"a.txt": "x"},
                     missing=["pdf_render"])
    result = verify_tree(inp, out, require_caps=("pdf_render",))
    assert result["overall"] == "failed"
    assert result["checks"]["capabilities"]["unmet"] == ["pdf_render"]


def test_binary_output_is_unsupported_not_passed(tmp_path):
    inp, out = build(tmp_path, inputs={"scan.pdf": "text"}, released={})
    _write(out / "sanitized", "scan.pdf", "%PDF-1.4 binary")
    (out / "report.json").write_text(json.dumps({"files": [
        {"path": "scan.pdf", "status": "sanitized", "output": "sanitized/scan.pdf"}],
        "capabilities": {"missing": []}}), encoding="utf-8")
    result = verify_tree(inp, out)
    assert result["checks"]["coverage"]["status"] == "unsupported"
    assert result["files"][0]["verification_status"] == "unsupported"


def test_missing_report_cannot_verify(tmp_path):
    inp, out = build(tmp_path, inputs={"a.txt": "x"}, released={"a.txt": "x"})
    (out / "report.json").unlink()
    result = verify_tree(inp, out)
    assert result["overall"] == "cannot_verify"


def test_evidence_never_republishes_the_identifier(tmp_path):
    inp, out = build(tmp_path, inputs={"a.txt": "Sunita Patel 6910522119"},
                     released={"a.txt": "Sunita Patel 6910522119"})
    blob = json.dumps(verify_tree(inp, out)["findings"])
    assert "Sunita Patel" not in blob and "6910522119" not in blob


def test_uuid_digits_are_not_an_aadhaar(tmp_path):
    """FHIR fullUrl UUIDs match the Aadhaar digit shape; reporting them is a false positive."""
    body = '{"fullUrl": "urn:uuid:6cd93b57-6d6d-453c-aaf2-829280011963", "subject": "urn:uuid:231534ba-b5a1-4c1e-9f3d-0a1b2c3d4e5f"}'
    inp, out = build(tmp_path, inputs={"fhir/b.json": body}, released={"fhir/b.json": body})
    result = verify_tree(inp, out)
    assert result["overall"] == "passed", result["checks"]


def test_label_does_not_adopt_digits_from_another_chunk(tmp_path):
    """A label in one flattened JSON chunk must not claim a number from the next (UUID fragments)."""
    from tools.verify import candidate_identifiers
    text = "subject\nreference\nurn:uuid:231534ba-b5a1-4c1e-9f3d-0a1b2c942005\ndisplay\nDischarge summary"
    assert [v for k, v in candidate_identifiers(text) if k == "MRN"] == []
