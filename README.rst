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
    :target: https://codecov.io/github/Vauxoo/pre-commit-vauxoo

.. |version| image:: https://img.shields.io/pypi/v/pre-commit-vauxoo.svg
    :alt: PyPI Package latest release
    :target: https://pypi.org/project/pre-commit-vauxoo

.. |wheel| image:: https://img.shields.io/pypi/wheel/pre-commit-vauxoo.svg
    :alt: PyPI Wheel
    :target: https://pypi.org/project/pre-commit-vauxoo

.. |supported-versions| image:: https://img.shields.io/pypi/pyversions/pre-commit-vauxoo.svg
    :alt: Supported versions
    :target: https://pypi.org/project/pre-commit-vauxoo

.. |commits-since| image:: https://img.shields.io/github/commits-since/Vauxoo/pre-commit-vauxoo/v3.4.0.svg
    :alt: Commits since latest release
    :target: https://github.com/Vauxoo/pre-commit-vauxoo/compare/v3.4.0...main



.. end-badges

pre-commit script to run automatically the configuration and variables custom from Vauxoo

* Free software: GNU Lesser General Public License v3 or later (LGPLv3+)

Installation
============

Using pypi

    pip install -U pre-commit-vauxoo

Using github directly

    pip install -U git+https://github.com/Vauxoo/pre-commit-vauxoo.git@main

Usage
=====

Run pre-commit-vauxoo command in git repository where you want to run our lints

The autofixes are disabled by default you can use the following option to enable it

  pre-commit-vauxoo -f

Full --help command result:

::

  Usage: pre-commit-vauxoo [OPTIONS]

    pre-commit-vauxoo run pre-commit with custom validations and configuration
    files

  Options:
    -p, --paths PATH CSV            PATHS are the specific filenames to run
                                    hooks on separated by commas.  [env var:
                                    INCLUDE_LINT; default: .]
    -w, --overwrite BOOLEAN         Overwrite configuration files.

                                    *If True, existing configuration files into
                                    the project will be overwritten.

                                    *If False, then current files will be used,
                                    if they exist.  [env var:
                                    PRECOMMIT_OVERWRITE_CONFIG_FILES; default:
                                    True]
    -w, --fail-optional BOOLEAN     Change the exit_code for 'optional'
                                    precommit-hooks-type.

                                    *If True, exit_code=-1 (error).

                                    *If False, exit_code=0 (successful).  [env
                                    var: PRECOMMIT_FAIL_OPTIONAL; default:
                                    False]
    -x, --exclude-autofix PATH CSV  Exclude paths on which to run the autofix
                                    pre-commit configuration, separated by
                                    commas  [env var: EXCLUDE_AUTOFIX]
    -l, --exclude-lint PATH CSV     Paths to exclude checks, separated by
                                    commas.  [env var: EXCLUDE_LINT]
    -d, --pylint-disable-checks TEXT CSV
                                    Pylint checks to disable, separated by
                                    commas.  [env var: PYLINT_DISABLE_CHECKS]
    -f, --autofix                   Run pre-commit with autofix configuration to
                                    change the source code.

                                    Overwrite '-t mandatory,optional,fix'  [env
                                    var: PRECOMMIT_AUTOFIX]
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
