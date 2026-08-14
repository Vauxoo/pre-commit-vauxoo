"""Keep pytest from ever trying to collect/import the verbatim upstream
fixture copies under this directory as test modules.

pytest.ini enables --doctest-modules and --pyargs, and this repo's testpaths
includes "tests/" (not just files matching test_*.py), so without this file
pytest would recurse into tests/data/test_repo_pylint_odoo and
tests/data/test_repo_oca_hooks and try to import every *.py there (including
deliberately-broken fixture files, e.g. syntax_err_module) as doctest
modules, which fails collection outright. These fixture trees are read by
the parity tests as plain files (invoked via a ruff subprocess and/or
compared against upstream EXPECTED_ERRORS dicts), never imported by pytest,
so they must stay out of collection entirely. See tests/_parity_helpers.py
and tests/data/README.md for how they're used and refreshed.
"""

from __future__ import annotations

collect_ignore = ["test_repo_pylint_odoo", "test_repo_oca_hooks"]
