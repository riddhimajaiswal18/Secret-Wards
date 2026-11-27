# Evaluation

The Team Kit development corpus contains 200 synthetic files and truth labels. Results below are from a local Windows run with a temporary `resource` compatibility shim; Linux target-resource compliance remains unverified. Full results and caveats are in [BASELINE_RESULTS.md](BASELINE_RESULTS.md).

| Measure | Latest practice result |
|---|---:|
| Direct PII surfaces still visible | 27 / 3,234 (0.84%) |
| Clinical values retained | 4,825 / 4,855 (99.38%) |
| Canary strings found | 0 / 4 |
| Files | 197 sanitized, 3 quarantined, 0 unaccounted |
| Pseudonym linkage | precision 1.00, recall 0.51, F0.5 0.84; zero observed false merges |
| Same secret / different secret | deterministic / output changed |
| Independent verifier | accounting passes; 492 NAME candidates cause verifier failure |
| Runtime | 3.42-3.52 seconds per local run; memory not measured |

The scorecard and Team Kit self-check have different labeled-surface denominators (3,234 vs 3,230). Percentages are practice-set measurements, not held-out accuracy or anonymity guarantees. Verifier names are candidate findings and may include false positives; they must not be silently disregarded.

## Reproduction

```bash
export RAKSHA_SECRET=practice
python3 main.py --input <kit>/dev/input --output build/out
python3 <kit>/validate_output.py --input <kit>/dev/input --output build/out
python3 <kit>/check_dev.py --output build/out
python3 tools/scorecard.py --kit <kit> --output build/out
python3 tools/verify.py <kit>/dev/input build/out
```

The organizer's `check_submission.py --run` should be run on Linux, as supplied. On this Windows host its POSIX shell quoting fails on local paths, so the three pipeline runs, contract validation, self-check, determinism and changed-secret checks were executed directly instead.
