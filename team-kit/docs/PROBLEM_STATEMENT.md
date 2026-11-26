# Track 3: "Secret Wards"

**Domain:** Privacy Engineering, Multilingual Information Extraction, Record Linkage & Data Security

**Environment:** A synthetic Indian hospital records dump (English, Hindi & Hinglish) from 4 hospital systems, provided by the organizers, plus a hidden attacker that hunts for patients in your output. No real patient data is used anywhere in this track.

*What happens in the ward stays in the ward.*

> The practice dataset, the format checker, the self-check and a starter are in this kit. New here? Read [START_HERE.md](../START_HERE.md) first.

---

## 1. Mission Brief

Hospitals in Yugaantar Pradesh are merging years of patient records into one research database for public-health studies. What arrives is chaos: registration exports with shifted columns, legacy CSVs in old encodings, nested JSON, FHIR bundles, discharge summaries, prescriptions and nursing notes that jump between English, Devanagari Hindi and Hinglish in the same sentence.

The same patient shows up as "Mohammad Arif" in a registration file, "मोहम्मद आरिफ" in a Hindi prescription, "Md. Arif" in a nursing note and "Arif sahab ka BP 150/90" in an OPD record. Each copy has a different phone format, a half-written address and a different hospital ID. Names also hide inside JSON keys, file names and file attachments.

Your challenge is to build an **offline, CPU-only, LLM-free privacy firewall** that:

- removes every piece of personal information,
- keeps every medically useful value exactly intact,
- recognizes the same patient across languages, files and hospitals without merging different people, and
- leaks nothing: not in outputs, logs, temp files or error messages.

Removing names is the easy part. The real test is whether an attacker holding a voter list who knows *"a 47-year-old woman from a small village was admitted for 9 days with dengue"* can still find her in your output. After you submit, our automated attacker tries exactly that. Your job is to make it fail.

A practice dataset with full answers is in [`dev/`](../dev).

## 2. Core Challenge Objectives

- **The Language Trap:** Detect patients across English, Hindi and Hinglish: names in any order (surname first, initials, honorifics like ji, sahab, didi), transliteration variants (Mohammad / Mohd / Md. / मोहम्मद), relatives via S/o, D/o, W/o, and Indian IDs (Aadhaar-like, ABHA, UHID / MRN, insurance IDs, PAN) and phone numbers in every format.
- **The Meaning Trap:** "C/O Ramesh" (care of a relative) is not "C/O fever" (complaint of). "Dr. Ramesh" stays; relative "Ramesh" goes. "Ramipril 5 mg", "Dolo 650 BD x 5 days" and "1-0-1" are doses, not phone numbers or IDs. "Parkinson's disease" is not a person.
- **The Fragmented Identity Trap:** Give every real patient one stable pseudonym across all records, languages and hospitals, even when a note only says "Meera, W/o Rajan". Never merge two different people who share a name. When evidence is too weak, don't link.
- **The Re-identification Trap:** Quasi-identifiers (age, village, PIN code, exact dates, length of stay, rare diagnoses) can still single someone out. Decide what to generalize, shift or suppress, and justify the privacy-vs-utility trade-off.
- **The Clinical Integrity Trap:** Medicines, doses, frequencies, vitals, lab values with units, diagnoses and procedures must survive exactly. If you shift dates, a 9-day stay must still be 9 days. Age bands must contain the real age.
- **The Hidden Leakage Trap:** Clean JSON keys, CSV headers, file names, metadata and attachments. Quarantine any file you cannot safely process instead of passing it through half-cleaned.

## 3. Deliverables & System Architecture

Your submission is a **public GitHub repository** with a runnable pipeline, a **README.md**, and a **2-page Project Brief PDF** ([how to write it](PROJECT_BRIEF.md)) covering:

- **Ingestion:** Reads CSV, TSV, JSON, FHIR R4 and text notes in different encodings, including broken, truncated and unsupported files.
- **Detection Engine:** How personal data is found in structured columns and free text across three scripts: rules, gazetteers, transliteration, classical ML, and how they are combined.
- **Linkage & Pseudonymization:** How records of the same patient are clustered (blocking, fuzzy and phonetic matching, cross-script comparison) and how stable, non-reversible pseudonyms are issued (keyed HMAC, not plain hashing).
- **Privacy Layer:** How quasi-identifiers are handled (per-patient date shifting, age banding, location generalization, rare-value suppression) and your measured re-identification risk.
- **Security Design:** Encryption of raw and intermediate data at rest, keys kept away from data, PII-free logging and a quarantine design. Assume your server will be breached one day.
- **README & 2-Page Project Brief (PDF):** Setup steps, architecture diagram, USP, privacy-utility trade-off analysis, and known limitations.

