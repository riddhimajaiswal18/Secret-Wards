# Privacy model

## Threat model

An attacker holds the released tree plus external knowledge (a voter list, a hospital registry). They
try to re-identify a patient from direct identifiers, from structural leakage (keys, filenames,
metadata, encoded blobs) or from quasi-identifier combinations. They do not hold the release secret.

## Protected

Direct identifiers: names (patient, relative, attendant), phones, Aadhaar, ABHA, PAN, email, MRN,
hospital UHIDs. Six channels are treated as channels: content, filename/path, header, JSON key,
metadata, base64. Role matters: **patient names are removed, clinician names are retained** — measured
as necessary for utility, and enforced by a role guard.

## Transformation

Substitution by kind token from `config/policy.yaml`. Clinical values are protected by a veto on
value+unit, ratios, frequencies, eponyms and drug forms, plus a lexicon harvested from the input's own
reference files. A contact label (`Mob:`) overrides the clinical veto for that number only.

## Release rules

* parsing success is never sanitisation success;
* detection found spans but bytes unchanged ⇒ **quarantine** (`untransformed_identifiers`);
* unsupported or unreadable content ⇒ typed quarantine, never a raw copy;
* every file gets exactly one fate, recorded in `report.json`.

## Residual risk, stated plainly

This is not anonymity. Quasi-identifier generalisation and date shifting are not implemented
(`config/capabilities.json`), so combinations of age, place, date and rare diagnosis remain a
re-identification path — measured externally at 12% unique rows on the shipped attacker registry.
