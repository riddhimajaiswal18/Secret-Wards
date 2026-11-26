"""CLI: parse one supported Team Kit file into the IR JSON representation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.ingestion.file_router import parse_document_file


def _document_id(relative) -> str:
    """Stable per-file identity derived from the relative path, never the bare stem."""
    import hashlib
    return hashlib.sha256(relative.as_posix().encode()).hexdigest()[:16]


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a Team Kit document into Secret Wards IR")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.input)
    output = Path(args.output)
    if source.is_file():
        try:
            ir = parse_document_file(source)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(ir.to_deterministic_json(), encoding="utf-8")
        except OSError:
            print("Could not write IR output.", file=sys.stderr)
            return 2
        print("IR written successfully." if ir.validation.parse_status == "SUCCESS"
              else "IR written with a parse error status.")
        return 0

    if not source.is_dir():
        print("Input path does not exist or is not a file/folder.", file=sys.stderr)
        return 2
    try:
        source_resolved = source.resolve()
        output_resolved = output.resolve()
        if output_resolved == source_resolved or source_resolved in output_resolved.parents:
            print("Batch output must be outside the input folder.", file=sys.stderr)
            return 2
        paths = sorted(p for p in source.rglob("*") if p.is_file())
        output.mkdir(parents=True, exist_ok=True)
        results = []
        for path in paths:
            relative = path.relative_to(source)
            # Keep the entire input filename so different extensions cannot collide.
            output_file = output / relative.parent / f"{relative.name}.ir.json"
            try:
                ir = parse_document_file(path, document_id=relative.as_posix())
                output_file.parent.mkdir(parents=True, exist_ok=True)
                output_file.write_text(ir.to_deterministic_json(), encoding="utf-8")
                status = "parsed" if ir.validation.parse_status == "SUCCESS" else "error"
                reason = ir.validation.parse_status if status == "error" else None
            except (OSError, ValueError, RecursionError, UnicodeError) as exc:
                # One hostile file must never take the batch down; a typed reason is enough.
                status = "error"
                reason = "unhandled_" + type(exc).__name__.lower()
            results.append({"input": relative.as_posix(),
                            "output": output_file.relative_to(output).as_posix(),
                            "status": status, "reason": reason})
        summary = {"schema": "secret-wards-ir-batch/1", "files_total": len(results),
                   "files_parsed": sum(r["status"] == "parsed" for r in results),
                   "files_errored": sum(r["status"] == "error" for r in results),
                   "files": results}
        (output / "batch-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        print("Could not write IR output.", file=sys.stderr)
        return 2
    print(f"Batch complete: {summary['files_parsed']} parsed, {summary['files_errored']} errors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
