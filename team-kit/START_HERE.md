# Start here: Secret Wards in plain words

New to privacy engineering? Good. This page explains everything you need, step by step.
Read it once from top to bottom (about 15 minutes) and you will know exactly what to build.

---

## 1. The game in 30 seconds

You get a folder of **fake hospital records** from 4 hospitals. They are messy: English,
Hindi and Hinglish mixed together, broken files, odd formats.

Your program must produce a **clean copy** of that folder where:

| ✅ Must happen | ❌ Must never happen |
|---|---|
| every name, phone, address, ID number is gone | a real patient can still be found |
| every medicine, dose, lab value and diagnosis is **exactly** the same | medical values are changed or lost |
| the same patient gets the **same fake ID** in every file | two different people get the same fake ID |
| files you cannot clean are put aside ("quarantined") | a dirty file is copied out as if it were clean |

Then **our attacker** gets your clean folder plus a voter list, and tries to find real
people in it. If it can't, you win points.

There's no internet, no LLMs and no GPU. It runs on a normal 2-CPU machine.

---

## 2. Your first 5 minutes

```bash
git clone https://github.com/kartikeyajay2006/Secret-Wards.git
cd Secret-Wards

# 1. run the starter on the practice data
RAKSHA_SECRET=practice python3 starter/main.py --input dev/input --output my_output

# 2. is the FORMAT right?
python3 validate_output.py --input dev/input --output my_output
#    -> CONTRACT OK

# 3. how GOOD is it? (uses the answer key)
python3 check_dev.py --output my_output --show 10
```

The starter passes the format check but leaks almost everything, which is expected. It
scores about **8 / 100** officially. Your job is to push that number up. Re-run step 3
after every change and watch the leak numbers fall.

### Then make your own repository

The kit is for reading and testing. Your **submission** is your own new repo, created
during the hackathon. Keep the two folders side by side:

```
hackathon/
├── Secret-Wards/     ← this kit (read and test with it)
└── your-repo/        ← your submission
```

```bash
cd ..
git clone https://github.com/<your-team>/<your-repo>.git
cp -r Secret-Wards/starter/* your-repo/        # raksha.toml, main.py, requirements.txt, config/
cd your-repo
RAKSHA_SECRET=practice python3 main.py --input ../Secret-Wards/dev/input --output out
python3 ../Secret-Wards/validate_output.py --input ../Secret-Wards/dev/input --output out
python3 ../Secret-Wards/check_dev.py --output out
python3 ../Secret-Wards/check_submission.py --repo . --run
```

> On Windows, set the secret with `set RAKSHA_SECRET=practice` (cmd) or
> `$env:RAKSHA_SECRET="practice"` (PowerShell) before step 1.

---

## 3. A tour of the practice data (`dev/input/`)

200 files, 48 patients, 4 hospitals. Open a few of them now; they explain the challenge
better than any document.

| Folder | What's inside | What's tricky |
|---|---|---|
| `registration/` | patient lists: CSV, TSV (UTF-16!), JSON, a legacy cp1252 export | the same person in several hospitals with different IDs; a duplicate file `sanjeevani_registration (1).csv` |
| `opd/` | outpatient visits as nested JSON | PII hidden in **metadata**, e.g. `"source_path": "D:\\HIS\\exports\\opd\\Anita_Sharma_010565\\..."` |
| `prescriptions/` | short notes, many in **Hindi** | `नाम: मोहम्मद शाहिद`: the name is in Devanagari; `650mg 1-1-1 x 5 days` is a dose, keep it |
| `discharge/` | discharge summaries | admission/discharge dates: the stay length must stay exact |
| `notes/` | nursing notes in Hinglish | `Shahid sahab ka BP 117/82` and `Mohd. Shahid` are the same man; `S/o Zubair` is a relative (remove); `K/C/O addison's disease` is a medical history (keep) |
| `lab/` | lab reports, WhatsApp forwards | **file names contain phone numbers** (`7148988804_report_0047.json`); `Asha ji 48 Y / F` in a forward |
| `fhir/` | FHIR R4 Bundles (JSON) | must stay valid FHIR; IDs hide in `meta.source`, `identifier`, references |
| `billing/` | insurance claims | insurance IDs, PAN, MRNs |
| `misc/` | the nasty ones: PDF, JPG, XML, a corrupt file, an empty file, a truncated JSON, a 1,500-level-deep JSON, a base64 "scanned" form, helpdesk tickets | decide: clean it or quarantine it; **never** copy it raw |
| `clean/` | protocols, a drug formulary, lab ranges: **no patient data** | don't destroy these; they are pure medical value |

