# Practice-set evaluation

**Corpus:** supplied Secret Wards Team Kit development set, 200 synthetic files. **Run:** latest stored rescue iteration, 2026-11-27. **Environment:** Windows, Python 3.10.11; a temporary compatibility shim supplied the Linux-only `resource` module for the local tools. The shim is outside application source and is not part of the release. This snapshot is not a hidden-set or Linux submission score.

## Results

| Measure | Result |
|---|---:|
| Files accounted for | 200 / 200 |
| Unit tests | 145 passed |
| Sanitized | 197 |
| Quarantined | 3: empty, malformed JSON, excessive depth |
| Truth-labeled direct-PII surfaces visible | 27 / 3,234 (0.84%) |
| Clinical values retained | 4,825 / 4,855 (99.38%) |
| Canary strings detected in release | 0 / 4 |
| Same-secret deterministic exported files | 197 / 197 identical |
| Identifier-derived tokens emitted | 609 records |
| Practice-set pseudonym linkage | precision 1.00, recall 0.51, F0.5 0.84 (0 false merges) |
| Same-secret / changed-secret behavior | same-secret sanitized tree and manifest identical; changed secret changed output |
| Contract validator | Passed on the current three-run corpus output (`CONTRACT OK`) |
| Independent verifier | Fails with 492 NAME candidates (candidate findings, not confirmed PII count) |

Visible labeled PII by type: `PATIENT_NAME` 21, `RELATIVE_NAME` 4 and `LOCALITY` 2. No identifier or phone surfaces were labeled as visible in this run. The 609 token count is not an accuracy metric and does not mean 609 patients were correctly linked.

## Leakage rates

| Grouping | Visible-surface rate |
|---|---:|
| Content | 0.84% |
| Metadata | 5.00% |
| Filename | 0% |
| Header | 0% |
| JSON key | 0% |
| Base64 | 0% |
| Latin script | 0.40% |
| Devanagari | 0.00% |
| Hinglish | 14.40% |

The channel/script denominators describe labeled surfaces and may overlap; they are not the 3,234 overall denominator partitioned in the same way. Rates are rounded. They measure this synthetic set only and do not imply zero risk in a category with no observed miss.

## Tool and capability caveats

The current scorecard is the ignored local evaluation artifact `build/rescue-baseline-20261127/scorecard-final3.json`. It reports optional cross-script transliteration package, phone validation, PDF text, image metadata and OCR capabilities missing in that environment. The built-in transliteration fallback is approximate, and does not resolve identity by itself. OCR has no local Tesseract binary in the measured environment. These limitations can lead to quarantine or degraded detection.

The supplied self-check measures the reported precision/recall/F0.5 values above on this synthetic set; the 609-token count alone is not linkage accuracy. These figures do not establish hidden-set performance or broad cross-hospital identity resolution. Re-identification risk, Linux resource consumption and full FHIR reference correctness remain unmeasured. The separate verifier flags 492 name candidates on the latest output; candidates are not all confirmed leaks, but each needs triage and the verifier does not establish release safety. The organizer's three-run helper is not runnable with Windows paths here because its POSIX `shlex.quote` arguments are passed to the Windows shell; the equivalent three runs, contract validator, self-check, determinism and secret-variation checks were run directly. Before submission, run `team-kit/check_submission.py --run` on the target Linux environment and inspect every verifier finding.
