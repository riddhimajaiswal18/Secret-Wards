# The dataset

> Your practice copy is in [`dev/`](../dev). This page explains what every dataset contains,
> practice and hidden. New to this? Read [START_HERE.md](../START_HERE.md) first.

All data is **synthetic**: names, villages and identifiers are generated, and nothing
describes a real person. District and tehsil names are real public administrative areas.
The practice and hidden datasets come from the same generator with different seeds. The
hidden seed is committed (hashed) before the event ([FAIRNESS.md](FAIRNESS.md)), so the
hidden data is fixed in advance, identical for every team, and unknown to everyone.
The hidden datasets have **new patients** and are larger than the practice set.

## Layout

```
dev/input/                      what your system receives (read-only on event day)
  registration/                 4 hospital systems, 4 formats, 4 encodings, different date conventions
  opd/                          nested JSON per hospital and month, with export metadata
  discharge/                    English, Hindi (Devanagari) and fragmentary discharge notes
  notes/                        Hinglish nursing notes
  prescriptions/                English / Hinglish and Hindi OPD prescriptions
  fhir/                         FHIR R4 document Bundles
  lab/                          lab CSVs, JSON reports, WhatsApp forwards
  billing/                      insurance claims
  clean/                        documents with no PII at all (don't damage them)
  misc/                         hidden-leakage traps and malformed / unsupported files
dev/truth/truth.json            the answer key (practice only; never available on event day)
dev/attacker/registry.csv       voter-roll-style population register
dev/attacker/known_facts.jsonl  partial knowledge about some people (+ decoys)
dev/dataset_manifest.json       counts and SHA-256 hashes
```

## Four hospital systems, four ways of doing things

| System | Registration export | Encoding | Dates |
|---|---|---|---|
| Sanjeevani Multispeciality | CSV with full names, Aadhaar, ABHA, plus a duplicate copy of the file | UTF-8 with BOM | day first |
| Jeevan Jyoti Charitable | "Unicode text" TSV with Hindi headers and many Devanagari rows | **UTF-16** | day first |
| Arogya Seva Sadan | legacy CSV, split first/last name, ragged rows, multi-line notes | **cp1252** | **month first** |
| District Hospital Hardoi | nested JSON, an Aadhaar stored as a number under a misspelled key | UTF-8 | ISO |

Some patients appear at more than one hospital, and some re-register at the same hospital
with a new ID: the same person, different records.

## The traps (what each one tests)

| Trap | What you will find | Scored by |
|---|---|---|
| Language | one person written in Latin, Devanagari and Hinglish, sometimes with no ID at all | leak recall per script; linking across scripts |
| Meaning | relatives vs doctors with the same first name, "C/O <name>" vs "C/O <complaint>", wards, doses (`1-0-1`, `BD x 5 days`), disease eponyms | relative-name leaks vs doctor / complaint / dose values kept |
| Fragmented identity | a note that only says "<first name>, W/o <husband>" plus a date | linking through name + relative |
| Re-identification | very old patients, tiny villages, rare diseases and procedures, exact dates | the attack arena ([ATTACKS.md](ATTACKS.md)) |
| Clinical integrity | DOB, admission and discharge (real stay length), vitals, labs, doses, diagnoses | values kept, intervals kept, truthful age bands, research statistics |
| Hidden leakage | PII in JSON **keys**, a CSV **header**, **file names**, export **metadata**, FHIR narrative, base64 **attachments**, `\u`-escaped Devanagari | leak scan per hiding place |
| Robustness | a large bulk export, deeply nested JSON, truncated JSON, XML, PDF, JPEG, an empty file, invalid UTF-8, JSON behind a `.csv` extension | speed, memory, no crash, correct quarantine |

## The unseen-format round

At least one hidden dataset keeps the same traps but adds variation that **never appears
in the practice data**: names, field labels, identifier and date formats, and column
names you have not seen. What exactly changes stays sealed until the results. A solution
tuned only to the practice files loses a lot of points there. Build rules that understand
**context** ("this is a label for a name", "this column holds phone numbers") instead of
lists of exact strings.

## Canaries

Every dataset plants **canary identities**: names and numbers that exist nowhere else in
the data and in no name list. Only context-aware detection finds them. If one appears
anywhere in your release or side channels (logs, temp files, errors, report), that proves
a leak path and costs −3 each ([SCORING.md](SCORING.md)).

## Same name, different people

Some patients share **exactly the same name** with someone else who has a different
village, age and relative. Merging them is a false merge, which costs more than a missed link.

## The answer key (`truth.json`)

The scoring unit is a **record**: `row:N` (a CSV/TSV data row), a JSON pointer
(`/visits/3`), `doc` (a whole text or FHIR document), or a file-level place (`@file`
for metadata and keys, `@header`, `@filename`). Each record lists:

* `entities`: every piece of PII, with type, exact text, script (`latin`, `deva`,
  `hinglish`), hiding place (`channel`), and whether it is a critical direct identifier.
  Generic name parts such as *Devi*, *Kumar*, *Md.* and *ji* don't identify anyone on their own;
* `preserve`: medical and context values that must survive;
* `dates`: the true clinical dates (shift them, but keep the gaps);
* `fields`: true age, DOB, gender, village, district and PIN (your bands must contain them);
* `patient`, `link`, `cid`: who the record belongs to and whether it must be linked.

### When must two records be linked?

Only when the data itself connects them:

* a shared strong identifier (UHID, IPD no., Aadhaar, ABHA, phone, email, PAN, insurance
  ID) that belongs to that patient alone, **or**
* the same name plus a second clue (DOB, relative's name, or village + age ±1) whose
  combination is unique to that patient in the whole dataset.

Records with no such path are *ambiguous*: leaving them unlinked costs nothing, but
linking one to the wrong patient is a false merge. That is how "don't link when the
evidence is too weak" is measured.

## What the attacker knows

* `registry.csv`: everyone in the synthetic population (patients and many non-patients),
  with name, relative, gender, age, house, mohalla, village, tehsil, district and PIN, like
  an electoral roll. Some people also have a "leaked contacts" overlay: phone, email and
  the last 4 Aadhaar digits.
* `known_facts.jsonl`: for some people, a true visit date, the hospital, and sometimes
  the condition. Decoys (people who never visited) test whether your output reveals who
  was a patient at all.

On event day the attacker uses the hidden versions of these files. Your system never sees them.
