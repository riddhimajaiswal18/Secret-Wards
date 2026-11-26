"""Policy: the single place where a finding becomes a transformation.

Detection says *what* a span is. This module decides *what happens to it*, and it is the only
module allowed to hold that opinion, so a privacy review can change behaviour without touching
detection code.

Vocabulary follows the method set used by established health-data anonymisers
(keep · redact · substitute · cryptoHash · dateShift · generalize · perturb). At this stage only
`substitute` (typed token) is applied, because patient-level identity resolution has not run yet:
a pseudonym derived before linkage would be a lie. Identifiers therefore become typed tokens and
`[NAME]`, and the pseudonym appears in the next stage.
"""
from __future__ import annotations

from typing import Any, Protocol, Sequence

from src.detection.engine import build_edits
from src.detection.protection import ProtectionIndex
from src.ir import Annotation, IntermediateRepresentation, PendingEdit

# Technique per kind. `None` means keep: a clinician is not the patient, and an institution is
# context that carries utility rather than identity.
DEFAULT_TECHNIQUE: dict[str, str] = {
    "PHONE": "substitute",
    "EMAIL": "substitute",
    "AADHAAR": "substitute",
    "PAN": "substitute",
    "ABHA": "substitute",
    "UHID": "substitute",
    "PIN": "generalize",
    "NAME": "substitute",
    "RELATIVE": "substitute",
    "HOUSE": "generalize",
    "VILLAGE": "generalize",
    "ADDRESS": "substitute",
    "LANDMARK": "generalize",
    "DOB": "substitute",
    "INSURANCE": "substitute",
}

DEFAULT_TOKENS: dict[str, str] = {
    "PHONE": "[PHONE]",
    "EMAIL": "[EMAIL]",
    "AADHAAR": "[AADHAAR]",
    "PAN": "[PAN]",
    "ABHA": "[ABHA]",
    "UHID": "[UHID]",
    "PIN": "[PIN]",
    "NAME": "[NAME]",
    "RELATIVE": "[RELATIVE]",
    "HOUSE": "[HOUSE]",
    "VILLAGE": "[VILLAGE]",
    "ADDRESS": "[ADDRESS]",
    "LANDMARK": "[LANDMARK]",
    "DOB": "[DOB]",
    "INSURANCE": "[INSURANCE]",
}


class PolicyEngine(Protocol):
    def evaluate(self, document: IntermediateRepresentation,
                 annotations: Sequence[Annotation]) -> Sequence[PendingEdit]:
        """Return proposed edits without mutating annotations or source data."""


def resolve_tokens(policy: dict[str, Any] | None = None) -> dict[str, str]:
    """Token text per kind, overridable from config without code changes."""
    tokens = dict(DEFAULT_TOKENS)
    section = (policy or {}).get("redaction") or {}
    overrides = section.get("tokens") if isinstance(section, dict) else None
    if isinstance(overrides, dict):
        for kind, token in overrides.items():
            if isinstance(token, str) and token:
                tokens[str(kind).upper()] = token
    returns = section.get("return_original_if_single") if isinstance(section, dict) else None
    if returns is False:
        for kind in list(tokens):
            tokens.setdefault(kind, tokens[kind])
    return tokens


def evaluate(document: IntermediateRepresentation, protection: ProtectionIndex,
             policy: dict[str, Any] | None = None) -> dict[str, int]:
    """Queue the edits for one document and return per-kind counts (never values)."""
    tokens = resolve_tokens(policy)
    edits, counts = build_edits(document, protection, tokens)
    document.pending_edits = edits
    return counts
