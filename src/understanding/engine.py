"""Structural context, contextual classification, and relationship extraction.

This stage reads the format-native IR and reuses Normalize annotations. It only
adds sparse ``UND-`` annotations; source values and existing findings are left
untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from src.ir import (Annotation, DetectionStatus, IntermediateRepresentation,
                    ProcessingStatus, get_value, iter_field_metadata)
from src.normalization.semantic import (SemanticNormalizationConfig, map_field_name,
                                        normalize_field_key)


@dataclass(frozen=True)
class UnderstandingConfig:
    """Context vocabulary and field aliases, layered on Normalize's lexicons."""
    semantic: SemanticNormalizationConfig = SemanticNormalizationConfig()
    section_aliases: dict[str, tuple[str, ...]] | None = None


_SECTIONS: dict[str, tuple[str, ...]] = {
    "PATIENT_DETAILS": ("patient details", "patient information", "patient particulars",
                        "demographics", "patient demographics", "रोगी विवरण", "मरीज का विवरण"),
    "MEDICAL_HISTORY": ("medical history", "past medical history", "clinical history",
                        "history of present illness", "history", "medical hx", "रोग इतिहास"),
    "PRESCRIPTION": ("prescription", "prescriptions", "medication", "medications",
                     "treatment", "treatment plan", "दवा", "नुस्खा"),
    "DIAGNOSIS": ("diagnosis", "diagnoses", "assessment", "clinical impression"),
    "FAMILY_HISTORY": ("family history", "family medical history"),
    "EXAMINATION": ("examination", "physical examination", "clinical examination"),
    "INVESTIGATIONS": ("investigation", "investigations", "laboratory", "lab results", "test results"),
}
_HEADING_FIELDS = {"title", "heading", "section", "sectiontitle", "sectionname"}
_TEXT_HEADING = re.compile(r"^\s*(.{2,80}?)\s*[:：]?\s*$")
_LABELED_LINE = re.compile(r"^\s*([^:\n：]{1,64})\s*[:：]\s*(.*?)\s*$")
_PRESCRIBED_BY = re.compile(r"(?i)\bprescribed\s+by\b\s*[:,-]?\s*(.+?)\s*$")
_DIAGNOSED_WITH = re.compile(r"(?i)\bdiagnosed\s+with\b\s*[:,-]?\s*(.+?)\s*$")
_RELATIVE_MARKER = re.compile(r"(?i)(?:^|\b)(s\s*/\s*o|d\s*/\s*o|w\s*/\s*o)\s*[:.-]?\s*(.+)$")
_CARE_OF = re.compile(r"(?i)(?:^|\b)(c\s*/\s*o)\s*[:.-]?\s*(.+)$")


def _section_lookup(config: UnderstandingConfig) -> dict[str, str]:
    vocab = dict(_SECTIONS)
    for canonical, aliases in (config.section_aliases or {}).items():
        if isinstance(aliases, str):
            aliases = (aliases,)
        vocab[canonical] = tuple(dict.fromkeys((*vocab.get(canonical, ()), *aliases)))
    return {normalize_field_key(alias): canonical for canonical, aliases in vocab.items()
            for alias in (canonical, *aliases)}


def _heading(value: str, lookup: dict[str, str]) -> str | None:
    cleaned = value.strip().strip("#*-_ ").strip(".:")
    return lookup.get(normalize_field_key(cleaned))


def _path_has_ancestor(locator: str, ancestor: str) -> bool:
    if locator == ancestor:
        return True
    return locator.startswith(ancestor + ".") or locator.startswith(ancestor + "[")


def _span_for_line(start: int, line: str, value: str) -> tuple[int, int]:
    found = value.find(line, start)
    return (found, found + len(line)) if found >= 0 else (start, start + len(line))


def _annotation_map(ir: IntermediateRepresentation) -> dict[str, list[Annotation]]:
    return ir.annotations


def _normalized_facts(items: list[Annotation]) -> tuple[str | None, list[Annotation], list[Annotation], list[Annotation]]:
    canonical: str | None = None
    canonical_ann = []
    terms = []
    names = []
    roles = []
    for item in items:
        if item.finding_type == "canonical_field":
            canonical_ann.append(item)
            candidate = item.details.get("canonical_field")
            if isinstance(candidate, str) and item.details.get("status") == "RESOLVED":
                canonical = candidate
        elif item.finding_type == "clinical_term":
            terms.append(item)
        elif item.finding_type == "normalized_name":
            names.append(item)
        elif item.finding_type == "person_role":
            roles.append(item)
    return canonical, terms, names, roles


