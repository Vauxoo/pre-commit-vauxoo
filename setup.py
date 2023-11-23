#!/usr/bin/env python

import re
from glob import glob
from os.path import basename, dirname, join, splitext

from setuptools import find_packages, setup

try:
    from pbr import git
except ImportError:
    git = None


def generate_changelog():
    fname = "ChangeLog"
    if not git:
        changelog_str = '# ChangeLog was not generated. You need to install "pbr"'
        with open(fname, "w") as fchg:
            fchg.write(changelog_str)
        return changelog_str
    changelog = git._iter_log_oneline()
    changelog = git._iter_changelog(changelog)
    git.write_git_changelog(changelog=changelog)
    # git.generate_authors()
    return read(fname)


def generate_dependencies():
    return read("requirements.txt").splitlines()


def read(*names, **kwargs):
    with open(join(dirname(__file__), *names), encoding=kwargs.get("encoding", "utf8")) as fh:
        return fh.read()


setup(
    name="pre-commit-vauxoo",
    version="8.0.0",
    license="LGPL-3.0-or-later",
    description="pre-commit script to run automatically the configuration and variables custom from Vauxoo",
    long_description_content_type="text/x-rst",
    long_description="{}\n{}".format(
        re.compile("^.. start-badges.*^.. end-badges", re.M | re.S).sub("", read("README.rst")),
        re.sub(":[a-z]+:`~?(.*?)`", r"``\1``", generate_changelog()),
    ),
    author="Vauxoo",
    author_email="info@vauxoo.com",
    url="https://github.com/Vauxoo/pre-commit-vauxoo",
    packages=find_packages("src"),
    package_dir={"": "src"},
    py_modules=[splitext(basename(path))[0] for path in glob("src/*.py")],
    include_package_data=True,
    zip_safe=False,
    classifiers=[
        # complete classifier list: http://pypi.python.org/pypi?%3Aaction=list_classifiers
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)",
        "Operating System :: Unix",
        "Operating System :: POSIX",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: MacOS",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        # 'Programming Language :: Python :: Implementation :: CPython',
        # 'Programming Language :: Python :: Implementation :: PyPy',
        # uncomment if you test on these interpreters:
        # 'Programming Language :: Python :: Implementation :: IronPython',
        # 'Programming Language :: Python :: Implementation :: Jython',
        # 'Programming Language :: Python :: Implementation :: Stackless',
        "Topic :: Utilities",
    ],
    project_urls={
        "Documentation": "https://pre-commit-vauxoo.readthedocs.io/",
        "Changelog": "https://pre-commit-vauxoo.readthedocs.io/en/latest/changelog.html",
        "Issue Tracker": "https://github.com/Vauxoo/pre-commit-vauxoo/issues",
    },
    keywords=[
        # eg: 'keyword1', 'keyword2', 'keyword3',
    ],
    python_requires=">=3.8",
    install_requires=generate_dependencies(),
    extras_require={
        # eg:
        #   'rst': ['docutils>=0.11'],
        #   ':python_version=="2.6"': ['argparse'],
    },
    entry_points={
        "console_scripts": [
            "pre-commit-vauxoo = pre_commit_vauxoo.cli:main",
            "vx-check-deactivate = pre_commit_vauxoo.hooks.check_deactivate_jinja:main",
        ]
    },
)
