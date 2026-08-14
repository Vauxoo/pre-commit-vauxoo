"""Detection-parity between ruff-odoo (this project's ODOO/OAPP linter group)
and pylint-odoo, the tool most ruff-odoo ODOO checks were ported from.

This formalizes, as a permanent regression test, the manual
"ruff check ... | diff pylint-odoo-output" comparison that caught two real
ruff-odoo bugs by hand (a manifest ast.literal_eval-skip gap and a
sql-injection false negative) rather than relying on someone remembering to
repeat that exercise. It reuses pylint-odoo's own EXPECTED_ERRORS dict (loaded
live from the sibling checkout, see tests/_parity_helpers.py) as ground truth
and its own fixture tree (tests/data/test_repo_pylint_odoo, a verbatim copy --
see tests/data/README.md) as input, so both stay authoritative and don't drift
from hand-copied numbers.

See tests/_parity_helpers.py's module docstring for the sibling-checkout
assumption, the decision not to wire this into CI, and how the fixtures are
refreshed.

Three kinds of pylint-odoo checks are handled:

1. Checks with no ruff-odoo rule at all yet (KNOWN_UNPORTED_CHECKS, computed
   from `ruff rule --all`, not hand-maintained): skipped from the strict
   comparison, but the discovered set is asserted against a reviewed literal
   so a newly-ported check is immediately noticed (the set shrinks) and
   starts being compared automatically, and a newly-added-but-not-yet-ported
   pylint-odoo check is also noticed (the set grows).
2. Checks that are ported but whose count doesn't match pylint-odoo's exactly
   (KNOWN_COUNT_DISCREPANCIES), each documented with why, found and verified
   by hand while writing this suite. Comparing against the exact documented
   count (rather than skipping outright) still catches further drift.
3. Everything else: strict count equality.
"""

# pylint:disable=redefined-outer-name
# Pytest fixtures used as plain function parameters (rather than through a
# unittest-style class, as tests/test_pre_commit_vauxoo.py does) legitimately
# share a name with their fixture function; pylint doesn't understand pytest
# fixture injection and flags every use as shadowing.

from __future__ import annotations

import pytest

from _parity_helpers import (
    PYLINT_ODOO_FIXTURE,
    all_rule_names,
    assert_dict_equal,
    find_ruff_odoo_binary,
    load_pylint_odoo_test_main,
    run_ruff_odoo,
    ruff_name_for,
    skip_if_prerequisites_missing,
)

# pylint-odoo checks with no ruff-odoo rule yet. Computed each run from
# `ruff rule --all` (see KNOWN_UNPORTED_CHECKS fixture below) and asserted
# against this literal so the list is a living, reviewed record: it must be
# updated by hand (in either direction) whenever a check gets ported or a new
# pylint-odoo check appears, which is the point -- a silent, un-reviewed
# change here would mean the parity comparison quietly started (or stopped)
# covering a check.
KNOWN_UNPORTED_CHECKS = {
    "manifest-version-format",
}

# pylint-odoo checks that ARE ported (a ruff-odoo rule with the mapped name
# exists) but whose count doesn't match pylint-odoo's exactly, each with the
# currently-verified ruff-odoo count and why. Excluded from the strict
# per-check equality loop below, but still asserted against these exact
# counts so further drift is caught.
KNOWN_COUNT_DISCREPANCIES = {
    # 3 occurrences in the fixture carry a `# pylint: disable=no-write-in-compute`
    # comment that pylint-odoo honors (suppressing them) but ruff-odoo can't:
    # ruff only understands its own "noqa" comment syntax, not pylint's pragma (this is the
    # exact gap the pylint-disable-comment rule exists to help migrate away
    # from). See broken_model.py lines 220, 241, 305.
    "no-write-in-compute": 19,
    # Same cause as no-write-in-compute: broken_model.py:1179 carries a
    # `# pylint: disable=no-wizard-in-models` comment pylint-odoo honors and
    # ruff-odoo does not.
    "no-wizard-in-models": 2,
    # broken_module/__openerp__.py lists "duplicated.xml" twice under the same
    # manifest data key. pylint-odoo's resource-not-exist checks for the
    # file's existence once per unique filename (the duplication itself is a
    # separate manifest-data-duplicated hit); ruff-odoo's port checks each
    # manifest entry independently, so it reports the missing file for both
    # listed positions.
    "resource-not-exist": 5,
    # ruff-odoo's translation-required only covers untranslated string
    # arguments to message_post(...). pylint-odoo also flags untranslated
    # strings raised via UserError(...)/Warning(...), which ruff-odoo does
    # not detect yet (5 fixture occurrences at broken_model.py:681-733).
    "translation-required": 11,
}

# pylint-odoo checks whose --valid-odoo-versions gating ruff-odoo's
# --odoo-version doesn't reproduce yet: ruff-odoo currently reports these
# regardless of the Odoo version passed, while pylint-odoo only reports them
# from a given version onward. Excluded from the version-scoped comparison.
KNOWN_VERSION_GATING_GAPS = {
    "deprecated-odoo-model-method",  # never gated by ruff-odoo; pylint-odoo gates it off before 17.0
    "prefer-env-translation",  # never gated by ruff-odoo; pylint-odoo gates it off before 18.0
}

# A handful of representative Odoo versions spanning pylint-odoo's
# CHECKS_BY_ODOO_VERSION exclusion boundaries (see pylint-odoo/tests/test_main.py),
# not the full version matrix, to keep this bounded.
REPRESENTATIVE_ODOO_VERSIONS = ["14.0", "17.0", "20.0"]


