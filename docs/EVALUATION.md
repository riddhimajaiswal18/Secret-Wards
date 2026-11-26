# Evaluation

Reproduce with the Team Kit, never with hardcoded numbers.

```bash
export RAKSHA_SECRET=practice
python3 main.py --input <kit>/dev/input --output build/out
python3 <kit>/validate_output.py --input <kit>/dev/input --output build/out
python3 tools/scorecard.py --kit <kit>          # independent: measures input+output trees only
python3 tools/verify.py <kit>/dev/input build/out
python3 <kit>/check_dev.py --output build/out   # official scoring, if shipped
```

## Baseline measured on this corpus (200 files)

| Measure | Value | Denominator |
|---|---|---|
PII surfaces visible | 13.6% | 440 / 3230 |
Clinical values kept | 99.4% | 4824 / 4855 |
Canaries found | 0 | of 4 |
Accounting | 197 exported, 3 quarantined, 0 unaccounted | 200 |
Raw copies | 0 | — |
Verifier survivors | 557 (all name-like) | 2459 candidates |
Runtime / peak RSS | 0.8 s / 66 MB | 2 vCPU budget |

Channels: content 13.9 · metadata 7.5 · filename 8.3 · key 0 · header 0 · base64 0.
Scripts: Devanagari 19.6 · Hinglish 42.3 · Latin 12.2.

## Ground truth available for this corpus

`<kit>/dev/truth/truth.json` provides per-unit labels: 883 units across 200 files, 771 of them
requiring a patient link, with `entities[]` carrying `type`, `surface`, `role`, `script`, `channel`,
`critical`. Use it to compute precision, recall and F1 per kind and channel, and to score identity
grouping against truth patient ids. It is the practice set, not a held-out one: results tuned here
overstate hidden-corpus performance, which is a different and narrower caveat than "no labels exist".

## What each number does *not* mean

A surface count is not recall. The verifier's survivor count is a candidate count, not a confirmed
leak count. `check_dev.py`'s linking line measures the shipped rule (0 false merges) and not a
linkage system that does not exist.
