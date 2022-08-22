import os
import unittest
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


class TestStringMethods(unittest.TestCase):
    def test_basic(self):
        runner = CliRunner()
        env = os.environ
        env['INCLUDE_LINT'] = 'resources'
        env['PRECOMMIT_AUTOFIX'] = '1'
        result = runner.invoke(main, [], env=env)
        self.assertEqual(result.output, '')
        self.assertEqual(result.exit_code, 0)

    def test_chdir(self):
        runner = CliRunner()
        env = os.environ
        env['PRECOMMIT_AUTOFIX'] = '1'
        with chdir("resources"):
            result = runner.invoke(main, [], env=env)

        self.assertEqual(result.output, '')
        self.assertEqual(result.exit_code, 0)

    def test_exclude_lint(self):
        runner = CliRunner()
        env = os.environ
        env['PRECOMMIT_AUTOFIX'] = '1'
        env['EXCLUDE_LINT'] = 'import-error'
        with chdir("resources"):
            result = runner.invoke(main, [], env=env)

        self.assertEqual(result.output, '')
        self.assertEqual(result.exit_code, 0)

    def test_exclude_autofix(self):
        runner = CliRunner()
        env = os.environ
        env['PRECOMMIT_AUTOFIX'] = '1'
        env['EXCLUDE_AUTOFIX'] = 'resources/module_example1/demo/'
        with chdir("resources"):
            result = runner.invoke(main, [], env=env)

        self.assertEqual(result.output, '')
        self.assertEqual(result.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
