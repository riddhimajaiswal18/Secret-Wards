"""Pipeline entry point: enumerate → parse → (detect) → (link) → (privatise) → serialise → report.

Today only the mechanical half is wired. With no detector the pass must reproduce every
parseable input byte-for-byte; that is the fidelity gate the rest of the system is built on.
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
    if secret:
        register(secret, token="[SECRET]")
    else:
        LOG.warning("no run secret supplied: pseudonyms will not be produced in this pass")

    policy = load_policy(policy_path)
    enforce(policy)                      # fail closed when a required capability is absent
    report = write_submission(input_dir, output_dir, submission=submission,
                              policy_digest=policy_digest(policy_path), policy=policy)
    counts = report["counts"]
    LOG.info("files %d · sanitized %d · quarantined %d · %.2fs",
             counts["files_total"], counts["files_sanitized"], counts["files_quarantined"],
             report["timing"]["seconds"])
    return report
