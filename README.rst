========
Overview
========

.. image:: https://www.vauxoo.com/logo.png
   :alt: Vauxoo
   :target: https://www.vauxoo.com/


.. start-badges

.. list-table::
    :stub-columns: 1

    * - docs
      - | |docs|
    * - tests
      - | |github-actions| |codecov|
    * - package
      - | |version| |
        | |commits-since| |
        | |supported-versions| |
        | |wheel|

.. |docs| image:: https://readthedocs.org/projects/pre-commit-vauxoo/badge/?style=flat
    :target: https://pre-commit-vauxoo.readthedocs.io/
    :alt: Documentation Status

.. |github-actions| image:: https://github.com/Vauxoo/pre-commit-vauxoo/actions/workflows/github-actions.yml/badge.svg
    :alt: GitHub Actions Build Status
    :target: https://github.com/Vauxoo/pre-commit-vauxoo/actions

.. .. |requires| image:: https://requires.io/github/Vauxoo/pre-commit-vauxoo/requirements.svg?branch=main
..     :alt: Requirements Status
..     :target: https://requires.io/github/Vauxoo/pre-commit-vauxoo/requirements/?branch=main

.. |codecov| image:: https://codecov.io/gh/Vauxoo/pre-commit-vauxoo/branch/main/graphs/badge.svg?branch=main
    :alt: Coverage Status
    :target: https://app.codecov.io/github/Vauxoo/pre-commit-vauxoo

.. |version| image:: https://img.shields.io/pypi/v/pre-commit-vauxoo.svg
    :alt: PyPI Package latest release
    :target: https://pypi.org/project/pre-commit-vauxoo

.. |wheel| image:: https://img.shields.io/pypi/wheel/pre-commit-vauxoo.svg
    :alt: PyPI Wheel
    :target: https://pypi.org/project/pre-commit-vauxoo

.. |supported-versions| image:: https://img.shields.io/pypi/pyversions/pre-commit-vauxoo.svg
    :alt: Supported versions
    :target: https://pypi.org/project/pre-commit-vauxoo

.. |commits-since| image:: https://img.shields.io/github/commits-since/Vauxoo/pre-commit-vauxoo/v8.3.13.svg
    :alt: Commits since latest release
    :target: https://github.com/Vauxoo/pre-commit-vauxoo/compare/v8.3.13...main



.. end-badges

pre-commit script to run automatically the configuration and variables custom from Vauxoo

* Free software: GNU Lesser General Public License v3 or later (LGPLv3+)

Installation
============

Install in the same way than you usually install pypi packages

    python3 -m pip install --force-reinstall -U pre-commit-vauxoo

Or using 'sudo':

    sudo python3 -m pip install --force-reinstall -U pre-commit-vauxoo

Or using '--user':

    python3 -m pip install --user --force-reinstall -U pre-commit-vauxoo

Or using virtualenv

    source YOUR_VENV/bin/activate && pip install --force-reinstall -U pre-commit-vauxoo

You can confirm your environment running `pre-commit-vauxoo --version`

Usage
=====

Run pre-commit-vauxoo command in git repository where you want to run our lints

The autofixes are disabled by default you can use the following option to enable it

  pre-commit-vauxoo -t all

By default the hooks run on the whole repository (``--all``), which is what the CI does.
While developing you usually only need to check what you are working on, so use one of
the following options to get a faster result:

    pre-commit-vauxoo --diff  # only the changes not committed yet (staged, unstaged and untracked)

    pre-commit-vauxoo --last-commit  # only the files added or modified by the last commit

Full --help command result:

