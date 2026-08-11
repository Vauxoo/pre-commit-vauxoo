#!/usr/bin/env python3
"""Prototype: run pylint ONCE (mandatory+optional+experimental checks all
enabled together) and split the findings into 3 report sections using the
check_buckets.yaml mapping built by build_check_buckets.py.

Goal: avoid the 3x full AST re-parse that happens today when
pre-commit-vauxoo invokes `pylint --rcfile=.pylintrc`,
`pylint --rcfile=.pylintrc-optional` and `pylint --rcfile=.pylintrc-experimental`
as 3 separate processes over the same file set.

This script is a standalone prototype for benchmarking. It intentionally does
NOT touch pre_commit_vauxoo.py / the real CLI.

Usage:
    pylint_unified.py <cfg_dir> <check_buckets.yaml> <path> [<path> ...]
"""

import argparse
import json
import subprocess
import sys
from configparser import ConfigParser
from pathlib import Path

import yaml

MSG_TEMPLATE = "{path}:{line}:{column}: ({symbol}) {message}"
BUCKET_TITLES = {
    "mandatory": "pylint mandatory checks",
    "optional": "pylint optional checks",
    "experimental": "pylint EXPERIMENTAL checks (Won't affect CI status)!",
}


def build_merged_rcfile(cfg_dir, buckets, out_path):
    cfg_dir = Path(cfg_dir)
    mandatory = ConfigParser(inline_comment_prefixes=("#", ";"))
    mandatory.read(cfg_dir / ".pylintrc")
    optional = ConfigParser(inline_comment_prefixes=("#", ";"))
    optional.read(cfg_dir / ".pylintrc-optional")

    disabled_ids = sorted(k for k, v in buckets.items() if v == "disabled")

    # Merge check-specific option sections that optional/experimental override
    # for checks that only run under their bucket (e.g. optional's
    # max-complexity=15 for the mccabe-based too-complex check, which
    # mandatory's rcfile doesn't set at all since it disables that check).
    # [ODOOLINT]: union of both, optional's values win on conflict
    # (mandatory doesn't define license-allowed at all).
    for section in ("ODOOLINT", "DESIGN"):
        if optional.has_section(section):
            if not mandatory.has_section(section):
                mandatory.add_section(section)
            for key, value in optional.items(section):
                mandatory.set(section, key, value)

    mandatory.set("MESSAGES CONTROL", "enable", "all")
    mandatory.set("MESSAGES CONTROL", "disable", ",".join(disabled_ids))

    with Path(out_path).open("w") as f:
        mandatory.write(f)


def run_pylint(rcfile, targets):
    cmd = [
        sys.executable,
        "-m",
        "pylint",
        f"--rcfile={rcfile}",
        "--load-plugins=pylint.extensions.docstyle,pylint.extensions.mccabe,pylint_odoo",
        "--output-format=json",
        "--jobs=0",
        *targets,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return proc.stdout, proc.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cfg_dir")
    parser.add_argument("buckets_yaml")
    parser.add_argument("targets", nargs="+")
    args = parser.parse_args()

    with Path(args.buckets_yaml).open() as f:
        buckets = yaml.safe_load(f)

    merged_rcfile = "/tmp/.pylintrc-unified"
    build_merged_rcfile(args.cfg_dir, buckets, merged_rcfile)

    stdout, _ = run_pylint(merged_rcfile, args.targets)
    try:
        findings = json.loads(stdout) if stdout.strip() else []
    except json.JSONDecodeError:
        print("Could not parse pylint JSON output:", file=sys.stderr)
        print(stdout[:2000], file=sys.stderr)
        sys.exit(2)

    sections = {"mandatory": [], "optional": [], "experimental": [], "unclassified": []}
    for item in findings:
        bucket = buckets.get(item["symbol"], "unclassified")
        sections[bucket].append(item)

    if sections["unclassified"]:
        symbols = sorted({i["symbol"] for i in sections["unclassified"]})
        print(f"WARNING: unclassified check ids hit (treating as mandatory): {symbols}", file=sys.stderr)
        sections["mandatory"].extend(sections["unclassified"])

    for bucket in ("mandatory", "optional", "experimental"):
        title = BUCKET_TITLES[bucket]
        items = sections[bucket]
        print(f"\n{title}\n{'-' * len(title)}")
        for item in items:
            print(MSG_TEMPLATE.format(**item))
        print(f"({len(items)} findings)")

    sys.exit(1 if sections["mandatory"] else 0)


if __name__ == "__main__":
    main()
