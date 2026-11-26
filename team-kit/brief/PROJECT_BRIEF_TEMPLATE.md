# <Team name>: <one-line pitch>

**Track 3 · Secret Wards** · Members: <names> · Repo: <github link>

## 1. In one paragraph
<What your firewall does and the single idea that makes it better than a plain PII tool.>

## 2. Architecture
<Diagram: input files → ingestion → detection → linking → privacy layer → sanitized/ + report.json + records.jsonl>

## 3. How it works
- **Ingestion:** <formats, encodings, how broken / unsupported files are quarantined>
- **Detection:** <rules, gazetteers, transliteration, classical ML; how English, Hindi and Hinglish are handled; the meaning traps>
- **Linkage & pseudonyms:** <blocking, fuzzy / phonetic / cross-script matching, how you avoid over-merging, keyed HMAC IDs>
- **Privacy layer:** <date shifting, age bands, location generalisation, rare-value suppression>
- **Security:** <encryption at rest, key handling, PII-free logs, quarantine>

## 4. USP
<2–3 bullet points: what you do that others don't.>

## 5. Privacy–utility trade-off (measured on the practice data)

| Measure | Value |
|---|---|
| personal data leaked (overall / Hindi / Hinglish) | <x% / y% / z%> |
| medical values kept | <x%> |
| linking precision / recall / F0.5 | <p / r / f> |
| re-identification risk (your estimate) | <e.g. % of patients unique on age band + district + admission week> |
| run time / peak memory | <s / MB> |
| on data you did not tune on | <how the numbers change> |

<Why you chose these settings: what you give up in utility and what you gain in privacy.>

## 6. Known limitations
<What still fails and what you would do next.>
