# Design decisions and open questions

These are initial choices, not validated implementation results.

## Decisions

1. **Fail closed.** A file that is malformed, unsupported, undecodable, too deeply nested, or cannot be proven safe must be quarantined rather than copied.
2. **Common model with provenance.** Parse formats into typed records while retaining source paths, row numbers/JSON pointers/document locators, original types and serialization context.
3. **Context-first multilingual detection.** Combine field/key/header semantics with patterns, transliteration and name resources; scan filenames and metadata too. Avoid memorized practice identities.
4. **Clinical protection precedes redaction.** Preserve medication, dose, frequency, lab, vital, diagnosis, procedure, and duration spans exactly; distinguish clinicians and complaints from identity references.
5. **Conservative linkage.** Require independent evidence or a unique strong identifier; do not link on names alone; return null under uncertainty and guard against homonyms/transitive over-merging.
6. **Keyed, separated HMAC purposes.** Use `RAKSHA_SECRET` for stable pseudonyms and date offsets with separate derivation domains. Never persist the secret or plain patient identifiers.
7. **Risk-based generalization.** Age/location/date policy must be configurable and evaluated against attack risk, not presented as a proven privacy guarantee.
8. **Small dependency surface.** Current candidates cover encoding, Indic transliteration, phones/dates, fuzzy/phonetic comparison, Pydantic/FHIR validation, JSON Schema, encryption, and YAML. Classical ML and privacy-metric libraries are deferred until requirements justify their cost.

## Open architectural questions

- What is the minimal internal record schema that can represent CSV rows, nested JSON, FHIR resources, text spans, unknown fields and attachments without lossy conversion?
- Which FHIR R4 library/version and validation scope will work across the target Python and Linux environment, and how will bundle references be rewritten consistently?
- How should content sniffing distinguish JSON-in-CSV-extension and other mislabelled data while preserving intended output formats safely?
- What dependency is actually needed for encryption at rest, and which sensitive intermediates can instead be avoided entirely? Where will keys live without sharing storage with ciphertext?
- What calibrated linkage evidence/thresholds achieve high precision on homonym, fragmented identity, and cross-script cases? How will cluster consistency prevent transitive over-merging?
- What practical Hindi/Hinglish name resources and transliteration direction(s) are legally and operationally suitable offline?
- How should the system handle partial dates, invalid dates, ages above the ordinary band range, minors, and date shifts near representational boundaries?
- Which risk threshold triggers suppression/generalization for rare diagnoses/procedures while preserving useful clinical statistics?
- What are safe parsing limits for bulk exports and 1,500-level nested JSON under the 4 GB/15-minute budget?
- How should file-level PII in a path be renamed deterministically while preserving the required directory structure and report mapping?
- Which policy settings and matching thresholds remain provisional until practice and hidden-style held-out testing?

## Dependency/version notes

The Team Kit starter itself uses only the Python standard library, so it establishes no dependency conflicts. This repository lists unpinned utility packages except a compatibility constraint pairing `fhir.resources` 7.x–8.x with Pydantic 2.x. Versions must be resolved on the target Python/Linux environment before the first implementation milestone. spaCy, scikit-learn, CRF libraries, Splink/recordlinkage, anonymeter and pycanon are not included yet: overlap, model/runtime cost, API compatibility and need should be assessed first. No pretrained models are required or downloaded.

## IR write-back decisions

- Keep JSON/FHIR values native, CSV/TSV as ordered header and row arrays, text as its original string, and XML as an ordered element/attribute/text/tail tree.
- Index annotations and pending edits by explicit source locator. Transformation code—not parsers or annotations—mutates the source core.
- Guard edits with optional expected values. Text spans apply from highest offset down; overlapping edits quarantine the document.
- Capture delimited dialect, encoding and BOM for re-serialization. Original byte-level whitespace/quoting and JSON number lexemes are not retained.
- Enforce a JSON nesting cap of 512 and return a controlled error instead of raising the recursion limit.
- FHIR validation remains structural; full R4 validation and reference-resolution checks are follow-up work.
- The policy package currently exposes an interface only; policy rules and PII detection remain unimplemented.

## Canonical source representation

`structure.data` is the single authoritative store of parsed source values. Its shape is format-specific: native ordered JSON objects/lists, CSV/TSV header and row arrays, a complete text string, or the XML element tree. `original_layout` stores source-format context needed to interpret the core. The serialized `fields[]` list was removed because it held no unique source values or populated schema/sensitivity data; names, types, parent relationships, and presence can be derived. `iter_field_metadata(ir)` supplies those details on demand, including missing-cell metadata for ragged delimited rows. Findings remain sparse in locator-indexed annotations.

## ADR-7 — Scanned documents are extracted, scrubbed and released as derived text

**Context.** PDF/JPEG inputs are marked "either" by the kit: quarantining is accepted, copying is
penalised. In the practice set one PDF carries a text layer (`Patient: … Mob …`) and one JPEG hides
a patient name in its EXIF description, so "unsupported" does not mean "unreadable".

**Decision.** A bounded offline ladder (text layer → raw stream carve → EXIF → printable-run carve →
OCR) extracts text; the tier-0 scrubber removes identifiers and name-shaped runs; the result is
written as `sanitized/<name>.txt` and declared in the report with its backend. Absent tooling
degrades to quarantine, never to failure.

**Consequences.** Two additional inputs are now processed instead of dropped, with zero raw copies.
OCR is a system dependency (tesseract) and is optional by design; page count, character count, DPI
and timeout are capped so a hostile file cannot exhaust the sandbox. Pixel-level redaction of the
original image is deliberately **not** attempted: writing a partially sanitised bitmap risks
publishing the identifier it could not detect.
