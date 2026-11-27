"""Optional transliteration as a separate, explicitly requested representation."""
from __future__ import annotations

from .unicode import identify_scripts


_DEVANAGARI_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "ळ": "l",
}
_DEVANAGARI_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ii", "उ": "u", "ऊ": "uu",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}
_DEVANAGARI_MATRAS = {
    "ा": "aa", "ि": "i", "ी": "ii", "ु": "u", "ू": "uu", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
}
_VIRAMA = "्"


def _fallback_devanagari(value: str) -> str:
    """Small deterministic name-oriented transliterator; never asserts identity equivalence.

    This is intentionally an approximate ASCII representation, not a Sanskrit transcription
    standard. It exists so deployments without the optional Indic package can normalize common
    Hindi spellings offline. Callers must retain the original and treat matches as uncertain.
    """
    output: list[str] = []
    pending_consonant = False
    for char in value:
        if char in _DEVANAGARI_CONSONANTS:
            if pending_consonant:
                output.append("a")
            output.append(_DEVANAGARI_CONSONANTS[char])
            pending_consonant = True
        elif char in _DEVANAGARI_MATRAS:
            if pending_consonant:
                output.append(_DEVANAGARI_MATRAS[char])
                pending_consonant = False
            else:
                output.append(_DEVANAGARI_MATRAS[char])
        elif char == _VIRAMA:
            if pending_consonant:
                pending_consonant = False
        elif char in _DEVANAGARI_VOWELS:
            if pending_consonant:
                output.append("a")
                pending_consonant = False
            output.append(_DEVANAGARI_VOWELS[char])
        elif char in {"ं", "ँ"}:
            output.append("n")
            pending_consonant = False
        elif char == "ः":
            output.append("h")
            pending_consonant = False
        elif char in {"़", "ऽ"}:
            continue
        else:
            if pending_consonant:
                # A space or punctuation ends the syllable; drop the inherent final schwa.
                pending_consonant = False
            output.append(char)
    # Hindi commonly drops the final inherent schwa in spoken names.
    if pending_consonant:
        output.append("a")
    result = "".join(output)
    # Remove a final schwa after a consonant transliteration (Ramesha -> Ramesh).
    if result.endswith("a") and value and value[-1] in _DEVANAGARI_CONSONANTS:
        result = result[:-1]
    return result.casefold()


def transliterate(value: str, *, source_script: str, scheme: str) -> tuple[str | None, str, list[str], dict[str, str]]:
    if source_script not in {"Devanagari", "Kannada"}:
        return None, "not_applicable", ["unsupported_source_script"], {}
    try:
        from indic_transliteration import sanscript
        from indic_transliteration.sanscript import transliterate as convert
    except ImportError:
        if source_script == "Devanagari" and scheme.lower() in {"itrans", "iast", "hk"}:
            return (_fallback_devanagari(value), "fallback",
                    ["indic_transliteration_dependency_unavailable"],
                    {"scheme": "ascii-name-key-v1", "source_script": source_script,
                     "identity_equivalence": "not_asserted", "approximate": "true"})
        return None, "unsupported", ["indic_transliteration_dependency_unavailable"], {}
    source = {"Devanagari": sanscript.DEVANAGARI, "Kannada": sanscript.KANNADA}[source_script]
    target = {"itrans": sanscript.ITRANS, "iast": sanscript.IAST,
              "hk": sanscript.HK}.get(scheme.lower())
    if target is None:
        return None, "unsupported", ["transliteration_scheme_unsupported"], {}
    try:
        result = convert(value, source, target)
    except (ValueError, KeyError):
        return None, "invalid", ["transliteration_failed"], {}
    return result, "success", [], {"scheme": scheme.lower(), "source_script": source_script,
                                    "identity_equivalence": "not_asserted",
                                    "approximate": "false"}
