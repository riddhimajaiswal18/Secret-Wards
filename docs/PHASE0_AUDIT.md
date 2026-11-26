# Phase 0 — Deep repository and architecture audit

**Repository** `riddhimajaiswal18/Secret-Wards` · **branch** `feat/detection-release-pipeline`
**Commit audited** `8f00dba` · **Date of audit** this session · **`main` untouched**

This document separates three things that are usually blurred: what was **verified by execution**,
what is a **hypothesis** that still needs a probe, and what is a **recommendation**. Nothing here was
fixed, installed, deleted or pushed. The working tree was clean before and after.

---

## 1. Repository state (VERIFIED)

| Fact | Value |
|---|---|
Branch · HEAD | `feat/detection-release-pipeline` · `8f00dba` |
Working tree | clean (no uncommitted files) |
Recent commits | `8f00dba` key channel · `9dc1863` consolidation · `62e70a1`, `15c57b4` (teammate) |
Test suite | **91 passed**, 1 deprecation warning, 0.5 s |
Source size | **5,131 LOC** across ~45 modules under `src/` + `main.py` + `tools/` |
Files processed | 197 / 200 exported · 3 quarantined · **0 unaccounted** |

### Reproduced scorecard (VERIFIED, same run)

```
PII        503/3234 still visible (15.6%)   ← denominator = entity surfaces in exported files
channels   base64 0.0% · content 15.9% · filename 8.3% · header 0.0% · key 0.0% · metadata 12.5%
scripts    deva 21.0% · hinglish 42.3% · latin 14.3%
utility    4824/4855 clinical values kept (99.4%)
canaries   1/4 found
integrity  7 identical-to-input (0 on files the kit expects quarantined) · identity 0 linked
deps       MISSING at run time: pdftoppm_binary
```

Every figure carries its denominator. The key channel is now **0.0%** (was 41.7% at the start of
this session, root cause in §3.1).

---

## 2. Architecture: the real execution path (VERIFIED by import graph)

The documented architecture has nine stages. The code has **one orchestrator** and a support ring:

```
main.py                     CLI, exit codes
  └─ src/pipeline.py        68 L  policy load, capability enforcement, log filter
      └─ src/output/writer.py  223 L  THE orchestrator
          ├─ src/ingestion/parse_file.py → file_router.py
          │     ├─ csv_tsv.py   ir_json.py   xml_parser.py   fhir_parser.py   text_parser.py
          │     ├─ encoding.py            (BOM / charset detection)
          │     └─ scanned.py   276 L      PDF → image → OCR ladder, typed quarantine
          ├─ src/ir.py          433 L      IntermediateRepresentation, provenance, source locations
          ├─ src/normalization/ 1,100 L    unicode · names · dates · phones · transliteration ·
          │                                other · semantic (654 L: canonical fields, roles,
          │                                identifier classification)
          ├─ src/understanding/engine.py  514 L   contextual + relationship annotations
          ├─ src/detection/     885 L      engine · identifiers · protection · columns · paths ·
          │                                structural
          ├─ src/policy/engine.py 88 L     technique decision
          ├─ src/transformation/engine.py 250 L  locator-based edits, reverse ordering
          └─ src/security/      248 L      safe_logging (leak scan, log filter) · capabilities ·
                                           quarantine
tools/scorecard.py          252 L  independent measurement (does not import detector decisions)
```

**Verified structural fact:** `policy/engine.py` decides the technique; `transformation/engine.py`
applies it; detection never writes. That separation is real and is the best thing in this repo.

### Implementation status, module by module (VERIFIED by line count + import graph)

| Stage | Status | Evidence |
|---|---|---|
Secure ingestion, size/depth caps, quarantine | **implemented** | `file_router.py` 184 L, `quarantine.py` 70 L |
Format parsers (CSV/TSV/JSON/FHIR/XML/TXT) | **implemented** | 6 parser modules, all imported |
PDF/JPG extraction ladder + OCR | **implemented, degraded** | `scanned.py` 276 L; `pdftoppm` absent |
IR + provenance + source locations | **implemented** | `ir.py` 433 L |
Normalization (annotations only) | **implemented** | 1,100 L; non-destructive, verified earlier |
Detection | **partial** | 885 L; name F1 51.2, phone recall 70.8 |
Clinical protection | **implemented** | `protection.py` 195 L; utility 99.4% |
Policy engine | **implemented but thin** | 88 L, single technique table |
Transformation | **implemented** | 250 L, locator-based, fail-closed |
Independent verification | **missing** | `evaluation/{metrics,validation}.py` are 1-line stubs |
Release gate | **missing** | criteria written in `docs/RELEASE_CRITERIA.md`, no code enforces them |
Identity linkage | **missing** | `linkage/{blocking,comparison,clustering,matching}.py` — 1-line stubs |
Pseudonymization | **missing** | `pseudonymization/hmac_ids.py` — 1-line stub |
Date shifting | **missing** | `privacy/date_shifting.py` — 1-line stub |
Quasi-identifier protection | **missing** | `privacy/{age_banding,location,suppression,risk_assessment}.py` — 1-line stubs |
Encryption / key management | **missing** | `security/{encryption,key_management}.py` — 1-line stubs |

