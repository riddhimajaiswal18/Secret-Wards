# Secret Wards

An offline, CPU-only Python privacy firewall for synthetic multilingual healthcare exports.

**Current state (honest):** ingestion, the intermediate representation, the locator-based edit
engine and the release-output pipeline are implemented and verified. `validate_output.py` reports
**CONTRACT OK** on the practice set: 195 of 200 files are sanitized, 5 are quarantined with typed
reasons, two runs are byte-identical, and `parse → serialize` reproduces the input for 189 of the
195 emitted files. PII detection, linkage, pseudonymization and the privacy transformations are
**still stubs**, so the release currently removes nothing — the practice self-check reports
**99.8% of personal data still visible**. Nothing here is yet a privacy guarantee.

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
