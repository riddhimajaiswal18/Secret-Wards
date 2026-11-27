"""Release pipeline: validate configuration, then parse, detect, link, transform and report.

Each format is parsed into the common IR. Detection and privacy stages attach locator-based edits,
which are serialized without mutating the authoritative parsed source structure.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from src.output.writer import write_submission
from src.security.capabilities import enforce
from src.security.safe_logging import install_log_filter, register

LOG = logging.getLogger("raksha")


def load_policy(path: str | Path | None) -> dict:
    """Policy is YAML when PyYAML is present, otherwise a flat 'key: value' reader."""
    if not path:
        return {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        import yaml  # type: ignore
        loaded = yaml.safe_load(text)
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass
    flat: dict[str, str] = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line and ":" in line:
            key, value = line.split(":", 1)
            flat[key.strip()] = value.strip()
    return flat


def policy_digest(path: str | Path | None) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except (OSError, TypeError):
        return ""


def run(input_dir: str | Path, output_dir: str | Path, *, policy_path: str | Path | None = None,
        submission: str = "secret-wards") -> dict:
    install_log_filter()
    secret = os.environ.get("RAKSHA_SECRET", "")
    if not secret:
        raise RuntimeError("RAKSHA_SECRET is required for a privacy release")
    register(secret, token="[SECRET]")

    policy = load_policy(policy_path)
    enforce(policy)                      # fail closed when a required capability is absent
    report = write_submission(input_dir, output_dir, submission=submission,
                              policy_digest=policy_digest(policy_path), policy=policy)
    counts = report["counts"]
    LOG.info("files %d · sanitized %d · quarantined %d · %.2fs",
             counts["files_total"], counts["files_sanitized"], counts["files_quarantined"],
             report["timing"]["seconds"])
    return report
