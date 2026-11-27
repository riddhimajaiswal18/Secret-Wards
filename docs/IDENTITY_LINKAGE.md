# Record linkage and pseudonyms

## Implemented behavior

`src/privacy/linkage.py` extracts record-scoped evidence from the common IR. Records with the same direct identifier keep the existing secret-keyed token. If different facility identifiers are present, the linker can connect records when each record has exactly one normalized patient name and exactly one phone number and the composite pair matches. Sex and date-of-birth conflicts block a merge. Name-only and phone-only links are not allowed. Cluster merges are checked against existing member evidence to reduce transitive conflicts.

`src/privacy/pseudonyms.py` derives domain-separated HMAC-SHA256 tokens from `RAKSHA_SECRET`. Raw normalized identity evidence remains in process memory and is not written as a mapping table. Records without sufficient evidence may remain unlinked.

## Practice measurement

On the synthetic 200-file Toolkit development corpus, the self-check measured precision **1.00**, recall **0.61**, F0.5 **0.89**, and zero observed false merges. The output contained 665 linked records. The count is not an accuracy measure; linkage precision and recall are the scored evidence. A separate run with a different secret changed the output, while two runs with the same secret matched byte-for-byte for all 197 exported files.

These results do not establish hidden-set performance or complete cross-hospital identity resolution. The exact name/phone rule does not resolve broad spelling variants, transliteration ambiguity, shared family phones, fragmented identifiers, complex homonyms, or cross-release identity.

## Not implemented

- Fuzzy or phonetic alias matching and broad cross-script identity equivalence.
- Persistent identity graph or mapping service across separate releases.
- Calibrated match/review confidence values and a human review workflow.
- A comprehensive guarantee against transitive cluster errors beyond implemented conflict checks.

The policy is intentionally conservative: do not merge on name alone, do not equate approximate transliteration with proof of identity, and leave uncertain records unlinked. See [BASELINE_RESULTS.md](BASELINE_RESULTS.md) and [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).
