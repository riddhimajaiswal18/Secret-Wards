# Known limitations

The current system is a competition prototype. Its toolkit scores describe one synthetic development corpus and do not establish hidden-set performance, anonymity, or suitability for real patient data.

## Detection and formats

- The practice labels showed 0 visible direct-PII surfaces in both the scorecard (0/3,234) and the Toolkit self-check (0/3,230). These are corpus-specific observations, not general recall guarantees.
- The Linux evaluation lacked `pdftoppm` and the Tesseract executable. Image-only PDF rendering and pixel OCR were unavailable even though the Python wrappers were installed. The runtime reports these missing capabilities; OCR-dependent inputs may be quarantined or incompletely inspected.
- CSV/TSV, JSON, FHIR-shaped JSON, XML, and text use the shared IR, but format-specific semantic coverage is not uniform. Full FHIR R4 schema validation and comprehensive Bundle reference validation are not implemented.
- Date/age/location transforms cover common structured paths and selected text patterns. XML, uncommon date labels, partial dates, and free-text contexts have limited transformation coverage.
- The independent verifier passed the current 200-file corpus, but it checks only the patterns and readable channels it implements. It is run separately and does not block `main.py` from releasing output.

## Identity and privacy

- The within-run linker groups direct identifier evidence and can join different hospital IDs only on an exact patient-name plus phone pair, subject to sex and date-of-birth conflict checks. It deliberately does not link on name alone or phone alone.
- Alias spelling changes, script variants, fragmented identities, shared phones, complex homonyms, and identity ambiguity are not comprehensively handled. There is no persistent cross-release identity service.
- Date shifting, age bands, village/locality generalization and PIN-prefix masking are implemented for covered contexts. The practice run shifted 696 date values and generalized 1,358 fields across 699 records. These counts do not assess privacy risk.
- Rare-combination suppression and attack-based re-identification-risk measurement are not implemented. A zero direct-PII score does not imply resistance to linkage, singling-out, or auxiliary-data attacks.
- Pseudonyms use HMAC and a caller-provided secret. There is no key rotation service. Parsed source values and linkage evidence remain in memory during the run; persisted-data encryption and secure-deletion guarantees are absent.

## Evaluation and operation

- The project passed 162 tests and the Toolkit's three-run submission helper in a Python 3.10 Linux container with 2 CPUs, 4 GB RAM, and no network during execution. That proves behavior only for the tested source, environment and synthetic corpus.
- Clinical value retention was 4,825/4,855 (99.38%). The remaining 30 exact-match misses require continued clinical-utility review; this aggregate does not identify which changes were intentional privacy transforms.
- The report records missing optional capabilities. Deployment should install and require the OCR native tools if image-only scans must be processed instead of quarantined.
- `report.json` avoids source filenames and the Toolkit helper confirmed the test secret was absent from output and logs. This does not cover every host-level crash dump, filesystem snapshot, antivirus index, or operator-created copy.

Do not describe this prototype as anonymous, production safe, or fully compliant. Before real-world use, complete broad hidden-style evaluation, FHIR validation, OCR capability handling, privacy-risk attacks, stronger linkage review, and security operations review.
