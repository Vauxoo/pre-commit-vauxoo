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

.. |commits-since| image:: https://img.shields.io/github/commits-since/Vauxoo/pre-commit-vauxoo/v8.0.0.svg
    :alt: Commits since latest release
    :target: https://github.com/Vauxoo/pre-commit-vauxoo/compare/v8.0.0...main



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

Full --help command result:

::

  Usage: pre-commit-vauxoo [OPTIONS]

    pre-commit-vauxoo run pre-commit with custom validations and configuration
    files

  Options:
    -p, --paths PATH CSV            PATHS are the specific filenames to run
                                    hooks on separated by commas.  [env var:
                                    INCLUDE_LINT; default: .]
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
                                    commas.  [env var: PYLINT_DISABLE_CHECKS]
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
                                    commit-vauxoo' before to commit
    --version                       Show the version of this package
    --odoo-version TEXT             Odoo version used for the repository.  [env
                                    var: VERSION]
    --help                          Show this message and exit.


.. Documentation
.. =============


.. https://pre-commit-vauxoo.readthedocs.io/


Development
===========

To run all the tests run::

    tox

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
