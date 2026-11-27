# Identity linkage and pseudonyms

## Current mechanism

`src/privacy/pseudonyms.py` derives deterministic patient tokens using HMAC-SHA256 keyed by `RAKSHA_SECRET`, with domain separation. The secret is not persisted. Records with insufficient or conflicting evidence may remain unlinked. Available identifier evidence is included in sanitized records and `records.jsonl` according to the current output contract.

## Practice-set measurement

The Team Kit self-check reports precision **1.00**, recall **0.51**, F0.5 **0.84**, and zero observed false merges on the 200-file development set. The current pipeline emitted identifier-derived tokens for 609 records; that count is not itself an accuracy result. These measurements do not establish hidden-set performance or complete resolution across aliases, hospitals, scripts, homonyms and conflicting identifiers.

## Remaining work

Build a more complete conservative record-level linker with stronger blocking, independent evidence, conflict detection, cluster-level checks, and explicit ambiguity. Improve the 0.51 practice recall without introducing false merges, then measure on renamed/held-out examples. Do not merge on name alone. Date shifting and cross-release linkage are not implemented. See [BASELINE_RESULTS.md](BASELINE_RESULTS.md) and [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).
