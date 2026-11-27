# Independent verification

`tools/verify.py` independently reads the input tree, the hash-keyed report and released files. It imports no sanitizer detector, policy, transformation, writer or pipeline module. It checks file accounting, supported identifier patterns, unchanged unsafe outputs, reported capabilities and readable coverage.

```bash
python tools/verify.py <input> <output> [--require cap,cap] [--json report.json]
# exit 0 passed; 1 failed; 2 cannot verify
```

The verifier maps `input_sha256` report entries to source inputs without requiring source paths in `report.json`; it accepts older path-keyed reports for compatibility. Its JSON evidence avoids storing candidate text. CLI diagnostics are intended for local triage and should not be copied into public reports without review.

## Latest practice result

The verifier passed on the supplied 200-file development corpus. It accounted for 200/200 files, inspected all 200, and found no surviving supported identifier candidates. It also reported that PDF rendering and OCR native capabilities were unavailable. This is a check of the verifier's implemented patterns and readable channels; it does not prove anonymity, assess quasi-identifier risk, inspect unrendered image pixels, or validate all FHIR references.

The verifier is an independent command, not an automatic release gate inside `main.py`. The Toolkit's submission checker separately validated the output contract, repeatability, secret handling and source immutability. See [BASELINE_RESULTS.md](BASELINE_RESULTS.md) for the command conditions and results.
