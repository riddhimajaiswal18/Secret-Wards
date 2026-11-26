# Submission contract (v1): Track 3 "Secret Wards"

This contract is the "specified submission format" required by §4 (Submission Format) of the problem
statement. Every team is run and scored through exactly this interface. Nothing
outside it earns or loses points.

## 1. Repository

Your GitHub repository must contain **`raksha.toml`** at its root:

```toml
[submission]
name  = "team-rakshak"                       # shown on the leaderboard (blind mode hides it)
setup = "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"   # optional, network ALLOWED
run   = ".venv/bin/python -m rakshak --input {input} --output {output}"         # required, network DENIED

[submission.env]                              # optional extra environment variables
RAKSHAK_POLICY = "config/policy.yaml"
```

* `setup` runs once in the repository root, with network access and a 30-minute limit.
  A private virtual environment (`.venv/`) is created for you **before** `setup` and put
  first on `PATH`, so `pip install -r requirements.txt` installs into it. If you have no
  `setup` but ship `requirements.txt`, we run `pip install -r requirements.txt` for you.
  Even during `setup` you cannot read anything outside your repository (see [SANDBOX.md](SANDBOX.md)).
* `run` runs in the repository root with **no network** (an empty network namespace,
  so every connection fails). The evaluator replaces `{input}` and `{output}` with
  absolute, shell-quoted paths.
* If `.venv/bin` exists it is prepended to `PATH`.
* Any language is allowed, as long as `setup` can build it offline-runnable on Linux.

## 2. Execution environment

| Item | Value |
|---|---|
| CPUs | 2 (enforced with CPU affinity) |
| Memory | 4,096 MB peak RSS of your **whole process tree** (sampled every 50 ms; killed above it) |
| Time | a fixed wall-clock limit per run, as stated in the problem statement (§7: 15 minutes). Fast systems also earn speed points |
| Network | none during `run` (connection attempts are logged and flagged for the judges) |
| Visibility | only your repository, the read-only input copy, your output folder and private TMP/HOME; truth, seeds, other teams and host processes are hidden |
| Input | a fresh read-only copy; it is re-hashed after the run, and modifying it is penalised |
| `TMPDIR`, `HOME` | private empty directories, **scanned for PII after the run** |

Environment variables passed to `run`:

| Variable | Meaning |
|---|---|
| `RAKSHA_INPUT` / `RAKSHA_OUTPUT` | same paths as `{input}` / `{output}` |
| `RAKSHA_SECRET` | a per-release secret. Use it to key pseudonyms and date shifts. **Never write it anywhere.** |
| `RAKSHA_CPUS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, … | set to the CPU budget |
| `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` | model hubs must use local files |
| `LD_LIBRARY_PATH`, `JAVA_HOME`, `SSL_CERT_FILE`, `SSL_CERT_DIR` | passed through from the evaluation machine if set (runtime loaders only); no other host variable reaches your process |

## 3. Input

A directory tree of heterogeneous exports: `.csv`, `.tsv`, `.json` (nested JSON and FHIR R4
Bundles), `.txt`, and files you may not support (`.xml`, `.pdf`, `.jpg`, malformed JSON,
invalid UTF-8, zero-byte files, a 1,500-deep JSON). Encodings include UTF-8,
UTF-8 with BOM, UTF-16 and cp1252. Expect filenames containing PII.

## 4. Output layout

```
{output}/
  sanitized/       the research release: a mirror of the input tree
  report.json      REQUIRED: processing report (section 5)
  records.jsonl    REQUIRED for identity-resolution credit (section 6)
  logs/            optional: scanned for PII
  quarantine/      optional: NOT part of the release and NOT scanned
