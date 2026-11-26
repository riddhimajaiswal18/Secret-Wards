"""Conservative email, URL, country, and explicit unit helpers."""
from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, urlunsplit


_EMAIL = re.compile(r"^(?P<local>[^\s@<>(),;:\\[\]]{1,64})@(?P<domain>[^\s.@]+(?:\.[^\s.@]+)+)$")


def normalize_email(value: str) -> tuple[str | None, str, list[str], dict[str, object]]:
    candidate = value.strip()
    match = _EMAIL.fullmatch(candidate)
    if not match:
        return None, "invalid", ["email_syntax_invalid"], {}
    local, domain = match.group("local"), match.group("domain").rstrip(".")
    if len(candidate) > 254 or len(domain) > 253:
        return None, "invalid", ["email_too_long"], {}
    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None, "invalid", ["email_domain_invalid"], {}
    labels = ascii_domain.split(".")
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
        return None, "invalid", ["email_domain_invalid"], {}
    # Preserve local-part case and bytes: mailbox semantics may be case-sensitive.
    return f"{local}@{ascii_domain}", "success", [], {"deliverability_checked": False}


def normalize_url(value: str) -> tuple[str | None, str, list[str]]:
    raw = value.strip()
    try:
        parts = urlsplit(raw)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValueError
        if parts.username is not None or parts.password is not None:
            return None, "unsupported", ["credentials_in_url_not_normalized"]
        host = parts.hostname.encode("idna").decode("ascii").lower()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"  # urlsplit removes brackets from IPv6 hostnames.
        port = parts.port
    except (ValueError, UnicodeError):
        return None, "invalid", ["url_invalid"]
    netloc = f"{host}:{port}" if port and not ((parts.scheme.lower() == "http" and port == 80) or
                                                (parts.scheme.lower() == "https" and port == 443)) else host
    normalized = urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, parts.fragment))
    return normalized, "success", []


def normalize_country(value: str) -> tuple[str | None, str, list[str]]:
    candidate = value.strip()
    try:
        import pycountry
        country = pycountry.countries.lookup(candidate)
        return country.alpha_2, "success", []
    except ImportError:
        return None, "unsupported", ["pycountry_dependency_unavailable"]
    except LookupError:
        return None, "invalid", ["country_not_recognized"]


# Explicitly configured base-unit conversions. No measurement type is inferred.
_UNIT_TABLE: dict[str, tuple[str, float, str]] = {
    "g": ("mass", 1.0, "g"), "kg": ("mass", 1000.0, "g"),
    "mg": ("mass", 0.001, "g"), "ug": ("mass", 0.000001, "g"),
    "ml": ("volume", 1.0, "mL"), "l": ("volume", 1000.0, "mL"),
    "cm": ("length", 1.0, "cm"), "mm": ("length", 0.1, "cm"),
}


def normalize_measurement(value: object, unit: str | None, *, canonical_unit: str | None,
                         locator: str | None = None) -> tuple[object | None, str, list[str], dict[str, object]]:
    meta = {"original_unit": unit, "canonical_unit": canonical_unit}
    if unit is None or not unit.strip():
        return None, "invalid", ["unit_missing"], meta
    source = _UNIT_TABLE.get(unit.strip().casefold())
    target = _UNIT_TABLE.get(canonical_unit.strip().casefold()) if canonical_unit else None
    if source is None or target is None:
        return None, "unsupported", ["unit_unknown_or_canonical_not_configured"], meta
    if source[0] != target[0]:
        return None, "invalid", ["incompatible_units"], meta
    if isinstance(value, str):
        try:
            value = Decimal(value.strip())
        except InvalidOperation:
            return None, "invalid", ["measurement_value_not_numeric"], meta
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)):
        return None, "invalid", ["measurement_value_not_finite_number"], meta
    converted = float(value) * source[1] / target[1]
    if isinstance(value, int) and converted.is_integer():
        converted = int(converted)
    meta["source_locator"] = locator
    return {"value": converted, "unit": target[2]}, "success", [], meta
