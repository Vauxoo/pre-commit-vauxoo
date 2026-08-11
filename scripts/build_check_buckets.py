#!/usr/bin/env python3
"""Prototype: build a canonical check_id -> bucket mapping from the existing
.pylintrc / .pylintrc-optional / .pylintrc-experimental files, by combining
their enable=/disable= lists with the full universe of known pylint messages
(pylint --list-msgs).

This is the "single source of truth" step of the pylint-unified prototype:
instead of 3 separately-authored enable/disable lists, produce one explicit
mapping that a later single pylint invocation can use to route each finding
to the right report section (mandatory/optional/experimental/disabled).

Usage:
    build_check_buckets.py <rendered .config dir> [-o check_buckets.yaml]
"""

import argparse
import re
import sys
from configparser import ConfigParser
from io import StringIO
from pathlib import Path

import yaml
from pylint.lint import Run

PLUGINS = "pylint.extensions.docstyle,pylint.extensions.mccabe,pylint_odoo"


def get_pylint_universe():
    """Same technique already used by pre-commit-vauxoo's own
    test_valid_pylintrc_messages: enumerate every known check id via
    `pylint --list-msgs`.
    """
    from contextlib import redirect_stdout

    output = StringIO()
    with redirect_stdout(output):
        try:
            Run([f"--load-plugins={PLUGINS}", "--list-msgs"])
        except SystemExit as ex:
            if ex.code:
                raise RuntimeError("pylint --list-msgs failed") from ex
    output.seek(0)
    return set(re.findall(r"^:([a-z\-]+)", output.read(), re.MULTILINE))


def parse_message_list(config, section, key):
    if section not in config or key not in config[section]:
        return set()
    raw = config[section][key]
    return {v.strip() for v in raw.split(",") if v.strip() and v.strip() != "all"}


def load_rcfile(path):
    config = ConfigParser(inline_comment_prefixes=("#", ";"))
    config.read(path)
    return config


def build_buckets(cfg_dir):
    cfg_dir = Path(cfg_dir)
    mandatory = load_rcfile(cfg_dir / ".pylintrc")
    optional = load_rcfile(cfg_dir / ".pylintrc-optional")
    experimental = load_rcfile(cfg_dir / ".pylintrc-experimental")

    mandatory_disabled = parse_message_list(mandatory, "MESSAGES CONTROL", "disable")
    optional_enabled = parse_message_list(optional, "MESSAGES CONTROL", "enable")
    experimental_enabled = parse_message_list(experimental, "MESSAGES CONTROL", "enable")

    universe = get_pylint_universe()

    buckets = {}
    unclassified = set()
    for check_id in sorted(universe):
        if check_id in experimental_enabled:
            buckets[check_id] = "experimental"
        elif check_id in optional_enabled:
            buckets[check_id] = "optional"
        elif check_id in mandatory_disabled:
            buckets[check_id] = "disabled"
        else:
            buckets[check_id] = "mandatory"

    # Sanity: enable= lists should only ever reference real, known checks.
    # (mirrors test_valid_pylintrc_messages, extended to -experimental too)
    for name, ids in (
        ("optional", optional_enabled),
        ("experimental", experimental_enabled),
    ):
        bogus = ids - universe
        if bogus:
            print(f"WARNING: {name} enables unknown check ids: {sorted(bogus)}", file=sys.stderr)

    return buckets, unclassified


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cfg_dir", help="Directory containing rendered .pylintrc*")
    parser.add_argument("-o", "--output", default="check_buckets.yaml")
    args = parser.parse_args()

    buckets, _ = build_buckets(args.cfg_dir)

    counts = {}
    for bucket in buckets.values():
        counts[bucket] = counts.get(bucket, 0) + 1
    print("Bucket counts:", counts, file=sys.stderr)

    with Path(args.output).open("w") as f:
        yaml.safe_dump(buckets, f, sort_keys=True, default_flow_style=False)
    print(f"Wrote {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