### ⚠ Finding A1 — 21 modules are empty placeholders that look like features (VERIFIED)

`find src -name '*.py' | xargs wc -l | sort -n` returns **21 files with exactly 1 line**, and none of
them is imported by anything:

```
linkage/blocking.py  linkage/comparison.py  linkage/clustering.py  linkage/matching.py
privacy/age_banding.py  privacy/date_shifting.py  privacy/location.py
privacy/risk_assessment.py  privacy/suppression.py
pseudonymization/hmac_ids.py
evaluation/metrics.py  evaluation/validation.py
security/encryption.py  security/key_management.py
detection/dates.py  detection/gazetteers.py  detection/names.py
detection/phone.py  detection/structured.py  detection/unstructured.py
ingestion/json_parser.py
```

A reviewer listing the tree sees `pseudonymization/`, `linkage/`, `privacy/` and concludes the
project has them. It does not. Two consequences: the repository overstates its own capability, and
the 21 stubs will collide with real implementations later (different intended APIs, same names).

**Recommendation R1 (smallest safe change):** delete the stubs, or replace them with a
`capabilities.json`-style declaration that says `status: not_implemented`, and add a test that fails
when a module under `src/` is neither imported nor declared. This costs no behaviour and removes a
false claim.

### ⚠ Finding A2 — two sources of truth for identifier classification (VERIFIED)

Identifier knowledge exists in **both** `src/normalization/semantic.py` (654 L) and
`src/detection/engine.py` + `identifiers.py` (466 L). They disagree in a measured case: the
normalization classifier resolves a bare numeric MRN `010565`, while the detection regex requires a
letter prefix and separator — this disagreement is the measured cause of the **31.4 % MRN leak**.

**Recommendation R2:** `normalization/*` owns *evidence* (canonical field, role, identifier class);
`detection/*` owns *decisions* and must consume that evidence rather than re-deriving it. The
ownership contract already exists in the design notes; the code does not honour it yet.

---

## 3. Defect root causes (VERIFIED, each with a reproducible instance)

### 3.1 Key channel 41.7 % → 0.0 % (FIXED at `8f00dba`)
Not a missing rule but an **ordering defect**. For `{"Sunita Patel": "JJH-1"}` the value path
replaced the UHID and executed `continue`, so control never reached the key-rename block. The commit
that fixed string-valued identity keys had preempted the branch that renamed the key itself.
Fix: judge the key before its value; restrict renaming to identity *content*, never schema labels.

### 3.2 The remaining 15.6 % (503/3234) — attributed, not guessed (VERIFIED for channel, HYPOTHESIS for truth-split)
- **No ground-truth file ships with the kit** (`../kit/dev/dataset_manifest.json` only). So per-kind
  recall is *not* independently verifiable in this repository today — every precision/recall number
  quoted in this session came from a comparison harness, not from a versioned labelled set.
  **This is the single largest evaluation weakness** and the reason §5 proposes a labelled set first.
- Channel attribution is measurable: **content 15.9 %**, **metadata 12.5 %**, **filename 8.3 %**,
  header 0.0 %, base64 0.0 %, key 0.0 %.
- Worst-leak list names `registration/sanjeevani_registration.csv` × **VILLAGE / content** repeatedly.
  Village is a quasi-identifier retained deliberately until Phase 7 — a *policy* decision, not a
  detection bug. This must be stated in the report rather than counted as a detector failure.

### 3.3 Devanagari 21.0 % (VERIFIED measurement, HYPOTHESIS on mechanism)
24 `.txt` + 9 `.json` released files still contain Devanagari. Mechanism (hypothesis, needs a probe):
detection folds Devanagari with `unicodedata` + a `_NOT_NAMES_DEVA` stoplist, so it depends on
transliterated matches succeeding. The `regex` package (which provides `\p{Script=Devanagari}`) is
declared in `requirements.txt` but **never imported** — the script-class approach is simply absent.

