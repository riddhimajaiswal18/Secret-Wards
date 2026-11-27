# Independent verification

`tools/verify.py` independently reads the input tree, hash-keyed `report.json` and released files. It imports no sanitizer detection, policy, transformation, writer or pipeline modules. It checks file accounting, identifier-shaped candidates, unchanged unsafe outputs, required capabilities and readable coverage.

```bash
python tools/verify.py <input> <output> [--require cap,cap] [--json report.json]
# exit 0 passed; 1 failed; 2 cannot verify
```

The verifier maps current `input_sha256` entries to the input tree without requiring source paths in `report.json`; it still accepts older path-keyed reports for tests/compatibility. Its evidence masks candidate text as length plus digest. Paths in CLI diagnostics are for local triage and should not be copied into externally scanned reports.

## Current result and limits

On the latest practice output, accounting passed and all 200 files were inspectable. The verifier found 492 NAME candidates and returned failure. A candidate is not necessarily a confirmed PII leak, but this result requires review and means the verifier cannot approve the current output. It does not prove anonymity, assess quasi-identifier risk, inspect OCR-only image pixels, or validate all FHIR references. A clean result would only mean no known patterns survived in the channels the verifier can read.
