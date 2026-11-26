# Independent verification

`tools/verify.py` answers one question — *may this output be released?* — and imports nothing from
`src/detection`, `src/transformation`, `src/policy`, `src/output` or `src/pipeline`. It has its own
patterns and its own CSV/JSON/XML readers, so a blind spot would have to exist twice to pass.

```bash
python tools/verify.py <input> <output> [--require cap,cap] [--json report.json]
# 0 released · 1 failed · 2 cannot verify
```

| Check | Meaning |
|---|---|
`accounting` | one fate per input; no phantom, duplicated or missing outputs |
`surviving_identifiers` | an identifier in an input that still appears in the release, its path or filename |
`unchanged_outputs` | unchanged file that still carries identifiers |
`capabilities` | a required inspection stage that did not run |
`coverage` | uninspectable files are `unsupported`, never assumed safe |

Evidence is masked (`len=13 sha256=…`); the verifier never republishes what it finds.

## Precision is calibrated, with evidence

Numeric classes are label-gated (a 12-digit value is an Aadhaar only when the key says so); UUIDs are
excluded (FHIR `urn:uuid:` digit runs are not patient identifiers); labels cannot adopt digits from
another flattened JSON chunk. Each calibration has a regression test proving a real identifier of the
same class is still detected.

## What it cannot establish

OCR text inside images, compressed or encrypted payloads, Devanagari name pairs, and any
linkability-based risk. A pass means no known identifier class survived in the channels it can read —
not that the data is anonymous.
