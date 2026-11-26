"""Value-free logging plus the independent leak scan.

Nothing that came out of a file may reach a log line, a filename or the report; the filter
below blanks registered terms before any handler sees them, and leak_scan re-reads the finished
output tree from disk so it cannot be fooled by the pipeline's own bookkeeping.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

_TRACKED: dict[str, str] = {}


def register(*values: str, token: str = "[REDACTED]") -> None:
    """Remember a value (and the secret) that must never appear on any surface."""
    for value in values:
        if value and len(value) >= 4:
            _TRACKED[value] = token


def redact(text: str) -> str:
    for value in sorted(_TRACKED, key=len, reverse=True):
        if value in text:
            text = text.replace(value, _TRACKED[value])
    return text


class _NoValueFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        safe = redact(message)
        if safe != message:
            record.msg, record.args = safe, ()
        return True


def install_log_filter() -> None:
    for name in ("", "src", "raksha"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, _NoValueFilter) for f in logger.filters):
            logger.addFilter(_NoValueFilter())
        for handler in logger.handlers:
            handler.addFilter(_NoValueFilter())


def safe_write(out_root: str | Path, rel: str, data: bytes) -> Path:
    """The only writer: refuses traversal and symlinks, writes atomically."""
    root = Path(out_root).resolve()
    target = (root / rel).resolve()
    if not str(target).startswith(str(root) + os.sep):
        raise ValueError("refusing_to_write_outside_output_tree")
    if target.is_symlink():
        raise ValueError("refusing_to_write_through_symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    with open(temporary, "wb") as handle:
        handle.write(data)
    os.replace(temporary, target)
    return target


def leak_scan(root: str | Path, needles: list[str]) -> list[tuple[str, str]]:
    """Return (path, needle) for every tracked value still present anywhere under root."""
    hits: list[tuple[str, str]] = []
    wanted = [(n, n.encode("utf-8")) for n in needles if n and len(n) >= 4]
    if not wanted:
        return hits
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = Path(dirpath) / name
            for needle, _ in wanted:
                if re.sub(r"[^a-z0-9]", "", needle.lower()) in re.sub(r"[^a-z0-9]", "", name.lower()):
                    hits.append((str(path), f"filename:{needle}"))
            try:
                blob = path.read_bytes()
            except OSError:
                continue
            for needle, encoded in wanted:
                if encoded in blob:
                    hits.append((str(path), needle))
                elif needle.encode("utf-16-le") in blob:
                    hits.append((str(path), f"{needle}:utf16"))
    return hits


def scrub_names(root: str | Path) -> int:
    """Rename any output file whose name still carries a tracked value."""
    fixed = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            safe = redact(name)
            if safe != name:
                source = Path(dirpath) / name
                target = Path(dirpath) / re.sub(r"[^A-Za-z0-9._-]", "_", safe)
                os.replace(source, target)
                fixed += 1
    return fixed
