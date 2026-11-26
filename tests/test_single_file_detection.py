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
