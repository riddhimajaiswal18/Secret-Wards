# Known limitations

These are current implementation or evaluation gaps, not hypothetical risks. The project remains a prototype and must not be used for real patient data.

## Measured detection gaps

- On the 200-file Team Kit practice set, 27 of 3,234 labeled PII surfaces remained visible (0.84%). Most residuals were patient and relative names; residual Hinglish rate was 14.4%.
- The independent verifier is useful for finding candidates but is not a mandatory release gate. It reports 492 NAME candidates on the current practice output; some candidates may be benign, but each finding still needs triage.
- A successful parser or contract validation does not imply all PII was detected.

## Identity and privacy transformations

- The current token logic extracts strong-looking identifier evidence and emits HMAC-based pseudonyms where possible. It is not a complete linkage engine for spelling variants, multiple hospitals, fragmented records, cross-script identity, homonyms, or conflicts.
- The Team Kit self-check scored practice-set pseudonym linkage at precision 1.00, recall 0.51 and F0.5 0.84 with zero observed false merges. This does not guarantee hidden-set performance or solve all cross-hospital aliases, homonyms and conflicts. The number of tokenized records is not itself a linkage quality result.
- Date shifting, age-band generalization, location generalization and rare-combination suppression are not implemented in the release path. There is no measured re-identification-risk estimate.
- Approximate transliteration supports normalization experiments only; it must not be used as identity equivalence evidence by itself.

## Formats and execution

- CSV/TSV, JSON/FHIR-shaped JSON, XML and text parsers exist, but format preservation and semantic detection vary by input shape. Full FHIR R4 schema and all-reference validation need broader testing.
- PDF text extraction, image metadata extraction and OCR rely on optional dependencies and native tools. In the measured environment these were absent, so scanned content could not be inspected with OCR.
- The test run was performed on Windows with a temporary compatibility shim for the Linux-only `resource` module. The target Linux sandbox (2 CPUs, 4 GB RAM, 15 minutes, no network) still requires a full run. The organizer's `check_submission.py --run` helper also uses POSIX quoting and fails to invoke the pipeline correctly from this Windows shell; three-run behavior was checked directly instead.
- Same-secret determinism was measured on the practice set. A final different-secret unlinkability check and full three-run submission test remain required.

## Security and operations

- The report avoids original input paths, but every release still needs side-channel scans of logs, output paths, temporary files and errors.
- Sensitive parse structures exist in process memory. At-rest encryption for persisted sensitive intermediates and secure quarantine lifecycle are incomplete.
- The independent verifier is not currently wired as a blocking release gate.
- The 3 quarantined practice files demonstrate fail-closed behavior for known empty/malformed/deep cases; they do not prove all corrupt or unsupported files are safely quarantined.

Do not describe the system as anonymous, fully compliant, or ready for real clinical deployment. Treat practice-set results as development evidence only.
