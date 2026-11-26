# Secret Wards

An offline, CPU-only Python privacy firewall for synthetic multilingual healthcare exports. The repository currently implements file ingestion into an intermediate representation (IR), but not PII detection, linkage, privacy transformations, or the final release-output pipeline. No anonymization or output-contract success is claimed.

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

The initial `main.py` only parses these arguments and reports that processing is not implemented. It does not create sanitized output.

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

## Known limitations

Ingestion supports JSON/FHIR JSON, CSV, TSV, text, and XML. The IR retains original parsed values, so generated IR and batch outputs can contain PII; keep them local and out of version control. Detection, policy evaluation, linkage, anonymization, and final release serialization remain unimplemented. Do not claim privacy protection from this parser.
