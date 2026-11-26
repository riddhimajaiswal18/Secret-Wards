import json
import subprocess
import sys

from src.ingestion.file_router import parse_document_file


def test_csv_and_tsv_preserve_header_rows_and_string_types(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text('Name,Age\nAsha,42\n', encoding="utf-8")
    ir = parse_document_file(csv_path)
    assert ir.source.format == "csv"
    assert ir.structure.data == {"header": ["Name", "Age"], "rows": [["Asha", "42"]]}
    assert next(f for f in ir.fields if f.field_path == "$.rows[0][1]").actual_dtype == "string"

    tsv_path = tmp_path / "sample.tsv"
    tsv_path.write_bytes("नाम\tउम्र\nआशा\t42\n".encode("utf-16"))
    tsv = parse_document_file(tsv_path)
    assert tsv.source.format == "tsv"
    assert tsv.source.encoding == "utf-16"
    assert tsv.structure.data["rows"][0] == ["आशा", "42"]


def test_text_is_preserved_as_document(tmp_path):
    path = tmp_path / "note.txt"
    path.write_bytes(b"Clinical note\nDose: 5 mg")
    ir = parse_document_file(path)
    assert ir.source.format == "text"
    assert ir.structure.data == "Clinical note\nDose: 5 mg"
    assert ir.structure.root_type == "string"


def test_fhir_bundle_is_routed_and_preserved(tmp_path):
    path = tmp_path / "bundle.json"
    source = {"resourceType": "Bundle", "type": "document", "entry": []}
    path.write_text(json.dumps(source), encoding="utf-8")
    ir = parse_document_file(path)
    assert ir.source.format == "fhir"
    assert ir.structure.data == source


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
    assert any(f.field_path.endswith("children[1].text") for f in ir.fields)


def test_xml_rejects_malformed_and_entity_declarations_safely(tmp_path):
    for content in (b"<root>", b'<!DOCTYPE root [<!ENTITY x "secret">]><root>&x;</root>'):
        path = tmp_path / "bad.xml"
        path.write_bytes(content)
        ir = parse_document_file(path)
        assert ir.validation.parse_status.startswith("ERROR:")
        assert ir.fields[0].presence_status.value == "parse_error"
        assert "secret" not in ir.model_dump_json()


def test_unsupported_and_malformed_files_get_parse_error_state(tmp_path):
    unsupported = tmp_path / "scan.pdf"
    unsupported.write_bytes(b"%PDF fake")
    ir = parse_document_file(unsupported)
    assert ir.validation.parse_status == "ERROR:unsupported_format"
    assert ir.fields[0].presence_status.value == "parse_error"

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