def _stable_annotation(locator: str, finding_type: str, counter: int, status: str,
                       details: dict[str, Any], *, entity_type: str | None = None) -> Annotation:
    detection_status = (DetectionStatus.DETECTED if status == "RESOLVED" else
                        DetectionStatus.UNCERTAIN if status == "AMBIGUOUS" else
                        DetectionStatus.NOT_EVALUATED)
    return Annotation(annotation_id=f"UND-{counter:08d}", finding_type=finding_type,
                      locator=locator, entity_type=entity_type,
                      detection_method=details.get("method"), detection_status=detection_status,
                      validation_result=status,
                      uncertain=status in {"AMBIGUOUS", "UNKNOWN"},
                      review_required=status == "AMBIGUOUS",
                      details={**details, "status": status})


def _line_sections(value: str, lookup: dict[str, str]) -> tuple[list[dict[str, Any]], list[tuple[int, int, str]]]:
    """Recognize exact standalone headings and return their subsequent content spans."""
    lines: list[tuple[int, int, str]] = []
    offset = 0
    for raw_line in value.splitlines(keepends=True):
        content = raw_line.rstrip("\r\n")
        end = offset + len(content)
        lines.append((offset, end, content))
        offset += len(raw_line)
    if value and (not lines or offset < len(value)):
        lines.append((offset, len(value), value[offset:]))
    headings: list[tuple[int, int, str, str]] = []
    for start, end, line in lines:
        match = _TEXT_HEADING.fullmatch(line)
        section = _heading(match.group(1), lookup) if match else None
        if section:
            headings.append((start, end, line, section))
    ranges: list[tuple[int, int, str]] = []
    findings: list[dict[str, Any]] = []
    for index, (start, end, line, section) in enumerate(headings):
        scope_end = headings[index + 1][0] if index + 1 < len(headings) else len(value)
        findings.append({"heading": line.strip(), "canonical_section": section,
                         "heading_span": [start, end], "content_span": [end, scope_end],
                         "method": "standalone_text_heading"})
        ranges.append((end, scope_end, section))
    return findings, ranges


def _xml_section_root(ir: IntermediateRepresentation, heading_locator: str,
                      metadata_by_locator: dict[str, Any]) -> str | None:
    current = metadata_by_locator.get(heading_locator)
    parent = current.parent_locator if current else None
    nearest_container = None
    while parent and parent in metadata_by_locator:
        item = metadata_by_locator[parent]
        try:
            value = get_value(ir, parent)
        except (ValueError, TypeError):
            value = None
        if isinstance(value, dict) and value.get("node_type") == "element":
            tag = normalize_field_key(str(value.get("tag", "")).rsplit("}", 1)[-1])
            if nearest_container is None:
                nearest_container = parent
            if tag in {"section", "article", "div", "history", "prescription"}:
                return parent
        parent = item.parent_locator
    return nearest_container


