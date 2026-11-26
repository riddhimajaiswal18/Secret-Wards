# The Privacy Attack Arena

The statement's main twist (§1, Mission Brief) is an automated adversary that tries to work out *which
original patient* each sanitised record belongs to. This document specifies that
adversary. Following Kerckhoffs' principle, the **method is public** and the
**knowledge is secret**: this page describes the attack exactly (the code itself is published with the evaluator after the
results), while the registry and the
known facts come from the hidden seed and are never mounted into a submission's sandbox.

> As the statement says, no finite synthetic attack proves anonymity. The arena measures
> resistance against these defined, reproducible attacks.

## What the attacker knows

| Source | Content |
|---|---|
| The release | everything under `sanitized/`, plus the pseudonyms that are actually present in the exported records |
| `attacker/registry.csv` | an electoral-roll-style list of the **whole population** (4–5× the patient count): name, S/o-D/o-W/o + relative, gender, age, house number, mohalla, village, tehsil, district, PIN |
| leaked-contacts overlay | for 60% of people: phone, email, last 4 Aadhaar digits (a third-party breach) |
| `attacker/known_facts.jsonl` | for ~30% of patients plus every re-identification-trap patient: one true visit date, the hospital, sometimes the condition (always the **rare** one for trap patients), and the length of stay for admissions. Decoys (people who never visited) are mixed in. |
| Public knowledge | Indian name transliteration tables (Latin, variants, Devanagari), the district/tehsil gazetteer, village-name morphology, rare-disease vocabulary |

## Evidence extraction (generic, format-aware)

For every record of the release the attacker reads `(field, value)` pairs (CSV header →
cell, JSON key → leaf, free text) and extracts:

* ages (`52`, `52/M`, `52 Yrs`, `52 वर्ष`, bands `50-54`, `85+`, `[50,60)`), birth years
  (from DOB fields or `DOB:` anchors), gender (fields, `/M`, Hindi words, S/o / W/o,
  honorifics such as *sahab* / *behenji*);
* district, tehsil and village (Latin **and** Devanagari forms), 6-digit PINs and
  3-digit PIN prefixes (`226***`);
* names via transliteration-aware token lookup (doctors after `Dr.` are skipped),
  relative names after S/o, D/o, W/o, C/O;
* full phones, masked phones (`98XXXXXX10`), masked Aadhaar (`XXXX XXXX 1234`), emails,
  house numbers, rare conditions and procedures, hospital names, and every date.

## The attacks

**A1: Direct exposure.** Any surviving direct identifier or full patient name, found by the
leak scan in content *or* side channels, exposes that patient.

**A2/A3: Record linkage (Sweeney-style).** Registry candidates are filtered by the
evidence in this order: phone, email, last-4 digits, masked phone, district, gender,
age ranges (±1/+2 years for encounter-date drift), birth year, tehsil, village, PIN, PIN
prefix. A filter that would empty the set is **skipped**, so wrong or contradictory
evidence (surrogates, noise) cannot crash the attack, but it does weaken it. The
remaining candidates are weighted: full-name match ×60, given name ×8, surname ×3,
relative ×8, house number ×2. The record's risk is the probability mass on the true
person.

**A4: Profile aggregation.** Records are joined into profiles through shared pseudonyms
(only those present in the data) and shared reference values (`patient_ref`, `uhid`, …).
The pooled evidence is attacked again. A record's risk is the maximum of its
record-level and profile-level probability. The headline number is the share of
patients the attacker identifies with confidence ≥ 0.5.

**A5: Targeted attack (known facts, with shift recovery).** For each person in the known
facts, the attacker looks for profiles that match at least one known fact: the visit
date, the condition (weighted ×8 when at most three profiles share it, so rare
diseases are near-unique), or the length of stay (every interval between dates inside
one record; per-patient shifting cannot hide it). The profile's evidence must also be
consistent with that person. Hospital matches double the weight. First it tries to
**recover a global date shift**: from profiles it has already re-identified with
confidence ≥ 0.9, it compares their dates with the known visit dates. If at least two
people agree on one offset, every date in the release is un-shifted by it. A single
global shift, therefore, protects nobody; per-patient secret shifts do. Claims against
decoys are reported as membership-inference false positives.

**A6: Pseudonym inversion.** A dictionary of each patient's originals (all UHIDs, Aadhaar,
phone, ABHA, Latin full name) is expanded with common transforms: case, digits only,
MD5/SHA-1/SHA-256/SHA-512 hex (full or truncated prefixes ≥ 8), base64, reversal. A
pseudonym is inverted if it equals or prefixes a transform of its own patient's
original, or embeds the UHID digit core or the phone number. Unkeyed hashing is
caught; HMAC with the per-release secret is not.

**A7: Cross-release linkability.** The evaluator runs the submission a third time with a
different `RAKSHA_SECRET`. The risk is the larger of: patients who keep the same
pseudonym, and shifted dates that land on the same value. Stable pseudonyms let anyone
link two "anonymous" releases.

## Normalisation against raw data

A1–A5 are also run on the **raw input** (cached per dataset). Each component is the
team's risk divided by the raw risk, so the scale means "how much of the attack surface
you removed". It does not depend on how easy the particular hidden dataset happens to be.

## Example readings (a practice-style dataset)

| Submission | A3 record linkage (vs raw) | A4 patients re-identified | A5 targeted success |
|---|---:|---:|---:|
| passthrough | 100% | 99.3% | 97.1% |
| reference (5-year bands, district kept, per-patient shifts) | 27.7% | 16.7% | 40.1% |
| redact everything | ≈ 0% | 0% | 0% |

The reference resists profile attacks reasonably well (district + gender + 5-year band
leaves several people per cell in the registry), but its targeted-attack
exposure stays high. The 56 rare-condition hits show that keeping a rare diagnosis
next to an exact age band and district identifies the "97-year-old with a rare
procedure" (the Re-identification Trap) even after every date was shifted. Defending against that
needs suppression or coarser generalisation **of the rare records only**, which is the
k-anonymity-style risk analysis the statement asks for (the Re-identification Trap, and your measured re-identification risk).

### Attacker self-checks

The attacker's age parser only reads ages in age forms (`52/M`, `52 Yrs/F`, `52 वर्ष`,
`Age: 52`, bands `50-54 Yrs/F`, `85+`). It does not read history durations
(`x 12 yrs`, `7 yrs back`) or lab reference ranges (`70-140`). An earlier version read
"50-54 Yrs/F" as an exact age 54, which wrongly *filtered out* the true person and
overstated privacy. Parsing mistakes weaken the attacker, so they are tested as
carefully as the scorer.
