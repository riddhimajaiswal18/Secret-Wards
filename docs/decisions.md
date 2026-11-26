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
