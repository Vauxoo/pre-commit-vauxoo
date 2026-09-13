export INCLUDE_LINT="src,tests,resources,setup.py,docs/conf.py"
export PRECOMMIT_HOOKS_TYPE="all"
# resources/module_autofix1 is excluded from the lint, not only from the autofix below:
# it has to stay unfixed for the autofix tests, and the checks it trips (file-not-used
# and xml-tag-position) were optional until the optional level was merged into the
# mandatory one for ruff
export EXCLUDE_LINT="resources/module_warnings1,resources/module_uninstallable,resources/module_autofix1"
# docs/conf.py keeps a "# pylint: disable=invalid-name,redefined-builtin" that both worlds
# still need: pylint reads it in the matrix without ruff, and in the ruff one the same
# suppression comes from the docs/conf.py per-file-ignores. Letting the autofix migrate
# the pragma to a "# ruff: disable" pair would take it away from pylint
export EXCLUDE_AUTOFIX="resources/module_autofix1,docs/conf.py"
export VERSION="16.0"
export LINT_COMPATIBILITY_VERSION="0.0.0.0.0.0.0.0.0.0"
# "assert" is meant for Odoo addons, whose tests are unittest and assert through
# self.assertX(); this repository is a pytest package, so its own tests are all asserts
export RUFF_DISABLE_CHECKS="print,assert"
