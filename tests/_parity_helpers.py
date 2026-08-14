"""Shared plumbing for the ruff-odoo detection-parity test suite.

``test_ruff_odoo_parity.py`` and ``test_oca_hooks_parity.py`` both compare
ruff-odoo's ``ODOO*``/``OAPP*`` rule group detection counts against the
ground-truth ``EXPECTED_ERRORS`` dicts owned by the two upstream tools it
ports checks from (``pylint-odoo`` and ``odoo-pre-commit-hooks``). This module
factors out the ~80% of logic both test files share: locating a ruff-odoo
binary, running it and tallying rule-name occurrences, loading the upstream
``EXPECTED_ERRORS`` dicts straight from the sibling checkouts (instead of
hand-copying numbers that would silently drift), and the rename table used to
map an upstream check name onto the ruff-odoo rule name that covers it.

Sibling-checkout assumption
----------------------------
These are local dev-machine parity tests. They assume the Vauxoo standard
layout of keeping every repo directly under ``~/odoo/<repo-name>``, so they
can read the *live* ``EXPECTED_ERRORS`` dicts and fixture trees from
``~/odoo/pylint-odoo`` and ``~/odoo/odoo-pre-commit-hooks`` rather than
duplicating numbers by hand (numbers that would then drift the moment those
tools gain a new check or fixture case). Every test in both files calls
``skip_if_prerequisites_missing()`` first and calls ``pytest.skip(...)`` with
a clear reason when a sibling checkout or the ruff-odoo binary isn't
available, so the suite degrades gracefully on any machine that doesn't have
this exact layout (e.g. CI, see below).

CI decision
-----------
This suite is intentionally **not** wired into ``.github/workflows/github-actions.yml``.
Doing so would require: (1) checking out two extra sibling repos, (2) installing
a Rust toolchain and running a `cargo build` for ruff-odoo (this project's own
CI has neither today), and (3) accepting the extra runtime across an already
sizeable os/python matrix. Given ruff-odoo is invoked here as a subprocess
binary (not a pip dependency of this project), and pre-commit-vauxoo's CI
otherwise never builds Rust code, that's a disproportionate amount of new CI
surface for what is fundamentally a local "did I just introduce a regression"
sanity check. The tests are written to skip cleanly where the prerequisites
aren't present, so they cost nothing in CI today; wiring up a dedicated,
opt-in CI job (sibling checkouts + a cached `cargo build`) is a reasonable
follow-up if this suite proves valuable, but is left out of scope here.

Refreshing the fixture copies
------------------------------
``tests/data/test_repo_pylint_odoo`` and ``tests/data/test_repo_oca_hooks``
are verbatim copies of the upstream fixture trees (see ``tests/data/README.md``).
Do not hand-edit them; regenerate with::

    rm -rf tests/data/test_repo_pylint_odoo && cp -r ~/odoo/pylint-odoo/testing/resources/test_repo tests/data/test_repo_pylint_odoo
    rm -rf tests/data/test_repo_oca_hooks && cp -r ~/odoo/odoo-pre-commit-hooks/test_repo tests/data/test_repo_oca_hooks
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import types
from collections import Counter
from pathlib import Path

import pytest

HOME_ODOO = Path(os.path.expanduser("~/odoo"))
PYLINT_ODOO_REPO = HOME_ODOO / "pylint-odoo"
OCA_HOOKS_REPO = HOME_ODOO / "odoo-pre-commit-hooks"
RUFF_ODOO_REPO = HOME_ODOO / "ruff-odoo"

DATA_DIR = Path(__file__).resolve().parent / "data"
PYLINT_ODOO_FIXTURE = DATA_DIR / "test_repo_pylint_odoo"
OCA_HOOKS_FIXTURE = DATA_DIR / "test_repo_oca_hooks"

# Plain-name renames from ruff-odoo's own MESSAGE_ALIASES table. Only the
# pylint-odoo/pylint plain check-name entries are ported here (not the pylint
# message-code entries like "C8101"/"E8102", which are irrelevant for this
# count-based comparison). Keep in sync with:
# ~/odoo/ruff-odoo/crates/ruff_linter/src/rules/odoo/rules/pylint_disable_comment.rs
PYLINT_TO_RUFF_ALIASES = {
    "attribute-string-redundant": "field-string-redundant",
    "consider-merging-classes-inherited": "duplicate-inherited-model-extension",
    "prefer-env-translation": "direct-translation-call",
    "print-used": "print",
    "too-complex": "complex-structure",
    "translation-positional-used": "translation-positional",
    "use-vim-comment": "vim-comment",
}

# Renamed aliases whose ruff rule lives in a linter group outside ODOO/OAPP
# (pylint-odoo reused these checks from upstream Ruff/pylint rather than
# reimplementing them), so their rule codes must be added to --select
# explicitly alongside "ODOO,OAPP".
EXTRA_SELECT_CODES = {"print": "T201", "complex-structure": "C901"}

RULE_LINE_RE = re.compile(r"^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+): (?P<rule>[\w-]+): ")


def skip_if_prerequisites_missing(*, need_pylint_odoo=False, need_oca_hooks=False):
    """Skip the current test when a required sibling checkout or the
    ruff-odoo binary isn't available on this machine."""
    if need_pylint_odoo and not PYLINT_ODOO_REPO.is_dir():
        pytest.skip(f"Sibling checkout not found: {PYLINT_ODOO_REPO} (see tests/_parity_helpers.py docstring)")
    if need_oca_hooks and not OCA_HOOKS_REPO.is_dir():
        pytest.skip(f"Sibling checkout not found: {OCA_HOOKS_REPO} (see tests/_parity_helpers.py docstring)")
    if find_ruff_odoo_binary() is None:
        pytest.skip(
            "No ruff-odoo binary found. Build one with: cd ~/odoo/ruff-odoo && "
            "CARGO_PROFILE_DEV_OPT_LEVEL=1 CARGO_PROFILE_DEV_LTO=off "
            'CARGO_PROFILE_DEV_DEBUG="line-tables-only" cargo build --bin ruff -p ruff'
        )


