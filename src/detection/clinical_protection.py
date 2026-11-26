"""Reusable clinical spans that downstream PII classifiers should preserve."""
from __future__ import annotations

from typing import Any

from src.normalization.semantic import (SemanticNormalizationConfig,
                                        clinical_protected_spans)


def protected_spans(text: str, *,
                    config: SemanticNormalizationConfig | None = None) -> list[dict[str, Any]]:
    """Identify dictionary terms, explicit units/doses, and schedules by span."""
    return clinical_protected_spans(text, config=config)
