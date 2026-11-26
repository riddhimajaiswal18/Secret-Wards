"""Optional transliteration as a separate, explicitly requested representation."""
from __future__ import annotations

from .unicode import identify_scripts


def transliterate(value: str, *, source_script: str, scheme: str) -> tuple[str | None, str, list[str], dict[str, str]]:
    if source_script not in {"Devanagari", "Kannada"}:
        return None, "not_applicable", ["unsupported_source_script"], {}
    try:
        from indic_transliteration import sanscript
        from indic_transliteration.sanscript import transliterate as convert
    except ImportError:
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
                                    "identity_equivalence": "not_asserted"}
