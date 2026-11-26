# Limitations

## Not implemented

| Capability | Status |
|---|---|
Identity linkage at record granularity | `patient: null` for ambiguous exports (0 false merges by design) |
Quasi-identifier generalisation | not implemented — 12% unique rows under the shipped attacker registry |
Date shifting | not implemented |
Envelope encryption / key rotation | not implemented (no mapping table is stored, so there is no envelope) |
OCR for text inside images | degrades: declared in `report.json.capabilities`, affected files quarantined |

## Weak classes

* **Names.** Heuristic and context-dependent. The independent verifier reports ~557 surviving
  name-like candidates on the dev corpus. Triaged: ~79 are drug/product labels with formulary
  evidence, ~353 are other Titlecase pairs including places, analytes and drug lines. They are
  **unverified**, not dismissed — there is no labelled set in the repository to settle them.
* **Devanagari 19.6%, Hinglish 42.3%** of surfaces still visible; Latin 12.2%.

## Evaluation caveat

`14%`-style figures are *surface counts against this corpus*, not recall against ground truth. Never
quote them as detector accuracy.