### 3.4 Hinglish 42.3 % (VERIFIED measurement, HYPOTHESIS on method)
Current coverage is a single rule for name + lowercase kinship suffix (`Kamal bhaiya`, `Asha ji`).
Untested by it: lowercase-initial names, role words (`attendant`, `compounder`, `didi`), and names
inside parentheses.

### 3.5 The last canary — `Zorawar Qadri` (VERIFIED, and the most important finding of this audit)

```
VISITOR LOG
18:40 - Zorawar Qadri (attendant, bed 12), mob 6910522119
19:10 - Dr. Ramesh Srivastava took evening round.
```

Extracting that file alone and running the pipeline on a one-file corpus produced **no change at
all** — not the name, not the phone number.

**Finding A3 (VERIFIED): a meaningful part of detection is corpus-derived, not rule-derived.** The
detector harvests lexicons from the input tree's own reference files (drug formulary, ward census,
district/state columns). On a single unseen file it detects nothing. Consequence: the 15.6 % figure
is **not transferable to the hidden corpus**, which is exactly the "chaos" half of the scoring.
This outranks the canary itself as a defect.

### 3.6 Re-identification 12 % (VERIFIED by attacker replay)
240 registry rows / 216 distinct `(sex, age, district)` keys → **7 of 57 released registration rows**
uniquely identifiable, 2/7 name-confirmed. Cause: exact age + district retained. This is Phase 7
work, correctly deferred.

### 3.7 Silent capability degradation (VERIFIED by our own scorecard)
`deps MISSING: pdftoppm_binary`. `capabilities.py` (75 L) detects and reports this, and
`config/policy.yaml: capabilities.require` *can* fail closed — but the shipped policy does not
require it, so a run whose OCR path was never exercised still reports success. The scorecard prints
the warning; the pipeline does not act on it.

---

## 4. External references — what to reuse (≠ integrate)

| Project | Problem it solves | Reuse? | Evidence quality |
|---|---|---|---|
**Presidio** | pluggable recognizer architecture, anonymizer, explanations | **architecture yes, engine no** — measured on our data: **1 of 20** PII spans found; flagged `BP 117/82` and `30 days` as DATE_TIME | **measured** (this session) |
**UCSF Philter** | clinical free-text de-identification with annotated evaluation workflow | **evaluation methodology** — its annotated-note workflow is the model for our Phase 1 lab | **desk review**, not run |
**medSpaCy** | clinical sections, sentence splitting, context (negation/family/history) | **concept only** — heavy spaCy dependency; our `protection.py` already covers the veto function at 99.4 % utility | **desk review** |
**scrubadub** | modular detector registry, conservative handling | **pattern only** — our detector registry is already modular | **desk review** |
**IHE De-Identification Handbook** | architectural treatment of pseudonymization, re-linking, risk, validation | **structure** — its separation of *de-identify / pseudonymize / re-link / assess* maps onto our Phase 0/5/6/7 split | **desk review** |
**NIST SP 800-188** | disclosure-risk methodology, measurable release standards | **methodology** — the basis for `docs/RELEASE_CRITERIA.md` and for reporting risk as measured, not claimed | **desk review** |

Licence/dependency notes: Presidio (MIT, heavy deps, no Indic defaults), Philter (mixed/UC licence —
must be read before any reuse), medSpaCy (MIT, spaCy model download conflicts with offline runs),
scrubadub (MIT, lightweight). **None is a drop-in**: the measured Presidio result (1/20) is the
evidence that a general-purpose engine does not transfer to Indian hospital text.

**Recommendation R3:** do not integrate any of them. Take the *architecture* (recognizer registry +
independent verifier) and the *evaluation workflow* (annotated held-out notes), which is what the
measurements support.

---

## 5. Evaluation programme — the honest gap

What exists (VERIFIED): `tools/scorecard.py`, 252 L, computes everything from input tree + output
tree, prints a denominator beside every percentage, and does not import detector decisions. It has
already caught three of its own bugs.

What does not exist (VERIFIED): a **versioned labelled corpus**, a **held-out split**, and
**per-language / per-format denominators**. Without those, "PII 15.6 %" is a *surface count*, not a
recall figure, and cannot be compared to a future run with a different corpus.

**Recommendation R4 (highest value, lowest risk):** build the labelled set before any further
detection work — schema from MAMA (17,838 spans, 18 label types, CC-BY-4.0, already audited),
generated additional cases via Faker `en_IN`/`hi_IN` (test-only dependency), split dev/held-out by
**file**, and record `(kind, channel, script, format, found/missed)` per surface.

---

## 6. Prioritised technical debt