> **Note on Innovation:** Wrapping an off-the-shelf PII tool with default settings will score poorly. These tools miss Hindi and Hinglish, break on Indian name structures, and do nothing against linkage attacks. Deleting everything scores about 20/100, and copying data unchanged scores below zero. We reward cross-script identity matching, smart quasi-identifier handling, measurable privacy and systems that still work on formats they have never seen.

## 4. Submission Format

### Step 1: Add `raksha.toml` at the root of your repo

It tells us how to run your system:

```toml
[submission]
name  = "your-team-name"
setup = "pip install -r requirements.txt"                    # run once, internet allowed
run   = "python main.py --input {input} --output {output}"   # run with NO internet
```

We replace `{input}` with the hidden data folder and `{output}` with an empty folder. Your secret key arrives in the environment variable `RAKSHA_SECRET`. Use it for pseudonyms and date shifts, and never write it anywhere.

### Step 2: Your system must create these inside `{output}`

```
output/
├── sanitized/       ← cleaned files: same folders, names and formats as the input
├── report.json      ← what you processed
└── records.jsonl    ← which record belongs to which fake patient ID
```

**① `sanitized/`**

- `input/registration/hospital.csv` becomes `output/sanitized/registration/hospital.csv`, with the same columns.
- CSV stays CSV, JSON stays JSON, FHIR stays valid FHIR R4. Save everything as UTF-8.
- If a file name itself contains personal data, rename it and record the new name in the report.
- Never copy a file you could not process. Mark it quarantined instead.

**② `report.json`**: every input file (identified by its SHA-256 hash, never its name), plus totals:

```json
{
  "files": [
    {"input_sha256": "9f2c…", "output": "sanitized/discharge/note1.txt", "status": "sanitized"},
    {"input_sha256": "51aa…", "output": null, "status": "quarantined", "reason": "unsupported format"}
  ],
  "counts": {"files_total": 817, "files_sanitized": 809, "files_quarantined": 8,
             "records_processed": 5756, "identifiers_detected": 21950, "records_linked": 5690,
             "records_generalized": 2100, "records_suppressed": 3, "records_quarantined": 0},
  "timing": {"seconds": 41.2},
  "resources": {"peak_rss_mb": 380}
}
```

The SHA-256 is one line of Python: `hashlib.sha256(open(path, "rb").read()).hexdigest()`. Report numbers must be true; we cross-check them.

**③ `records.jsonl`**: one line per patient record, with the fake ID you assigned:

```json
{"file": "sanitized/registration/hospital.csv", "loc": "row:12", "patient": "PSN-7Q2K9D"}
{"file": "sanitized/opd/visits.json", "loc": "/visits/3", "patient": "PSN-7Q2K9D"}
{"file": "sanitized/discharge/note1.txt", "loc": "doc", "patient": "PSN-7Q2K9D"}
```

| Record type | `loc` value |
|---|---|
| CSV / TSV row | `row:N` (first data row after the header is `row:0`) |
| JSON record | its path, e.g. `/visits/3` |
| Text note / FHIR file | `doc` (the whole file) |

- The same patient gets the same ID in every file, and that ID must also appear inside the cleaned record.
- Not sure who the patient is? Write `"patient": null`. A wrong link costs more than no link.

Full details: [SPEC.md](SPEC.md).

### Step 3: Check before submitting

```bash
python3 validate_output.py --input dev/input --output my_output/    # must print CONTRACT OK
python3 check_submission.py --repo path/to/your-repo --run          # must print READY TO SUBMIT
```

### Step 4: Submit

Submit your **GitHub repo link** and **2-page Project Brief PDF** before the deadline. We record your last commit at the deadline; later commits are ignored.

**Minimal repo layout**

```
your-repo/
├── raksha.toml
├── requirements.txt
├── README.md
├── config/policy.yaml    ← your privacy rules
└── main.py               ← plus the rest of your code
```

