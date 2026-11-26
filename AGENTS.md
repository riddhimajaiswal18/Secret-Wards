# Secret Wards: engineering guide

## Mission and constraints

Build an offline, CPU-only, LLM-free privacy firewall for synthetic Indian healthcare exports. It must remove direct identifiers, conservatively link records across four hospital systems and scripts, assign keyed pseudonyms, reduce re-identification risk, preserve clinical facts, and quarantine anything that cannot be safely processed. Privacy must not compromise clinical integrity. Uncertain identity means no link; unsafe input means quarantine.

Runtime target: Linux, 2 CPUs, 4 GB RAM, at most 15 minutes, and no network. Python is the implementation language. Do not use real patient data, hardcode practice identities, use generative models/LLMs, download models at runtime, use pretrained transformers above 50M parameters, modify inputs, or use plain hashes for patient pseudonyms. Output and side channels (logs, report, temp files and errors) must not reveal PII or `RAKSHA_SECRET`.

## Team Kit reference and observed edge cases

The organizer's Team Kit ZIP is the authoritative input/output reference. Its `START_HERE.md`, `docs/SPEC.md`, `docs/DATASET.md`, `docs/ATTACKS.md`, `docs/SANDBOX.md`, starter and validators should be reviewed before implementation. The inspected kit describes 200 practice files and 48 synthetic patients from four hospitals. Important cases include UTF-8 with BOM, UTF-16 TSV, cp1252, mixed date conventions, ragged/multiline CSV, nested JSON, FHIR R4 Bundles, Hindi/Devanagari and Hinglish, transliterated and fragmented identities, same-name different patients, duplicate exports, PII in filenames/headers/JSON keys/metadata/FHIR narratives/base64 attachments, and clean clinical reference documents.

The robustness set includes empty and invalidly encoded files, truncated JSON, 1,500-level nesting, JSON content mislabeled as CSV, XML, PDF, JPEG, and bulk exports. Clinical/meaning traps include `Dr. <name>` (preserve), `C/O fever` (clinical complaint), `C/O <name>` and S/o/D/o/W/o relatives (remove), medicines/doses/frequencies, lab values, eponyms such as Addison's/Parkinson's disease, and admission/discharge intervals. Re-identification traps include rare conditions/procedures, exact dates, older ages and small villages. Hidden data also changes names, labels, date/identifier formats, and columns; implement context-aware general rules, not practice-specific lookups. These observations guide architecture and test coverage; never hardcode the kit's identities or filenames.

## Architecture and data flow

1. Enumerate inputs deterministically without modifying them; hash original bytes for the report.
2. Route by content and format, detect encoding strictly, and parse within depth/size/resource limits. Capture safe source locations and source metadata.
3. Convert parseable content into a common internal record model while retaining enough format structure to serialize it back. Preserve unknown fields and types unless unsafe; do not silently discard them.
4. Detect and classify PII across values and side channels (filename, header, key, metadata, attachment). Normalize scripts and protect clinical spans before substitutions.
5. Collect identity evidence, block candidates, compare independent clues, and cluster only with conservative evidence. Uncertain records have no patient link.
6. Apply per-patient HMAC-keyed pseudonyms/date shifts and policy-driven age/location generalization and rare-combination suppression.
7. Serialize in original supported formats, validate safety and format, and write output records and a truthful report. Quarantine unprocessable files; never fall back to copying raw bytes.

Processing should be deterministic for identical inputs and `RAKSHA_SECRET`. Use bounded processing for large, malformed, deeply nested or adversarial files. Prefer fail-closed behavior: do not emit partially sanitized data if the file's safety cannot be established.

## Module boundaries

