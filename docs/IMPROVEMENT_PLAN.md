# Secret Wards improvement plan and current state

The work below follows the supplied Toolkit's actual contracts and synthetic test corpus. Truth labels are evaluation-only; production rules and tests use general patterns, not answer-key identities. The project remains a prototype and must not be used with real patient data.

## Latest evidence

| Measure | Current result | Interpretation |
|---|---:|---|
| Project tests | 162 passed on Python 3.10 Linux | Unit/adversarial suite is green in the tested environment |
| Toolkit inputs | 197 sanitized, 3 quarantined, 0 unaccounted / 200 | Contract validator passed |
| Labeled direct PII | 0 / 3,234 scorecard; 0 / 3,230 self-check | Two different practice-set denominators; not hidden-set recall |
| Clinical utility | 4,825 / 4,855 retained (99.38%) | 30 exact-match misses require error-class review |
| Linkage | P=1.00, R=0.61, F0.5=0.89; 0 observed false merges | Practice self-check exceeds current F0.5 gate |
| Independent verifier | Passed; 200 files inspected | Separate tool, not a pipeline gate |
| Linux operation | Organizer three-run check passed offline, 2 CPUs / 4 GB | Same-secret match, changed-secret difference, no secret leak, no input mutation |
| Runtime / memory | 5.44 s reported; 58.3 MB peak RSS | Staged Linux run; official helper run from OneDrive took 27 s |
| Missing runtime capabilities | `pdf_render`, `ocr_binary` | Native `pdftoppm` and Tesseract absent; image-only PDF OCR unavailable |

## Completed work in this iteration

### 0. Reproduce the contract and baseline

- Inspected the Toolkit, its specification, test data, validation scripts, answer keys and practice scorer.
- Ran the project suite and the organizer's actual three-run helper on Linux with network disabled and the stated CPU/memory limits.
- Confirmed output accounting, contract validity, same-secret repeatability, changed-secret output, secret non-disclosure and unchanged inputs.

### 1. Close measured direct-PII gaps

- Added deterministic contextual handling for patient/relative name forms, titles, guardian/attendant markers, Hinglish possessives and source-path metadata.
- Added positive and clinical/role negative tests.
- Latest practice scorers report zero visible labeled PII surfaces. This result is limited to their synthetic answer keys.

### 2. Add conservative within-run linkage

- Preserved direct-identifier tokens and added an exact patient-name plus phone composite for records carrying different hospital IDs.
- Rejects name-only and phone-only matching and blocks merges with conflicting sex or DOB evidence; checks component compatibility to limit transitive conflicts.
- Practice linkage scored P=1.00, R=0.61, F0.5=0.89 with zero observed false merges.

### 3. Add privacy transformations

- Implemented per-patient deterministic event-date offsets, age bands, locality-to-district fallback, and PIN-prefix masking for supported structures.
- Added tests for consistency, changed secrets, clinical protections, clean-document behavior and invalid/partial dates.
- Rare-combination suppression and attack-based re-identification measurement remain open; transform coverage varies by format and context.

### 4. Improve independent verification

- Added context-aware checks for structured fields, XML, text and clinical/provider negatives.
- Current verifier passes the supplied practice corpus with full file accounting and no surviving supported identifier candidates.
- The verifier is still a separate command rather than a blocking stage in the release pipeline.

### 5. Validate offline Linux operation

- Ran the official three-run helper in Python 3.10 with 2 CPUs, 4 GB RAM and no network.
- Measured a staged run at 5.44 seconds and 58.3 MB reported peak RSS. The corpus is only 200 small synthetic files, so this is not a large-scale stress test.
- The environment lacked native `pdftoppm` and Tesseract executables. Add them to deployment setup and require these capabilities when image-only scans must be inspected.

## Remaining work

1. Review the 30 clinical-value exact-match misses and preserve intended clinical facts exactly.
2. Add held-out and adversarial name variants, shared-phone cases, cross-script aliases and complex homonyms; keep precision high.
3. Validate FHIR R4 schemas and all Bundle references after edits.
4. Implement rare-combination suppression and an attack-based re-identification-risk evaluation.
5. Make the independent verifier a blocking release condition and ensure failed/missing capabilities cannot be mistaken for complete inspection.
6. Decide and document deployment policy for native OCR tools; test both fully equipped and missing-backend environments.
7. Review crash dumps, temporary artifacts, process memory, key rotation and host-level side channels.

## Submission decision

The Toolkit's current repository and runtime checks pass, so the repository can be submitted as a competition prototype with these limitations disclosed. Do not call it perfect, anonymous, production safe, or validated on hidden cases. See [RELEASE_CRITERIA.md](RELEASE_CRITERIA.md) for the gate summary and [BASELINE_RESULTS.md](BASELINE_RESULTS.md) for commands and denominators.
