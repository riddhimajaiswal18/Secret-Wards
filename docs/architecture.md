# Architecture and data flow

This document describes the implemented ingestion/IR foundation and the intended downstream pipeline.

## Flow

```text
Input tree (read-only)
  │ deterministic walk + byte hashes
  ▼
Format router ── strict decoding / bounded parsers ── malformed or unsupported → quarantine
  ▼
Common record model + source provenance
  ▼
Structured and free-text PII detection ◄── clinical span protection
  ▼
Unicode / script normalization and transliteration
  ▼
Evidence blocking → comparison → conservative patient clusters (uncertain → null)
  ▼
HMAC pseudonyms + per-patient date shifts + age/location generalization + risk suppression
  ▼
Format-preserving serialization and safety checks
  ├── sanitized/ (supported, safe outputs)
  ├── report.json (hashes, statuses, truthful aggregate counts)
  └── records.jsonl (source locator and pseudonymous identity)
```

## Ingestion and provenance

The router must inspect both extension and content. It should strictly detect UTF-8, UTF-8 BOM, UTF-16 and legacy encodings such as cp1252, and enforce resource/depth limits. CSV/TSV parsing retains delimiter, header and row locators. JSON parsing retains field types and RFC 6901 paths; FHIR R4 is validated as a Bundle and references remain resolvable. Text documents use `doc` locators. Unknown fields must survive safe serialization. Malformed, truncated, empty, unsupported, or unsafe files are quarantined; raw bytes are never copied to the release as fallback.

## Detection, normalization, and clinical protection

Detection combines schema-aware field context, deterministic patterns, multilingual name resources, transliteration and (if later justified) classical ML. It scans values and side channels: filenames, headers, JSON keys, FHIR metadata/narrative, export paths and attachment encodings such as base64. Normalization retains offsets back to source text so redactions can be applied safely. Clinical spans are protected before edits: medicine/dose/frequency strings, labs and units, vitals, diagnoses, procedures, and durations must survive exactly. Clinician names and symptom complaints must not be mistaken for patient/relative names.

## Linkage and privacy

Records are blocked through multiple complementary keys, compared on independent evidence, and clustered conservatively. A name alone is not enough; homonyms, contradictory clues and transitive merges require explicit protection. Identity uncertainty produces a null patient ID. A confirmed cluster receives a stable HMAC-SHA256 pseudonym keyed with `RAKSHA_SECRET`; secret-derived date offsets use domain separation and remain consistent per patient. Age bands contain true ages. Locations are generalized based on policy and risk. Rare combinations may require suppression or coarser generalization.

## Output and security

Serializers preserve supported source formats and relative structure while replacing identifiers and including pseudonyms in records. `report.json` identifies each input by SHA-256 rather than source name and reports status/counts/timing/resources without exposing PII. `records.jsonl` maps each exported patient record to its source locator and pseudonym or null. Logs are counts/status only. Sensitive intermediates should be minimized, encrypted if persisted, and use keys stored separately. Runtime has no internet access.

## IR annotations, edits, and serialization

The IR envelope keeps annotations and pending edits indexed by locator. Findings and requested changes remain separate; neither mutates source data until the transformation engine runs. JSON/FHIR use structured JSONPath-like locators, CSV/TSV use `row:N,col:M`, text uses exact character spans, and XML uses paths through an ordered element representation. The transformation engine applies guarded edits to the format-specific core and quarantines the document on any edit failure. Delimited inputs retain delimiter, quoting parameters, line ending, encoding, BOM, header order, and row count. FHIR edits to `fullUrl` or resource IDs update exact matching FHIR `reference` properties only. The policy package currently defines an interface, not policy rules.

`structure.data` is the sole stored source-value representation. Its shape depends on the source format; the IR does not flatten CSV rows, text, JSON, FHIR, and XML into one tree. The old serialized `fields[]` index was removed because names, paths, parent links, types, and presence can be derived from the core. Consumers can call `iter_field_metadata(ir)` to derive value-free metadata on demand. Sparse detections remain in locator-indexed annotations.

## Team Kit cases informing the design

The inspected kit includes four encoding/date conventions, duplicate registration exports, ragged and multiline CSV, nested JSON and FHIR, Hindi/Hinglish and fragmented names, names/phones in filenames, metadata/keys/headers and base64, homonymous patients, relative-vs-clinical meaning traps, clean clinical reference files, and re-identification cases involving rare conditions, exact dates and tiny villages. Robustness inputs include bulk JSON, 1,500-level nesting, truncation, empty/invalid-byte files, mislabelled formats, XML, PDF and JPEG. XML is now represented as an ordered tree; PDF/JPEG remain unsupported and are marked with parse errors.

## Contract and validation

The ingestion CLI emits IR JSON; it is not yet the final privacy-firewall output contract. Before implementing release serialization, check the kit's `docs/SPEC.md`, `validate_output.py`, `check_dev.py`, and `check_submission.py`.
