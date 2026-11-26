"""Interface for future policy rules; this module intentionally contains no rules."""
from __future__ import annotations

from typing import Protocol, Sequence

from src.ir import Annotation, IntermediateRepresentation, PendingEdit


class PolicyEngine(Protocol):
    def evaluate(self, document: IntermediateRepresentation,
                 annotations: Sequence[Annotation]) -> Sequence[PendingEdit]:
        """Return proposed edits without mutating annotations or source data."""
