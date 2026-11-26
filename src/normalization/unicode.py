"""Deterministic Unicode, whitespace, and script utilities (no transliteration)."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class TextNormalization:
    value: str | None
    status: str
    warnings: tuple[str, ...] = ()


def normalize_unicode(value: str, *, form: str = "NFC") -> TextNormalization:
    if form not in {"NFC", "NFKC"}:
        return TextNormalization(None, "unsupported", ("unsupported_unicode_form",))
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        return TextNormalization(None, "invalid", ("unpaired_surrogate",))
    if any((ord(ch) & 0xFFFF) in {0xFFFE, 0xFFFF} for ch in value):
        return TextNormalization(None, "invalid", ("unicode_noncharacter",))
    if "\x00" in value:
        return TextNormalization(None, "invalid", ("nul_character",))
    warnings = []
    for char in value:
        category = unicodedata.category(char)
        if category == "Cf" and char not in {"\u200c", "\u200d"}:
            warnings.append("format_control_character_present")
            break
        if category == "Cc" and char not in {"\t", "\n", "\r"}:
            warnings.append("control_character_present")
            break
    return TextNormalization(unicodedata.normalize(form, value), "success", tuple(warnings))


def normalize_whitespace(value: str, *, collapse: bool = True) -> TextNormalization:
    """Normalize spaces for compact fields; callers must exclude free text."""
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        return TextNormalization(None, "invalid", ("unpaired_surrogate",))
    # str.split handles Unicode whitespace and removes leading/trailing runs.
    if not collapse:
        return TextNormalization(value.strip(), "success")
    return TextNormalization(" ".join(value.split()), "success")


def identify_scripts(value: str) -> dict[str, object]:
    counts: dict[str, int] = {}
    for char in value:
        if not char.isalpha():
            continue
        cp = ord(char)
        script = ("Devanagari" if 0x0900 <= cp <= 0x097F else
                  "Kannada" if 0x0C80 <= cp <= 0x0CFF else
                  "Latin" if "LATIN" in unicodedata.name(char, "") else "Other")
        counts[script] = counts.get(script, 0) + 1
    active = sorted(counts)
    if not active:
        primary = "unknown"
    else:
        primary = max(active, key=lambda s: (counts[s], s))
    mixed = len(active) > 1
    language_hint = "hinglish" if mixed and {"Latin", "Devanagari"}.issubset(set(active)) else "undetermined"
    # Script is evidence about writing system, not sufficient language evidence.
    return {"script": primary if not mixed else "Mixed", "scripts": active,
            "script_counts": counts, "mixed_script": mixed,
            "language": language_hint}
