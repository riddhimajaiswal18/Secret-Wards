# Scoring: every formula, published before the event

All weights and thresholds live in [`scoring.toml`](../scoring.toml). Its SHA-256
is stamped on every scorecard, so a changed rule is visible. The six category weights
are the official ones from §6 of the problem statement, unchanged.

```
total = 100 × Σ weight_c × score_c  −  critical penalties        (not floored at 0)
```

| Category | Weight | Score in [0, 1] |
|---|---:|---|
| Multilingual PII detection & contextual intelligence | 20% | F2(contextual precision, recall) |
| Cross-document identity resolution | 15% | 0.4·F0.5 + 0.3·B³F1 + 0.1·language trap + 0.1·fragmented trap + 0.1·homonym separation |
| Adversarial privacy & re-identification resistance | 25% | (1 − attack risk) × min(1, utility / 0.40) |
| Clinical utility preservation | 20% | weighted mix of six parts (below) |
| Data integrity & secure export | 10% | weighted mix of seven parts (below) |
| CPU efficiency & reliability | 10% | weighted mix of four or five parts (below) |

## How leaks are counted (shared by several categories)

The scoring unit is a record: a CSV row, a JSON record pointer, a whole document, or a
file-level channel (`@file` metadata/keys, `@header`, `@filename`). For each PII mention
the ground truth stores its *keys*:

* **identifying name tokens** (generic tokens such as *Devi*, *Kumar*, *Md.*, *ji* do
  not identify anyone on their own);
* **digit identifiers** (Aadhaar, phone, ABHA, the digit core of UHID/IPD numbers),
  matched across any separators, in Devanagari digits, or as JSON numbers;
* **exact text** (email, ABHA address, PAN, insurance IDs, house/locality/landmark/village);
* **DOB** (any date format that resolves to the true birth date).

For each key `x` in a unit:

```
allowed  = occurrences of x in the input inside a preserve-probe
           ("Ramesh" inside "Dr. Ramesh reviewed the patient")
pii_occ  = occurrences of x in the input − allowed
leaked   = clamp(occurrences of x in the output − allowed, 0, pii_occ)
leak(x)  = leaked / pii_occ            mention leak = mean over its keys
```

Before counting, **both sides** are normalised (NFKC, Cyrillic/Greek homoglyphs folded,
zero-width characters removed, Indic digits → ASCII, Latin diacritics stripped,
casefolded). Hidden payloads (base64, hex, `\uXXXX`, HTML entities, %-encoding) are
decoded and appended. Disguising a name therefore does not hide it, and a doctor
called Ramesh does not turn a removed relative into a leak. If a record cannot be
located in the output (restructured JSON), any occurrence anywhere in that output
file counts as a leak.

## 1. Detection & contextual intelligence (20%)

* **Recall** = 0.5 × weighted macro-average of per-type recall + 0.5 × macro-average of
  per-script recall (`latin`, `deva`, `hinglish`). Type weights are in the config
  (Aadhaar/ABHA/phone/email/MRN/PAN/name 1.0, relative 0.8, DOB 0.7, house/locality
  0.6, landmark/village/PIN/masked-Aadhaar 0.5). Because of the macro averages,
  perfect phone detection cannot hide poor Devanagari name detection.
* **Contextual precision** = mean over the Challenge-2 trap groups of the share of
  non-PII that survives (`doctor`, `doctor-vs-relative`, `c/o-complaint`, `k/c/o`, `h/o`,
  `hospital-ward`, `dose`, `1-0-1`, `eponym`, `asha`) plus token retention on the clean
  documents.
* **Score** = F2 = 5PR / (4P + R). Recall counts more than precision, but
  redacting everything gives P ≈ 0 and therefore F2 ≈ 0.

## 2. Identity resolution (15%)

