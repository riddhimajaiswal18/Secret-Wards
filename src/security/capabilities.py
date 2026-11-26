"""Capability probe: a run must never look successful while a check was silently unavailable.

Optional backends change what the pipeline can *see* — transliteration folds scripts, `phonenumbers`
validates phone shapes, OCR reads images, `pdftoppm` renders PDFs — so their absence quietly reduces
coverage. This module makes that visible in three places:

1. `report.json` → `capabilities`, with the interpreter path that produced it;
2. `report.json` → `capabilities.missing`, so a reviewer sees it without reading logs;
3. a policy switch, `capabilities.require`, which turns a missing capability into a hard failure
   instead of a degraded run.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from dataclasses import dataclass

# capability -> (kind, name, what its absence degrades)
_SPEC: dict[str, tuple[str, str, str]] = {
    "transliteration": ("module", "indic_transliteration",
                        "cross-script normalisation: Devanagari and Latin names cannot be compared"),
    "phone_validation": ("module", "phonenumbers",
                         "phone shapes are matched by regex only, without carrier validation"),
    "pdf_text": ("module", "pypdf", "PDF text layers cannot be read, only carved"),
    "pdf_render": ("binary", "pdftoppm", "image-only PDFs cannot be OCR'd"),
    "ocr": ("module", "pytesseract",
            "images are limited to metadata carving; pixels are not read"),
    "ocr_binary": ("binary", "tesseract", "OCR cannot run even if pytesseract is installed"),
    "imaging": ("module", "PIL", "image metadata (EXIF/XMP) is unreachable"),
    "yaml_policy": ("module", "yaml", "policy falls back to the flat key:value reader"),
}


@dataclass(frozen=True)
class Capability:
    name: str
    available: bool
    degrades: str


def probe() -> dict[str, Capability]:
    found: dict[str, Capability] = {}
    for name, (kind, target, degrades) in _SPEC.items():
        available = (shutil.which(target) is not None if kind == "binary"
                     else importlib.util.find_spec(target) is not None)
        found[name] = Capability(name=name, available=available, degrades=degrades)
    return found


def report_section() -> dict:
    caps = probe()
    missing = [name for name, cap in caps.items() if not cap.available]
    return {
        "interpreter": sys.executable,
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "available": sorted(name for name, cap in caps.items() if cap.available),
        "missing": missing,
        "degraded": {name: caps[name].degrades for name in missing},
    }


def enforce(policy: dict | None) -> None:
    """Raise when the policy requires a capability this interpreter does not have."""
    section = (policy or {}).get("capabilities") or {}
    required = section.get("require") if isinstance(section, dict) else None
    if not required:
        return
    caps = probe()
    absent = [name for name in required if name in caps and not caps[name].available]
    if absent:
        raise RuntimeError(
            "required_capability_missing: " + ", ".join(absent)
            + " — install them in the interpreter that runs main.py, or drop them from "
              "config/policy.yaml capabilities.require")
