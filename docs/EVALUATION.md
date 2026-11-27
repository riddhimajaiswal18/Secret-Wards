# Evaluation

The latest practice evaluation used the supplied 200-file synthetic Team Kit corpus in a Python 3.10 Linux container, limited to 2 CPUs and 4 GB RAM with network disabled during execution. The organizer's three-run pre-submit check passed. Full metrics and caveats are in [BASELINE_RESULTS.md](BASELINE_RESULTS.md).

| Check | Result |
|---|---:|
| Project tests | 162 passed |
| Files | 197 sanitized, 3 quarantined, 0 unaccounted / 200 |
| Output contract | Passed (`CONTRACT OK`) |
| Labeled direct PII | 0 / 3,234 by scorecard; 0 / 3,230 by practice self-check |
| Clinical values | 4,825 / 4,855 retained (99.38%) |
| Linkage | precision 1.00, recall 0.61, F0.5 0.89; zero observed false merges |
| Canaries and unsafe raw copies | 0 / 4 canaries; 0 penalized raw copies |
| Independent verifier | Passed; all 200 inputs inspectable, no surviving identifier candidates |
| Determinism | same-secret output identical; a changed secret changed output |
| Runtime | 5.44 s reported pipeline time; 58.3 MB reported peak RSS on staged Linux input |

The denominators are not interchangeable. The toolkit's answer-key results are practice-set measurements only. The two missing native tools (`pdftoppm` and `tesseract`) limit image-only PDF rendering and OCR; see [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

## Reproduction

```bash
KIT=/path/to/extracted/Secret-Wards-ToolKit
INPUT="$KIT/dev/input"
python -m pytest -q
export RAKSHA_SECRET='practice-only-secret'
python main.py --input "$INPUT" --output build/practice-output
python "$KIT/validate_output.py" --input "$INPUT" --output build/practice-output
python "$KIT/check_dev.py" --output build/practice-output
python tools/scorecard.py --kit "$KIT" --output build/practice-output
python tools/verify.py "$INPUT" build/practice-output
python "$KIT/check_submission.py" --repo . --input "$INPUT" --run
```

The submission helper runs three times with two random test secrets. It passed in an offline Linux container under the Toolkit's resource limits. Keep synthetic outputs, secrets, and private test data out of version control.
