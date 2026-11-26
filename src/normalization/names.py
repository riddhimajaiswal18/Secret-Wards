"""Name-form normalization that preserves source script and initials."""
from __future__ import annotations

from dataclasses import dataclass
import unicodedata
from typing import Any

from .unicode import identify_scripts, normalize_unicode, normalize_whitespace


_HONORIFICS = {
    "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "miss", "dr", "dr.",
    "shri", "shree", "smt", "kumari", "श्री", "श्रीमती", "सुश्री", "डॉ", "डॉ.",
}
_HONORIFIC_CANON = {"dr": "Dr", "dr.": "Dr", "डॉ": "डॉ", "डॉ.": "डॉ",
                    "mr": "Mr", "mr.": "Mr", "mrs": "Mrs", "mrs.": "Mrs",
                    "ms": "Ms", "ms.": "Ms", "श्री": "श्री", "श्रीमती": "श्रीमती",
                    "सुश्री": "सुश्री", "shri": "Shri", "shree": "Shri", "smt": "Smt"}
_NAME_SUFFIXES = {"ji", "sahab", "sahib", "didi"}


@dataclass(frozen=True)
class NameNormalization:
    normalized_value: str
    honorifics: tuple[str, ...]
    metadata: dict[str, Any]


def normalize_person_name(value: str) -> NameNormalization:
    """Normalize spacing/punctuation while retaining order, script and initials."""
    nfc = normalize_unicode(value)
    source = nfc.value if nfc.value is not None else value
    collapsed = normalize_whitespace(source).value or ""
    tokens = collapsed.split(" ")
    honorifics: list[str] = []
    while tokens and (tokens[0].casefold() in _HONORIFICS or
                      tokens[0].casefold().rstrip(".") in _HONORIFICS):
        token = tokens.pop(0)
        honorifics.append(_HONORIFIC_CANON.get(token.casefold(), token.rstrip(".")))
    while tokens and tokens[-1].casefold().strip(".,") in _NAME_SUFFIXES:
        honorifics.append(tokens.pop().strip(".,"))
    cleaned: list[str] = []
    for token in tokens:
        chars = []
        for char in token:
            category = unicodedata.category(char)
            chars.append(char if not category.startswith("P") or char in {"'", "’", "-", "."} else " ")
        part = "".join(chars).strip(",;:!?()[]{}\"“”‘’")
        if len(part) > 2 and part.endswith(".") and part[:-1].isalpha():
            part = part[:-1]
        if part:
            cleaned.extend(part.split())
    normalized = " ".join(cleaned)
    return NameNormalization(normalized_value=normalized, honorifics=tuple(honorifics),
                             metadata={"script": identify_scripts(value), "initials_expanded": False,
                                       "transliteration_is_identity": False,
                                       "unicode_form": "NFC"})
