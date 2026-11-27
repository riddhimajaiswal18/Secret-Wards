# Engineering audit and rescue changes

This audit covers the working tree based on local commit `1008133`, evaluated on the supplied 200-file Team Kit development corpus. It is not a production security assessment. The authoritative output requirements are in `team-kit/docs/SPEC.md`.

## Changes made

- Reworked the release report to use input SHA-256 values instead of source paths, use the `raksha-report/1` schema name, and avoid exposing original names in quarantine entries.
- Added locator-based record pseudonym fields for supported CSV/JSON/FHIR output records and `records.jsonl`; deferred token embedding until edits have been applied so existing field preconditions remain valid.
- Fixed identifier evidence extraction where a prefixed hospital ID and its numeric suffix were incorrectly treated as competing identities.
- Added deterministic approximate Devanagari transliteration fallback, explicitly not treated as proof of identity equivalence.
- Improved structured field detection for Hindi/English aliases, phone formatting, relative markers and Hinglish context, while tightening clinical false-positive handling.
- Improved FHIR patient/practitioner role handling and resource ID/reference edits; added nested JSON and FHIR regression coverage.
- Corrected a Windows path conversion bug in module-discovery tests and changed scorecard accounting to use input hashes.
- Replaced stale documentation and prepared a current submission brief based on measured behavior.

## Latest practice-corpus snapshot

See [BASELINE_RESULTS.md](BASELINE_RESULTS.md) for denominators and caveats. Latest recorded iteration:

- 197 sanitized, 3 quarantined, 0 unaccounted of 200 inputs.
- 27 / 3,234 labeled direct-PII surfaces remained visible (0.84%). Hinglish was 14.4%, Devanagari 0%, Latin 0.4% by the scorecard's script grouping.
- Clinical values retained: 4,825 / 4,855 (99.38%).
- Same-secret deterministic outputs matched for all 197 exported files; a changed secret changed outputs.
- Toolkit-contract validator had passed on prior rescue iterations; must be rerun against the final output before release.
- 609 records received an identifier-derived pseudonym. The Team Kit self-check scored linkage at precision 1.00, recall 0.51, F0.5 0.84 with zero observed false merges on this practice set; it is not a hidden-set guarantee.
- Contract-aware independent verifier: accounting passed, but 492 NAME candidates remain and require triage.

## Remaining engineering gaps

1. The scorecard still finds PII, concentrated in Hinglish and name/relative contexts. The 0.84% rate is not proof of safe release.
2. Identity linkage remains limited. The practice self-check found precision 1.00 and recall 0.51, but identifier-derived tokens do not solve all aliases, conflicting identifiers, homonyms or cross-script matches. Do not interpret the 609-token count as correctly linked records.
3. Per-patient date shifting, age bands, location generalization and rare-combination suppression are not implemented in the release path.
4. The independent verifier is diagnostic and is not wired as a blocking release gate. Current findings must be assessed, not waived.
5. Optional scan/PDF/OCR/image backends were absent from the measured environment; corresponding inputs cannot be claimed fully processed.
6. Current evaluation was on Windows with a temporary adapter for Linux-only `resource`; Linux organizer constraints, memory/time measurements, and changed-secret behavior remain to validate.
7. The three quarantined files and any capability degradation need clear reporting in the final competition environment.

## Operational boundaries

The Team Kit's truth labels are used by the evaluation tooling only. Production detection does not read truth files or hardcode practice identities. No real patient data, hosted models, network calls, or runtime downloads are used. The tree contains test/reference materials, not a claim that every Team Kit format is safely supported.
