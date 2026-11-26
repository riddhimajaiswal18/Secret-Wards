"""Strict date/time normalization; never fill missing components or guess."""
from __future__ import annotations

from datetime import date, datetime
import re


_NUMERIC = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$")
_DATEISH = re.compile(r"^\d{1,4}([./-])\d{1,2}(?:\1\d{1,4})?(?:[T ].*)?$")


def normalize_date(value: str, *, date_order: str | None = None,
                   formats: tuple[str, ...] = ()) -> tuple[str | None, str, list[str]]:
    raw = value.strip()
    if not raw:
        return None, "invalid", ["empty_date"]
    # ISO date-only stays date-only. ISO partial precision is retained as supplied.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            return date.fromisoformat(raw).isoformat(), "success", []
        except ValueError:
            return None, "invalid", ["invalid_calendar_date"]
    if re.fullmatch(r"\d{4}-\d{2}", raw):
        year, month = map(int, raw.split("-"))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}", "success", ["partial_precision_preserved"]
        return None, "invalid", ["invalid_calendar_date"]
    # ISO timestamps only; fromisoformat accepts offsets and does not invent one.
    if "T" in raw or re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:.*", raw):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.isoformat().replace("+00:00", "Z"), "success", []
        except ValueError:
            return None, "invalid", ["invalid_timestamp"]
    # Explicit custom formats are opt-in and must yield a complete date/time.
    for fmt in formats:
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        # Avoid silently supplying defaults for omitted components.
        if not all(token in fmt for token in ("%Y", "%m", "%d")):
            return None, "unsupported", ["format_omits_date_component"]
        if any(token in fmt for token in ("%H", "%I", "%M", "%S")):
            return parsed.isoformat(), "success", []
        return parsed.date().isoformat(), "success", []
    numeric = _NUMERIC.fullmatch(raw)
    if numeric:
        first, second, year = map(int, numeric.groups())
        if first <= 12 and second <= 12:
            if date_order not in {"DMY", "MDY"}:
                return None, "ambiguous", ["ambiguous_numeric_date"]
            day, month = (first, second) if date_order == "DMY" else (second, first)
        else:
            day, month = (first, second) if first > 12 else (second, first)
        try:
            return date(year, month, day).isoformat(), "success", []
        except ValueError:
            return None, "invalid", ["invalid_calendar_date"]
    if _DATEISH.match(raw):
        return None, "ambiguous", ["unrecognized_or_ambiguous_date"]
    return None, "not_applicable", ["not_date_candidate"]
