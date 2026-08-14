"""Detection-parity between ruff-odoo (this project's ODOO/OAPP linter group)
and odoo-pre-commit-hooks' oca-checks-odoo-module, the second tool ruff-odoo
ports checks from.

See tests/test_ruff_odoo_parity.py's module docstring for the general design
(this test reuses the same tests/_parity_helpers.py plumbing), and
tests/_parity_helpers.py's module docstring for the sibling-checkout
assumption and why this isn't wired into CI.

As of this writing, none of odoo-pre-commit-hooks' checks (all XML/CSV/PO/manifest-
structure focused: xml-*, csv-*, manifest-syntax-error, file-not-used,
weblate-component-too-long, prefer-readme-rst) have been ported to ruff-odoo
yet -- ruff-odoo's ODOO/OAPP group so far only covers pylint-odoo's
Python-AST-focused checks. So this file's job today is smaller than
test_ruff_odoo_parity.py's: it asserts that the "not yet ported" set is
exactly what's expected (a newly-ported check would shrink it, which is the
signal to add a real per-check comparison here, mirroring
test_detection_parity in test_ruff_odoo_parity.py), and that ruff-odoo
reports zero hits for every one of those still-unported checks (so a
newly-added-but-unnoticed rule with a colliding name would be caught
immediately instead of silently double-reporting).
"""

# pylint:disable=redefined-outer-name
# Pytest fixtures used as plain function parameters (rather than through a
# unittest-style class, as tests/test_pre_commit_vauxoo.py does) legitimately
# share a name with their fixture function; pylint doesn't understand pytest
# fixture injection and flags every use as shadowing.

from __future__ import annotations

import pytest

from _parity_helpers import (
    OCA_HOOKS_FIXTURE,
    all_rule_names,
    assert_dict_equal,
    find_ruff_odoo_binary,
    load_oca_hooks_test_checks,
    run_ruff_odoo,
    ruff_name_for,
    skip_if_prerequisites_missing,
)

# odoo-pre-commit-hooks checks with no ruff-odoo rule yet. Computed each run
# from `ruff rule --all` and asserted against this literal so the list is a
# living, reviewed record -- see test_ruff_odoo_parity.py's
# KNOWN_UNPORTED_CHECKS for the full rationale (same pattern, mirrored here).
KNOWN_UNPORTED_CHECKS = {
    "csv-duplicate-record-id",
    "csv-syntax-error",
    "file-not-used",
    "manifest-syntax-error",
    "prefer-readme-rst",
    "weblate-component-too-long",
    "xml-create-user-wo-reset-password",
    "xml-dangerous-qweb-replace-low-priority",
    "xml-deprecated-data-node",
    "xml-deprecated-oe-chatter",
    "xml-deprecated-openerp-node",
    "xml-deprecated-qweb-directive",
    "xml-deprecated-qweb-directive-15",
    "xml-deprecated-tree-attribute",
    "xml-duplicate-fields",
    "xml-duplicate-record-id",
    "xml-duplicate-template-id",
    "xml-field-bool-without-eval",
    "xml-field-numeric-without-eval",
    "xml-header-missing",
    "xml-header-wrong",
    "xml-not-valid-char-link",
    "xml-oe-structure-missing-id",
    "xml-record-missing-id",
    "xml-redundant-module-name",
    "xml-syntax-error",
    "xml-tag-position",
    "xml-template-prettier-incompatible",
    "xml-view-dangerous-replace-low-priority",
    "xml-xpath-translatable-item",
}


@pytest.fixture(autouse=True)
def _skip_if_missing():
    skip_if_prerequisites_missing(need_oca_hooks=True)


@pytest.fixture(scope="module")
def oca_hooks_test_checks():
    return load_oca_hooks_test_checks()


@pytest.fixture(scope="module")
def ruff_bin():
    ruff_bin = find_ruff_odoo_binary()
    assert ruff_bin, "find_ruff_odoo_binary() must not return None once skip_if_prerequisites_missing passed"
    return ruff_bin


def test_known_unported_checks_are_up_to_date(oca_hooks_test_checks, ruff_bin):
    """The computed set of odoo-pre-commit-hooks checks with no ruff-odoo
    rule yet must match the reviewed KNOWN_UNPORTED_CHECKS literal above.
    A shrink means a check was ported (add a real per-check count comparison
    here, mirroring test_ruff_odoo_parity.py's test_detection_parity); a
    growth means odoo-pre-commit-hooks gained a new check."""
    ruff_names = all_rule_names(ruff_bin)
    discovered_unported = {
        check for check in oca_hooks_test_checks.EXPECTED_ERRORS if ruff_name_for(check) not in ruff_names
    }
    assert discovered_unported == KNOWN_UNPORTED_CHECKS, (
        "The set of not-yet-ported odoo-pre-commit-hooks checks changed. Update "
        "KNOWN_UNPORTED_CHECKS in tests/test_oca_hooks_parity.py to match, and if a check was "
        "newly ported, add a real detection-count comparison for it instead of leaving it here."
    )


def test_unported_checks_still_exclusively_caught_by_oca_hooks(ruff_bin):
    """ruff-odoo must report zero hits for every check odoo-pre-commit-hooks
    still exclusively covers. This is the tripwire for the migration
    happening without this suite being updated: if ruff-odoo starts
    reporting a rule under one of these names, either a new ruff-odoo rule
    collides with an odoo-pre-commit-hooks check name, or the check was
    ported and KNOWN_UNPORTED_CHECKS above needs to shrink."""
    ruff_counts = run_ruff_odoo(ruff_bin, OCA_HOOKS_FIXTURE)
    actual = {check: ruff_counts.get(ruff_name_for(check), 0) for check in KNOWN_UNPORTED_CHECKS}
    expected = dict.fromkeys(KNOWN_UNPORTED_CHECKS, 0)
    assert_dict_equal(actual, expected, "ruff-odoo unexpectedly reported hits for a not-yet-ported oca_hooks check")
