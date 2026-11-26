# Evaluation: definitions, denominators and ownership

The sanitizer must not grade itself. `tools/scorecard.py` measures a release from three
independent sources only — the input tree, the output tree, and the kit's truth file — and prints
its denominator next to every percentage.

## Metric definitions

| Metric | Definition | Denominator |
|---|---|---|
| `direct_pii.rate` | entity surfaces from truth found verbatim in an **exported** file's content | entity surfaces belonging to exported files |
| `by_channel.filename` | the same test against the **released path**, not the source path | entity surfaces whose channel is `filename` |
| `by_channel.key/metadata/base64/header` | same test, per channel | per-channel entity surfaces |
| `by_script` | leak rate split by `latin` / `deva` / `hinglish` | per-script entity surfaces |
| `utility.rate` | values truth marks `preserve` that survive in the release | preserved values in exported files |
| `canaries.found` | canary surfaces found **anywhere** under the output root, including names and report | all canary surfaces |
| `integrity.raw_copies` | exported files whose bytes equal their input (reference data is legitimately identical) | exported files |
| `integrity.raw_copies_penalised` | the subset the kit marks `expect: either` — the only ones that cost points | files with `expect: either` |
| `integrity.unaccounted` | input files with no fate in `report.json` | input files |
| `determinism` | two runs into separate directories, byte compare of `sanitized/` | exported files |
| `dependencies` | optional backends present in the **running** interpreter | — |

## Why these definitions

* **A surface counts as leaked if it survives where the attacker can read it.** Quarantined files
  are not released, so their entities are not counted — that matches the kit and avoids rewarding
  output that was never exported.
* **Filenames are measured after sanitisation.** Measuring the source path scores a leak that the
  release no longer has (this bug existed in the first version of this tool and inverted the
  filename channel from 8% to 100%).
* **Raw copies are split.** A reference CSV that contains no personal data is *supposed* to be
  byte-identical; only files the kit marks `expect: either` are penalised when copied.
* **Dependencies are measured, not assumed.** A missing OCR or transliteration backend changes
  behaviour silently, so the scorecard reports it rather than letting a run look successful.

## Ownership contract (from the V2 plan, enforced here)

| Layer | Owns | Must not |
|---|---|---|
| `src/normalization/*` + `semantic.py` | canonical values, roles, identifier classification | edit source data, assign identity |
| `src/detection/*` | privacy findings and the clinical veto | re-implement normalizer validation |
| `src/policy/*` | technique per finding | hold detection logic |
| `src/transformation/*` | applying locator-addressed edits | invent classification |
| `src/output/*` | release artifacts and accounting | decide what is safe |
| `tools/scorecard.py` | independent measurement | import the sanitizer's decisions |

## Known limits of this harness

* It uses the kit's truth file, so it measures *this* dataset; it is not a generalisation test.
  Held-out evaluation is not built yet.
* It counts surfaces, not entities: a name appearing twice in one file counts twice, as in truth.
* It does not evaluate quasi-identifier risk, linkage quality or pseudonym scoping yet.
