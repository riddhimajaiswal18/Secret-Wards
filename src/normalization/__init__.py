"""Deterministic, sparse normalization overlays for parsed source documents."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from src.ir import (IntermediateRepresentation, NormalizationResult,
                    NormalizationStatus, get_value, iter_field_metadata)
from .dates import normalize_date
from .other import (normalize_country, normalize_email, normalize_measurement,
                    normalize_url)
from .phones import normalize_phone
from .semantic import (SemanticNormalizationConfig, map_field_name,
                       normalize_field_key, normalize_semantics)
from .unicode import identify_scripts, normalize_unicode, normalize_whitespace


@dataclass(frozen=True)
class NormalizationConfig:
    """Explicit, conservative configuration for field-directed normalizers."""
    default_phone_region: str | None = None
    date_order: str | None = None
    date_formats: tuple[str, ...] = ()
    field_mappings: dict[str, str] = field(default_factory=dict)
    normalize_urls: bool = False
    normalize_countries: bool = False
    transliterate_fields: frozenset[str] = frozenset()
    transliteration_scheme: str = "itrans"
    # Explicit value-field -> (sibling unit field, canonical unit) mappings.
    measurement_fields: dict[str, tuple[str, str]] = field(default_factory=dict)
    semantic: SemanticNormalizationConfig = field(default_factory=SemanticNormalizationConfig)


_DATE_FIELDS = {"dob", "dateofbirth", "birthdate", "admissiondate", "dischargedate",
                "visitdate", "encounterdate", "date", "datetime", "timestamp"}
_PHONE_FIELDS = {"phone", "mobile", "mobileno", "phonenumber", "contactnumber", "telephone",
                 "contactphone", "emergencycontactnumber"}
_EMAIL_FIELDS = {"email", "emailaddress", "contactemail"}
_NAME_FIELDS = {"name", "patientname", "firstname", "lastname", "fullname", "fathername",
                "mothername", "spousename", "relative"}
_URL_FIELDS = {"url", "website", "weburl", "link"}
_COUNTRY_FIELDS = {"country", "countryname", "countrycode"}


def _field_key(name: str) -> str:
    return "".join(ch.casefold() for ch in name if ch.isalnum())


def _result(locator: str, kind: str, value: Any, status: str,
            warnings: list[str] | tuple[str, ...] = (), metadata: dict[str, Any] | None = None) -> NormalizationResult:
    return NormalizationResult(locator=locator, normalization_type=kind,
                               normalized_value=value, status=NormalizationStatus(status),
                               warnings=list(warnings), metadata=metadata or {})


def normalize_ir(ir: IntermediateRepresentation, *, config: NormalizationConfig | None = None) -> IntermediateRepresentation:
    """Attach deterministic derived values; never edits or copies ``structure.data``."""
    if ir.processing_status.value == "QUARANTINED":
        return ir
    cfg = config or NormalizationConfig()
    overlay: dict[str, list[NormalizationResult]] = {}

    def add(result: NormalizationResult) -> None:
        overlay.setdefault(result.locator, []).append(result)

    field_metadata = list(iter_field_metadata(ir))
    siblings = {(item.parent_locator, item.field_name): item.locator for item in field_metadata}
    for meta in field_metadata:
        if meta.field_kind != "leaf":
            continue
        try:
            original = get_value(ir, meta.locator)
        except ValueError:
            # Ragged CSV/TSV cells have metadata but no corresponding source value.
            # Semantic field mapping still annotates the column/cell locator.
            continue
        if not isinstance(original, str):
            continue
        normalized = normalize_unicode(original)
        if (normalized.value != original or normalized.status != "success" or normalized.warnings):
            add(_result(meta.locator, "unicode_nfc", normalized.value, normalized.status,
                        normalized.warnings, {"original_type": "string", "form": "NFC"}))
        script_info = identify_scripts(original)
        add(_result(meta.locator, "script_identification", None, "success", (), script_info))
        effective_name = meta.field_name
        # In the lossless XML tree, scalar text lives under a generic `text` key;
        # its containing element tag is the available structural field hint.
        if meta.field_name == "text" and meta.parent_locator:
            try:
                parent = get_value(ir, meta.parent_locator)
                if isinstance(parent, dict) and parent.get("node_type") == "element":
                    effective_name = str(parent.get("tag", "text")).rsplit("}", 1)[-1]
            except (ValueError, TypeError):
                pass
        key = _field_key(effective_name)
        mapped = cfg.field_mappings.get(effective_name, cfg.field_mappings.get(key, ""))
        is_header = meta.locator.startswith("header:col:")
        field_type = mapped.casefold() if mapped else ""
        is_name_like = key in _NAME_FIELDS or key.endswith("name")
        is_atomic = (is_name_like or key in _DATE_FIELDS or key in _PHONE_FIELDS or
                     key in _EMAIL_FIELDS or key in _URL_FIELDS or key in _COUNTRY_FIELDS or
                     field_type in {"date", "phone", "email", "name", "url", "country"})
        if is_atomic and not is_header:
            ws = normalize_whitespace(normalized.value or "")
            if ws.value != normalized.value or ws.status != "success" or ws.warnings:
                add(_result(meta.locator, "whitespace", ws.value, ws.status, ws.warnings,
                            {"context": "atomic_field"}))
        candidate = normalized.value if normalized.value is not None else original
        if not is_header and (field_type == "date" or key in _DATE_FIELDS):
            value, status, warnings = normalize_date(candidate, date_order=cfg.date_order,
                                                     formats=cfg.date_formats)
            add(_result(meta.locator, "date", value, status, warnings,
                        {"date_order": cfg.date_order, "precision_preserved": True}))
        if not is_header and (field_type == "phone" or key in _PHONE_FIELDS):
            value, status, warnings, details = normalize_phone(candidate, default_region=cfg.default_phone_region)
            add(_result(meta.locator, "phone", value, status, warnings, details))
        if not is_header and (field_type == "email" or key in _EMAIL_FIELDS):
            value, status, warnings, details = normalize_email(candidate)
            add(_result(meta.locator, "email", value, status, warnings, details))
        measure_mapping = cfg.measurement_fields.get(effective_name, cfg.measurement_fields.get(key))
        if not is_header and measure_mapping:
            unit_field, canonical_unit = measure_mapping
            unit_value = None
            unit_locator = None
            unit_resolution_status = None
            if ir.source.format in {"csv", "tsv"} and meta.locator.startswith("row:"):
                try:
                    row_match = re.fullmatch(r"row:(\d+),col:(\d+)", meta.locator)
                    if row_match:
                        row_index, _ = map(int, row_match.groups())
                        header = ir.structure.data["header"]
                        columns = [i for i, label in enumerate(header) if label == unit_field]
                        if len(columns) == 1:
                            unit_locator = f"row:{row_index},col:{columns[0]}"
                            unit_value = get_value(ir, unit_locator)
                        else:
                            unit_resolution_status = "ambiguous" if columns else "invalid"
                except (ValueError, IndexError):
                    unit_resolution_status = "invalid"
            elif meta.parent_locator:
                try:
                    parent = get_value(ir, meta.parent_locator)
                    if isinstance(parent, dict) and unit_field in parent:
                        unit_value = parent[unit_field]
                        # JSONPath generation is centralized in the IR; find exact sibling.
                        unit_locator = siblings.get((meta.parent_locator, unit_field))
                except (ValueError, TypeError):
                    unit_value = None
            value, status, warnings, details = normalize_measurement(
                candidate, unit_value if isinstance(unit_value, str) else None,
                canonical_unit=canonical_unit, locator=unit_locator)
            if unit_value is not None and not isinstance(unit_value, str):
                status, warnings = "invalid", ["unit_value_not_string"]
            if unit_resolution_status:
                status = unit_resolution_status
                warnings = ["unit_field_duplicate" if status == "ambiguous" else "unit_field_missing"]
            add(_result(meta.locator, "measurement", value, status, warnings,
                        {**details, "unit_locator": unit_locator}))
        if (not is_header and cfg.normalize_urls and (field_type == "url" or key in _URL_FIELDS)):
            value, status, warnings = normalize_url(candidate)
            add(_result(meta.locator, "url", value, status, warnings))
        if (not is_header and cfg.normalize_countries and (field_type == "country" or key in _COUNTRY_FIELDS)):
            value, status, warnings = normalize_country(candidate)
            add(_result(meta.locator, "country", value, status, warnings))
        if (not is_header and (key in cfg.transliterate_fields or effective_name in cfg.transliterate_fields)):
            from .transliteration import transliterate
            info = identify_scripts(original)
            script = info["script"]
            value, status, warnings, details = transliterate(
                original, source_script=script if isinstance(script, str) else "unknown",
                scheme=cfg.transliteration_scheme)
            add(_result(meta.locator, "transliteration", value, status, warnings, details))

    # Each result was constructed through its validated Pydantic model. Avoid
    # triggering a second whole-document validation/tree walk on large inputs.
    object.__setattr__(ir, "normalizations", overlay)
    normalize_semantics(ir, config=cfg.semantic, default_phone_region=cfg.default_phone_region)
    return ir


def normalize_document_file(path: str, *, document_id: str | None = None,
                            source_identity: str | None = None,
                            config: NormalizationConfig | None = None) -> IntermediateRepresentation:
    """Actual ingestion-to-normalization path for a single supported/unsupported file."""
    from src.ingestion.file_router import parse_document_file
    return normalize_ir(parse_document_file(path, document_id=document_id,
                                            source_identity=source_identity), config=config)


__all__ = ["NormalizationConfig", "SemanticNormalizationConfig", "map_field_name",
           "normalize_field_key", "normalize_semantics",
           "normalize_ir", "normalize_document_file",
           "normalize_date", "normalize_phone", "normalize_email", "normalize_url",
           "normalize_country", "normalize_measurement"]
