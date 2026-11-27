# Limitations

The current implementation is a measured prototype, not a certified privacy system. The current 200-file practice results and all unimplemented controls are summarized in [BASELINE_RESULTS.md](BASELINE_RESULTS.md) and [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

Key limits: 27 / 3,234 labeled PII surfaces remained visible (0.84%); the verifier reports 492 name candidates that need triage; Hinglish remains the weakest script group (14.4% visible); cross-hospital identity resolution is incomplete; quasi-identifier transformations and re-identification-risk measurement are absent; and Linux target-resource behavior has not been validated.

The Team Kit includes development truth labels. They are used only by evaluation tools, not by production detectors. Practice scores are not held-out performance. See [RELEASE_CRITERIA.md](RELEASE_CRITERIA.md) for the gates that remain before main-branch promotion or a readiness claim.
