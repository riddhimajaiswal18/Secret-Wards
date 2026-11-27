# Privacy model

## Goal and boundary

Secret Wards is an offline prototype that removes selected direct identifiers from synthetic Indian healthcare exports while preserving clinical content. It is not a formal anonymization method and does not make records safe against every auxiliary-data or singling-out attack.

## Implemented controls

- Detects selected identifiers using field semantics, hierarchy, section context, text markers and deterministic patterns.
- Stores findings as locator-based annotations and pending edits; the parsed `structure.data` remains the authoritative source representation.
- Quarantines known malformed, empty, unsupported, undecodable and over-depth inputs instead of copying them unchanged as sanitized output.
- Generates keyed pseudonyms with HMAC and `RAKSHA_SECRET`; uses a direct identifier or an exact patient-name/phone pair subject to sex/DOB conflict checks.
- Applies deterministic per-patient event-date offsets, age bands, locality-to-district fallback and PIN-prefix masking in supported contexts.
- Records capability degradation in the report. The independent verifier can inspect the release separately.

## Assumptions and limitations

The code and Toolkit's synthetic test data are not representative of all hospitals, scripts, schema variants, corrupt files, or clinical workflows. Native OCR was absent in the tested Linux environment, so image-only PDF rendering and pixels were not fully inspectable. FHIR is handled as structured JSON but does not receive complete R4 schema and reference validation.

Rare-combination suppression and attack-based re-identification-risk measurement are not implemented. The verifier is not automatically blocking. Sensitive values remain in process memory while documents are parsed and transformed; persistent intermediate encryption, secure deletion and key rotation are incomplete. HMAC tokens are pseudonyms, not anonymization.

On the current 200-file practice corpus, the scorecard and self-check found 0 visible labeled direct-PII surfaces, and the verifier passed. Those measurements do not establish hidden-set recall, re-identification resistance, or production safety. See [BASELINE_RESULTS.md](BASELINE_RESULTS.md) and [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).
