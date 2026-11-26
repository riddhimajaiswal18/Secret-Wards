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

## Independent release verification

`tools/verify.py` is a second scanner that imports nothing from `src/detection`, `src/transformation`,
`src/policy`, `src/output` or `src/pipeline`. It re-reads only the released tree with its own patterns
and its own CSV/JSON/XML readers, so a blind spot would have to exist twice to pass:

```bash
python tools/verify.py <input_dir> <output_dir> [--require pdf_render] [--json out.json]
# exit 0 released · 1 failed · 2 cannot verify
```

Checks: accounting (one fate per input), surviving identifiers in content, relative path and filename,
unchanged outputs that still carry identifiers, required capabilities, and coverage (unreadable files
are reported `unsupported`, never assumed safe). `tools/run_dev.sh` treats a failure as blocking.
Evidence is masked (`len=13 sha256=…`); the verifier never republishes what it finds.

## Measured state and known limitations

Development corpus, 200 files, every figure with its denominator:

| Measure | Value |
|---|---|
Clinical values preserved | 99.4% (4,824 / 4,855) |
PII surfaces still visible | 14.0% (453 / 3,234) |
Channels: content 14.2% · metadata 12.5% · filename 8.3% · key 0.0% · header 0.0% · base64 0.0% |
Scripts: Devanagari 19.6% · Hinglish 42.3% · Latin 12.7% |
Canaries | 0 / 4 (baseline 4 / 4) |
Accounting | 197 exported · 3 quarantined · 0 unaccounted |
Independent verifier | **fails**: 564 surviving candidates (NAME 557, AADHAAR 4, MRN 3) |

Known limitations, stated plainly:

* **Not anonymity.** Quasi-identifier generalisation, date shifting and cross-hospital identity linkage
  are scoped but not implemented; `config/capabilities.json` records them as not implemented.
* **Names are the weakest class** and account for almost all verifier findings; they are not yet
  triaged against a labelled evaluation set.
* **Scanned images** need a rendering binary for OCR; when it is absent the affected files are
  declared in `report.json.capabilities` and quarantined rather than released uninspected.
* The verifier knows a fixed set of identifier classes in the channels it can read. It is a
  release-safety layer, not proof of anonymity, and it says so in every report it writes.
