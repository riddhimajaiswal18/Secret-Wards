"""Identity consistency: same patient, same token; different patients, different tokens.

The contract (SPEC.md §6) wants {"file": ..., "loc": ..., "patient": "PSN-7Q2K9D"}.
These tests pin the three properties that matter and the one that must never happen (a merge).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from src.output.writer import write_submission
from src.privacy.pseudonyms import pseudonym_for

SECRET = "test-secret-1"


def _run(tmp_path: Path, files: dict[str, str], secret: str | None = SECRET) -> list[dict]:
    previous = os.environ.get("RAKSHA_SECRET")
    if secret:
        os.environ["RAKSHA_SECRET"] = secret
    else:
        os.environ.pop("RAKSHA_SECRET", None)
    try:
        inputs, outputs = tmp_path / "in", tmp_path / "out"
        for rel, body in files.items():
            path = inputs / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        write_submission(inputs, outputs)
        return [json.loads(line) for line in
                (outputs / "records.jsonl").read_text().splitlines() if line.strip()]
    finally:
        if previous is None:
            os.environ.pop("RAKSHA_SECRET", None)
        else:
            os.environ["RAKSHA_SECRET"] = previous


def test_same_identifier_gets_the_same_pseudonym_across_files(tmp_path):
    records = _run(tmp_path, {
        "reg/a.csv": "uhid,name\nJJH-0077112,Sunita Patel\n",
        "opd/b.json": json.dumps({"uhid": "JJH-0077112", "visit": 1}),
    })
    tokens = {r["patient"] for r in records if r["patient"]}
    assert len(tokens) == 1, tokens
    assert tokens.pop().startswith("PSN-")


def test_different_patients_get_different_pseudonyms(tmp_path):
    records = _run(tmp_path, {
        "reg/a.csv": "uhid,name\nJJH-0077112,Sunita Patel\n",
        "reg/c.csv": "uhid,name\nJJH-0099999,Mohd Shahid\n",
    })
    tokens = [r["patient"] for r in records if r["patient"]]
    assert len(set(tokens)) == 2, tokens


def test_same_name_different_identifier_is_not_merged(tmp_path):
    """Name-only linkage is the measured failure mode (96 false merges); names are not evidence."""
    records = _run(tmp_path, {
        "reg/a.csv": "uhid,name\nJJH-0077112,Sunita Patel\n",
        "reg/b.csv": "uhid,name\nJJH-0055555,Sunita Patel\n",
    })
    tokens = [r["patient"] for r in records if r["patient"]]
    assert len(set(tokens)) == 2, tokens


def test_no_identifier_means_no_pseudonym(tmp_path):
    records = _run(tmp_path, {"notes/a.txt": "Patient Sunita Patel, stable, discharged.\n"})
    assert all(r["patient"] is None for r in records)


def test_no_secret_means_no_pseudonym(tmp_path):
    records = _run(tmp_path, {"reg/a.csv": "uhid,name\nJJH-0077112,Sunita Patel\n"}, secret=None)
    assert all(r["patient"] is None for r in records)


def test_pseudonym_is_deterministic_and_secret_dependent(tmp_path):
    first = _run(tmp_path, {"reg/a.csv": "uhid,name\nJJH-0077112,Sunita Patel\n"})[0]["patient"]
    again = _run(tmp_path / "r2", {"reg/a.csv": "uhid,name\nJJH-0077112,Sunita Patel\n"})[0]["patient"]
    other = _run(tmp_path / "r3", {"reg/a.csv": "uhid,name\nJJH-0077112,Sunita Patel\n"},
                 secret="another-secret")[0]["patient"]
    assert first == again and first != other


def test_pseudonym_does_not_contain_the_identifier():
    token = pseudonym_for(SECRET, "JJH-0077112")
    assert token and "0077112" not in token and token.startswith("PSN-") and len(token) == 10


def test_batch_file_assigns_independent_row_pseudonyms(tmp_path):
    records = _run(tmp_path, {"reg/batch.csv":
                             "uhid,name\nJJH-0077112,Sunita Patel\nJJH-0099999,Mohd Shahid\n"})
    linked = [r for r in records if r["patient"]]
    assert [r["loc"] for r in linked] == ["row:0", "row:1"]
    assert len({r["patient"] for r in linked}) == 2


def test_row_pseudonyms_are_embedded_in_sanitized_csv(tmp_path):
    previous = os.environ.get("RAKSHA_SECRET")
    os.environ["RAKSHA_SECRET"] = SECRET
    try:
        inputs, outputs = tmp_path / "in", tmp_path / "out"
        inputs.mkdir()
        (inputs / "batch.csv").write_text(
            "uhid,name,amount\nJJH-0077112,Sunita Patel,450\nJJH-0099999,Mohd Shahid,600\n",
            encoding="utf-8")
        write_submission(inputs, outputs)
        rows = (outputs / "sanitized" / "batch.csv").read_text(encoding="utf-8").splitlines()
        assert rows[0].endswith(",patient_ref")
        assert "PSN-" in rows[1] and "PSN-" in rows[2]
        assert rows[1].split(",")[-1] != rows[2].split(",")[-1]
    finally:
        if previous is None:
            os.environ.pop("RAKSHA_SECRET", None)
        else:
            os.environ["RAKSHA_SECRET"] = previous
