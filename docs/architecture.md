# Architecture

One coordinator, one responsibility per package, no stage reaching into another's internals.

```
main.py                       CLI, exit codes
└── src/pipeline.py           policy load, capability enforcement, log filter
    └── src/output/writer.py  coordinator: enumerate → parse → detect → policy → transform
        │                     → serialise → report → release gate
        ├── src/ingestion/    file_router, csv_tsv, ir_json, xml_parser, fhir_parser,
        │                     text_parser, encoding, scanned (PDF/EXIF/OCR ladder)
        ├── src/ir.py         IntermediateRepresentation: structure, provenance, source locations
        ├── src/normalization/ unicode, names, dates, phones, transliteration, semantic (evidence)
        ├── src/understanding/ contextual and relationship annotations
        ├── src/detection/    engine, identifiers, protection, columns, paths, structural
        ├── src/policy/       technique table: the only place that decides substitute/keep
        ├── src/transformation/ locator-based edits, applied in reverse order, fail-closed
        ├── src/privacy/      pseudonyms (HMAC), the only place identity tokens are made
        └── src/security/     safe_logging (leak scan), capabilities, quarantine
tools/verify.py               independent verifier — imports none of the above
```

## Boundaries that are load-bearing

| Package | Owns | Must never |
|---|---|---|
`normalization/` | *evidence*: canonical field, role, identifier class | edit content or assign identity |
`detection/` | *findings* with spans and confidence | modify the document, or re-derive validation |
`policy/` | the technique per kind | parse or transform |
`transformation/` | applying edits by locator | decide what to edit |
`privacy/` | pseudonym generation | store a mapping table |
`output/` | artifacts, accounting, release gate | trust detection to have worked |
`tools/verify.py` | the release question, asked independently | import the detector |

## Data flow invariant

Every edit carries a locator into the IR, so a change can be applied, audited and reversed. Text is
edited back-to-front to keep earlier offsets valid. An IR that cannot be edited fails closed into
quarantine rather than emitting a partial file.
