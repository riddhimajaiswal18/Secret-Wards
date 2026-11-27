# Current Team Kit evaluation

**Corpus:** Secret Wards Toolkit development set, 200 synthetic input files. **Runtime:** Python 3.10 Linux container, 2 CPUs, 4 GB memory limit, and network disabled during execution. Dependencies were installed before the offline run. The organizer's `check_submission.py --run` helper and the project's own tests were run against the current working tree.

## Results

| Measure | Linux result |
|---|---:|
| Project tests | 162 passed |
| Files | 200 accounted for: 197 sanitized, 3 quarantined, 0 unaccounted |
| Toolkit contract | `CONTRACT OK` |
| Labeled direct PII visible | 0 / 3,234 (independent scorecard) |
| Toolkit self-check PII visible | 0 / 3,230 |
| Clinical values retained | 4,825 / 4,855 (99.38%) |
| Linkage | precision 1.00, recall 0.61, F0.5 0.89; 0 observed false merges |
| Canaries | 0 / 4 found |
| Unsafe unchanged copies | 0 penalized raw copies; two byte-identical outputs were not files expected to be quarantined |
| Independent verifier | Passed; 200 / 200 inputs inspectable, no surviving identifier candidates |
| Reproducibility | Same secret produced identical output for 197 files; a changed secret changed output |
| Runtime and memory | 5.44 s reported pipeline time; 5.98 s wall time; 58.3 MB reported peak RSS |

The scorecard and practice self-check use different denominators and counting logic. Their zero-miss results apply only to the provided synthetic labels and output surfaces; they are not held-out recall estimates and do not establish anonymity. The utility metric retained 99.38% of its labeled clinical values; 30 exact-value checks did not match, and those cases need review to distinguish expected transformations from unintended loss.

## Transform and linkage activity

The Linux run reported 665 linked records, 699 records with at least one generalization, 1,358 generalized fields, and 696 shifted date values. No records were suppressed. These are activity counts, not independent accuracy or privacy-risk scores. The deterministic linker uses same-record direct identifiers and exact patient-name-plus-phone composite evidence with sex/date-of-birth conflict checks; it does not perform broad fuzzy alias resolution.

## Capability caveats

The run reported `pdf_render` and `ocr_binary` missing: `pdftoppm` and the native Tesseract executable were not installed. Python packages for PDF text, image metadata, and the OCR wrapper were installed, but image-only PDF rendering and pixel OCR were not available. The report records this degradation. Do not treat zero labeled misses as evidence that unseen image pixels were inspected.

The independent verifier passed, but it is a separate command, not an automatic blocking step in `main.py`. Full FHIR R4 schema validation and comprehensive reference checking, rare-combination suppression, and attack-based re-identification-risk measurement remain unimplemented. Sensitive source values exist in process memory during parsing.

## Reproduction

Set `KIT` to the extracted Toolkit root and `INPUT` to its `dev/input` directory:

```bash
python -m pytest -q
export RAKSHA_SECRET='practice-only-secret'
python main.py --input "$INPUT" --output build/practice-output
python "$KIT/validate_output.py" --input "$INPUT" --output build/practice-output
python "$KIT/check_dev.py" --output build/practice-output
python tools/scorecard.py --kit "$KIT" --output build/practice-output
python tools/verify.py "$INPUT" build/practice-output
python "$KIT/check_submission.py" --repo . --input "$INPUT" --run
```

The organizer helper was run in an offline Linux container with 2 CPUs and 4 GB RAM. Its check passed, including contract validation, same-secret determinism, changed-secret output, secret non-disclosure, and input immutability. One run from the host-mounted OneDrive path took 27 seconds; a staged local Linux run took 5.98 seconds wall time. Both are well under the 900-second per-run limit. Memory is measured by the application report and has not been measured with an independent process-tree profiler.
