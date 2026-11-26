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

## Ground truth exists and was previously misreported

An earlier revision of this document claimed "no labelled set exists in the repository". **That was
wrong.** The Team Kit ships `dev/truth/truth.json`: 200 files, 883 units, 771 records carrying
`"link": "required"` with a truth patient id (`PT00004`), and per-entity labels carrying `type`,
`surface`, `role`, `script`, `channel` and `critical`.

Consequences for this project:

* name candidates **can** be adjudicated against labelled surfaces instead of argued about;
* identity linkage **can** be scored per record, so aligning our pseudonym groups with the truth
  patient ids is a solvable engineering task, not an absence of data;
* the 13.6% surface figure can be replaced by real recall, precision and F1 per kind and channel.

What is genuinely missing is a *held-out* split — the corpus is the practice set, so tuning against it
will overstate performance on hidden data. That distinction matters and is not the same claim.

## Evaluation caveat

`14%`-style figures are *surface counts against this corpus*, not recall against ground truth. Never
quote them as detector accuracy.
