# Design decisions and open questions

These describe the current implementation choices and unresolved architecture decisions. Practice-set measurements are in [BASELINE_RESULTS.md](BASELINE_RESULTS.md); passing them is not a general privacy guarantee.

## Decisions

1. **Fail closed.** A file that is malformed, unsupported, undecodable, too deeply nested, or cannot be proven safe must be quarantined rather than copied.
2. **Common model with provenance.** Parse formats into typed records while retaining source paths, row numbers/JSON pointers/document locators, original types and serialization context.
3. **Context-first multilingual detection.** Combine field/key/header semantics with patterns, transliteration and name resources; scan filenames and metadata too. Avoid memorized practice identities.
4. **Clinical protection precedes redaction.** Preserve medication, dose, frequency, lab, vital, diagnosis, procedure, and duration spans exactly; distinguish clinicians and complaints from identity references.
5. **Conservative linkage.** Require independent evidence or a unique strong identifier; do not link on names alone; return null under uncertainty and guard against homonyms/transitive over-merging.
6. **Keyed, separated HMAC purposes.** Use `RAKSHA_SECRET` for stable pseudonyms and date offsets with separate derivation domains. Never persist the secret or plain patient identifiers.
7. **Risk-based generalization.** Age/location/date policy must be configurable and evaluated against attack risk, not presented as a proven privacy guarantee.
8. **Small pinned dependency surface.** Only packages imported by the current implementation are declared. Exact versions were exercised on Python 3.10/Linux. FHIR model validation, fuzzy/phonetic matching, JSON Schema validation and persisted-data encryption are not claimed capabilities.

## Open architectural questions

- What is the minimal internal record schema that can represent CSV rows, nested JSON, FHIR resources, text spans, unknown fields and attachments without lossy conversion?
- Which FHIR R4 library/version and validation scope will work across the target Python and Linux environment, and how will bundle references be rewritten consistently?
- How should content sniffing distinguish JSON-in-CSV-extension and other mislabelled data while preserving intended output formats safely?
- What dependency is actually needed for encryption at rest, and which sensitive intermediates can instead be avoided entirely? Where will keys live without sharing storage with ciphertext?
- What evidence and review process should extend exact name-plus-phone matching to homonyms, fragmented identity and cross-script aliases without increasing false merges?
- What practical Hindi/Hinglish name resources and transliteration direction(s) are legally and operationally suitable offline?
- How should partial dates, uncommon date formats, date-boundary handling, minors and older ages be generalized across every input format?
- Which risk threshold triggers suppression/generalization for rare diagnoses/procedures while preserving useful clinical statistics?
- What are safe parsing limits for bulk exports and 1,500-level nested JSON under the 4 GB/15-minute budget?
- Which output naming policy should cover filename fragments and nested paths whose names contain PII while preserving a stable, useful directory layout?
- Which policy settings and matching thresholds remain provisional until practice and hidden-style held-out testing?

## Dependency/version notes

`requirements.txt` pins the runtime packages verified with Python 3.10/Linux. FHIR-shaped JSON currently uses the project's common JSON IR; `fhir.resources` is not installed because it is not wired into the runtime. `charset-normalizer`, fuzzy/phonetic matcher packages, JSON Schema libraries, and encryption packages were removed because the current code does not import them. spaCy, scikit-learn, CRF libraries, Splink/recordlinkage, anonymeter and pycanon remain excluded until evaluation demonstrates a need. No pretrained models are used or downloaded.

## IR write-back decisions

- Keep JSON/FHIR values native, CSV/TSV as ordered header and row arrays, text as its original string, and XML as an ordered element/attribute/text/tail tree.
- Index annotations and pending edits by explicit source locator. Transformation code—not parsers or annotations—mutates the source core.
- Guard edits with optional expected values. Text spans apply from highest offset down; overlapping edits quarantine the document.
- Capture delimited dialect, encoding and BOM for re-serialization. Original byte-level whitespace/quoting and JSON number lexemes are not retained.
- Enforce a JSON nesting cap of 512 and return a controlled error instead of raising the recursion limit.
- FHIR validation remains structural; full R4 validation and comprehensive reference-resolution checks are follow-up work.
- Policy rules and privacy transforms are implemented for the supported fields; rare-combination suppression and attack-based risk measurement remain open.

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
