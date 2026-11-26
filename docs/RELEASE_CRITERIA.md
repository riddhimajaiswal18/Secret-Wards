# Release criteria: when this repository may become `main`

Work happens on feature branches. Promotion to `main` is a release decision, not a merge
convenience, so it is gated on measurements produced by `tools/scorecard.py` and the Team Kit
validators — not on "the pipeline ran without an exception".

## Mandatory gates (all must pass in the same run)

| Gate | Threshold | Command |
|---|---|---|
| Output contract | `CONTRACT OK` | `python3 team-kit/validate_output.py --input … --output …` |
| Direct PII visible | **≤ 5 %** of measured surfaces | `tools/scorecard.py` |
| Canaries | **0 / 4** | `tools/scorecard.py` |
| Raw copies (penalised) | **0** | `tools/scorecard.py` |
| Clinical values kept | **≥ 99 %** | `tools/scorecard.py` |
| Determinism | byte-identical across two runs | `tools/scorecard.py` |
| Files accounted for | 0 unexplained fates | `tools/scorecard.py` |
| Identity linkage | precision **≥ 0.98**, **0 false merges**, F0.5 ≥ 0.85 | linkage harness (to build) |
| Re-identification (shipped attacker registry) | **≤ 10 %** of released rows uniquely matched | attacker harness (to build) |
| Date recovery | global-offset attack recovers **0 %** | date harness (to build) |
| Release verifier | can reject a deliberately unsafe build | `tools/verify.py` (to build) |
| Test suite | green | `pytest tests -q` |

## Current status (measured, not projected)

| Gate | Status |
|---|---|
Contract, determinism, accounting, utility, raw copies | ✅ pass |
Direct PII 15.7 % | ❌ (needs ≤ 5 %) |
Canaries 1 / 4 | ❌ |
Identity linkage | ❌ not implemented |
Re-identification 12 % | ❌ |
Date recovery | ❌ not implemented |
Release verifier | ❌ not implemented |

**Therefore: promotion to `main` is blocked.** The repository is a strong, measured prototype of
the transformation stage, not a releasable privacy system.

## Promotion procedure (when every gate above is green)

1. Rebase the feature branch onto `origin/main`; resolve conflicts in favour of the measured result.
2. Re-run every gate command above; attach the scorecard JSON to the merge description.
3. Open a pull request; require one human review — never self-merge, never force-push `main`.
4. Only then merge. Tag the merge commit with the scorecard's numbers.