@pytest.fixture(autouse=True)
def _skip_if_missing():
    skip_if_prerequisites_missing(need_pylint_odoo=True)


@pytest.fixture(scope="module")
def pylint_odoo_test_main():
    return load_pylint_odoo_test_main()


@pytest.fixture(scope="module")
def ruff_bin():
    ruff_bin = find_ruff_odoo_binary()
    assert ruff_bin, "find_ruff_odoo_binary() must not return None once skip_if_prerequisites_missing passed"
    return ruff_bin


def test_known_unported_checks_are_up_to_date(pylint_odoo_test_main, ruff_bin):
    """The computed set of pylint-odoo checks with no ruff-odoo rule yet must
    match the reviewed KNOWN_UNPORTED_CHECKS literal above. A mismatch means
    a check was ported (the discovered set shrank -- update the literal and
    move the check into the strict comparison or KNOWN_COUNT_DISCREPANCIES)
    or pylint-odoo gained a new check (the discovered set grew -- update the
    literal to acknowledge the new gap)."""
    ruff_names = all_rule_names(ruff_bin)
    discovered_unported = {
        check for check in pylint_odoo_test_main.EXPECTED_ERRORS if ruff_name_for(check) not in ruff_names
    }
    assert discovered_unported == KNOWN_UNPORTED_CHECKS, (
        "The set of not-yet-ported pylint-odoo checks changed. Update KNOWN_UNPORTED_CHECKS "
        "in tests/test_ruff_odoo_parity.py to match, and if a check was newly ported, verify "
        "its count now matches (it will start being compared automatically once removed here)."
    )


def test_detection_parity(pylint_odoo_test_main, ruff_bin):
    """Per-check detection count parity between pylint-odoo and ruff-odoo
    across the whole pylint-odoo fixture tree, for every check that isn't a
    known gap (see the module docstring)."""
    expected_errors = pylint_odoo_test_main.EXPECTED_ERRORS
    ruff_counts = run_ruff_odoo(ruff_bin, PYLINT_ODOO_FIXTURE)

    strict_checks = {
        check: count
        for check, count in expected_errors.items()
        if check not in KNOWN_UNPORTED_CHECKS and check not in KNOWN_COUNT_DISCREPANCIES
    }
    actual = {check: ruff_counts.get(ruff_name_for(check), 0) for check in strict_checks}
    assert_dict_equal(actual, strict_checks, "ruff-odoo vs pylint-odoo detection count mismatch")


def test_known_count_discrepancies_are_up_to_date(ruff_bin):
    """The documented (understood, non-blocking) count discrepancies must
    still hold exactly. A mismatch here means either the discrepancy was
    fixed (great -- move the check into the strict comparison) or a new
    regression appeared on top of the already-known gap (investigate)."""
    ruff_counts = run_ruff_odoo(ruff_bin, PYLINT_ODOO_FIXTURE)
    actual = {check: ruff_counts.get(ruff_name_for(check), 0) for check in KNOWN_COUNT_DISCREPANCIES}
    assert_dict_equal(actual, KNOWN_COUNT_DISCREPANCIES, "Known ruff-odoo/pylint-odoo count discrepancy drifted")


@pytest.mark.parametrize("odoo_version", REPRESENTATIVE_ODOO_VERSIONS)
def test_detection_parity_by_odoo_version(pylint_odoo_test_main, ruff_bin, odoo_version):
    """The same per-check parity holds when both tools are restricted to a
    specific Odoo version (pylint-odoo's --valid-odoo-versions vs
    ruff-odoo's --odoo-version), for checks whose version gating isn't a
    documented gap (KNOWN_VERSION_GATING_GAPS).

    Iterates over the *unversioned* EXPECTED_ERRORS keys (not just the ones
    pylint-odoo still reports at this version) so a check ruff-odoo fails to
    gate off would show up as a mismatch (expected 0, actual non-zero), not
    silently pass by never being compared.
    """
    tm = pylint_odoo_test_main.TestMain()
    tm.setup_method(None)
    try:
        tm.default_extra_params += [f"--valid-odoo-versions={odoo_version}"]
        pylint_res = tm.run_pylint(tm.paths_modules)
        pylint_by_version = dict(pylint_res.linter.stats.by_msg)
    finally:
        # run_pylint() extends sys.path with every fixture path; TestMain's own
        # teardown_method() is what restores it (see pylint-odoo/tests/test_main.py).
        # Without this, sys.path leaks across the 3 parametrized versions and into
        # whatever test runs next in the same pytest-xdist worker.
        tm.teardown_method(None)

    ruff_counts = run_ruff_odoo(ruff_bin, PYLINT_ODOO_FIXTURE, odoo_version=odoo_version)

    checks = {
        check
        for check in tm.expected_errors
        if check not in KNOWN_UNPORTED_CHECKS
        and check not in KNOWN_COUNT_DISCREPANCIES
        and check not in KNOWN_VERSION_GATING_GAPS
    }
    expected = {check: pylint_by_version.get(check, 0) for check in checks}
    actual = {check: ruff_counts.get(ruff_name_for(check), 0) for check in checks}
    assert_dict_equal(
        actual, expected, f"ruff-odoo vs pylint-odoo detection count mismatch for --odoo-version={odoo_version}"
    )
