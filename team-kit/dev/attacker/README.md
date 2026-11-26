# Attacker auxiliary knowledge (synthetic)

* `registry.csv` - electoral-roll style population registry (every patient *and* non-patients).
  Contact columns (phone, email, last 4 Aadhaar digits) mimic a leaked third-party database.
* `known_facts.jsonl` - partial knowledge about some people: a visit date, the hospital, sometimes a
  condition.  Some targets never visited any hospital (membership-inference decoys).
