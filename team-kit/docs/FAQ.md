# FAQ

Short answers to the questions teams ask most. Longer answers are linked.

## Submitting

**What exactly do we submit?**
A **public** GitHub repository link and a **2-page Project Brief PDF** ([what to put in it](PROJECT_BRIEF.md)).
We record your **last commit at the deadline**, and later commits are ignored.

**What goes in the 2-page brief?**
Your architecture diagram, how each part works, your USP, the privacy-utility trade-off with
measured numbers, the security design and known limitations. A fill-in template is in
[`brief/`](../brief/PROJECT_BRIEF_TEMPLATE.md).

**Which file tells you how to run our code?**
`raksha.toml` at the root of the repository:

```toml
[submission]
name  = "your-team-name"
setup = "pip install -r requirements.txt"                    # run once, internet allowed
run   = "python main.py --input {input} --output {output}"   # run with NO internet
```

We replace `{input}` with the hidden data folder and `{output}` with an empty folder.
`setup` may take up to 30 minutes. A private `.venv` is created for you before `setup`,
so `pip install` goes into it. Details: [SPEC.md §1](SPEC.md#1-repository).

**Can we use another language (Java, Go, Rust…)?**
Yes, as long as `setup` can build it on Linux and `run` works offline.

**Where is the secret key?**
In the environment variable `RAKSHA_SECRET`. Use it to make your fake IDs and date
shifts, and never print or save it.

## Output

**What must the output folder contain?**

```
output/
├── sanitized/       cleaned files: same folders, names and formats as the input
├── report.json      every input file (by SHA-256) and honest totals
└── records.jsonl    which record belongs to which fake patient ID
```

**A file name contains a name or a phone number. What do I do?**
Rename the file in `sanitized/` and record its new path in `report.json` under that
file's `input_sha256`.

**I can't read a file (PDF, image, corrupt). What do I do?**
Don't copy it. Put `"status": "quarantined"` and a `reason` in `report.json`. You may
store it in `output/quarantine/`, which is not scanned and not part of the release.

**What is `loc` in `records.jsonl`?**

| Record type | `loc` |
|---|---|
| CSV / TSV row | `row:N` (the first row after the header is `row:0`) |
| JSON record | its JSON pointer, e.g. `/visits/3` |
| text note, FHIR bundle, single-object JSON | `doc` |

**What if I'm not sure which patient a record belongs to?**
Write `"patient": null`. A missing link costs little, and a wrong link costs more.

**Does the fake ID have to be inside the cleaned file too?**
Yes. It must appear inside that record (e.g. a `patient_ref` column or a `Patient:` line),
otherwise it earns no consistency credit.

**Can I change the folder structure or the columns?**
No. Keep the same relative paths, the same CSV delimiter and header, and the same JSON
structure and value types. You may only rename a header or key if it **contains** PII.

**Which encoding should the output use?**
UTF-8 (a BOM is fine), whatever the input encoding was.

## Checking

**How do I know my format is right?**
`python3 validate_output.py --input dev/input --output my_output` must print `CONTRACT OK`.

**How do I know my repo is ready to submit?**
`python3 check_submission.py --repo <your-repo> --run` checks `raksha.toml`, README, the PDF and
your requirements, then runs your system 3 times: contract, identical repeat, a different
secret, the secret never written, the input untouched. It must print `READY TO SUBMIT`.

**How do I know if I'm doing well?**
`python3 check_dev.py --output my_output` compares you with the practice answer key:
leaks by type, language and hiding place, canaries, medical values kept, linking
quality and raw copies. It's a guide, not the official score.

**Will the hidden data look like the practice data?**
Similar, but with **new patients**, and at least one hidden dataset has names, labels and
formats that never appear in practice data. Memorising practice names or files will fail.

## Rules

**Can we use spaCy / scikit-learn / rapidfuzz / cryptography…?**
Yes. Rules, gazetteers, CRFs, classical ML and small models you train yourself are all
fine. **Not allowed:** any LLM (hosted, local or distilled), generative models, or
pretrained transformers above 50M parameters. Declare every model in your README.

**What machine will run our code?**
Linux, 2 CPUs, 4 GB RAM, no internet, no GPU, with the per-run time limit from the problem
statement. Your code sees only its own repository, a read-only copy of the input and
its output folder ([SANDBOX.md](SANDBOX.md)).

**What happens if our code tries to use the internet?**
The call fails because there is no network. The attempt is logged and the judges review
it; the statement says it is grounds for disqualification.

**Will you run our code more than once?**
Yes: on 3 hidden datasets, once more with the same secret (the output must be
byte-identical) and once with a different secret (fake IDs and dates must change).

**How are ties decided?**
A team ranks above another only if it scores more than 1 point higher on **every** hidden
dataset ([FAIRNESS.md](FAIRNESS.md)).

**Is the ranking fair?**
The hidden data's seed is committed (hashed) before the event, every team runs on the
same data on identical isolated hardware, and the leaderboard is computed blind
([FAIRNESS.md](FAIRNESS.md)).