Here is one real row from `registration/sanjeevani_registration.csv`. Everything in
**bold** is personal data:

> **SNJ/26/064127**, **Mahesh Chauhan**, M, **48**, **12/04/1977**, S/o, **Naresh Chauhan**,
> "C/O **Naresh Chauhan**, **H.No. 364**, **Ward 20**, **Mohalla Raja Bazar**, **near Pani Tanki**, Tehsil Lalganj, Distt. Rae Bareli",
> **Durgamau Kalan**, Lalganj, Rae Bareli, **229073**, **+91 72864 90658**, **397205839628**, **91-7938-3729-8403**, 30/06/2025

The age (48), PIN, village and dates are **quasi-identifiers**. Together they can single
someone out, so you generalise them (age 45–49, village → district, shifted dates)
rather than just deleting them.

---

## 4. The answer key (`dev/truth/truth.json`)

For practice only: this tells you exactly what's inside every file. The hidden datasets
have their own answer key that you will never see.

```text
truth.json
├── files                       one entry per input file
│   └── "registration/sanjeevani_registration.csv"
│       ├── sha256, encoding, delimiter, format
│       ├── expect              "sanitize" or "either" (either = fine to quarantine)
│       └── units               one per record:  "row:0", "/visits/3", "doc"
│           ├── patient         the TRUE patient (PT00004)  → compare with your fake IDs
│           ├── link            "required" (must be linked) / "none" / "ambiguous"
│           ├── entities        every piece of personal data in that record:
│           │     type    PATIENT_NAME, PHONE, AADHAAR, ABHA_NUMBER, MRN, PAN, DOB, VILLAGE, PIN, ...
│           │     surface the exact text, e.g. "Naresh Chauhan"
│           │     script  latin / deva (Hindi) / hinglish
│           │     channel content / filename / header / key / metadata / base64  ← where it hides
│           │     role    patient or relative
│           ├── preserve        medical values that must survive exactly
│           ├── dates           real dates (shift them, but keep the gaps)
│           └── fields          real age, gender, village… (your bands must contain these)
├── patients                    48 people, their hospitals and IDs
├── traps                       which patients are the language / fragmented / meaning /
│                               re-identification / same-name (homonym) traps
└── canaries                    4 planted fake identities (find them all!)
```

`check_dev.py` reads this file for you. Open it yourself when you want to know *why*
something counts as a leak.

---

## 5. The attacker's files (`dev/attacker/`)

This is what the attacker knows. Study it to understand what to protect.

| File | What it is |
|---|---|
| `registry.csv` | a voter-list-style register of the whole area: name, relative, age, house, village, PIN, phone, last 4 Aadhaar digits. It contains patients **and** people who never visited a hospital |
| `known_facts.jsonl` | gossip-level knowledge about some people: "visited Sanjeevani on 2026-10-06 with diabetes" |

The attacker joins these with your output: *"female, 45–49, from this village, admitted
on that date, dengue"* → if only one record fits, that patient is found. The attacks are
listed in [docs/ATTACKS.md](docs/ATTACKS.md).

**How to beat it:** shift dates per patient (secretly, with `RAKSHA_SECRET`), use age
bands, generalise villages to tehsil/district, and suppress very rare combinations.

---

## 6. What earns points

| Points | Area | You get them when… |
|---:|---|---|
| 25 | 🛡️ Privacy against attacks | the attacker finds few patients in your output |
| 20 | 🔎 Personal data detection | you remove PII in all 3 scripts and in hidden places, **without** removing doctors, doses or diseases |
| 20 | 💊 Medical data kept | medicines, doses, vitals, labs, diagnoses, stay lengths and true age bands survive |
| 15 | 🔗 Same patient, same ID | your fake IDs group records exactly like the truth (wrong merges hurt more than missed links) |
| 10 | 📦 Output quality | valid CSV/JSON/FHIR, an honest report, nothing leaked in logs or temp files |
| 10 | ⚡ Speed & reliability | fast, low memory, no crash, identical output on a repeat run |

**Penalties** (subtracted at the end):

