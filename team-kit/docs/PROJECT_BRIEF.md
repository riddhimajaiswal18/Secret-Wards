# The 2-page Project Brief (PDF)

Along with your GitHub link, you submit a **2-page PDF** that explains your system.
Judges read it next to your README, so make it clear and short: **2 pages maximum**
(A4, readable font, 10 pt or larger). Pages after the second are not read.

A ready-to-fill template is in [`brief/PROJECT_BRIEF_TEMPLATE.md`](../brief/PROJECT_BRIEF_TEMPLATE.md).

## What it must cover

| Section | What to write | Tip |
|---|---|---|
| **1. Team & one-line pitch** | team name, members, repo link, one sentence on what makes your firewall special | the pitch is the first thing judges read |
| **2. Architecture diagram** | the pipeline from input files to the 3 outputs | one clear picture: ingestion → detection → linking → privacy layer → export |
| **3. How each part works** | ingestion, detection (3 scripts), linkage & HMAC pseudonyms, privacy layer, security design | 2–4 lines each; say *which technique* and *why* |
| **4. USP** | what you do that a plain PII tool does not | e.g. cross-script name matching, context rules for the meaning traps |
| **5. Privacy–utility trade-off** | what you generalise, shift or suppress, and what that costs | show **measured numbers** (see below) |
| **6. Security design** | encryption at rest, where keys live, PII-free logging, quarantine | "assume your server will be breached one day" |
| **7. Known limitations** | what still fails, honestly | judges value honesty over claims |

## Measure, don't guess

Run your system on the practice data and the self-check, and put the numbers in the brief:

```bash
RAKSHA_SECRET=practice python3 main.py --input dev/input --output out
python3 check_dev.py --output out
```

Useful numbers to quote:

* personal data still visible (% leaked, overall and per language);
* medical values kept (%);
* linking precision / recall / F0.5;
* how many patients remain unique on (age band, district, admission week, diagnosis),
  i.e. your own re-identification risk estimate;
* run time and peak memory from your `report.json`.

Also say how your numbers change when you test on data you did **not** tune on (renamed
columns, new names, new date formats). That shows the system generalises.

## How to make the PDF

Any tool works: Google Docs, Word, LaTeX, or Markdown → PDF
(`pandoc PROJECT_BRIEF_TEMPLATE.md -o brief.pdf`, or "Print → Save as PDF" from any
Markdown preview). Put the final PDF in your repo too (for example `docs/brief.pdf`), so
it is frozen with your last commit.