| # | Item | Cost | Risk if ignored |
|---|---|---|---|
1 | 21 empty modules masquerading as features | 30 min | reviewer discovers it; naming collisions later |
2 | No labelled/held-out evaluation set | 1 day | every improvement is unprovable |
3 | Detection depends on the input tree's own lexicons | 3–4 h | hidden corpus underperforms badly |
4 | Two identifier classifiers that disagree (31.4 % MRN leak) | 2–3 h | MRN + numeric IDs keep leaking |
5 | No independent verifier / release gate in code | 3–4 h | the system can ship its own mistakes |
6 | `capabilities.require` not enforced by shipped policy | 30 min | OCR-less run reports success |
7 | `requirements.txt` declares 14, code imports 4 | 30 min | supply-chain surface, reviewer question |
8 | No linkage / pseudonyms / dates / quasi-identifiers | 20–25 h | ~27 score points unclaimed |
9 | `batch-ir/` PII in git history (partner commit) | needs approval | history purge on a shared repo |

---

## 7. Proposed target architecture (deltas only)

Keep the existing spine — ingestion → IR → normalization → detection → policy → transformation →
serialisation → report. Add exactly three rings, in this order:

1. **Independent verifier** (`tools/verify.py`): re-scans *released* files with its own code path
   (no import of `src/detection/*`), checks canaries, channels, accounting, capabilities, and can
   **fail the build**. This is the airport's second scanner.
2. **Per-file evidence record**: every file carries `detectors_run[]`, `detectors_unavailable[]`,
   `surfaces_found`, `surfaces_edited`, so a degraded run cannot look clean.
3. **Phase 4–7 layers** (`linkage/` → `pseudonymization/` → `privacy/`), implemented behind the
   role guard proven necessary by the normalization audit (`Dr. Ramesh Kumar` ≠ `Ramesh Kumar`).

---

## 8. Roadmap with measurable exit criteria

| Phase | Exit criterion (all measured, all with denominators) |
|---|---|
**0** (this) | architecture mapped; every defect has a file+function+reproduction |
**1** | labelled corpus + held-out split; precision/recall/F1 per kind, channel, script, format |
**2** | zero silent degradation: every unsupported capability appears in `report.json` and either quarantines or fails the run |
**3** | held-out recall ≥ 0.90 for PHONE/PAN/AADHAAR/ABHA/EMAIL; NAME F1 ≥ 0.70; **single-file corpus detects name + phone** (no lexicon) |
**4** | clinical utility ≥ 99 % with the new name rules; no clinical value removed |
**5** | linkage: 0 false merges, F0.5 ≥ 0.85, explicit `uncertain` outcome |
**6** | pseudonyms: same patient same token across hospitals; different secret ⇒ different tokens **and** dates |
**7** | A3 unique ≤ 10 %; A5 global-shift recovery 0 %; LOS preserved exactly |
**8** | verifier rejects a deliberately unsafe build; passes a safe one |
**9** | threat model, limitations, DPDP/HIPAA mapping, clean dependency set |

---

## 9. Exact first implementation task (recommended, not started)

> **Task: make the repository tell the truth about itself, in one commit, with zero behaviour change.**
>
> 1. Delete the 21 one-line stubs (or park them under `archive/`) and record the missing capability
>    in `config/capabilities.json` with `"status": "not_implemented"`.
> 2. Add `tests/test_module_truth.py`: every `src/**/*.py` must be imported by something or declared
>    in that file — the audit's Finding A1 cannot silently return.
> 3. Add `tests/test_single_file_detection.py`: a one-file corpus containing one phone and one
>    `Titlecase Pair` must produce at least one edit — this pins Finding A3 as a failing test we can
>    then fix deliberately in Phase 3.

Estimated 45 minutes, no detection logic touched, no number moves, and it converts two audit findings
into permanent guards.

---

## 10. Verified / hypothesis / recommendation — summary

**Verified by execution today:** commit and clean tree; 91 tests; 197/200 exported; 15.6 % with
denominators; channel split; 1/4 canaries; 4,824/4,855 utility; key channel 0.0 %; 21 stub modules;
orphan import graph; `pdftoppm` missing; single-file corpus detects nothing; worst-leak files;
the 12 % re-identification replay.

**Hypothesis requiring a probe:** the exact Devanagari and Hinglish mechanisms; whether the 7
identical-to-input files are only the kit's clean reference files; whether MRN leakage is fully
explained by the classifier disagreement; the true per-kind recall (no labelled set exists).

**Recommendation, not fact:** the three external projects worth architectural study (Presidio
registry, Philter evaluation workflow, IHE structure); the ownership contract between
`normalization/*` and `detection/*`; Phase order 0→9 above.

**Not done in this audit, by instruction:** no code changes, no dependency installed, no external
project integrated, no history rewritten, no push, `main` untouched.
