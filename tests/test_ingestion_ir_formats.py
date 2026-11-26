import json
import subprocess
import sys

from src.ingestion.file_router import parse_document_file
from src.ir import get_value, iter_field_metadata


def test_csv_and_tsv_preserve_header_rows_and_string_types(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text('Name,Age\nAsha,42\n', encoding="utf-8")
    ir = parse_document_file(csv_path)
    assert ir.source.format == "csv"
    assert ir.structure.data == {"header": ["Name", "Age"], "rows": [["Asha", "42"]]}
    assert not hasattr(ir, "fields")  # Cell provenance is derived from row/column locators.
    cells = list(iter_field_metadata(ir))
    assert next(field for field in cells if field.locator == "row:0,col:1").field_name == "Age"

    tsv_path = tmp_path / "sample.tsv"
    tsv_path.write_bytes("नाम\tउम्र\nआशा\t42\n".encode("utf-16"))
    tsv = parse_document_file(tsv_path)
    assert tsv.source.format == "tsv"
    assert tsv.source.encoding == "utf-16"
    assert tsv.structure.data["rows"][0] == ["आशा", "42"]


def test_ragged_csv_and_duplicate_headers_remain_distinct_and_report_missing_cells(tmp_path):
    path = tmp_path / "duplicate.csv"
    path.write_text('Name,Name,Age\nAsha,Devi,42\nRavi,\n', encoding="utf-8")
    ir = parse_document_file(path)
    metadata = list(iter_field_metadata(ir))
    assert ir.structure.data["header"] == ["Name", "Name", "Age"]
    assert ir.structure.data["rows"] == [["Asha", "Devi", "42"], ["Ravi", ""]]
    assert next(m for m in metadata if m.locator == "row:0,col:0").field_name == "Name"
    assert next(m for m in metadata if m.locator == "row:0,col:1").field_name == "Name"
    assert next(m for m in metadata if m.locator == "row:1,col:2").presence_status.value == "not_found"
    assert next(m for m in metadata if m.locator == "row:1,col:1").presence_status.value == "present"
    assert get_value(ir, "row:0,col:1") == "Devi"


def test_text_is_preserved_as_document(tmp_path):
    path = tmp_path / "note.txt"
    path.write_bytes(b"Clinical note\nDose: 5 mg")
    ir = parse_document_file(path)
    assert ir.source.format == "text"
    assert ir.structure.data == "Clinical note\nDose: 5 mg"
    assert ir.structure.root_type == "string"
    assert get_value(ir, "doc") == ir.structure.data


def test_fhir_bundle_is_routed_and_preserved(tmp_path):
    path = tmp_path / "bundle.json"
    source = {"resourceType": "Bundle", "type": "document", "entry": []}
    path.write_text(json.dumps(source), encoding="utf-8")
    ir = parse_document_file(path)
    assert ir.source.format == "fhir"
    assert ir.structure.data == source
    assert get_value(ir, "$.resourceType") == "Bundle"


def test_xml_preserves_order_repeated_children_attributes_and_text(tmp_path):
    path = tmp_path / "clinical.xml"
    path.write_bytes(b'<root id="r1">start<item code="a">one</item><item>two</item>end</root>')
    ir = parse_document_file(path)
    assert ir.validation.parse_status == "SUCCESS"
    assert ir.source.format == "xml"
    node = ir.structure.data
    assert node["tag"] == "root"
    assert node["attributes"] == [["id", "r1"]]
    assert [child["text"] for child in node["children"]] == ["one", "two"]
    assert node["text"] == "start"
    assert node["children"][1]["tail"] == "end"
    assert any(f.locator.endswith("children[1].text") for f in iter_field_metadata(ir))


def test_xml_preserves_namespaces_comments_processing_instructions_and_mixed_content(tmp_path):
    path = tmp_path / "namespaced.xml"
    path.write_text(
        '<?xml version="1.0"?><h:root xmlns:h="urn:h" id="1">before'
        '<h:child h:kind="a">inside</h:child><!--keep--><?audit ok?>after</h:root>',
        encoding="utf-8",
    )
    ir = parse_document_file(path)
    node = ir.structure.data
    assert node["tag"] == "{urn:h}root"
    assert node["attributes"] == [["id", "1"]]
    assert ir.structure.original_layout["namespaces"] == [["h", "urn:h"]]
    assert [child["node_type"] for child in node["children"]] == [
        "element", "comment", "processing_instruction"
    ]
    assert node["children"][0]["tag"] == "{urn:h}child"
    assert node["children"][0]["attributes"] == [["{urn:h}kind", "a"]]
    assert node["text"] == "before"
    assert node["children"][-1]["tail"] == "after"
    assert ir.structure.original_layout["xml_declaration"].startswith("<?xml")
    assert get_value(ir, "$.children[0].text") == "inside"


def test_xml_rejects_malformed_and_entity_declarations_safely(tmp_path):
    for content in (b"<root>", b'<!DOCTYPE root [<!ENTITY x "secret">]><root>&x;</root>'):
        path = tmp_path / "bad.xml"
        path.write_bytes(content)
        ir = parse_document_file(path)
        assert ir.validation.parse_status.startswith("ERROR:")
        assert next(iter_field_metadata(ir)).presence_status.value == "parse_error"
        assert "secret" not in ir.model_dump_json()


def test_invalid_bom_encoding_is_quarantined_not_mojibaked(tmp_path):
    path = tmp_path / "broken_utf16.txt"
    path.write_bytes(b"\xff\xfe\x00")
    ir = parse_document_file(path)
    assert ir.validation.parse_status == "ERROR:unsupported_encoding"
    assert ir.processing_status.value == "QUARANTINED"


def test_unsupported_and_malformed_files_get_parse_error_state(tmp_path):
    unsupported = tmp_path / "scan.pdf"
    unsupported.write_bytes(b"%PDF fake")
    ir = parse_document_file(unsupported)
    assert ir.validation.parse_status == "ERROR:unsupported_format"
    assert next(iter_field_metadata(ir)).presence_status.value == "parse_error"

    malformed = tmp_path / "broken.json"
    malformed.write_text('{"unfinished":', encoding="utf-8")
    ir = parse_document_file(malformed)
    assert ir.validation.parse_status.startswith("ERROR:")
    assert "unfinished" not in ir.model_dump_json()


def test_json_content_mislabeled_csv_is_sniffed(tmp_path):
    path = tmp_path / "mislabel.csv"
    source = {"patients": [{"id": 1}]}
    path.write_text(json.dumps(source), encoding="utf-8")
    ir = parse_document_file(path)
    assert ir.source.format == "json"
    assert ir.structure.data == source


def test_folder_batch_writes_one_ir_per_input_and_summary_after_errors(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "ok.txt").write_text("note", encoding="utf-8")
    (source / "bad.pdf").write_bytes(b"%PDF")
    (source / "nested").mkdir()
    (source / "nested" / "data.json").write_text('{"x": 1}', encoding="utf-8")
    output = tmp_path / "ir-output"
    completed = subprocess.run(
        [sys.executable, "-m", "src.ingestion.parse_file", "--input", str(source),
         "--output", str(output)], capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0
    assert (output / "ok.txt.ir.json").is_file()
    assert (output / "bad.pdf.ir.json").is_file()
    assert (output / "nested" / "data.json.ir.json").is_file()
    summary = json.loads((output / "batch-summary.json").read_text(encoding="utf-8"))
    assert summary["files_total"] == 3
    assert summary["files_parsed"] == 2
    assert summary["files_errored"] == 1
    assert next(x for x in summary["files"] if x["input"] == "bad.pdf")["status"] == "error"