::

  Usage: pre-commit-vauxoo [OPTIONS]

    pre-commit-vauxoo run pre-commit with custom validations and configuration
    files

  Options:
    -p, --paths PATH CSV            PATHS are the specific filenames to run
                                    hooks on separated by commas.  [env var:
                                    INCLUDE_LINT; default: .]
    --all                           Run the hooks on the whole repository. It
                                    is the default one.
    --last-commit                   Run the hooks only on the files added or
                                    modified by the last commit (HEAD).
    --diff                          Run the hooks only on the files with
                                    changes not committed yet: staged,
                                    unstaged and untracked ones.
    --no-overwrite                  Overwrite configuration files.

                                    *If True, existing configuration files into
                                    the project will be overwritten.

                                    *If False, then current files will be used,
                                    if they exist.  [env var:
                                    PRECOMMIT_NO_OVERWRITE_CONFIG_FILES]
    --fail-optional                 Change the exit_code for 'optional'
                                    precommit-hooks-type.

                                    *If this flag is enabled so the exit_code
                                    will be -1 (error) if 'optional' fails.

                                    *If it is disabled (by default), exit_code
                                    will be 0 (successful) even if 'optional'
                                    fails.  [env var: PRECOMMIT_FAIL_OPTIONAL]
    -x, --exclude-autofix PATH CSV  Exclude paths on which to run the autofix
                                    pre-commit configuration, separated by
                                    commas  [env var: EXCLUDE_AUTOFIX]
    -l, --exclude-lint PATH CSV     Paths to exclude checks, separated by
                                    commas.  [env var: EXCLUDE_LINT]
    -d, --pylint-disable-checks TEXT CSV
                                    Pylint checks to disable, separated by
                                    commas.

                                    The checks migrated to ruff are disabled
                                    from the ruff configuration files too using
                                    their equivalent ruff codes.  [env var:
                                    PYLINT_DISABLE_CHECKS]
    --oca-hooks-disable-checks TEXT CSV
                                    OCA Hooks checks to disable, separated by
                                    commas.  [env var: OCA_HOOKS_DISABLE_CHECKS]
    --ruff-disable-checks TEXT CSV  Ruff checks to disable, separated by commas.
                                    [env var: RUFF_DISABLE_CHECKS]
    -S, --skip-string-normalization
                                    If '-t fix' is enabled, don't normalize
                                    string quotes or prefixes '' -> ""

                                    This parameter is related to 'black' hook
                                    [env var: BLACK_SKIP_STRING_NORMALIZATION]
    -t, --precommit-hooks-type [mandatory|optional|fix|experimental|all|-mandatory|-optional|-fix|-experimental]
                                    Pre-commit configuration file to run hooks,
                                    separated by commas.

                                    prefix '-' means that the option will be
                                    removed.

                                    *Mandatory: Stable hooks that needs to be
                                    fixed (Affecting build status).

                                    *Optional: Optional hooks that could be
                                    fixed later. (No affects build status almost
                                    '--fail-optional' is set).

                                    *Experimental: Experimental hooks that only
                                    to test. (No affects build status).

                                    *Fix: Hooks auto fixing source code (Affects
                                    build status).

                                    *All: All configuration files to run hooks.
                                    [env var: PRECOMMIT_HOOKS_TYPE; default:
                                    all, -fix]
    --install                       Install the pre-commit script

                                    Using this option a '.git/hooks/pre-commit'
                                    will be created

                                    Now your command 'git commit' will run 'pre-
                                    commit-vauxoo --diff' before to commit
    --version                       Show the version of this package
    --odoo-version TEXT             Odoo version used for the repository.

                                    It enables/disables the version-dependent
                                    checks in the generated configuration files
                                    (e.g. the ruff ODOO* checks) and maps the
                                    ruff target-version python value.  [env var:
                                    VERSION]
    --is-project-for-apps BOOLEAN   It is a project for apps (manifest with
                                    price) enabling special pylint checks  [env
                                    var: PRECOMMIT_IS_PROJECT_FOR_APPS]
    --only-cp-cfg                   Only copy configuration files without
                                    running the pre-commit script
    --compatibility-version COMPATIBILITY-VERSION
                                    Defines the compatibility and behavior level
                                    for each linter tooling.

                                    This parameter controls how aggressive or
                                    modern the enabled linters, formatters, and
                                    autofixes are. Each position in the version
                                    represents a specific tool and its behavior
                                    level.

                                    Lower values prioritize backward
                                    compatibility and minimal diffs. Higher
                                    values enable newer versions, stricter
                                    rules, and more aggressive autofixes.

                                    Default: 10.10.10.10.10.10.10.10.10.10

                                    Example: * 0.0.0.0.0.0.0 → Using zero 0 or
                                    not defined will use the latest behavior
                                    ever * 10.10.10.10.10.10.10 → Freeze old
                                    behavior <=2025 year (safe, backward-
                                    compatible) * 20.20.20.20.20.20.20 → Enable
                                    new 2026 behaviors and aggressive autofixes
                                    * (future changes may add more values) *
                                    Mixed values (e.g. 10.20.10.20.0.20) allow
                                    fine-grained control per tool

                                    Tool order: 🟢 1. Prettier (20 → Enable XML
                                    aggressive whitespace fixes) 🟢 2. OCA hooks
                                    https://github.com/OCA/odoo-pre-commit-hooks
                                    (20 → rm py headers, rm unused logger,
                                    change xml id position first, change xml
                                    bool/integer to eval,      add xml-header-
                                    missing uppercase, mv README.md to
                                    README.rst,      change py _('translation')
                                    to self.env._('translation'), rm manifest
                                    superfluous keys, rm field-string-redundant)
                                    🟢 3. ESLint 🟢 4. Black / Autoflake (30 →
                                    Use ruff instead. It also migrates to ruff
                                    the mandatory and optional pylint/flake8
                                    checks already implemented in ruff,
                                    disabling them from the original tool) 🟢 5.
                                    pre-commit framework 🟢 6. Pylint/pylint-
                                    odoo 🟢 7. flake8

                                    ⚠️ Higher values or empty valuesmay
                                    introduce formatting changes, stricter
                                    linting, or non-backward-compatible fixes
                                    (especially for XML, Python, and JS files).
                                    [env var: LINT_COMPATIBILITY_VERSION]
    --help                          Show this message and exit.


