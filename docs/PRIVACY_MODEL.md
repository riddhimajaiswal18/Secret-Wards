# Privacy model

## Threat model

An attacker may see the released tree plus external knowledge such as public registries or hospital exports. Risk comes from direct identifiers, structural channels (keys, filenames, metadata, encoded content), and combinations of quasi-identifiers. A release secret is not available to the attacker.

## Current protections

The implementation detects selected patient/relative names, phone and Indian identifier patterns across supported content and structural channels, applies locator-based substitutions, protects selected clinical spans, and quarantines known parse failures. Patient pseudonyms use secret-keyed HMAC; the secret comes from the environment. Reports identify input files by SHA-256 rather than their original path.

The system uses contextual and structural evidence to distinguish patient, relative, clinician and institution information. The practice scorecard still records misses; see [BASELINE_RESULTS.md](BASELINE_RESULTS.md).

## Unimplemented protections

Per-patient date shifting, age bands, location generalization, rare-combination suppression, full conservative record linkage, and measured re-identification-risk assessment are not implemented in the release path. Persisted sensitive intermediate-data encryption and a blocking release verifier are also incomplete.

## Release rules and residual risk

Parsing success is not proof of sanitization. Unsupported or unparseable inputs must be quarantined, and partial edits must not be represented as safe output. The current verifier reports candidate names and fails the practice output; candidate counts are not a ground-truth leak count, but every finding requires review. No anonymity claim is made. Do not use real patient data.