def find_ruff_odoo_binary() -> str | None:
    """Locate a ruff-odoo binary to test against.

    Preference order:
    1. ``RUFF_ODOO_BIN`` environment variable (explicit override, e.g. for a
       future CI job).
    2. A fresh local debug/release build at ``~/odoo/ruff-odoo/target/{debug,release}/ruff``,
       matching this repo's sibling-checkout convention. Preferred over an
       arbitrary PATH ruff so the parity tests exercise today's fixes rather
       than whatever was last published to PyPI/a GitHub release.
    3. ``ruff`` resolved via ``$PATH``, as a last resort.
    """
    env_override = os.environ.get("RUFF_ODOO_BIN")
    if env_override and Path(env_override).is_file():
        return env_override
    for profile in ("debug", "release"):
        candidate = RUFF_ODOO_REPO / "target" / profile / "ruff"
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ruff")


def _rule_catalog(ruff_bin: str) -> list[dict]:
    result = subprocess.run(
        [ruff_bin, "rule", "--all", "--output-format=json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


_RULE_CATALOG_CACHE: dict[str, list[dict]] = {}


def all_rule_names(ruff_bin: str) -> set[str]:
    """Every rule name ruff-odoo currently exposes, across all linter groups
    (not just ODOO/OAPP): some pylint-odoo checks were ported onto a
    pre-existing upstream Ruff rule in another group instead of a native
    ODOO/OAPP rule (e.g. print-used -> print/T201, too-complex ->
    complex-structure/C901, see PYLINT_TO_RUFF_ALIASES). Used to
    programmatically tell apart "not yet ported" pylint-odoo/odoo-pre-commit-hooks
    checks from checks that are ported but merely differ in count."""
    if ruff_bin not in _RULE_CATALOG_CACHE:
        _RULE_CATALOG_CACHE[ruff_bin] = _rule_catalog(ruff_bin)
    catalog = _RULE_CATALOG_CACHE[ruff_bin]
    return {rule["name"] for rule in catalog}


def run_ruff_odoo(ruff_bin: str, path: Path, odoo_version: str | None = None) -> Counter:
    """Run ruff-odoo's ODOO/OAPP rule group (plus the handful of upstream
    Ruff rules that some pylint-odoo checks were ported onto, e.g. print/T201)
    against `path` in a single subprocess call, and return a Counter of
    rule-name -> occurrence count.

    A single full run (mirroring pylint's own one-shot ``linter.stats.by_msg``
    approach in ``pylint-odoo/tests/test_main.py``) keeps this fast instead of
    invoking ruff once per check.
    """
    select = "ODOO,OAPP," + ",".join(sorted(set(EXTRA_SELECT_CODES.values())))
    cmd = [
        ruff_bin,
        "check",
        f"--select={select}",
        "--preview",
        "--no-cache",
        "--isolated",
        "--output-format=concise",
    ]
    if odoo_version:
        cmd.append(f"--odoo-version={odoo_version}")
    cmd.append(str(path))
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    counts: Counter = Counter()
    for line in result.stdout.splitlines():
        match = RULE_LINE_RE.match(line)
        if match:
            counts[match.group("rule")] += 1
    return counts


def ruff_name_for(check_name: str) -> str:
    """Map an upstream (pylint-odoo/odoo-pre-commit-hooks) check name to the
    ruff-odoo rule name that covers it, defaulting to the same name when
    there's no rename in PYLINT_TO_RUFF_ALIASES."""
    return PYLINT_TO_RUFF_ALIASES.get(check_name, check_name)


def _load_module_from_path(module_name: str, file_path: Path):
    """Load a standalone module (no package-relative imports of its own) by
    file path, without touching sys.path or sys.modules under a name that
    could collide with this project's own ``tests`` collection (both
    pylint-odoo and this repo have a ``tests/`` directory)."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_module_as_package_member(pkg_name: str, submodule_name: str, file_path: Path, package_dir: Path):
    """Load `file_path` as `pkg_name.submodule_name`, registering a synthetic
    parent package rooted at `package_dir` first. Needed for modules (like
    odoo-pre-commit-hooks' tests/test_checks.py) that use a package-relative
    import such as ``from . import common``."""
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(package_dir)]
        sys.modules[pkg_name] = pkg
    full_name = f"{pkg_name}.{submodule_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, file_path, submodule_search_locations=[])
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


def _ensure_sibling_src_on_path(src_dir: Path) -> None:
    """Prepend a sibling checkout's `src/` to sys.path if not already present.

    Both `pylint_odoo` and `oca_pre_commit_hooks` may or may not be pip-installed
    in the current environment (e.g. `pylint-odoo` happens to be a declared test
    dependency of this project today, `odoo-pre-commit-hooks` is not -- see
    test-requirements.txt). Relying on whatever happens to be installed would
    silently test a possibly-stale PyPI release instead of the live sibling
    checkout, defeating the point of a parity *oracle*. Prepending (not
    appending) so the live checkout wins over an installed version of the
    same package.
    """
    src_str = str(src_dir)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


def load_pylint_odoo_test_main():
    """Load pylint-odoo's tests/test_main.py from the sibling checkout,
    giving access to its real EXPECTED_ERRORS dict and TestMain.run_pylint
    harness -- the exact ground truth pylint-odoo asserts against itself,
    instead of a hand-copied (and driftable) number."""
    _ensure_sibling_src_on_path(PYLINT_ODOO_REPO / "src")
    return _load_module_from_path("_pylint_odoo_test_main", PYLINT_ODOO_REPO / "tests" / "test_main.py")


def load_oca_hooks_test_checks():
    """Load odoo-pre-commit-hooks' tests/test_checks.py from the sibling
    checkout (via a synthetic parent package so its `from . import common`
    resolves), giving access to its real EXPECTED_ERRORS dict."""
    _ensure_sibling_src_on_path(OCA_HOOKS_REPO / "src")
    tests_dir = OCA_HOOKS_REPO / "tests"
    _load_module_as_package_member("_oca_hooks_tests", "common", tests_dir / "common.py", tests_dir)
    return _load_module_as_package_member("_oca_hooks_tests", "test_checks", tests_dir / "test_checks.py", tests_dir)


def assert_dict_equal(actual: dict, expected: dict, msg: str = ""):
    """Same ordered-diff style helper pylint-odoo's and odoo-pre-commit-hooks'
    own test suites use, so a multi-check mismatch prints a readable diff
    instead of pytest's default (much noisier) dict-diff."""
    diff = []
    for key in sorted(set(actual) | set(expected)):
        if key not in expected:
            diff.append(f"- {key}: {actual[key]}")
        elif key not in actual:
            diff.append(f"+ {key}: {expected[key]}")
        elif actual[key] != expected[key]:
            diff.append(f"~ {key}: expected {expected[key]} -> actual {actual[key]}")
    assert not diff, f"{msg}  {diff}".strip()
