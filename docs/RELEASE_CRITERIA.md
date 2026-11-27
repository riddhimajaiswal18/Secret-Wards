# Release criteria and current decision

The Team Kit's repository and runtime checks have been exercised on the current working tree. Current measurements are detailed in [BASELINE_RESULTS.md](BASELINE_RESULTS.md). Passing the practice checks supports a competition submission; it does not establish general privacy safety or production readiness.

## Gate status

| Gate | Evidence required | Current status |
|---|---|---|
| Repository contract | Root `raksha.toml`, README, dependencies and policy | Pass; Toolkit pre-submit checker reports `READY TO SUBMIT` |
| Output contract | Toolkit validator accepts output | Pass on the Linux practice run (`CONTRACT OK`) |
| Accounting | Every input has one output fate | Pass: 197 sanitized, 3 quarantined, 0 unaccounted / 200 |
| Direct PII | Practice-set labeled surfaces | Pass on this corpus: 0/3,234 and 0/3,230 in separate Toolkit checks |
| Canaries and raw-copy safety | No canaries; no penalized unchanged unsupported files | Pass: 0/4 canaries; 0 penalized raw copies |
| Clinical utility | At least 99% exact-value retention | Pass on practice set: 99.38%; 30 exact values were not retained and need error-class review |
| Determinism and key variation | Same secret is repeatable; a new secret changes output | Pass in official three-run check |
| Linkage | Precision ≥0.98, no false merges, F0.5 ≥0.85 | Pass on practice self-check: P=1.00, R=0.61, F0.5=0.89, zero observed false merges |
| Independent verifier | No surviving supported identifier candidates | Pass on current practice output; verifier is not wired as a pipeline release gate |
| Linux limits and offline run | 2 CPUs, 4 GB RAM, ≤15 minutes, no network | Pass: 5.44 s reported pipeline time and 58.3 MB reported peak RSS on staged input; official helper also passed |
| OCR capability | Required image-only PDF and image pixels are inspected or quarantined | Partial: `pdftoppm` and Tesseract binaries were absent; runtime reported the degradation |
| FHIR and privacy-risk validation | Schema/reference validation and attack-based risk evidence | Not complete: full R4 validation, rare-combination suppression and re-identification-risk measurement remain |
| Project tests | All current unit and adversarial tests | Pass: 162 tests on Python 3.10 Linux |

## Decision

The repository passes the Toolkit's current submission checker and its three-run Linux execution gate. It is reasonable to submit as a competition prototype with the stated OCR and evaluation limitations. Do not claim the system is perfect, anonymous, safe for real patient data, or validated against hidden cases.

## Remaining work before any production use

1. Install and require native PDF rendering/OCR tools for workloads containing image-only scans; verify quarantine behavior when they are absent.
2. Add broader held-out identity variants and review the 30 clinical-value exact-match misses.
3. Complete FHIR R4 schema and reference validation.
4. Add attack-based re-identification measurement and rare-combination suppression.
5. Integrate the independent verifier as a blocking release step and review its scope.
6. Review key lifecycle, memory handling, crash dumps, temporary files and host-level side channels.
