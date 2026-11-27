"""Privacy transforms: stable per-record shifts, truthful bands and negative controls."""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from src.output.writer import write_submission


def _run(tmp_path: Path, files: dict[str, str], secret: str):
    old = os.environ.get("RAKSHA_SECRET")
    os.environ["RAKSHA_SECRET"] = secret
    try:
        inputs, outputs = tmp_path / "in", tmp_path / "out"
        for relative, value in files.items():
            path = inputs / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
        report = write_submission(inputs, outputs)
        return report, outputs
    finally:
        if old is None:
            os.environ.pop("RAKSHA_SECRET", None)
        else:
            os.environ["RAKSHA_SECRET"] = old


def test_dates_use_one_per_patient_offset_and_change_with_secret(tmp_path):
    rows = {
        "a/visit.json": json.dumps({
            "uhid": "JJH-0077112", "patient_name": "Sunita Patel", "phone": "9876543210",
            "visit_date": "2026-01-01", "age": 52, "sex": "F",
            "dob": "1974-08-16", "village": "Village X", "district": "Sitapur",
            "pin": "261167",
        }),
        "b/visit.json": json.dumps({
            "uhid": "SNJ-26064508", "patient_name": "Sunita Patel", "phone": "9876543210",
            "visit_date": "2026-01-10", "age": 52, "sex": "F",
            "dob": "1974-08-16", "village": "Village X", "district": "Sitapur",
            "pin": "261167",
        }),
    }
    _, first = _run(tmp_path / "first", rows, "secret-one")
    _, repeated = _run(tmp_path / "again", rows, "secret-one")
    _, changed_secret = _run(tmp_path / "other", rows, "secret-two")

    first_values = [
        json.loads((first / "sanitized" / name).read_text(encoding="utf-8"))
        for name in ("a/visit.json", "b/visit.json")
    ]
    repeated_values = [
        json.loads((repeated / "sanitized" / name).read_text(encoding="utf-8"))
        for name in ("a/visit.json", "b/visit.json")
    ]
    changed_values = [
        json.loads((changed_secret / "sanitized" / name).read_text(encoding="utf-8"))
        for name in ("a/visit.json", "b/visit.json")
    ]
    assert first_values[0]["visit_date"] != "2026-01-01"
    assert first_values[1]["visit_date"] != "2026-01-10"
    delta = (date.fromisoformat(first_values[1]["visit_date"])
             - date.fromisoformat(first_values[0]["visit_date"])).days
    assert delta == 9
    assert first_values == repeated_values
    assert first_values[0]["visit_date"] != changed_values[0]["visit_date"]
    assert [item["age"] for item in first_values] == ["50-54", "50-54"]
    assert [item["village"] for item in first_values] == ["Sitapur", "Sitapur"]
    assert [item["pin"] for item in first_values] == ["261***", "261***"]
    assert all(item["dob"] == "[DOB]" for item in first_values)


def test_combined_age_sex_text_is_banded_without_touching_dosage(tmp_path):
    body = (
        "Patient Name: Sunita Patel Age/Sex: 17 Yrs/F\n"
        "Admission Date: 01/02/2026\n"
        "Discharge Date: 06/02/2026\n"
        "Tab. Metformin 500 mg BD x 5 days\n"
    )
    _, outputs = _run(tmp_path, {"summary.txt": body}, "secret-text")
    text = (outputs / "sanitized" / "summary.txt").read_text(encoding="utf-8")
    assert "0-17 Yrs/F" in text
    assert "01/02/2026" not in text and "06/02/2026" not in text
    assert "Metformin 500 mg BD x 5 days" in text


def test_clean_document_age_and_dates_are_not_generalized(tmp_path):
    clean = json.dumps({
        "document_type": "medical reference", "age": 52,
        "date": "2026-01-01", "diagnosis": "Acute Kidney Injury",
    })
    _, outputs = _run(tmp_path, {"clean/reference.json": clean}, "secret-clean")
    produced = json.loads(
        (outputs / "sanitized" / "clean" / "reference.json").read_text(encoding="utf-8")
    )
    assert produced["age"] == 52
    assert produced["date"] == "2026-01-01"
    assert produced["diagnosis"] == "Acute Kidney Injury"


def test_ambiguous_and_partial_dates_are_not_guessed():
    from src.privacy.transforms import _shift_date

    assert _shift_date("2026-02", 4, "DMY") is None
    assert _shift_date("01/02/2026", 4, "DMY") == "05/02/2026"
    assert _shift_date("31/02/2026", 4, "DMY") is None
