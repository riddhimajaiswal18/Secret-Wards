# Engineering audit and current improvements

This audit describes the current working tree and the supplied Toolkit's 200-file synthetic development set. It is an implementation/evaluation record, not a production security review.

## Implemented in the current working tree

- Added deterministic contextual name and relative-name handling for honorifics, kinship markers, explicit attendant/guardian labels and multiline Hinglish phrases, while retaining clinical and ward-label negative controls.
- Scrubbed person-name fragments in export-path metadata when the parser can identify their role.
- Added within-run record linkage using direct identifiers and exact name-plus-phone composites, with sex/DOB conflict checks and cluster-level compatibility checks. Name-only links remain forbidden.
- Added HMAC-keyed, per-patient event-date shifts, age-band generalization, village/locality-to-district generalization, and PIN-prefix masking for supported contexts. The original parsed structure remains authoritative; changes are queued as locator-based edits.
- Added a date prepass that avoids shifting an event date onto a source DOB found in the same corpus; if no safe offset is available, the exact date is suppressed.
- Updated the independent verifier to use contextual candidate checks for supported structured formats and XML/text, reducing false findings for clinicians and clinical vocabulary.
- Made the pipeline fail closed when `RAKSHA_SECRET` is missing and added tests for that behavior.
- Removed unused dependency declarations and pinned the Python packages exercised by the Python 3.10 Linux run.
- Added regression tests for names, relationship/clinical negatives, linkage conflicts, transformations, verifier behavior and missing secrets.

## Current Toolkit evidence

- 162 project tests pass on Python 3.10 Linux.
- The organizer's three-run submission helper passes with network disabled and 2 CPUs / 4 GB RAM. Output contract, same-secret determinism, changed-secret behavior, secret non-disclosure and input immutability all pass.
- 197 inputs sanitized and 3 quarantined; all 200 have an accounted fate.
- Labeled direct-PII misses: 0/3,234 in the independent scorecard and 0/3,230 in the Toolkit practice self-check. These denominators differ.
- Clinical values retained: 4,825/4,855 (99.38%). Linkage: precision 1.00, recall 0.61, F0.5 0.89, with zero observed false merges. Canaries: 0/4.
- The verifier passes and inspects all 200 files. The scorecard reports 665 linked records; the count itself is not an identity-accuracy metric.
- A staged Linux run reports 5.44 seconds and 58.3 MB peak RSS. The official helper's first run took 27 seconds when reading the host-mounted OneDrive corpus.

## Remaining gaps

1. The Linux environment lacked `pdftoppm` and the Tesseract executable; image-only PDF rendering and pixel OCR therefore remain unavailable unless deployment installs and requires those native tools.
2. The 30 exact clinical-value misses need error-class review. The aggregate utility metric does not establish which misses were expected transformations.
3. Linkage does not fully resolve aliases, transliteration variants, shared phones, fragmented identities, complex homonyms or cross-release identity.
4. Rare-combination suppression and attack-based re-identification-risk evaluation are not implemented.
5. Full FHIR R4 schema and reference validation are incomplete. XML and free-text privacy transformations have narrower coverage than CSV/TSV and JSON.
6. The independent verifier is not wired as an automatic blocking release stage. It only checks patterns and channels it knows how to inspect.
7. Sensitive source structures remain in process memory; persisted-data encryption, secure deletion and key rotation are incomplete.

See [BASELINE_RESULTS.md](BASELINE_RESULTS.md), [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md), and [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) for methods and remaining work.
