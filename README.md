# Secret Wards

An offline, CPU-only Python privacy firewall for synthetic multilingual healthcare exports. This repository is at the initial scaffolding stage: ingestion, detection, linkage, privacy transformations, security, and serialization are not implemented yet. No output contract or validation result is claimed.

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

Dependencies are candidates for planned modules and are not used by this scaffold. No models are downloaded or required.

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

Nothing in this initial repository processes or sanitizes records yet. Policies and matching thresholds are provisional and unvalidated. Do not use this scaffold to handle real patient data or claim privacy protection.
