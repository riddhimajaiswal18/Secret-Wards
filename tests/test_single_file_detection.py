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