## 5. Prerequisites & Recommended Libraries

**Core Libraries**

- `regex`, `phonenumbers`, `dateparser`: Indian phones, dates and ID patterns
- `indic-transliteration` / `indic-nlp-library`: Devanagari ↔ Latin transliteration and normalization
- `rapidfuzz`, `jellyfish`: fuzzy and phonetic matching
- `sklearn-crfsuite` / spaCy (rule-based Matcher, small non-LLM pipelines): classical NER
- `splink` / `recordlinkage`: probabilistic record linkage (Fellegi–Sunter)
- `fhir.resources`, `pydantic`, `jsonschema`: valid FHIR R4 and JSON output
- `cryptography`: AES-GCM / Fernet encryption, HMAC keyed pseudonyms
- `anonymeter`, `pycanon`: measuring re-identification risk, k-anonymity and l-diversity
- `Faker` (en_IN, hi_IN): generating extra test data of your own

**Key Concepts to Research**

- **Indian Name Structures:** patronymics, initials, honorifics, cross-script spellings and nicknames
- **Quasi-identifiers & Linkage Attacks:** k-anonymity, l-diversity, date shifting, generalization hierarchies
- **Record Linkage:** blocking, Fellegi–Sunter, clustering without transitive over-merging
- **De-identification Standards:** HIPAA Safe Harbor's 18 identifiers, India's DPDP Act 2023, ABDM health data guidelines
- **Secure Data Handling:** envelope encryption, HMAC vs plain hashing, canary tokens, log hygiene

## 6. Evaluation & Scoring

**Automated Scoring (100 Points):** Your system runs on 3 hidden datasets, then our automated attacker runs on your output.

| # | Criteria | Points | What is measured |
|---|---|---:|---|
| 1 | Privacy Against Attacks | 25 | How few patients the attacker can re-identify using a voter-list-style register and known facts (visit dates, rare diseases, length of stay) |
| 2 | Personal Data Detection | 20 | Personal data removed across English, Hindi and Hinglish, in content and hidden places; doctors, doses and medical terms kept |
| 3 | Medical Data Preservation | 20 | Medicines, doses, vitals, lab values, diagnoses, exact hospital-stay lengths, truthful age bands |
| 4 | Patient Identity Consistency | 15 | Same patient linked across files and languages; different people never merged |
| 5 | Output Quality & Validity | 10 | Valid CSV / JSON / FHIR, honest report, no leaks in logs or temp files, proper quarantine |
| 6 | Speed & Reliability | 10 | Speed, memory, no crashes, identical output on repeat runs |

**Penalties:** Points are deducted for every real ID or canary leaked, raw files copied out, files skipped silently, and modifying the input.

**Ties:** A team ranks above another only if it scores more than 1 point higher on every hidden dataset.

Every formula: [SCORING.md](SCORING.md).

> **Evaluation Principle:** Build a system that protects patient privacy without compromising the accuracy, integrity or medical usefulness of healthcare data.

## 7. Ground Rules

- **No LLMs:** No GPT, Llama, Gemini, Claude, Mistral or any other large language model, whether hosted, local or distilled. No generative models, and no pretrained transformers above 50M parameters. Rules, gazetteers, CRFs, classical ML and small models you train yourself are allowed; declare any model in your README.
- **Fully Offline, CPU-only:** Evaluation runs on organizer machines with no internet, 2 CPUs, 4 GB RAM and 15 minutes per run. Any network call during the run is blocked and is grounds for disqualification.
- **Synthetic Data Only:** All data comes from the organizers or is generated by your team. Real patient records are strictly prohibited.
- **No Hardcoding:** Hidden data uses new patients, and at least one hidden dataset has names, labels and formats never seen in practice data. Memorized names or files will fail.
- **Zero Leaks:** Hidden data contains planted canary PII. A canary found anywhere (outputs, logs, temp files, error messages or reports) counts as a leak and is heavily penalized.
- **Fail Safe:** Never silently skip files or export raw files as "cleaned". Exiting successfully with missing files is penalized.
- **Reproducible:** The same input and the same `RAKSHA_SECRET` must give exactly the same output. A different secret must give different pseudonyms and date shifts.
- **Original Work:** Your repository must be created during the hackathon. Open-source libraries are allowed, but your core pipeline, linkage logic and privacy layer must be built during the event.