def understand_ir(ir: IntermediateRepresentation, *,
                 config: UnderstandingConfig | None = None) -> IntermediateRepresentation:
    """Add deterministic structural/contextual findings to an IR.

    Call after Normalize to let this stage reuse its canonical-field, clinical
    term, normalized-name, and person-role annotations. Missing Normalize
    findings remain unknown; this function does not rerun normalization.
    """
    if ir.processing_status == ProcessingStatus.QUARANTINED:
        return ir
    cfg = config or UnderstandingConfig()
    lookup = _section_lookup(cfg)
    metadata = list(iter_field_metadata(ir))
    by_locator = {item.locator: item for item in metadata}
    old_annotations = _annotation_map(ir)
    generated: dict[str, list[Annotation]] = {}
    counter = 0

    def add(locator: str, kind: str, status: str, details: dict[str, Any],
            entity_type: str | None = None) -> Annotation:
        nonlocal counter
        counter += 1
        annotation = _stable_annotation(locator, kind, counter, status, details,
                                         entity_type=entity_type)
        generated.setdefault(locator, []).append(annotation)
        return annotation

    # Section roots discovered from headings/field labels are inherited by
    # descendants using the existing parent locator graph.
    section_roots: dict[str, dict[str, Any]] = {}
    text_scope: dict[str, list[dict[str, Any]]] = {}
    text_ranges: list[tuple[int, int, str]] = []
    if ir.source.format == "text" and isinstance(ir.structure.data, str):
        findings, text_ranges = _line_sections(ir.structure.data, lookup)
        for finding in findings:
            section = finding["canonical_section"]
            record = {**finding, "section_locator": "doc"}
            section_roots.setdefault("doc", record)
            add("doc", "section_context", "RESOLVED", record, entity_type="SECTION")
            text_scope.setdefault("doc", []).append(record)

    for item in metadata:
        section = _heading(item.field_name, lookup)
        try:
            value = get_value(ir, item.locator)
        except (ValueError, TypeError):
            value = None
        heading_field = normalize_field_key(item.field_name)
        if ir.source.format == "xml" and item.field_name == "text" and item.parent_locator:
            try:
                parent_node = get_value(ir, item.parent_locator)
                if isinstance(parent_node, dict) and parent_node.get("node_type") == "element":
                    heading_field = normalize_field_key(str(parent_node.get("tag", "")).rsplit("}", 1)[-1])
            except (ValueError, TypeError):
                pass
        if section is None and isinstance(value, str) and heading_field in _HEADING_FIELDS:
            section = _heading(value, lookup)
        if section:
            record = {"heading": str(item.field_name if _heading(item.field_name, lookup) else value),
                      "canonical_section": section, "section_locator": item.locator,
                      "method": "field_name_or_structural_heading"}
            root = item.locator
            if heading_field in _HEADING_FIELDS and item.parent_locator:
                root = item.parent_locator
            if ir.source.format == "xml" and heading_field in _HEADING_FIELDS:
                root = _xml_section_root(ir, item.locator, by_locator) or root
            record["section_locator"] = root
            section_roots[root] = record
            add(item.locator, "section_context", "RESOLVED", record, entity_type="SECTION")

    # Context per leaf from hierarchy, CSV header metadata, and text ranges.
    inherited: dict[str, list[dict[str, Any]]] = {}
    contextual_rows: list[tuple[Any, Any, list[dict[str, Any]], str | None]] = []
    for item in metadata:
        contexts = list(inherited.get(item.parent_locator or "", []))
        direct = _heading(item.field_name, lookup)
        if direct:
            record = section_roots.get(item.locator, {
                "heading": item.field_name, "canonical_section": direct,
                "section_locator": item.locator, "method": "field_name_heading"})
            contexts.append(record)
        for root, record in section_roots.items():
            if root != item.locator and _path_has_ancestor(item.locator, root) and record not in contexts:
                contexts.append(record)
        # Header labels are repeated as field_name on CSV/TSV data cells, so
        # direct section lookup also handles delimited formats.
        contexts = list({(x["canonical_section"], x["section_locator"]): x for x in contexts}.values())
        inherited[item.locator] = contexts
        try:
            value = get_value(ir, item.locator)
        except (ValueError, TypeError):
            value = None
        contextual_rows.append((item, value, contexts, None))
        if item.field_kind == "leaf" and contexts and not item.locator.startswith("header:col:"):
            for record in contexts:
                add(item.locator, "section_context", "RESOLVED", {
                    "canonical_section": record["canonical_section"],
                    "heading": record["heading"], "section_locator": record["section_locator"],
                    "method": record["method"],
                    "evidence": [{"kind": "ancestor_or_field_heading", "locator": record["section_locator"]}],
                }, entity_type="SECTION")

    # Existing Normalize outputs are indexed by exact source locator. They are
    # used as evidence; this stage never recalculates field or clinical meaning.
    for item, value, contexts, _unused in contextual_rows:
        if item.field_kind != "leaf" or item.locator.startswith("header:col:"):
            continue
        base = old_annotations.get(item.locator, [])
        canonical, terms, names, roles = _normalized_facts(base)
        section_names = list(dict.fromkeys(context["canonical_section"] for context in contexts))
        section_evidence = [{"kind": "section_context", "locator": context["section_locator"],
                             "section": context["canonical_section"]} for context in contexts]
        if canonical or terms or section_names:
            if canonical and terms:
                status = "RESOLVED"
                concept = "clinical_concept" if any(t.entity_type in {"DIAGNOSIS", "SYMPTOM", "MEDICATION"} for t in terms) else canonical
            elif canonical or terms:
                status, concept = "RESOLVED", canonical or "clinical_concept"
            elif len(section_names) == 1:
                status, concept = "RESOLVED", section_names[0].casefold()
            else:
                status, concept = "AMBIGUOUS", None
            add(item.locator, "contextual_semantic_classification", status, {
                "canonical_field": canonical, "semantic_class": concept,
                "clinical_concepts": [t.details.get("canonical_term") for t in terms],
                "normalization_evidence": [
                    {"annotation_id": a.annotation_id, "finding_type": a.finding_type,
                     "status": a.details.get("status")} for a in base
                    if a.finding_type in {"canonical_field", "clinical_term", "normalized_name"}],
                "section_context": section_names, "section_evidence": section_evidence,
                "method": "normalize_annotations_plus_structure" if base else "section_context_only",
            }, entity_type="SEMANTIC_CLASS")

        # Resolve a contextual role only from Normalize role evidence, a
        # canonical person field, a heading, or a relationship marker.
        role_candidates: list[tuple[str, dict[str, Any]]] = []
        ambiguous_normalize_role = False
        for annotation in roles:
            ambiguous_normalize_role = ambiguous_normalize_role or annotation.details.get("status") == "AMBIGUOUS"
            current = annotation.details.get("role")
            if isinstance(current, str) and current not in {"UNKNOWN", ""}:
                role_candidates.append((current, {"kind": "normalize_person_role",
                                                   "annotation_id": annotation.annotation_id,
                                                   "status": annotation.details.get("status")}))
            for current in annotation.details.get("candidate_roles", []):
                if isinstance(current, str) and current not in {"UNKNOWN", ""}:
                    role_candidates.append((current, {"kind": "normalize_role_candidate",
                                                       "annotation_id": annotation.annotation_id}))
        role_map = {"patient_name": "PATIENT", "doctor_name": "DOCTOR", "relative_name": "RELATIVE",
                    "caregiver_name": "CAREGIVER", "emergency_contact": "EMERGENCY_CONTACT"}
        if canonical in role_map:
            role_candidates.append((role_map[canonical], {"kind": "canonical_field", "locator": item.locator,
                                                           "canonical_field": canonical}))
        field_name_key = normalize_field_key(item.field_name)
        if names and not canonical and "PATIENT_DETAILS" in section_names and field_name_key in {
                "name", "given", "family", "fullname", "full name"}:
            role_candidates.append(("PATIENT", {"kind": "patient_details_section", "locator": item.locator}))
        if names and not canonical and "FAMILY_HISTORY" in section_names and field_name_key in {
                "name", "given", "family", "fullname", "full name"}:
            role_candidates.append(("RELATIVE", {"kind": "family_history_section", "locator": item.locator}))
        unique_roles = sorted({candidate for candidate, _ in role_candidates})
        if role_candidates:
            status = "RESOLVED" if len(unique_roles) == 1 and not ambiguous_normalize_role else "AMBIGUOUS"
            role = unique_roles[0] if status == "RESOLVED" else "UNKNOWN"
            add(item.locator, "contextual_person_role", status, {
                "role": role, "candidate_roles": unique_roles,
                "evidence": [evidence for _, evidence in role_candidates] + section_evidence,
                "method": "normalized_role_plus_context" if roles else "canonical_field_or_section_context",
            }, entity_type="PERSON_ROLE")

    # Plain text has no structural field nodes. Interpret explicit `Label: value`
    # lines using the same field mapper used by Normalize, while keeping the
    # source locator at `doc` and recording exact spans for the line/value.
    if ir.source.format == "text" and isinstance(ir.structure.data, str):
        source_text = ir.structure.data
        text_terms = [a for a in old_annotations.get("doc", []) if a.finding_type == "clinical_term"]
        text_lines = source_text.splitlines(keepends=True)
        offset = 0
        for raw_line in text_lines:
            line = raw_line.rstrip("\r\n")
            line_start, line_end = offset, offset + len(line)
            offset += len(raw_line)
            if not line:
                continue
            match = _LABELED_LINE.fullmatch(line)
            if not match:
                continue
            label, content = match.group(1).strip(), match.group(2)
            active_sections = [section for lo, hi, section in text_ranges if lo <= line_start < hi]
            canonical, status, method = map_field_name(label, context=active_sections,
                                                       value=content, config=cfg.semantic)
            if canonical is None and status == "UNKNOWN":
                continue
            content_start = line.find(content, match.start(2))
            value_start = line_start + max(content_start, 0)
            value_end = value_start + len(content)
            related_terms = [term for term in text_terms
                             if isinstance(term.details.get("start"), int) and
                             value_start <= term.details["start"] < value_end]
            add("doc", "contextual_semantic_classification", status, {
                "canonical_field": canonical, "semantic_class": canonical,
                "clinical_concepts": [term.details.get("canonical_term") for term in related_terms],
                "source_field": label, "source_span": [line_start, line_end],
                "value_span": [value_start, value_end], "section_context": active_sections,
                "normalization_evidence": [{"annotation_id": term.annotation_id,
                                            "finding_type": "clinical_term"} for term in related_terms],
                "method": "normalize_field_mapper_plus_text_label",
            }, entity_type="SEMANTIC_CLASS")
            roles = {"patient_name": "PATIENT", "doctor_name": "DOCTOR",
                     "relative_name": "RELATIVE", "caregiver_name": "CAREGIVER"}
            role = roles.get(canonical or "")
            if role:
                add("doc", "contextual_person_role", "RESOLVED", {
                    "role": role, "candidate_roles": [role],
                    "source_span": [value_start, value_end],
                    "evidence": [{"kind": "field_label", "label": label,
                                  "canonical_field": canonical, "span": [line_start, line_end]},
                                 *[{"kind": "section_context", "section": section}
                                   for section in active_sections]],
                    "method": "normalize_field_mapper_plus_explicit_text_label",
                }, entity_type="PERSON_ROLE")

    # Relationships are parsed per value or text line and cite Normalize
    # annotations when a concept/name classification supports the relation.
    def add_relation(locator: str, predicate: str, status: str, marker: str,
                     marker_span: tuple[int, int], object_span: tuple[int, int] | None,
                     sections: list[dict[str, Any]], evidence: list[dict[str, Any]],
                     *, subject_role: str | None = None, object_role: str | None = None) -> None:
        add(locator, "relationship", status, {
            "predicate": predicate, "marker": marker,
            "marker_span": list(marker_span),
            "object_span": list(object_span) if object_span else None,
            "subject_role": subject_role, "object_role": object_role,
            "section_context": list(dict.fromkeys(x["canonical_section"] for x in sections)),
            "evidence": evidence, "method": "contextual_marker_plus_normalize_evidence",
        }, entity_type="RELATIONSHIP")

    for item, value, contexts, _unused in contextual_rows:
        if not isinstance(value, str) or item.field_kind != "leaf" or item.locator.startswith("header:col:"):
            continue
        if ir.source.format == "text":
            line_contexts: list[tuple[str, int, int, list[dict[str, Any]]]] = []
            lines = value.splitlines(keepends=True)
            offset = 0
            for raw_line in lines:
                line = raw_line.rstrip("\r\n")
                start, end = offset, offset + len(line)
                active = [record for lo, hi, section in text_ranges if lo <= start < hi
                          for record in text_scope.get("doc", []) if record["canonical_section"] == section]
                line_contexts.append((line, start, end, active))
                offset += len(raw_line)
            segments = line_contexts
        else:
            segments = [(value, 0, len(value), contexts)]
        for segment, offset, _end, section_context in segments:
            if not segment:
                continue
            base = old_annotations.get(item.locator, [])
            canonical, terms, names, roles = _normalized_facts(base)
            role_values = sorted({str(role.details.get("role")) for role in roles
                                  if role.details.get("role") in {"PATIENT", "DOCTOR", "RELATIVE"}})
            patient_context = bool("PATIENT_DETAILS" in [x["canonical_section"] for x in section_context])
            medical_context = any(x["canonical_section"] in {"MEDICAL_HISTORY", "DIAGNOSIS"}
                                  for x in section_context)
            prescription_context = "PRESCRIPTION" in [x["canonical_section"] for x in section_context]

            match = _PRESCRIBED_BY.search(segment)
            if match:
                target = match.group(1).strip()
                target_start = match.start(1) + len(match.group(1)) - len(match.group(1).lstrip())
                status = "RESOLVED" if target and (prescription_context or canonical in {"medication", "dose"}) else "AMBIGUOUS"
                evidence = [{"kind": "relationship_marker", "rule": "prescribed_by",
                             "locator": item.locator, "span": [offset + match.start(), offset + match.end()]}]
                if prescription_context:
                    evidence.extend({"kind": "section_context", "locator": x["section_locator"],
                                     "section": x["canonical_section"]} for x in section_context)
                add_relation(item.locator, "PRESCRIBED_BY", status, match.group(0).split()[0],
                             (offset + match.start(), offset + match.end()),
                             (offset + target_start, offset + target_start + len(target)), section_context,
                             evidence, subject_role="MEDICATION" if canonical == "medication" or prescription_context else None,
                             object_role="DOCTOR" if status == "RESOLVED" else None)

            match = _DIAGNOSED_WITH.search(segment)
            if match:
                target_start = match.start(1) + len(match.group(1)) - len(match.group(1).lstrip())
                target_end = match.end(1)
                matched_terms = [term for term in terms
                                 if isinstance(term.details.get("start"), int) and
                                 offset + target_start <= term.details["start"] < offset + target_end]
                status = "RESOLVED" if matched_terms or medical_context else "AMBIGUOUS"
                evidence = [{"kind": "relationship_marker", "rule": "diagnosed_with",
                             "locator": item.locator, "span": [offset + match.start(), offset + match.end()]}]
                evidence.extend({"kind": "normalize_clinical_term", "annotation_id": term.annotation_id,
                                 "concept": term.details.get("canonical_term")} for term in matched_terms)
                evidence.extend({"kind": "section_context", "locator": x["section_locator"],
                                 "section": x["canonical_section"]} for x in section_context
                                if x["canonical_section"] in {"MEDICAL_HISTORY", "DIAGNOSIS"})
                add_relation(item.locator, "DIAGNOSED_WITH", status, "diagnosed with",
                             (offset + match.start(), offset + match.end()),
                             (offset + target_start, offset + target_end), section_context, evidence,
                             subject_role="PATIENT" if patient_context or "PATIENT" in role_values else None,
                             object_role="CONDITION" if matched_terms or medical_context else None)

            for pattern, label in ((_RELATIVE_MARKER, "relative_marker"), (_CARE_OF, "c_o")):
                for rel in pattern.finditer(segment):
                    target_start = rel.start(2) + len(rel.group(2)) - len(rel.group(2).lstrip())
                    target_end = rel.end(2)
                    target_role = "RELATIVE" if any(role.details.get("role") == "RELATIVE" for role in roles) else None
                    target_is_clinical = any(
                        isinstance(term.details.get("start"), int) and
                        offset + target_start <= term.details["start"] < offset + target_end
                        for term in terms)
                    if label == "c_o" and target_is_clinical:
                        add_relation(item.locator, "COMPLAINS_OF", "RESOLVED", "C/O",
                                     (offset + rel.start(1), offset + rel.end(1)),
                                     (offset + target_start, offset + target_end), section_context,
                                     [{"kind": "relationship_marker", "rule": "c_o_clinical_context",
                                       "locator": item.locator},
                                      *[{"kind": "normalize_clinical_term", "annotation_id": term.annotation_id,
                                         "concept": term.details.get("canonical_term")} for term in terms
                                        if isinstance(term.details.get("start"), int) and
                                        offset + target_start <= term.details["start"] < offset + target_end]],
                                     subject_role="PATIENT" if patient_context or "PATIENT" in role_values else None,
                                     object_role="CLINICAL_CONCEPT")
                    elif target_role or label == "relative_marker" and canonical in {"patient_name", "relative_name"}:
                        add_relation(item.locator, "RELATIVE_OF", "RESOLVED", rel.group(1),
                                     (offset + rel.start(1), offset + rel.end(1)),
                                     (offset + target_start, offset + target_end), section_context,
                                     [{"kind": "relationship_marker", "rule": label,
                                       "locator": item.locator},
                                      *[{"kind": "normalize_person_role", "annotation_id": role.annotation_id,
                                         "role": role.details.get("role")} for role in roles
                                        if role.details.get("role") == "RELATIVE"]],
                                     subject_role="PATIENT", object_role="RELATIVE")
                    elif label == "c_o":
                        add_relation(item.locator, "RELATIONSHIP_UNRESOLVED", "AMBIGUOUS", "C/O",
                                     (offset + rel.start(1), offset + rel.end(1)),
                                     (offset + target_start, offset + target_end), section_context,
                                     [{"kind": "relationship_marker", "rule": "ambiguous_c_o",
                                       "locator": item.locator},
                                      {"kind": "uncertainty", "candidate_predicates": ["COMPLAINS_OF", "RELATIVE_OF"]}])

    # Replace only prior Understanding annotations; Normalize/detection
    # annotations and any policy edits remain intact.
    merged = {locator: [a for a in items if not a.annotation_id.startswith("UND-")]
              for locator, items in old_annotations.items()}
    merged = {locator: items for locator, items in merged.items() if items}
    for locator, items in generated.items():
        merged.setdefault(locator, []).extend(items)
    object.__setattr__(ir, "annotations", merged)
    if generated and ir.processing_status == ProcessingStatus.PARSED:
        object.__setattr__(ir, "processing_status", ProcessingStatus.ANNOTATED)
    return ir

