# Identity linkage and pseudonyms

`SPEC.md §6` wants one line per patient-bearing record with a token like `PSN-7Q2K9D`.

## Mechanism

`src/privacy/pseudonyms.py` computes `PSN-` + 6 chars from `HMAC-SHA256(secret, scope|kind|identifier)`
on a base32 alphabet without `I O 0 1`. Properties: deterministic for a fixed `RAKSHA_SECRET`, different
for a different secret, no mapping table stored, no identifier recoverable from the token.
A name is never evidence: name-only linkage was measured at 96 false merges elsewhere.

## Granularity, decided by measurement

| Approach | Result on the dev corpus |
|---|---|
file-level, first identifier | 419 linked, precision **0.06**, **7 wrong merges** |
row-level, first id-looking column | recall 0.26, precision **0.03**, **1 wrong merge** |
single-identifier-or-null (shipped) | **0 wrong merges**, links only unambiguous records |

A wrong merge corrupts two patients' histories, which is worse than no link. The shipped rule
therefore answers ambiguity with `patient: null`. On a corpus of multi-patient exports this yields
**few or no links** — that is the honest outcome, not a solved feature.

## Not implemented

Per-row patient-key identification (the missing piece), probabilistic linkage, date shifting,
cross-release consistency. Listed in `config/capabilities.json` as `not_implemented`.
