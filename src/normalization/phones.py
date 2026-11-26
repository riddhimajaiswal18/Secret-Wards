"""Phone normalization via the offline phonenumbers metadata package."""
from __future__ import annotations


def normalize_phone(value: str, *, default_region: str | None = None) -> tuple[str | None, str, list[str], dict[str, object]]:
    try:
        import phonenumbers
        from phonenumbers import PhoneNumberFormat, NumberParseException
    except ImportError:
        return None, "unsupported", ["phonenumbers_dependency_unavailable"], {}
    try:
        parsed = phonenumbers.parse(value.strip(), default_region)
    except NumberParseException:
        return None, "invalid", ["phone_parse_failed"], {}
    possible = phonenumbers.is_possible_number(parsed)
    valid = phonenumbers.is_valid_number(parsed)
    details = {"possible": bool(possible), "valid": bool(valid),
               "extension": parsed.extension or None,
               "region": phonenumbers.region_code_for_number(parsed)}
    if not possible:
        return None, "invalid", ["phone_not_possible"], details
    if not valid:
        return None, "invalid", ["phone_not_valid"], details
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164), "success", [], details
