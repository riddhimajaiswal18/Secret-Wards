# Stage 2 normalization

`src.normalization.normalize_ir(ir, config=...)` attaches a sparse value
normalization overlay and semantic annotations to an already parsed IR.
`normalize_document_file(path, ...)` runs the existing router and then
normalizes its result. Neither path edits `ir.structure.data`; each finding
uses the existing source locator. `ir.normalizations` stores derived values;
`ir.annotations` stores canonical fields, normalized name forms, identifier
classifications, clinical terms and spans, abbreviation decisions, and
person-role findings.

Pass `source_identity` separately from `document_id` when the upstream source
system is known. The IR stores those concepts separately. Normalization does
not create `pending_edits` and does not treat a normalized value as a
replacement.

Eligibility is conservative. Unicode NFC and script identification run on text
leaves. Compact whitespace cleanup and date, phone, email, URL, and country
normalizers run only on recognized field names or explicit `field_mappings`.
Text/document narratives are never whitespace-collapsed or parsed as dates or
phones. CSV headers retain their values and receive canonical-field
annotations; they are excluded from value normalizers. XML text uses its
containing element tag as a field hint.

Semantic rules are exposed through `SemanticNormalizationConfig`: canonical
field synonyms, clinical term metadata, abbreviation expansion hints, and
opt-in name transliteration are configurable. Ambiguous abbreviations and
generic `value`, `type`, `description`, and `name` fields remain unresolved
unless structure or value evidence is sufficient. Role labels come from field
or resource context, or explicit title/relationship markers. A name by itself
does not assign a role or link records. Same-name records stay separate.

Identifier annotations distinguish format/context matches from stronger
validation. Aadhaar-like values use a Verhoeff checksum and field context; PAN
uses its format plus field context; phone validation uses `phonenumbers`; ABHA,
MRN/UHID, and insurance shapes stay low-confidence where validation is
insufficient. No annotation claims that an ID is current, belongs to a person,
or is government-issued. The reusable
`src.detection.clinical_protection.protected_spans` helper exposes exact
clinical term, dose/unit, and schedule spans for downstream detectors.

Example:

```python
from src.normalization import NormalizationConfig, SemanticNormalizationConfig

config = NormalizationConfig(
    default_phone_region="IN",
    date_order="DMY",  # leave unset if the source convention is unknown
    semantic=SemanticNormalizationConfig(
        field_synonyms={"patient_name": ("client full name",)},
        transliterate_names=False,
    ),
)
```

Date order defaults to unset, so `03/04/2002` remains ambiguous. Phone region
defaults to unset, so national-format numbers remain unsupported unless the
caller configures a region. Measurement conversions require an explicit
numeric field, sibling unit field, and canonical unit. The conversion table is
small and dimension-specific; it is not a clinical terminology system.

Python `unicodedata`, `datetime`, and `urllib.parse` cover Unicode, strict
ISO/common numeric dates, and URL components without runtime data downloads.
`phonenumbers`, `indic-transliteration`, and `pycountry` are declared
dependencies for phone validity, optional transliteration, and country lookup.
If unavailable, their operations report `unsupported`. `dateparser` is not
used because permissive parsing can guess missing/ambiguous components.
`email-validator` is not used: the implementation performs syntax checks and
IDNA domain normalization only, never DNS or deliverability checks. Pint is
not used because clinical conversion contexts must be explicit. A statistical
language detector and libpostal are omitted to avoid model/native-data costs;
script is identified from Unicode properties, mixed Latin/Devanagari is tagged
with the limited `hinglish` hint, and other language labels remain
`undetermined`.

The built-in clinical dictionary is intentionally small and is not a licensed
ICD-10, SNOMED CT, LOINC, or RxNorm distribution. Default terms have no
standard code; configured concept IDs are carried as supplied and are not
independently validated. Name matching, patient linkage, clinical conflict
resolution, and address equivalence remain out of scope.
