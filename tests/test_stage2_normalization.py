from __future__ import annotations

import json

from src.ingestion.file_router import parse_document_file
from src.ir import get_value
from src.normalization import NormalizationConfig, normalize_document_file, normalize_ir
from src.normalization.dates import normalize_date
from src.normalization.other import normalize_country, normalize_email, normalize_measurement, normalize_url
from src.normalization.phones import normalize_phone
from src.normalization.transliteration import transliterate
from src.normalization.unicode import identify_scripts, normalize_unicode, normalize_whitespace


def _at(ir, locator, kind):
    return next(item for item in ir.normalizations[locator] if item.normalization_type == kind)


def test_unicode_nfc_problem_values_and_script_mix():
    source = "e\u0301"
    result = normalize_unicode(source)
    assert result.status == "success"
    assert result.value == "é"
    assert source != result.value
    assert normalize_unicode("x\ud800").status == "invalid"
    assert normalize_unicode("x\x00").status == "invalid"
    assert normalize_unicode("Ａ", form="NFKC").value == "A"
    assert identify_scripts("नमस्ते")["script"] == "Devanagari"
    assert identify_scripts("ಕನ್ನಡ")["script"] == "Kannada"
    assert identify_scripts("Asha")["script"] == "Latin"
    assert identify_scripts("राम Asha")["mixed_script"] is True
    assert identify_scripts("राम Asha")["language"] == "hinglish"
    assert identify_scripts("नमस्ते")["language"] == "undetermined"


def test_whitespace_is_unicode_aware_and_context_directed():
    assert normalize_whitespace("\u00a0 Asha\t  Devi \u2003").value == "Asha Devi"
    narrative = " fever\n  continued\t at night "
    assert normalize_whitespace(narrative, collapse=False).value == "fever\n  continued\t at night"


def test_dates_are_strict_and_precision_preserving():
    assert normalize_date("2002-03-04")[:2] == ("2002-03-04", "success")
    assert normalize_date("2002-03")[:2] == ("2002-03", "success")
    assert normalize_date("2002-03-04T12:30:00+05:30")[:2] == ("2002-03-04T12:30:00+05:30", "success")
    assert normalize_date("2002-03-04T12:30:00Z")[:2] == ("2002-03-04T12:30:00Z", "success")
    assert normalize_date("03/04/2002")[1] == "ambiguous"
    assert normalize_date("03/04/2002", date_order="DMY")[:2] == ("2002-04-03", "success")
    assert normalize_date("04.03.2002", formats=("%d.%m.%Y",))[:2] == ("2002-03-04", "success")
    assert normalize_date("03/04", formats=("%d/%m",))[1] == "unsupported"
    assert normalize_date("31/04/2002")[1] == "invalid"
    assert normalize_date("245")[1] == "not_applicable"
    assert normalize_date("2002-03-04T25:30")[1] == "invalid"


def test_phone_requires_phonenumbers_and_exposes_validity_extension_metadata():
    canonical, status, warnings, metadata = normalize_phone("+1 415 555 2671 ext. 42")
    try:
        import phonenumbers  # noqa: F401
    except ImportError:
        assert status == "unsupported"
        assert warnings
        return
    assert status in {"success", "invalid"}  # lib metadata can age independently
    if status == "success":
        assert canonical.startswith("+1415")
        assert metadata["extension"] == "42"
    assert normalize_phone("not a telephone")[1] in {"invalid", "unsupported"}
    india = normalize_phone("98765 43210", default_region="IN")
    if status == "unsupported":
        assert india[1] == "unsupported"
    else:
        assert india[1] == "success" and india[0].startswith("+91")
    assert normalize_phone("12345", default_region="GB")[1] in {"invalid", "unsupported"}


def test_email_is_syntax_only_and_preserves_local_part_case():
    assert normalize_email(" User.Name@EXAMPLE.COM ")[0] == "User.Name@example.com"
    assert normalize_email("user@bad_domain")[1] == "invalid"
    normalized, status, _, metadata = normalize_email("u@bücher.example")
    assert status == "success" and normalized == "u@xn--bcher-kva.example"
    assert metadata["deliverability_checked"] is False


def test_explicit_units_conversion_rejects_incompatible_missing_and_unknown():
    converted, status, _, _ = normalize_measurement(1250, "mg", canonical_unit="g")
    assert (converted, status) == ({"value": 1.25, "unit": "g"}, "success")
    assert normalize_measurement(1, "kg", canonical_unit="mL")[1] == "invalid"
    assert normalize_measurement(1, None, canonical_unit="g")[1] == "invalid"
    assert normalize_measurement(1, "furlong", canonical_unit="m")[1] == "unsupported"
    assert normalize_measurement("1", "kg", canonical_unit="g")[1] == "success"