- `src/ingestion/`: format routing; strict encoding detection; CSV/TSV, JSON, FHIR R4 and text parsing; source locators; malformed/unsupported-file quarantine. Never sanitize content here.
- `src/detection/`: structured and free-text PII detection for names, relatives, identifiers, phones, addresses and other PII; gazetteers; clinical-span protection. Treat filenames, headers, keys, metadata and attachments as input channels.
- `src/normalization/`: Unicode normalization, Hindi-English transliteration, name variants, phone canonicalization and date standardization. Preserve original spans for safe edits.
- `src/linkage/`: multiple blocking strategies, comparison, calibrated/provisional matching and conservative clustering. Avoid transitive over-merging and expose uncertainty.
- `src/pseudonymization/`: stable patient-level HMAC-SHA256 pseudonyms derived only from a confirmed cluster key and `RAKSHA_SECRET`.
- `src/privacy/`: consistent patient-level date shifts, truthful age bands, location generalization, rare-value suppression and risk assessment.
- `src/security/`: encryption and key separation for sensitive intermediates, safe logging, quarantine and temporary-file handling.
- `src/output/`: deterministic serializers, `sanitized/`, `report.json`, and `records.jsonl`; preserve relative paths and supported formats.
- `src/evaluation/`: PII recall/precision, linkage quality, clinical preservation, privacy risk, determinism, runtime and memory metrics.
- `config/`: documented, configurable policy. Provisional values must be labeled and not represented as validated.
- `tests/`: boundary and adversarial behavior tests by component, including Team Kit edge cases and held-out variations.
- `docs/`: architecture, decisions, assumptions, and unresolved questions.

## Internal representation and provenance

Use a typed common record representation validated at module boundaries (Pydantic is the current candidate). Each record must retain source file identity, source format, source locator, relevant schema/path/key/header, original value types, and serialization context. Locators are `row:N` (zero-based data row) for CSV/TSV, RFC 6901 JSON Pointers for nested JSON records, and `doc` for text/FHIR/document-level records. File-level channels such as filename and header must also remain traceable for reports and tests without retaining exposed PII in output. Unknown fields are preserved safely. FHIR must remain a valid R4 Bundle with references resolving after edits.

## PII detection and multilingual strategy

Combine context-aware structured-field rules, deterministic identifier/phone patterns, name gazetteers, transliteration/normalization, and classical statistical methods only when justified by evaluation. Support English, Hindi in Devanagari, and Hinglish. Handle name-order variation, initials, honorifics/suffixes (`ji`, `sahab`, `didi`, `श्री`), variants such as Mohammad/Mohd./Md./मोहम्मद, and relative markers S/o, D/o, W/o, C/O. Detect Indian identifier families (Aadhaar-like, ABHA, UHID/MRN, PAN, insurance IDs) and phone variants.

Scan content plus filenames, CSV/TSV headers, JSON keys, FHIR metadata/narrative, export metadata and safely decoded attachment content such as base64. Do not assume extension identifies content. Ensure redactions cannot leak through errors, logs, temporary artifacts, report fields, or copied filenames. Generic name fragments alone should not be treated as globally identifying evidence. Rule thresholds are provisional until measured against practice and held-out data.

## Clinical preservation

Preserve medicines, doses, schedules/frequencies, vitals, laboratory results and units, diagnoses, procedures, and hospital-stay durations exactly. Protect spans such as `Ramipril 5 mg`, `Dolo 650 BD x 5 days`, `1-0-1`, `245 mg/dL`, and medical eponyms. Distinguish clinicians (`Dr. Ramesh`) from patients, and complaints (`C/O fever`) from relative names (`C/O Ramesh`). Shift dates consistently per patient while preserving intervals. Measure preservation explicitly; never claim success without evaluation.

## Conservative record linkage

Use multiple blocking strategies so cross-script/format variants can meet, then compare independent clues. Strong unique identifiers can support a link; name alone cannot. Combine name with independent evidence such as relative, DOB, village+age, phone or hospital identifiers. Detect homonyms and conflicting clues. Prevent transitive over-merging; a cluster merge must be consistent with all members or supported by a strong unique identifier. Keep match confidence distinct from confirmed identity. Return `null` when evidence is insufficient; false merges are costlier than missed links.

## HMAC pseudonymization

Read `RAKSHA_SECRET` from the environment. Generate patient pseudonyms with HMAC-SHA256, using domain separation for separate purposes such as pseudonyms and date shifts. Do not persist the secret or raw canonical patient identifiers. The same confirmed cluster and secret must yield the same `PSN-...` ID across files; a different secret must produce a different ID. Choose an ID length/encoding with an explicit collision analysis; detect collisions rather than silently assigning one ID to distinct clusters. Never use plain SHA-256 of identifiers.

## Privacy transformations

Use a deterministic secret-keyed per-patient date offset, common to every date for that patient, preserving intervals and stay durations. Date-shift behavior at invalid dates, partial dates, and boundary years remains an implementation decision to document. Age bands must include the true age; policy must address very old ages and minors explicitly. Generalize locations through configurable levels. Assess combinations and suppress/generalize rare cases when required; account for rare clinical values without indiscriminately destroying utility. Do not claim anonymity solely from direct-identifier removal. Report measured privacy risk and limitations.

