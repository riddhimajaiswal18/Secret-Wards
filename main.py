#!/usr/bin/env python3
"""Command-line placeholder for the Secret Wards pipeline.

The processing pipeline is intentionally not implemented in this initial scaffold.
"""
from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Secret Wards privacy firewall (scaffold)")
    parser.add_argument("--input", required=True, help="input directory (read-only)")
    parser.add_argument("--output", required=True, help="output directory")
    return parser


def main() -> int:
    build_parser().parse_args()
    print(
        "Secret Wards pipeline is not implemented yet; no files were processed.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
