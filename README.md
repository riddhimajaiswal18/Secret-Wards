# Secret Wards

An offline, CPU-only Python privacy firewall for synthetic multilingual healthcare exports.

**Current state (honest):** ingestion, the intermediate representation, the locator-based edit
engine, detection (tier-0 identifiers + tier-1 context + structural column/key/header rules), the
clinical protection layer, path sanitation and the release-output pipeline are implemented and
verified. On the practice set:

| Gate | Result |
|---|---|
| `validate_output.py` | **CONTRACT OK** |
| files | 197 / 200 sanitized, 3 quarantined with typed reasons |
| **personal data still visible** | **17.7%** (from 99.8% pass-through) |
| medical values preserved | **99.4%** (4824 / 4855) |
| leakage by channel | content 17.9% · filename 8.3% · header **0%** · base64 **0%** · metadata 12.5% · key 41.7% |
| raw copies | **0** |
| determinism | byte-identical across runs |
| tests | 41 passing |

Not implemented yet: cross-record **linkage** (so no patient pseudonyms and no patient-level date
shifting), quasi-identifier generalisation, and the independent verifier. Nothing here is yet a
privacy guarantee — see `docs/decisions.md` for what each layer does and does not claim.

## Challenge constraints

- Runtime target: 2 CPUs, 4 GB RAM, 15 minutes; no network.
- Support English, Hindi (Devanagari), and Hinglish records from heterogeneous hospital systems.
- Preserve clinical values exactly while removing direct identifiers and reducing re-identification risk.
- Use conservative cross-record linkage and keyed HMAC pseudonyms from `RAKSHA_SECRET`.
- Quarantine unsafe or unsupported files instead of copying them into the release.

The official Team Kit describes challenging encodings (UTF-8 BOM, UTF-16, cp1252), nested and malformed files, FHIR, PII in filenames/headers/keys/metadata/base64, homonyms, cross-script identity variants, rare-value attacks, and clinical false-positive traps. See [AGENTS.md](AGENTS.md) for the engineering requirements.

## Intended interface

```bash
python main.py --input {input} --output {output}
```

`main.py` runs the pipeline and writes `sanitized/`, `report.json` and `records.jsonl`.

## Setup

```bash
python -m pip install -r requirements.txt
```

Pydantic is used to validate IR models. Other listed dependencies are planned for later modules. No models are downloaded or required.

## Architecture

```text
read-only input
   → ingestion and provenance
   → PII detection + clinical protection
   → normalization and conservative linkage
   → HMAC pseudonyms + privacy transformations
   → safe serializers / report / records manifest
   → sanitized output or quarantine
```

See [docs/architecture.md](docs/architecture.md), [docs/decisions.md](docs/decisions.md), and [config/policy.yaml](config/policy.yaml). The exact submission contract must be checked against the supplied Team Kit `docs/SPEC.md` and validators before implementation.

## Scanned documents (PDF, JPEG, PNG)

Unsupported containers are not silently dropped. Each one is put through a bounded, offline ladder
and either released as **declared derived text** (`sanitized/<original name>.txt`, mapped in
`report.json` with `derived_from`) or quarantined with a typed reason:

| Step | Backend | Trigger |
|---|---|---|
| 1 | `pdf-text-layer` (pypdf) | PDF has a text layer |
| 2 | `pdf-raw-stream` | PDF parser refuses the file — streams are inflated and `Tj`/`TJ` operators read |
| 3 | `exif` | image metadata, XMP or comments carry text |
| 4 | `exif-carved` | malformed image: printable runs carved from the header |
| 5 | `ocr` (tesseract) | pixels only; bounded pages / DPI / timeout |

Extracted text is scrubbed with the identifier + name-shape rules before release, so the derived
file never contains the original identifier. Missing backend (no `tesseract`, no `pypdf`) is not an
error: the file is quarantined with `ocr_unavailable` and the run continues.

## Known limitations

Ingestion supports JSON/FHIR JSON, CSV, TSV, text, and XML. The IR retains original parsed values, so generated IR and batch outputs can contain PII; keep them local and out of version control. Detection, policy evaluation, linkage, anonymization, and final release serialization remain unimplemented. Do not claim privacy protection from this parser.
