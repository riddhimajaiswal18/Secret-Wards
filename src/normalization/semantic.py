"""Explainable semantic annotations; no source edits, matching, or linkage."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any

from src.ir import (Annotation, DetectionStatus, IntermediateRepresentation,
                    ProcessingStatus, get_value, iter_field_metadata)
from .names import normalize_person_name
from .dates import normalize_date
from .other import normalize_email


@dataclass(frozen=True)
class SemanticNormalizationConfig:
    """Configurable lexicons; keys are canonical concepts or normalized terms."""
    field_synonyms: dict[str, tuple[str, ...]] = field(default_factory=dict)
    clinical_terms: dict[str, dict[str, str]] = field(default_factory=dict)
    abbreviation_expansions: dict[str, str] = field(default_factory=dict)
    transliterate_names: bool = False
    transliteration_scheme: str = "itrans"


_DEFAULT_FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "patient_name": ("patient name", "patient full name", "name of patient", "beneficiary name",
                     "patientname", "patientfullname", "रोगी का नाम", "मरीज का नाम", "मरीज़ का नाम"),
    "person_name": ("person name", "full name", "given name", "family name", "first name",
                     "last name", "middle name"),
    "doctor_name": ("doctor name", "physician name", "provider name", "consultant name",
                    "doctor", "physician", "provider"),
    "relative_name": ("relative name", "father name", "mother name", "spouse name",
                      "guardian name", "next of kin", "nextofkin", "relative", "care of name",
                      "पिता का नाम", "माता का नाम", "पति का नाम", "पत्नी का नाम", "अभिभावक का नाम"),
    "caregiver_name": ("caregiver name", "caregiver", "attendant name"),
    "emergency_contact": ("emergency contact", "emergency contact name", "emergency contact number",
                          "emergencycontact", "emergencycontactname", "emergencycontactnumber"),
    "date_of_birth": ("date of birth", "birth date", "dob", "birthdate", "dateofbirth", "जन्म तिथि", "जन्म तारीख"),
    "phone": ("phone", "mobile", "mobile number", "telephone", "contact number", "phone number",
              "mobile no", "phone no", "contact no", "mobileno", "phonenumber", "contactnumber",
              "telephone number", "मोबाइल", "मोबाइल नंबर", "फोन नंबर"),
    "email": ("email", "email address", "contact email", "emailaddress"),
    "address": ("address", "home address", "residential address", "postal address"),
    "aadhaar": ("aadhaar", "aadhar", "aadhaar number", "aadhar number", "uid"),
    "abha": ("abha", "abha number", "abha id", "health id"),
    "pan": ("pan", "pan number", "permanent account number"),
    "mrn": ("mrn", "uhid", "medical record number", "hospital id", "patient id", "registration number"),
    "insurance_id": ("insurance id", "insurance number", "policy number", "member id", "insurancenumber"),
    "diagnosis": ("diagnosis", "condition", "disorder", "impression", "clinical impression"),
    "medication": ("medication", "medicine", "drug", "drug name", "prescription", "medication name", "दवा", "औषधि"),
    "dose": ("dose", "dosage", "strength"),
    "frequency": ("frequency", "schedule", "dosing frequency"),
    "measurement_value": ("measurement value", "result value", "observation value"),
    "measurement_unit": ("unit", "units", "measurement unit", "result unit"),
    "date": ("date", "visit date", "admission date", "discharge date", "encounter date", "timestamp"),
}

_DEFAULT_CLINICAL_TERMS: dict[str, dict[str, str]] = {
    "parkinson's disease": {"canonical_term": "Parkinson's disease", "category": "diagnosis"},
    "parkinson disease": {"canonical_term": "Parkinson's disease", "category": "diagnosis"},
    "addison's disease": {"canonical_term": "Addison's disease", "category": "diagnosis"},
    "addison disease": {"canonical_term": "Addison's disease", "category": "diagnosis"},
    "diabetes mellitus": {"canonical_term": "diabetes mellitus", "category": "diagnosis"},
    "hypertension": {"canonical_term": "hypertension", "category": "diagnosis"},
    "fever": {"canonical_term": "fever", "category": "symptom"},
    "cough": {"canonical_term": "cough", "category": "symptom"},
    "headache": {"canonical_term": "headache", "category": "symptom"},
    "ramipril": {"canonical_term": "ramipril", "category": "medication"},
    "metformin": {"canonical_term": "metformin", "category": "medication"},
    "paracetamol": {"canonical_term": "paracetamol", "category": "medication"},
    "dolo": {"canonical_term": "Dolo", "category": "medication", "brand_name": "true"},
    "बुखार": {"canonical_term": "fever", "category": "symptom"},
    "खांसी": {"canonical_term": "cough", "category": "symptom"},
    "मधुमेह": {"canonical_term": "diabetes mellitus", "category": "diagnosis"},
    "उच्च रक्तचाप": {"canonical_term": "hypertension", "category": "diagnosis"},
}

_RELATIVE_MARKER = re.compile(r"(?i)(?:^|\b)(s\s*/\s*o|d\s*/\s*o|w\s*/\s*o)\s*[:.-]?\s*(.+)$")
_CARE_OF = re.compile(r"(?i)(?:^|\b)(c\s*/\s*o)\s*[:.-]?\s*(.+)$")
_DR_PREFIX = re.compile(r"(?i)^\s*(?:dr\.?|डॉ\.?)(?:\s+|$)")
_PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
_MRN_RE = re.compile(r"^[A-Z0-9][A-Z0-9/-]{2,31}$", re.I)
_ABHA_ADDR_RE = re.compile(r"^[A-Z0-9._-]{2,64}@abdm$", re.I)
_DOSE_OR_UNIT = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?\s*(?:mmol/l|mg/dl|mmhg|mcg|μg|ug|mg|kg|g|ml|l|bpm|°c|%)(?!\w)", re.I)
_DOSE_SCHEDULE = re.compile(r"(?<!\w)\d+-\d+-\d+(?!\w)")

# Verhoeff checksum tables for Aadhaar-like format validation.
_D = ((0,1,2,3,4,5,6,7,8,9),(1,2,3,4,0,6,7,8,9,5),(2,3,4,0,1,7,8,9,5,6),
      (3,4,0,1,2,8,9,5,6,7),(4,0,1,2,3,9,5,6,7,8),(5,9,8,7,6,0,4,3,2,1),
      (6,5,9,8,7,1,0,4,3,2),(7,6,5,9,8,2,1,0,4,3),(8,7,6,5,9,3,2,1,0,4),
      (9,8,7,6,5,4,3,2,1,0))
_P = ((0,1,2,3,4,5,6,7,8,9),(1,5,7,6,2,8,3,0,9,4),(5,8,0,3,7,9,6,1,4,2),
      (8,9,1,6,0,4,3,5,2,7),(9,4,5,3,1,2,6,8,7,0),(4,2,8,6,5,7,3,9,0,1),
      (2,7,9,3,8,0,6,4,1,5),(7,0,4,6,9,1,3,2,5,8))


def _key(value: str) -> str:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("_", " ")
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def normalize_field_key(value: str) -> str:
    """Normalize a field/heading label with the same rules used by Normalize."""
    return _key(value)


def _verhoeff_valid(digits: str) -> bool:
    if not digits or len(set(digits)) == 1:
        return False
    check = 0
    for position, char in enumerate(reversed(digits)):
        check = _D[check][_P[position % 8][int(char)]]
    return check == 0


def _canonical_fields(config: SemanticNormalizationConfig) -> dict[str, tuple[str, ...]]:
    combined = dict(_DEFAULT_FIELD_SYNONYMS)
    for canonical, aliases in config.field_synonyms.items():
        if isinstance(aliases, str):
            aliases = (aliases,)
        combined[canonical] = tuple(dict.fromkeys((*combined.get(canonical, ()), *aliases)))
    normalized: dict[str, tuple[str, ...]] = {}
    for canonical, aliases in combined.items():
        normalized[canonical] = tuple(dict.fromkeys(_key(alias) for alias in (canonical, *aliases)))
    return normalized


def _map_field(name: str, context: list[str], siblings: dict[str, Any], value: Any,
               aliases: dict[str, tuple[str, ...]]) -> tuple[str | None, str, str]:
    key = _key(name)
    matches = [concept for concept, terms in aliases.items() if key in terms]
    if key in {"name", "fullname", "given", "family", "firstname", "lastname"}:
        context_key = " ".join(_key(item) for item in context)
        if "patient" in context_key or siblings.get("resourceType") == "Patient":
            matches.append("patient_name")
        if siblings.get("resourceType") in {"Practitioner", "PractitionerRole"} or any(
                token in context_key for token in ("doctor", "physician", "practitioner", "provider")):
            matches.append("doctor_name")
        if any(token in context_key for token in ("relative", "guardian", "father", "mother", "spouse", "next of kin")):
            matches.append("relative_name")
    if key == "value":
        system = str(siblings.get("system", siblings.get("type", ""))).casefold()
        if system in {"phone", "mobile", "telephone", "contact phone"}:
            matches.append("phone")
        elif system in {"email", "email address"}:
            matches.append("email")
        elif system == "fax":
            matches.append("contact_value")
        parent_hint = " ".join(_key(item) for item in context)
        if siblings.get("unit") and any(x in parent_hint for x in ("weight", "height", "observation", "measurement")):
            matches.append("measurement_value")
    # Value patterns can resolve a generic field only for a highly specific format.
    if isinstance(value, str) and key in {"value", "contact", "detail"}:
        if normalize_email(value)[1] == "success":
            matches.append("email")
        if normalize_date(value)[1] == "success":
            matches.append("date")
    matches = list(dict.fromkeys(matches))
    if len(matches) == 1:
        return matches[0], "RESOLVED", "field_synonym_or_structural_context"
    if len(matches) > 1:
        return None, "AMBIGUOUS", "conflicting_field_context"
    if key in {"value", "type", "description", "name", "id", "identifier"}:
        return None, "UNKNOWN", "generic_field_without_sufficient_context"
    return None, "UNKNOWN", "no_configured_field_mapping"


def map_field_name(name: str, *, context: list[str] | None = None,
                   siblings: dict[str, Any] | None = None, value: Any = None,
                   config: SemanticNormalizationConfig | None = None) -> tuple[str | None, str, str]:
    """Public Normalize field mapper reused by later contextual stages."""
    return _map_field(name, context or [], siblings or {}, value,
                      _canonical_fields(config or SemanticNormalizationConfig()))


def _clinical_lexicon(config: SemanticNormalizationConfig) -> dict[str, dict[str, str]]:
    result = dict(_DEFAULT_CLINICAL_TERMS)
    for term, metadata in config.clinical_terms.items():
        result[_clinical_key(term)] = dict(metadata)
    return result


def _clinical_key(value: str) -> str:
    value = unicodedata.normalize("NFC", value).casefold().replace("’", "'")
    return " ".join(value.split())


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.replace("’", "'" )).replace("'", "['’]")
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE | re.UNICODE)


def _identifier_findings(value: str, field: str | None, context: list[str],
                         default_phone_region: str | None = None) -> list[dict[str, Any]]:
    if not value.strip():
        return []
    field_key = _key(field or "")
    context_key = " ".join(_key(x) for x in context)
    findings: list[dict[str, Any]] = []
    compact = re.sub(r"[\s-]", "", value).upper()
    digits = "".join(str(unicodedata.digit(ch)) if ch.isdecimal() else ch
                     for ch in compact if ch.isdigit())
    aadhaar_context = "aadhaar" in context_key + " " + field_key or "aadhar" in context_key + " " + field_key or field_key == "uid"
    if aadhaar_context:
        clean_digit_string = all(ch.isdecimal() for ch in compact)
        format_match = len(digits) == 12 and digits.isascii() and digits[0] in "23456789" and clean_digit_string
        valid = format_match and _verhoeff_valid(digits)
        findings.append({"classification": "aadhaar", "format_match": format_match,
                         "checksum_valid": valid,
                         "status": "RESOLVED" if valid else "INVALID",
                         "method": "aadhaar_field_context+verhoeff"})
    elif len(digits) == 12 and digits.isascii() and digits[0] in "23456789" and _verhoeff_valid(digits):
        findings.append({"classification": "possible_aadhaar", "format_match": True,
                         "checksum_valid": True, "status": "AMBIGUOUS",
                         "method": "verhoeff_without_identifier_field_context"})
    pan_context = "pan" in context_key + " " + field_key or "permanent account" in context_key
    if pan_context:
        pan_valid = bool(_PAN_RE.fullmatch(compact) and compact[3] in "ABCFGHJLPT")
        findings.append({"classification": "pan", "format_match": pan_valid,
                         "status": "RESOLVED" if pan_valid else "INVALID",
                         "method": "pan_field_context+format"})
    elif _PAN_RE.fullmatch(compact) and compact[3] in "ABCFGHJLPT":
        findings.append({"classification": "possible_pan", "format_match": True,
                         "status": "AMBIGUOUS", "method": "pan_format_without_field_context"})
    if "abha" in context_key + " " + field_key or "health id" in context_key:
        abha_shape = bool(_ABHA_ADDR_RE.fullmatch(value.strip()) or (len(digits) == 14 and digits.isascii()))
        findings.append({"classification": "abha", "format_match": abha_shape,
                         "status": "LOW_CONFIDENCE" if abha_shape else "INVALID",
                         "method": "abha_field_context+shape_only"})
    if (field_key == "phone" or "phone" in field_key or "mobile" in field_key or
            "telephone" in field_key or field_key in {"contact number", "emergency contact number"}):
        from .phones import normalize_phone
        canonical, status, warnings, details = normalize_phone(value, default_region=default_phone_region)
        if status == "success":
            findings.append({"classification": "phone", "format_match": True,
                             "normalized_value": canonical, "status": "RESOLVED",
                             "method": "phone_field_context+phonenumbers",
                             "number_validation": details})
        elif status == "unsupported":
            findings.append({"classification": "phone", "format_match": False,
                             "status": "UNKNOWN", "method": "phone_library_unavailable",
                             "warnings": warnings})
        elif status == "invalid":
            findings.append({"classification": "phone", "format_match": False,
                             "status": "INVALID", "method": "phone_field_context+phonenumbers",
                             "warnings": warnings, "details": details})
    mrn_context = any(x in context_key + " " + field_key for x in ("mrn", "uhid", "medical record", "hospital id", "patient id"))
    if mrn_context:
        valid = bool(_MRN_RE.fullmatch(compact) and any(ch.isdigit() for ch in compact) and any(ch.isalpha() for ch in compact))
        findings.append({"classification": "uhid_mrn", "format_match": valid,
                         "status": "LOW_CONFIDENCE" if valid else "INVALID",
                         "method": "identifier_field_context+alphanumeric_shape"})
    insurance_context = any(x in context_key + " " + field_key for x in ("insurance", "policy number", "member id"))
    if insurance_context:
        valid = bool(re.fullmatch(r"[A-Z0-9][A-Z0-9/-]{4,31}", compact))
        findings.append({"classification": "insurance_id", "format_match": valid,
                         "status": "LOW_CONFIDENCE" if valid else "INVALID",
                         "method": "insurance_field_context+shape_only"})
    return findings


def _role_findings(value: str, field: str | None, context: list[str], clinical_terms: dict[str, Any]) -> list[dict[str, Any]]:
    field_key = _key(field or "")
    context_key = " ".join(_key(x) for x in context)
    evidence: list[tuple[str, str]] = []
    if field_key in {"patient name", "date of birth", "patientname", "dateofbirth"} or (
            "patient" in field_key and any(x in field_key for x in ("name", "given", "family"))):
        evidence.append(("PATIENT", "patient_field"))
    elif "patient" in context_key and field_key in {"name", "given", "family", "text"}:
        evidence.append(("PATIENT", "patient_resource_context"))
    if any(resource in context_key for resource in ("practitioner", "practitioner role")) and field_key in {
            "name", "given", "family", "text"}:
        evidence.append(("DOCTOR", "practitioner_resource_context"))
    if any(x in field_key for x in ("doctor", "physician", "practitioner", "provider")):
        evidence.append(("DOCTOR", "clinician_field"))
    if any(x in field_key for x in ("relative", "father", "mother", "spouse", "guardian", "nextofkin")):
        evidence.append(("RELATIVE", "relative_field"))
    if "caregiver" in field_key or "attendant" in field_key:
        evidence.append(("CAREGIVER", "caregiver_field"))
    if "emergency contact" in field_key or "emergencycontact" in field_key.replace(" ", ""):
        evidence.append(("EMERGENCY_CONTACT", "emergency_contact_field"))
    if _DR_PREFIX.search(value):
        evidence.append(("DOCTOR", "explicit_dr_honorific"))
    relative = _RELATIVE_MARKER.search(value)
    if relative:
        evidence.append(("RELATIVE", "explicit_s_d_w_of_marker"))
    care = _CARE_OF.search(value)
    if care:
        candidate = care.group(2).strip().split()[0].strip(".,;:").casefold()
        if _clinical_key(candidate) in clinical_terms:
            return [{"role": "UNKNOWN", "status": "NOT_APPLICABLE",
                     "method": "c_o_clinical_complaint_context", "candidate_roles": []}]
        if any(role == "PATIENT" for role, _ in evidence) and care.start() > 0 and care.group(1).strip():
            return [
                {"role": "PATIENT", "status": "RESOLVED", "method": "patient_field",
                 "candidate_roles": ["PATIENT"], "start": 0, "end": care.start()},
                {"role": "RELATIVE", "status": "RESOLVED", "method": "explicit_c_o_marker",
                 "candidate_roles": ["RELATIVE"], "start": care.start(2), "end": care.end(2)},
            ]
        if any(token in field_key for token in ("relative", "caregiver", "contact", "guardian")):
            evidence.append(("RELATIVE", "c_o_relation_field_context"))
        else:
            return [{"role": "UNKNOWN", "status": "AMBIGUOUS",
                     "method": "c_o_marker_without_relation_context",
                     "candidate_roles": ["RELATIVE", "COMPLAINT"],
                     "start": care.start(1), "end": care.end(1)}]
    roles = sorted({item[0] for item in evidence})
    if relative and "PATIENT" in roles:
        # A patient record may include an explicit relative alongside the patient.
        # Keep both roles and their spans instead of collapsing them into a conflict.
        result = []
        if relative.start() > 0:
            result.append({"role": "PATIENT", "status": "RESOLVED", "method": "patient_field",
                           "candidate_roles": ["PATIENT"], "start": 0, "end": relative.start()})
        result.append(
            {"role": "RELATIVE", "status": "RESOLVED", "method": "explicit_s_d_w_of_marker",
             "candidate_roles": ["RELATIVE"], "start": relative.start(2), "end": relative.end(2)})
        return result
    if len(roles) == 1:
        return [{"role": roles[0], "status": "RESOLVED",
                 "method": "+".join(sorted({method for role, method in evidence if role == roles[0]})),
                 "candidate_roles": roles, "start": 0, "end": len(value)}]
    if len(roles) > 1:
        return [{"role": "UNKNOWN", "status": "AMBIGUOUS", "method": "conflicting_role_evidence",
                 "candidate_roles": roles, "start": 0, "end": len(value)}]
    return []


def _abbreviation_findings(value: str, field: str | None, context: list[str],
                           config: SemanticNormalizationConfig, clinical_terms: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    all_text = " ".join([value, field or "", *context])
    patterns = {
        "C/O": re.compile(r"(?i)\bc\s*/\s*o\b"),
        "BD": re.compile(r"(?i)\bb\.?d\.?\b"),
        "PT": re.compile(r"(?i)\bpt\b"),
        "DC": re.compile(r"(?i)\bd\.?c\.?\b"),
    }
    for abbr, pattern in patterns.items():
        for match in pattern.finditer(value):
            before, after = value[:match.start()].casefold(), value[match.end():].casefold()
            context_lower = all_text.casefold()
            expansion = {key.upper(): item for key, item in config.abbreviation_expansions.items()}.get(abbr)
            status = "AMBIGUOUS"
            method = "abbreviation_requires_context"
            candidates: list[str] = []
            if abbr == "C/O":
                following = after.strip(" :.-").split()
                token = re.sub(r"[^\w']", "", following[0]).casefold() if following else ""
                if token in clinical_terms and clinical_terms[token].get("category") in {"symptom", "diagnosis"}:
                    expansion, status, method = "complaint_of", "RESOLVED", "c_o_followed_by_clinical_term"
                    candidates = ["complaint_of"]
                elif any(label in _key(field or "") + " " + " ".join(_key(item) for item in context)
                         for label in ("relative", "caregiver", "contact", "guardian")):
                    expansion, status, method = "care_of_relative", "RESOLVED", "c_o_relation_field_context"
                    candidates = ["care_of_relative"]
                else:
                    candidates = ["complaint_of", "care_of_relative"]
            elif abbr == "BD":
                field_context = _key(field or "") + " " + " ".join(_key(item) for item in context)
                med_context = ("frequency" in field_context or "medication" in field_context or
                               "prescription" in field_context or "drug" in field_context or bool(
                    re.search(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml)\b", before + " " + after)) or any(
                    _key(term) in _key(context_lower) for term, meta in clinical_terms.items()
                    if meta.get("category") == "medication"))
                if med_context:
                    expansion, status, method = "twice_daily", "RESOLVED", "bd_medication_or_dose_context"
                    candidates = ["twice_daily"]
                else:
                    candidates = ["twice_daily", "other_abbreviation"]
            elif abbr == "PT":
                if re.search(r"\b(?:sec|secs|second|seconds|inr)\b", after) or re.search(r"\b(?:sec|secs|second|seconds|inr)\b", before):
                    expansion, status, method = "prothrombin_time", "RESOLVED", "pt_coagulation_unit_context"
                    candidates = ["prothrombin_time"]
                elif "physical therapy" in context_lower or "physiotherapy" in context_lower:
                    expansion, status, method = "physical_therapy", "RESOLVED", "pt_therapy_context"
                    candidates = ["physical_therapy"]
                else:
                    candidates = ["patient", "prothrombin_time", "physical_therapy"]
            elif abbr == "DC":
                if any(x in context_lower for x in ("discharge", "disposition", "home today")):
                    expansion, status, method = "discharge", "RESOLVED", "dc_disposition_context"
                    candidates = ["discharge"]
                elif any(x in context_lower for x in ("medication", "stop drug", "discontinue", "prescription")):
                    expansion, status, method = "discontinue", "RESOLVED", "dc_medication_instruction_context"
                    candidates = ["discontinue"]
                else:
                    candidates = ["discharge", "discontinue", "other_abbreviation"]
            if expansion and status == "AMBIGUOUS":
                # User-supplied expansion is retained as a candidate only; a
                # dictionary alone cannot resolve a context-sensitive acronym.
                candidates = list(dict.fromkeys([expansion, *candidates]))
            findings.append({"abbreviation": abbr, "expansion": expansion if status == "RESOLVED" else None,
                             "candidates": candidates, "status": status, "method": method,
                             "start": match.start(), "end": match.end()})
    return findings


def _emit(locator: str, finding_type: str, *, entity_type: str | None = None,
          pii_classification: str | None = None, details: dict[str, Any], status: str,
          counter: int) -> Annotation:
    detect_status = (DetectionStatus.DETECTED if status in {"RESOLVED", "LOW_CONFIDENCE"}
                     else DetectionStatus.UNCERTAIN if status == "AMBIGUOUS"
                     else DetectionStatus.NOT_DETECTED if status == "INVALID"
                     else DetectionStatus.NOT_EVALUATED)
    return Annotation(annotation_id=f"SEM-{counter:08d}", finding_type=finding_type,
                      locator=locator, entity_type=entity_type,
                      pii_classification=pii_classification, detection_method=details.get("method"),
                      validation_result=status,
                      detection_status=detect_status, uncertain=status in {"AMBIGUOUS", "UNKNOWN", "LOW_CONFIDENCE"},
                      review_required=status in {"AMBIGUOUS", "LOW_CONFIDENCE"},
                      details={**details, "status": status})


def normalize_semantics(ir: IntermediateRepresentation, *,
                        config: SemanticNormalizationConfig | None = None,
                        default_phone_region: str | None = None) -> IntermediateRepresentation:
    """Add sparse semantic annotations while preserving source data and existing edits."""
    if ir.processing_status == ProcessingStatus.QUARANTINED:
        return ir
    cfg = config or SemanticNormalizationConfig()
    aliases = _canonical_fields(cfg)
    terms = _clinical_lexicon(cfg)
    metadata = list(iter_field_metadata(ir))
    by_locator = {item.locator: item for item in metadata}
    repeated_column_hints: dict[int, tuple[str | None, str, str]] = {}
    if ir.source.format in {"csv", "tsv"}:
        header, rows = ir.structure.data.get("header", []), ir.structure.data.get("rows", [])
        for column, label in enumerate(header):
            if _key(str(label)) not in {"value", "type", "description", "contact", "detail"}:
                continue
            concepts: list[str | None] = []
            for row in rows:
                if column >= len(row) or not isinstance(row[column], str) or not row[column].strip():
                    continue
                cell = row[column]
                email_status = normalize_email(cell)[1]
                date_status = normalize_date(cell)[1]
                concepts.append("email" if email_status == "success" else
                                "date" if date_status == "success" else None)
            if len(concepts) >= 2:
                known = [concept for concept in concepts if concept]
                if len(known) == len(concepts) and len(set(known)) == 1:
                    repeated_column_hints[column] = (known[0], "RESOLVED", "repeated_column_value_consensus")
                elif len(known) == len(concepts) and len(set(known)) > 1:
                    repeated_column_hints[column] = (None, "AMBIGUOUS", "conflicting_repeated_value_patterns")
    sibling_index: dict[str, dict[str, Any]] = {}
    for item in metadata:
        if item.parent_locator:
            sibling_index.setdefault(item.parent_locator, {})[item.field_name] = item
    generated: dict[str, list[Annotation]] = {}
    counter = 0

    def add(locator: str, kind: str, *, details: dict[str, Any], status: str,
            entity_type: str | None = None, pii_classification: str | None = None) -> None:
        nonlocal counter
        counter += 1
        generated.setdefault(locator, []).append(_emit(
            locator, kind, entity_type=entity_type, pii_classification=pii_classification,
            details=details, status=status, counter=counter))

    for meta in metadata:
        if meta.field_kind != "leaf":
            continue
        try:
            value = get_value(ir, meta.locator)
        except (ValueError, TypeError):
            value = None
        context: list[str] = []
        parent = meta.parent_locator
        while parent and parent in by_locator:
            ancestor = by_locator[parent]
            context.append(ancestor.field_name)
            try:
                ancestor_value = get_value(ir, ancestor.locator)
                if isinstance(ancestor_value, dict) and isinstance(ancestor_value.get("resourceType"), str):
                    context.append(ancestor_value["resourceType"])
            except (ValueError, TypeError):
                pass
            parent = ancestor.parent_locator
        context.reverse()
        siblings: dict[str, Any] = {}
        if meta.parent_locator:
            for name, item in sibling_index.get(meta.parent_locator, {}).items():
                if name == meta.field_name:
                    continue
                try:
                    siblings[name] = get_value(ir, item.locator)
                except (ValueError, TypeError):
                    continue
            try:
                parent_value = get_value(ir, meta.parent_locator)
                if isinstance(parent_value, dict):
                    for field_name in ("resourceType", "system", "type", "unit"):
                        if isinstance(parent_value.get(field_name), str):
                            siblings[field_name] = parent_value[field_name]
                    if isinstance(parent_value.get("resourceType"), str):
                        context.append(parent_value["resourceType"])
            except (ValueError, TypeError):
                pass
        effective_name = meta.field_name
        if effective_name.isdigit() and meta.parent_locator in by_locator:
            # Array leaf values (notably FHIR `given[]`) inherit their array
            # field's schema name while retaining the exact indexed locator.
            effective_name = by_locator[meta.parent_locator].field_name
        if meta.field_name == "text" and meta.parent_locator:
            try:
                parent_value = get_value(ir, meta.parent_locator)
                if isinstance(parent_value, dict) and parent_value.get("node_type") == "element":
                    effective_name = str(parent_value.get("tag", "text")).rsplit("}", 1)[-1]
            except (ValueError, TypeError):
                pass
        canonical, field_status, field_method = _map_field(effective_name, context, siblings, value, aliases)
        column_match = re.fullmatch(r"(?:header:col:|row:\d+,col:)(\d+)", meta.locator)
        repeated_hint = repeated_column_hints.get(int(column_match.group(1))) if column_match else None
        if repeated_hint and _key(effective_name) in {"value", "type", "description", "contact", "detail"}:
            if repeated_hint[1] == "AMBIGUOUS":
                canonical, field_status, field_method = repeated_hint
            elif canonical is None and field_status == "UNKNOWN":
                canonical, field_status, field_method = repeated_hint
        if canonical or field_status in {"AMBIGUOUS", "UNKNOWN"} and _key(effective_name) in {
            "value", "type", "description", "name", "id", "identifier"
        }:
            add(meta.locator, "canonical_field", entity_type="FIELD", status=field_status,
                details={"canonical_field": canonical, "source_field": effective_name,
                         "method": field_method, "context": context})
        if meta.locator.startswith("header:col:"):
            continue
        text_value = value if isinstance(value, str) else ""
        if not text_value:
            continue

        if canonical in {"patient_name", "person_name", "doctor_name", "relative_name", "caregiver_name"}:
            relation = _RELATIVE_MARKER.search(text_value)
            care_relation = _CARE_OF.search(text_value)
            if relation is None and care_relation and canonical in {"patient_name", "relative_name"}:
                relation = care_relation
            name_source = text_value
            name_start, name_end = 0, len(text_value)
            relationship_marker = None
            if relation:
                relationship_marker = (relation.group(1).upper().replace(" ", "")
                                       if relation.re is _RELATIVE_MARKER else "C/O")
                if canonical == "relative_name":
                    name_source = relation.group(2)
                    name_start, name_end = relation.start(2), relation.end(2)
                elif canonical == "patient_name":
                    name_source = text_value[:relation.start()].strip()
                    name_end = relation.start()
            name_form = normalize_person_name(name_source)
            normalized_name, honorifics, name_meta = (name_form.normalized_value,
                                                       list(name_form.honorifics), name_form.metadata)
            if normalized_name:
                add(meta.locator, "normalized_name", entity_type="PERSON_NAME", status="RESOLVED",
                    details={"canonical_field": canonical, "normalized_value": normalized_name,
                             "honorifics": honorifics, "method": "unicode_whitespace_punctuation",
                             "source_span": [name_start, name_end],
                             "relationship_marker": relationship_marker, **name_meta})
            if relation and canonical == "patient_name" and relation.group(2).strip():
                relative_form = normalize_person_name(relation.group(2))
                if relative_form.normalized_value:
                    add(meta.locator, "normalized_name", entity_type="PERSON_NAME", status="RESOLVED",
                        details={"canonical_field": "relative_name",
                                 "normalized_value": relative_form.normalized_value,
                                 "honorifics": list(relative_form.honorifics),
                                 "source_span": [relation.start(2), relation.end(2)],
                                 "relationship_marker": relationship_marker,
                                 "method": "explicit_s_d_w_of_relation_marker",
                                 **relative_form.metadata})
            if cfg.transliterate_names and normalized_name:
                from .transliteration import transliterate
                script = name_meta["script"]["script"]
                if script in {"Devanagari", "Kannada"}:
                    output, translit_status, warnings, details = transliterate(
                        normalized_name, source_script=script, scheme=cfg.transliteration_scheme)
                    add(meta.locator, "transliterated_name", entity_type="PERSON_NAME",
                        status="RESOLVED" if translit_status == "success" else "UNKNOWN",
                        details={"normalized_value": output, "warnings": warnings,
                                 "method": "indic_transliteration", **details,
                                 "identity_equivalence": "not_asserted"})

        for identifier in _identifier_findings(text_value, effective_name, [*context, canonical or ""],
                                               default_phone_region=default_phone_region):
            status = identifier.pop("status", "UNKNOWN")
            classification = identifier.get("classification")
            identifier["verification_scope"] = "format_or_checksum_only; identity_and_ownership_unverified"
            add(meta.locator, "identifier_classification", entity_type="IDENTIFIER",
                pii_classification=classification if classification not in {"possible_aadhaar", "possible_pan"} else None,
                status=status, details=identifier)

        # Recognize terminology as spans, never replacing the source text.
        for term_key, info in sorted(terms.items(), key=lambda item: (-len(item[0]), item[0])):
            pattern = _term_pattern(term_key)
            for match in pattern.finditer(text_value):
                category = info.get("category", "clinical")
                add(meta.locator, "clinical_term", entity_type=category.upper(),
                    status="RESOLVED", details={"term": text_value[match.start():match.end()],
                    "canonical_term": info.get("canonical_term", term_key),
                    "concept_id": info.get("concept_id"), "category": category,
                    "method": "configurable_dictionary_exact", "start": match.start(), "end": match.end(),
                    "brand_name": info.get("brand_name") == "true"})

        for match in _DOSE_OR_UNIT.finditer(text_value):
            add(meta.locator, "clinical_measurement", entity_type="CLINICAL_MEASUREMENT",
                status="RESOLVED", details={"value": match.group(0), "category": "explicit_number_unit",
                "method": "numeric_value_and_explicit_unit", "start": match.start(), "end": match.end()})
        for match in _DOSE_SCHEDULE.finditer(text_value):
            add(meta.locator, "clinical_measurement", entity_type="CLINICAL_SCHEDULE",
                status="RESOLVED", details={"value": match.group(0), "category": "explicit_schedule_pattern",
                "method": "three_part_dose_schedule_pattern", "start": match.start(), "end": match.end()})

        for abbreviation in _abbreviation_findings(text_value, canonical or effective_name, context, cfg, terms):
            status = abbreviation.pop("status")
            add(meta.locator, "clinical_abbreviation", entity_type="CLINICAL_ABBREVIATION",
                status=status, details={**abbreviation, "method": abbreviation.get("method")})

        for role in _role_findings(text_value, canonical or effective_name, context, terms):
            status = role.pop("status")
            if status != "NOT_APPLICABLE":
                add(meta.locator, "person_role", entity_type="PERSON_ROLE", status=status,
                    details=role)

    # Replace only this stage's prior annotations; preserve independent detections.
    merged = {locator: [item for item in items if not item.annotation_id.startswith("SEM-")]
              for locator, items in ir.annotations.items()}
    merged = {locator: items for locator, items in merged.items() if items}
    for locator, items in generated.items():
        merged.setdefault(locator, []).extend(items)
    object.__setattr__(ir, "annotations", merged)
    if generated and ir.processing_status == ProcessingStatus.PARSED:
        object.__setattr__(ir, "processing_status", ProcessingStatus.ANNOTATED)
    return ir


def clinical_protected_spans(value: str, *,
                             config: SemanticNormalizationConfig | None = None) -> list[dict[str, Any]]:
    """Return explicit clinical spans for downstream PII detectors to exclude."""
    terms = _clinical_lexicon(config or SemanticNormalizationConfig())
    spans: list[dict[str, Any]] = []
    for term, metadata in terms.items():
        for match in _term_pattern(term).finditer(value):
            spans.append({"start": match.start(), "end": match.end(),
                          "kind": metadata.get("category", "clinical"),
                          "term": value[match.start():match.end()], "method": "clinical_dictionary"})
    for pattern, kind in ((_DOSE_OR_UNIT, "measurement"), (_DOSE_SCHEDULE, "dose_schedule")):
        for match in pattern.finditer(value):
            spans.append({"start": match.start(), "end": match.end(), "kind": kind,
                          "term": match.group(0), "method": "explicit_numeric_clinical_pattern"})
    return sorted(spans, key=lambda item: (item["start"], item["end"], item["kind"]))