Input: your `records.jsonl` (see [SPEC.md](SPEC.md)). Ground-truth linkability is computed
from evidence present in the data ([DATASET.md](DATASET.md#linkability-is-computed-not-hand-labelled)).

* **Pairwise precision** = correct same-pseudonym pairs / all same-pseudonym pairs
  (ambiguous records included: a wrong link is a false merge).
* **Pairwise recall** = correctly linked pairs / linkable pairs (ambiguous records excluded).
* **F0.5** weights precision twice as heavily, because a wrong merge corrupts two
  patients' histories.
* **B-cubed F1** gives per-record cluster quality.
* **Trap scores**: pair recall inside the language-trap and fragmented-trap patients,
  plus the share of homonym pairs (same name, different people) that never share a
  pseudonym.
* If no record carries a pseudonym, the category scores **0** (homonym separation is
  not free).

## 3. Privacy attack arena (25%)

See [ATTACKS.md](ATTACKS.md) for the attacker. Each attack yields a risk; four of them are
expressed **relative to the same attack on the raw, unsanitised input**:

| Component | Weight | Risk value |
|---|---:|---|
| A1 direct exposure | 0.20 | share of patients with a surviving direct identifier or full name (anywhere, any channel) |
| A2/A3 record linkage | 0.20 | mean probability the registry attacker assigns to the true person, ÷ raw |
| A4 profile re-identification | 0.20 | share of patients confidently (≥ 0.5) re-identified from pooled cross-document evidence, ÷ raw |
| A5 targeted attack | 0.20 | success probability against people with known visit dates, after global-shift recovery, ÷ raw |
| A6 pseudonym inversion | 0.10 | share of pseudonymised patients whose pseudonym is reversible (only if pseudonyms exist) |
| A7 cross-release linkability | 0.10 | max(stable pseudonyms, stable date shifts) under a different `RAKSHA_SECRET` (only if comparable) |

```
risk        = Σ w_i · risk_i / Σ w_i        (over applicable components)
resistance  = 1 − risk
privacy     = resistance × min(1, utility_score / 0.40)
```

The **utility coupling**: privacy is only fully credited for a release that
keeps at least 40% of its clinical utility, so "delete everything" cannot collect the
heaviest category.

## 4. Clinical utility (20%)

| Part | Weight | Definition |
|---|---:|---|
| clinical probes | 0.35 | weighted share of preserve-probes still present (1.0 at the original field, 0.8 elsewhere in the record, 0 lost). Covers medication + dose, frequency (`1-0-1`), vitals, labs, diagnoses and ICD codes, complaints, history, procedures, doctor lines and wards. |
| temporal | 0.20 | 0.6 × interval preservation (for every pair of a patient's dated events, the output interval must equal the true interval: 1.0 exact, 0.5 at ±1 day) + 0.4 × length-of-stay preservation |
| generalization | 0.10 | structured age/DOB/village/district/PIN/gender fields: informative **and truthful**. Age: exact 1.0, ≤5-year band 0.9, ≤10 0.8, ≤20 0.6, wider 0.3. A band that excludes the real age scores 0 and is flagged. Village: kept 1.0, tehsil 0.8, district 0.7. PIN: 6 digits 1.0, true 3-digit prefix 0.7. DOB: exact 1.0, shifted ≤ 1 year 0.9, year only 0.8. |
| statistics | 0.15 | research reproducibility: 1 − TVD of the ICD-10 diagnosis distribution (× coverage), 1 − TVD of the length-of-stay histogram (× coverage), and per-test lab medians within 10% |
| token retention | 0.10 | multiset share of non-PII input tokens still present (dates, ages and PII tokens excluded). This is the over-redaction detector (Team A vs Team B). |
| record retention | 0.10 | share of records still locatable in the output (the over-suppression detector) |

## 5. Data integrity & secure export (10%)

| Part | Weight | Definition |
|---|---:|---|
| format validity | 0.15 | sanitised files parse in their original format and are UTF-8 |
| schema preservation | 0.20 | CSV: column count, header names (unless the header held PII), row count, row shape. JSON: key-path Jaccard + unchanged value types (declared generalisable paths exempt). Text: line-count ratio. |
| FHIR validity | 0.15 | structural R4 validator (`raksha_eval/scoring/fhir.py`): resource types, ids, required elements, value sets, date/dateTime/instant syntax, base64 attachments, every reference resolvable inside the Bundle |
| pseudonym consistency | 0.10 | share of `records.jsonl` claims whose pseudonym is actually present in that exported record |
| channel hygiene | 0.15 | seven side channels: `report.json`, `records.jsonl`, `logs/`, other output files, output file names, stdout/stderr, TMPDIR/HOME. Each is clean (1), has PII (0), or has leftover temp files without PII (0.5). |
| quarantine handling | 0.15 | 0.5 × malformed/unsupported files handled safely (quarantined, or exported without a raw copy) + 0.3 × (1 − silent-drop rate) + 0.2 × (1 − unprocessed-copy rate) |
| report quality | 0.10 | 0.5 × completeness ([SPEC §5](SPEC.md#5-reportjson) fields, timing, resources, every file listed) + 0.5 × honesty (`files_total`, `files_sanitized`, `files_quarantined` equal what was really exported) |

## 6. CPU efficiency & reliability (10%)

Absolute thresholds per dataset profile (identical for every team):

| Part | Weight | Definition |
|---|---:|---|
| reliability | 0.30 | exit 0 → 1.0; non-zero exit → 0.3; timeout / memory kill / launch error → 0 |
| wall time | 0.30 | 1 below `time_good_s`, 0 above `time_limit_s`, log-linear in between (`standard`: 60 s / 900 s) |
| peak memory | 0.20 | same shape on the whole process tree's RSS (512 MB / 4,096 MB) |
| determinism | 0.20 | share of identical `sanitized/` files and `records.jsonl` across two runs with the same secret |
| scaling (optional) | 0.15 | runtime growth exponent on a larger dataset: ≤ 1.15 → 1, ≥ 2.0 → 0 |

## Critical penalties (§6 "Penalties")

| Event | Points |
|---|---:|
| each unique direct identifier or full patient name surviving anywhere in the release or side channels | −1 (cap −25) |
| each planted **canary** identity found anywhere (content, filenames, report, logs, stdout/stderr, temp files) | −3 (cap −15), counted once per canary and never also as an ordinary leak |
| each unsupported/malformed PII file copied byte-for-byte into `sanitized/` | −5 (cap −20) |
| exit 0 with `report.json` missing or inputs silently dropped ("falsely successful export") | −10 |
| modifying the read-only input | −5 |

A normal file left unchanged because its PII was missed is **not** an "unprocessed
export": that is a detection failure, already scored, and penalising it again would be
double jeopardy.

## Multi-dataset ranking

Every team runs on the same N hidden datasets (default 3, derived from the committed seed).
The leaderboard reports the mean, standard deviation and 95% Student-t interval.
Neighbouring teams get different ranks only if the **paired** difference across datasets
is significant at 95% *and* at least 0.5 points. Otherwise they share the rank.

## Calibration

The organisers' `raksha-eval calibrate` scores four built-in submissions (published with the evaluator after the results) on a fresh dataset and asserts
the ordering, so organisers can show the scale is sane before scoring any team:

| Submission | What it does | `small` normal | `small` chaos | `standard` normal | `standard` chaos |
|---|---|---:|---:|---:|---:|
| `baselines/reference` | context + gazetteer detection, evidence-based linking, keyed pseudonyms, per-patient date shifts, 5-year bands, quarantine | **80.28** | **47.71** | **84.84** | **50.33** |
| `baselines/redact_all` | destroys every value, key and file name | 22.75 | 22.64 | 21.70 | 21.68 |
| `baselines/naive_regex` | the 24-hour shortcut: regex + "Name:" labels, silent skips | 3.77 | 2.49 | 4.56 | 3.95 |
| `baselines/passthrough` | copies everything | −19.48 | −19.48 | −19.47 | −19.47 |

(`small`: seed `calibration-seed`; `standard`: seed `dev-seed-1`; evaluator 1.0.0.) The reference
was written against practice data. On the unseen-format dataset it loses about 30 points
(missed identifiers, labels and names it never saw). That is the memorisation gap the hidden
data exposes, and the headroom where strong teams separate.

Asserted checks on both the normal and the chaos dataset (calibration fails, and teams must not be scored, if any is false):

1. the reference beats redact-everything by more than 20 points;
2. the reference beats the naive shortcut by more than 20 points;
3. redact-everything stays below 45 (the privacy-utility coupling works);
4. passthrough stays below 10 (critical penalties work);
5. passthrough ranks last;
6. every anchor is fully deterministic (two runs with the same secret give the same bytes).
   A non-deterministic anchor would make the calibration table differ between machines.
   CI caught exactly that once: the reference picked a cluster by iterating a Python
   `set` and gave 57.08 locally but 57.99 on GitHub, until it was fixed.
