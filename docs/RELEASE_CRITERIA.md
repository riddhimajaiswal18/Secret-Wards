# Release criteria

This repository must not be described as submission-ready or safe for real clinical data until all organizer requirements are checked on the target Linux sandbox. Current practice-set evidence is in [BASELINE_RESULTS.md](BASELINE_RESULTS.md).

## Current gate status

| Gate | Required evidence | Current status |
|---|---|---|
| Output contract | Team Kit validator says `CONTRACT OK` | Pass on latest practice output |
| Accounting | every input gets one fate | Pass: 197 exported, 3 quarantined, 0 unaccounted |
| Direct PII | project target ≤5% labeled surfaces | Pass on practice set: 0.84%; not hidden-set evidence |
| Canaries and unsafe copies | 0 canaries; 0 penalized raw copies | Pass on practice set: 0/4; 0 penalized |
| Clinical utility | ≥99% measured values retained | Pass on practice set: 99.38% |
| Determinism and key variation | same secret identical; different secret changes tokens | Pass on three direct runs |
| Identity linkage | precision ≥0.98, 0 false merges, F0.5 ≥0.85 | Partial: P=1.00, R=0.51, F0.5=0.84; recall/score below target |
| Independent verifier | no unresolved candidate findings | Fail: 492 NAME candidates; each requires triage |
| Re-identification risk | attack-based evaluation on supplied registry | Not measured |
| Date recovery | date shift and recovery attack | Not implemented |
| Linux limits and offline operation | full run at 2 CPUs / 4 GB / 15 min / no network | Not verified on Linux |
| Test suite | all project tests pass | Pass: 145 tests |

**Current decision:** publish the rescue branch for review, but do not merge it as a final release or claim the project is fully submission-ready. Remaining requirements are measurable work, especially verifier triage, re-identification-risk controls, date transformations, and Linux validation.

## Promotion procedure

1. Run the full Team Kit three-run checker in the target Linux sandbox.
2. Resolve direct-PII and verifier findings; rerun the truth-based scorecard.
3. Implement and evaluate the missing linkage/privacy transforms and attack metrics.
4. Attach the final scores and known residuals to a pull request.
5. Merge only after the required gates pass and a human reviews the result. Do not force-push `main`.
