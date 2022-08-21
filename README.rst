========
Overview
========

.. start-badges

.. list-table::
    :stub-columns: 1

    * - docs
      - |docs|
    * - tests
      - | |github-actions| |travis| |appveyor| 
        | |coveralls| |codecov|
    * - package
      - | |version| |
        | |commits-since|
.. .. |docs| image:: https://readthedocs.org/projects/pre-commit-vauxoo/badge/?style=flat
..     :target: https://pre-commit-vauxoo.readthedocs.io/
..     :alt: Documentation Status

.. .. |travis| image:: https://api.travis-ci.com/Vauxoo/pre-commit-vauxoo.svg?branch=main
..     :alt: Travis-CI Build Status
..     :target: https://travis-ci.com/github/Vauxoo/pre-commit-vauxoo

.. .. |appveyor| image:: https://ci.appveyor.com/api/projects/status/github/Vauxoo/pre-commit-vauxoo?branch=main&svg=true
..     :alt: AppVeyor Build Status
..     :target: https://ci.appveyor.com/project/Vauxoo/pre-commit-vauxoo

.. |github-actions| image:: https://github.com/Vauxoo/pre-commit-vauxoo/actions/workflows/github-actions.yml/badge.svg
    :alt: GitHub Actions Build Status
    :target: https://github.com/Vauxoo/pre-commit-vauxoo/actions

.. .. |requires| image:: https://requires.io/github/Vauxoo/pre-commit-vauxoo/requirements.svg?branch=main
..     :alt: Requirements Status
..     :target: https://requires.io/github/Vauxoo/pre-commit-vauxoo/requirements/?branch=main

.. .. |coveralls| image:: https://coveralls.io/repos/Vauxoo/pre-commit-vauxoo/badge.svg?branch=main&service=github
..     :alt: Coverage Status
..     :target: https://coveralls.io/r/Vauxoo/pre-commit-vauxoo

.. .. |codecov| image:: https://codecov.io/gh/Vauxoo/pre-commit-vauxoo/branch/main/graphs/badge.svg?branch=main
..     :alt: Coverage Status
..     :target: https://codecov.io/github/Vauxoo/pre-commit-vauxoo

.. .. |version| image:: https://img.shields.io/pypi/v/pre-commit-vauxoo.svg
..     :alt: PyPI Package latest release
..     :target: https://pypi.org/project/pre-commit-vauxoo

.. .. |wheel| image:: https://img.shields.io/pypi/wheel/pre-commit-vauxoo.svg
..     :alt: PyPI Wheel
..     :target: https://pypi.org/project/pre-commit-vauxoo

.. .. |supported-versions| image:: https://img.shields.io/pypi/pyversions/pre-commit-vauxoo.svg
..     :alt: Supported versions
..     :target: https://pypi.org/project/pre-commit-vauxoo

.. .. |supported-implementations| image:: https://img.shields.io/pypi/implementation/pre-commit-vauxoo.svg
..     :alt: Supported implementations
..     :target: https://pypi.org/project/pre-commit-vauxoo

.. |commits-since| image:: https://img.shields.io/github/commits-since/Vauxoo/pre-commit-vauxoo/v1.2.1.svg
    :alt: Commits since latest release
    :target: https://github.com/Vauxoo/pre-commit-vauxoo/compare/v1.2.1...main



.. end-badges

pre-commit script to run automatically the configuration and variables custom from Vauxoo

* Free software: GNU Lesser General Public License v3 or later (LGPLv3+)

Installation
============

::

    pip install -U git+https://github.com/Vauxoo/pre-commit-vauxoo.git@main

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