```

Rules for `sanitized/`:

* Keep each file at the **same relative path**. If a filename itself contains PII, rename
  the file and declare the mapping in `report.json` (`input_sha256` → `output`).
* Keep the format: CSV stays CSV with the same delimiter and header (rename a header
  only if it contains PII), JSON stays JSON with the same structure and value types,
  and FHIR stays a valid R4 Bundle whose references resolve.
* Write text as **UTF-8** (a BOM is allowed), whatever the input encoding was.
* Never copy a file you could not process into `sanitized/`. Quarantine it instead.

## 5. `report.json`

```json
{
  "schema": "raksha-report/1",
  "files": [
    {"input_sha256": "9f2c…", "output": "sanitized/discharge/doc_0007.txt", "status": "sanitized"},
    {"input_sha256": "51aa…", "output": null, "status": "quarantined", "reason": "unsupported_format"}
  ],
  "counts": {
    "files_total": 817, "files_sanitized": 809, "files_quarantined": 8,
    "records_processed": 5756, "identifiers_detected": 21950, "records_linked": 5690,
    "records_generalized": 2100, "records_suppressed": 3, "records_quarantined": 0
  },
  "entities": {"PATIENT_NAME": 6600, "PHONE": 1540},
  "timing": {"seconds": 41.2},
  "resources": {"peak_rss_mb": 380.5}
}
```

* `files` must list **every input file**, identified by the SHA-256 of its bytes (never by
  its name, which may itself be PII). `status` is one of `sanitized`, `quarantined`
  or `suppressed`.
* The `counts` are cross-checked against what you actually exported. A report that
  claims more than it delivered loses report-quality points.
* The report is part of the release: it is scanned for PII like everything else.

## 6. `records.jsonl`

One JSON object per line, one line per patient-bearing record you exported:

```json
{"file": "sanitized/registration/sanjeevani_registration.csv", "loc": "row:12", "patient": "PSN-7Q2K9D"}
{"file": "sanitized/opd/sanjeevani_opd_2026_10.json", "loc": "/visits/3", "patient": "PSN-7Q2K9D"}
{"file": "sanitized/discharge/doc_0007.txt", "loc": "doc", "patient": "PSN-7Q2K9D"}
{"file": "sanitized/registration/arogya_legacy_export.csv", "loc": "row:40", "out": "row:39", "patient": "PSN-11XQ0A", "status": "generalized"}
```

| Field | Meaning |
|---|---|
| `file` | output path, relative to `{output}` |
| `loc` | **input** locator of the record: `row:N` for CSV/TSV (0-based, header excluded); an RFC 6901 JSON pointer for JSON (for example `/visits/3`, `/patients/12`); `doc` for a whole document (text note, FHIR Bundle, single-object JSON) |
| `out` | output locator, only if it differs from `loc` (for example after suppressing rows) |
| `patient` | your pseudonym for the patient, or `null` when you deliberately do not link the record |
| `status` | optional: `sanitized`, `generalized` or `suppressed` |

How it is used:

* **Identity resolution** compares your pseudonyms with the hidden truth: pairwise F0.5
  (false merges cost more than missed links), B-cubed, and the language, fragmented and
  homonym traps. A record you leave unlinked when the evidence is insufficient costs
  nothing. Linking it to the wrong patient is a false merge.
* **Consistency:** the `patient` value must actually appear inside that exported record
  (for example in the `patient_ref` column or a `Patient:` header line of a note).
  Claims that are not in the data earn no consistency credit, and the attacker
  does not see them.
* The evaluator matches each of its records to the **longest** `loc` you report for that
  file. `doc` covers the whole file.

## 7. Behaviour that is scored

* **Determinism:** the same input and the same `RAKSHA_SECRET` must produce byte-identical
  `sanitized/` and `records.jsonl`. The evaluator runs you twice.
* **Unlinkability across releases:** with a *different* `RAKSHA_SECRET`, pseudonyms and
  date shifts should change. The evaluator runs you a third time with another secret.
* **Exit code:** `0` means the release is complete. Exiting `0` while `report.json` is
  missing or input files were silently dropped triggers the *false success* penalty.
* **Side channels:** stdout, stderr, `logs/`, `report.json`, `records.jsonl`, output file
  names, `TMPDIR` and `HOME` are all scanned for direct identifiers and full patient names.

## 8. Self-check before you submit

In your repository, with `dev/`, `validate_output.py` and `check_dev.py` from this kit copied in:

```bash
RAKSHA_SECRET=practice python main.py --input dev/input --output my_output   # your system
python3 validate_output.py --input dev/input --output my_output              # must print CONTRACT OK
python3 check_dev.py --output my_output                                      # leaks, medical values, linking
```

The hidden datasets come from the same generator with a secret seed, committed before
the event ([FAIRNESS.md](FAIRNESS.md)).
