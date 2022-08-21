import os
from contextlib import contextmanager

from click.testing import CliRunner

from pre_commit_vauxoo.cli import main


@contextmanager
def chdir(path):
    curdir = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(curdir)


def test_basic():
    runner = CliRunner()
    env = os.environ
    env['INCLUDE_LINT'] = 'resources'
    env['PRECOMMIT_AUTOFIX'] = '1'
    result = runner.invoke(main, [], env=env)

    assert result.output == ''
    assert result.exit_code == 0


def test_chdir():
    runner = CliRunner()
    env = os.environ
    env['PRECOMMIT_AUTOFIX'] = '1'
    with chdir("resources"):
        result = runner.invoke(main, [], env=env)

    assert result.output == ''
    assert result.exit_code == 0


def test_exclude_lint():
    runner = CliRunner()
    env = os.environ
    env['PRECOMMIT_AUTOFIX'] = '1'
    env['EXCLUDE_LINT'] = 'import-error'
    with chdir("resources"):
        result = runner.invoke(main, [], env=env)

    assert result.output == ''
    assert result.exit_code == 0


def test_exclude_autofix():
    runner = CliRunner()
    env = os.environ
    env['PRECOMMIT_AUTOFIX'] = '1'
    env['EXCLUDE_AUTOFIX'] = 'resources/module_example1/demo/'
    with chdir("resources"):
        result = runner.invoke(main, [], env=env)

    assert result.output == ''
    assert result.exit_code == 0
