# Limitations

The prototype passes the supplied Toolkit's submission checks on its 200-file synthetic development corpus. The measured practice-set result is 0 visible labeled direct-PII surfaces, 99.38% exact clinical-value retention, and linkage F0.5 0.89 with zero observed false merges. These results are not a hidden-set guarantee or proof of anonymity.

The Linux run lacked native PDF rendering and OCR executables (`pdftoppm` and `tesseract`). Rare-combination suppression and attack-based re-identification measurement are absent. Linkage uses conservative exact evidence and does not cover broad aliases, transliteration variants, shared phones or cross-release identity. Full FHIR R4 schema/reference validation is incomplete; the independent verifier is separate from the pipeline. Parsed patient data remains in memory, without persisted-data encryption or secure-deletion guarantees.

The complete caveats are in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md); measured outputs and denominators are in [BASELINE_RESULTS.md](BASELINE_RESULTS.md). Do not use the prototype with real patient information or claim that it is anonymous or production safe.
