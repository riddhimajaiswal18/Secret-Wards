#!/usr/bin/env python3
"""Secret Wards runner.

Reads --input, writes --output, never modifies the input tree. The key comes from the
environment and is never logged, echoed or written to any file.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from src.pipeline import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Secret Wards privacy firewall")
    parser.add_argument("--input", required=True, help="input directory (read-only)")
    parser.add_argument("--output", required=True, help="output directory")
    parser.add_argument("--policy", default=os.environ.get("RAKSHA_POLICY", "config/policy.yaml"),
                        help="policy file (default: config/policy.yaml)")
    parser.add_argument("--submission", default="secret-wards")
    parser.add_argument("--quiet", action="store_true", help="only warnings on stderr")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO,
                        format="%(levelname)s %(message)s", stream=sys.stderr)
    if not Path(args.input).is_dir():
        print(f"input directory not found: {args.input}", file=sys.stderr)
        return 2
    run(args.input, args.output, policy_path=args.policy, submission=args.submission)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