def test_url_country_and_transliteration_are_separate_optional_representations():
    assert normalize_url("HTTPS://ExAmple.COM:443")[0] == "https://example.com/"
    assert normalize_url("javascript:alert(1)")[1] == "invalid"
    assert normalize_url("https://user:pass@example.com")[1] == "unsupported"
    # ISO code normalization does not require a country database.
    country, country_status, _ = normalize_country("India")
    try:
        import pycountry  # noqa: F401
    except ImportError:
        assert country is None and country_status == "unsupported"
    else:
        assert country == "IN" and country_status == "success"
    value = "नमस्ते"
    converted, status, warnings, _ = transliterate(value, source_script="Devanagari", scheme="itrans")
    assert value == "नमस्ते"
    try:
        import indic_transliteration  # noqa: F401
    except ImportError:
        assert converted is None and status == "unsupported" and warnings
    else:
        assert status == "success" and converted


def test_sparse_overlay_preserves_ir_and_is_deterministic():
    original = {"patient": {"dob": "03/04/2002", "phone": "+91 98765 43210",
                            "note": "e\u0301\n  fever"}, "count": 245}
    from src.ir import build_json_ir
    doc = build_json_ir(original, document_id="norm")
    before = json.dumps(doc.structure.data, ensure_ascii=False)
    cfg = NormalizationConfig(default_phone_region="IN")
    normalize_ir(doc, config=cfg)
    first = doc.to_deterministic_json()
    assert json.dumps(doc.structure.data, ensure_ascii=False) == before
    assert get_value(doc, "$.patient.dob") == "03/04/2002"
    assert _at(doc, "$.patient.dob", "date").status.value == "ambiguous"
    assert _at(doc, "$.patient.note", "unicode_nfc").normalized_value == "é\n  fever"
    assert "$.count" not in doc.normalizations
    normalize_ir(doc, config=cfg)
    assert doc.to_deterministic_json() == first


def test_configured_measurement_mapping_resolves_explicit_sibling_unit(tmp_path):
    path = tmp_path / "measurements.json"
    source = {"weight": "1250", "weightUnit": "mg", "dose": "245"}
    path.write_text(json.dumps(source), encoding="utf-8")
    cfg = NormalizationConfig(measurement_fields={"weight": ("weightUnit", "g")})
    ir = normalize_document_file(str(path), config=cfg)
    result = _at(ir, "$.weight", "measurement")
    assert result.status.value == "success"
    assert result.normalized_value == {"value": 1.25, "unit": "g"}
    assert result.metadata["unit_locator"] == "$.weightUnit"
    assert not any(r.normalization_type == "measurement"
                   for r in ir.normalizations.get("$.dose", []))


def test_ingestion_to_normalization_for_all_supported_formats(tmp_path):
    cases = {
        "x.csv": "DOB,Phone,Note\n2001-02-03,+1 415 555 2671,hello\n",
        "x.tsv": "Birth Date\tName\n03/04/2002\t Asha  Devi \n",
        "x.json": json.dumps({"birthDate": "2001-02-03", "email": "a@EXAMPLE.COM"}),
        "x.txt": "e\u0301 clinical note: C/O fever, Ramipril 5 mg",
        "x.xml": "<record><birthDate>2001-02-03</birthDate></record>",
        "x.fhir.json": json.dumps({"resourceType": "Bundle", "type": "document", "entry": [
            {"resource": {"resourceType": "Patient", "birthDate": "2001-02-03"}}]}),
    }
    for filename, content in cases.items():
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        ir = normalize_document_file(str(path), config=NormalizationConfig(default_phone_region="US"))
        assert ir.validation.parse_status == "SUCCESS", filename
        assert ir.normalizations, filename
        assert ir.structure.data is not None
    json_ir = normalize_document_file(str(tmp_path / "x.json"))
    assert _at(json_ir, "$.birthDate", "date").normalized_value == "2001-02-03"
    xml_ir = normalize_document_file(str(tmp_path / "x.xml"))
    assert any(r.normalization_type == "date" and r.normalized_value == "2001-02-03"
               for results in xml_ir.normalizations.values() for r in results)
    tsv_ir = normalize_document_file(str(tmp_path / "x.tsv"))
    assert _at(tsv_ir, "row:0,col:0", "date").status.value == "ambiguous"
    assert any(item.finding_type == "canonical_field" and
               item.details["canonical_field"] == "date_of_birth"
               for item in tsv_ir.annotations["row:0,col:0"])
    text_ir = normalize_document_file(str(tmp_path / "x.txt"))
    assert any(item.finding_type == "clinical_term" and item.details["canonical_term"] == "fever"
               for item in text_ir.annotations["doc"])
