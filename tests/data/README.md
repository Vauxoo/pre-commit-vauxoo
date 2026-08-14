# Parity fixtures

`test_repo_pylint_odoo/` and `test_repo_oca_hooks/` are verbatim, unedited
copies of the fixture trees the two upstream tools ruff-odoo ports checks
from assert their own `EXPECTED_ERRORS` counts against. They exist so
`tests/test_ruff_odoo_parity.py` and `tests/test_oca_hooks_parity.py` can run
ruff-odoo against the exact same inputs those tools use for their own tests,
and compare detection counts directly.

Do not hand-edit anything under these two directories. If a fixture case
looks wrong or incomplete, that's a signal the copy was taken from the wrong
path or is stale, not something to patch by hand here -- fix it upstream (in
`pylint-odoo` or `odoo-pre-commit-hooks`) and refresh the copy instead.

Refresh them periodically (they will drift as those repos gain new checks or
fixture cases) with:

```sh
rm -rf tests/data/test_repo_pylint_odoo && cp -r ~/odoo/pylint-odoo/testing/resources/test_repo tests/data/test_repo_pylint_odoo
rm -rf tests/data/test_repo_oca_hooks && cp -r ~/odoo/odoo-pre-commit-hooks/test_repo tests/data/test_repo_oca_hooks
```

`~/odoo/pylint-odoo/testing/resources/test_repo_odoo_namespace` is
intentionally *not* copied: it's assigned to an attribute in
`pylint-odoo/tests/test_main.py` but never actually read by any test there
(including `test_20_expected_errors`, the source of the `EXPECTED_ERRORS`
ground truth used here), so it isn't part of what these parity tests need.

See `tests/_parity_helpers.py`'s module docstring for why these tests assume
a local `~/odoo/<repo>` sibling-checkout layout, why they are not wired into
CI, and how they load the upstream `EXPECTED_ERRORS` dicts.