| Mistake | Cost |
|---|---|
| a real ID or full name leaked | −1 each (max −25) |
| a canary leaked (anywhere, even in a log or error message) | −3 each (max −15) |
| a broken/unsupported file copied out raw | −5 each (max −20) |
| exit "success" but files or the report are missing | −10 |
| your program changes the input folder | −5 |

For reference: deleting everything scores about **20**, and copying everything scores
**below 0**. Every formula is in [docs/SCORING.md](docs/SCORING.md).

---

## 7. A build plan that works

Do it in this order. Each step is measurable with `check_dev.py`.

1. **Format first.** Start from `starter/`: it already writes `sanitized/`,
   `report.json` and `records.jsonl` correctly. Keep `validate_output.py` green.
2. **Structured columns.** In CSV/TSV/JSON, decide per column or key: name, phone,
   address, ID → remove or replace. Don't trust exact column names; on hidden data
   they change (`Patient's Name`, `Contact#`, `Gram/Mohalla`).
3. **IDs and phones everywhere.** Regexes for Aadhaar (12 digits), ABHA (14), PAN,
   UHID/MRN styles, Indian phones (`+91 72864 90658`, `072864-90658`…). Leave doses
   (`650mg`, `1-0-1`, `BD x 5 days`) and lab values (`245 mg/dL`) alone.
4. **Names in free text.** Labels (`Name:`, `नाम:`, `Pt.`), honorifics (`ji`, `sahab`,
   `didi`, `श्री`), relatives (`S/o`, `W/o`, `C/O <name>`), a name list in Latin and
   Devanagari, and transliteration (Mohammad ≈ Mohd ≈ Md. ≈ मोहम्मद). Keep `Dr. <name>`.
5. **Hidden places.** File names, CSV headers, JSON keys, metadata fields, base64
   attachments.
6. **Linking.** Gather every record's clues (names in both scripts, phone, IDs, age,
   village). Link records that share strong clues and give each cluster one HMAC fake
   ID. Write that ID **inside** the cleaned record and in `records.jsonl`. When unsure,
   write `null`.
7. **Quasi-identifiers.** Per-patient date shift (same shift for all of one patient's
   dates), 5-year age bands, village → district, suppress rare values.
8. **Security, README and the brief.** Encrypt intermediate data at rest, keep keys out of the
   data folder, log only counts, document everything, and write the 2-page Project Brief
   PDF with your measured numbers ([docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md)).

---

## 8. Checklist before you submit

- [ ] `python3 check_submission.py --repo <your-repo> --run` prints **READY TO SUBMIT**
- [ ] `raksha.toml` is at the **root** of your repo
- [ ] `setup` installs everything; `run` needs **no internet**
- [ ] `validate_output.py` prints **CONTRACT OK**
- [ ] running twice with the same `RAKSHA_SECRET` gives identical output; a different secret gives different fake IDs and dates
- [ ] nothing personal in stdout, stderr, logs, temp files or `report.json`
- [ ] your program never writes `RAKSHA_SECRET` anywhere
- [ ] it finishes within the time limit on 2 CPUs and 4 GB RAM
- [ ] no LLMs and no model above 50M parameters; any model you use is declared in the README
- [ ] the README has setup, an architecture diagram, how each part works, the security design, and known limitations
- [ ] the **2-page Project Brief PDF** is ready ([docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md), template in [brief/](brief/)) with your measured numbers from `check_dev.py`
- [ ] you **tested on data you didn't tune on**: rename columns, swap in new names, change date formats, then run `check_dev.py` again

---

## 9. Where to read more

| Question | Document |
|---|---|
| the official problem statement | [docs/PROBLEM_STATEMENT.md](docs/PROBLEM_STATEMENT.md) |
| the exact output format | [docs/SPEC.md](docs/SPEC.md) |
| every scoring formula | [docs/SCORING.md](docs/SCORING.md) |
| what the attacker does | [docs/ATTACKS.md](docs/ATTACKS.md) |
| how the data is built, canaries, the unseen-format round | [docs/DATASET.md](docs/DATASET.md) |
| what your code can and cannot do on our machine | [docs/SANDBOX.md](docs/SANDBOX.md) |
| how we keep the ranking fair | [docs/FAIRNESS.md](docs/FAIRNESS.md) |
| what goes in the 2-page Project Brief PDF | [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md) |
| quick answers | [docs/FAQ.md](docs/FAQ.md) |