## Security and leakage prevention

Encrypt raw/intermediate sensitive data at rest when such data must be persisted; minimize persistence and separate encryption keys from ciphertext. Keep `RAKSHA_SECRET` out of files, logs, reports, exceptions and command output. Logs contain counts/status codes only. Avoid temporary copies of raw content; clean temporary files securely where feasible. Quarantine unsafe files outside `sanitized/` or omit their contents entirely; quarantine metadata must not reveal PII. Never copy an unprocessed file into the release. The runtime has no network. Do not add network calls, telemetry or model downloads.

## Output contract

Run interface: `python main.py --input {input} --output {output}`. Organizer supplies `RAKSHA_SECRET` in the environment. Output root contains:

- `sanitized/`: safe mirror of input structure and formats where possible; CSV/TSV preserve delimiter and header unless a header itself leaks PII, JSON shape/types stay intact, FHIR remains valid R4, text uses UTF-8. Rename PII-bearing filenames and map each input SHA-256 to the output path in the report. Never include unsafe raw copies.
- `report.json`: schema `raksha-report/1`; every input is identified by SHA-256, with status `sanitized`, `quarantined`, or `suppressed`, output path or null, safe reason when applicable, truthful counts, processing time and peak memory. No source filename or PII unless safely transformed and contractually needed.
- `records.jsonl`: one object per exported patient-bearing record with `file`, `loc`, pseudonymous `patient` or null; optional `out` if record locator changes and `status` if generalized/suppressed. Use `row:N`, JSON Pointer, or `doc` as above. Pseudonyms must be consistent with those written into sanitized records.

The Team Kit `docs/SPEC.md` and included `validate_output.py` are authoritative for exact contract details. Check the actual validator before choosing report fields or path conventions.

## Testing and evaluation strategy

Do not equate tests with claims of pipeline readiness. As implementation proceeds, test parser boundaries, malformed inputs, strict encoding handling, structure/type preservation, no-raw-fallback behavior, clinical preservation, cross-script detection/linkage, homonyms, deterministic HMACs/date shifts, and no side-channel leakage. Use synthetic fixtures and the organizer's practice self-check/contract validator. Add held-out tests that rename columns/keys, vary labels and dates, and use unseen names. Track PII by script/channel, clinical values retained, linkage precision/recall (favor precision), attack-based privacy risk, deterministic output, runtime and peak memory. Do not tune or snapshot against real patient data or hardcode answer-key identities.

## Coding conventions and boundaries

Use Python 3.10+ compatible, typed, small modules with explicit inputs/outputs. Keep parsing, detection, normalization, linkage, privacy transforms, security and serialization in their designated packages. Avoid global mutable state and order-dependent behavior. Validate configuration and inputs; cap recursion/depth/size. Errors surfaced to users/logs must be generic and PII-safe. Dependencies must be justified, compatible, and free of runtime downloads. Document every model and prohibit models disallowed by the challenge.

## Implementation milestones

- [ ] Inspect the Team Kit, its real schemas, exact output contract and validators.
- [ ] Establish the internal record model and source-location tracking.
- [ ] Build ingestion, encoding detection, parsing and quarantine.
- [ ] Build structured and unstructured PII detection.
- [ ] Implement Unicode normalization and cross-script transliteration.
- [ ] Implement clinical false-positive protection.
- [ ] Build blocking, comparison, matching and conservative clustering.
- [ ] Implement stable HMAC pseudonyms.
- [ ] Implement date shifting, age banding, location generalization and suppression.
- [ ] Implement encryption, safe logging and secure temporary-data handling.
- [ ] Implement serializers, `report.json` and `records.jsonl`.
- [ ] Run practice self-checks and optimize on held-out variations within resource limits.

## Explicitly prohibited

- LLMs, hosted AI, generative models, runtime internet calls, network telemetry, or runtime downloads.
- Pretrained transformers above 50M parameters or unlisted/unavailable model files.
- Hardcoded practice names, identities, file-specific redactions, or answer-key lookups.
- Plain hashing for patient IDs, writing `RAKSHA_SECRET`, or reversible/unkeyed pseudonyms.
- Unsafe fallback copying, outputting a partially sanitized file, or exposing PII through logs, reports, errors, filenames or temporary files.
- Silent loss of unknown fields or clinical values, and merging records based on name-only or weak transitive evidence.