.. Documentation
.. =============


.. https://pre-commit-vauxoo.readthedocs.io/


AI Agents Integration
=====================

``pre-commit-vauxoo`` natively ships with an AI Agent Skill (located in the ``.agents/skills/`` directory). This skill provides context to your AI assistants (such as Cursor, Claude Desktop, or Gemini) on how to properly handle pre-commit hooks in Vauxoo and OCA repositories, preventing silent CI failures and handling headless TTY environments correctly.

To enable this globally across all your projects, create a symbolic link from your local clone of ``pre-commit-vauxoo`` to your global AI skills directory.

For **Gemini / Antigravity**:
::

    ln -sfn /path/to/your/clone/pre-commit-vauxoo/.agents/skills/vauxoo-pre-commit ~/.gemini/antigravity/skills/vauxoo-pre-commit

For **Cursor** (using custom rules):
::

    ln -sfn /path/to/your/clone/pre-commit-vauxoo/.agents/skills/vauxoo-pre-commit/SKILL.md ~/.cursorrules_precommit

Once linked, your AI agents will automatically know they must verify and enforce ``pre-commit`` rules before attempting to commit code in the ecosystem.

Development
===========

To run all the tests run::

    tox

Use extra parameters to change the test behaviour.

e.g. particular python version::

    tox -e py310

e.g. particular unittest method::

    tox -e py310 -- -k test_basic

e.g. all the tests at the same time in parallel::

    tox -p auto


Note, to combine the coverage data from all the tox environments run:

.. list-table::
    :widths: 10 90
    :stub-columns: 1

    - - Windows
      - ::

            set PYTEST_ADDOPTS=--cov-append
            tox

    - - Other
      - ::

            PYTEST_ADDOPTS=--cov-append tox

Updating the pylint-odoo and ruff-odoo revs
-------------------------------------------

pylint-odoo and ruff-odoo release often so their revs in the
``.pre-commit-config*.yaml.jinja`` templates have their own standalone
bump2version configuration files::

    bump2version --config-file=.b2v-pylint.cfg patch
    bump2version --config-file=.b2v-ruff.cfg build

Use ``--new-version`` to jump to an arbitrary release::

    bump2version --config-file=.b2v-pylint.cfg patch --new-version 10.0.11
    bump2version --config-file=.b2v-ruff.cfg build --new-version 0.16.3.28

Each command updates only its own hook revs (the lines anchored with the
``{# b2v-pylint #}`` / ``{# b2v-ruff #}`` jinja comments, stripped when the
templates are rendered), then creates the commit reusing the usual
``[IMP] cfg: Update <tool> to <version>`` message, without creating tags and
without touching the package's own ``.bumpversion.cfg``.
