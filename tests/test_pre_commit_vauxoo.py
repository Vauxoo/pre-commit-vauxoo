import os
import shutil
import subprocess
import tempfile
import unittest

from click.testing import CliRunner

from pre_commit_vauxoo.cli import main


class TestPreCommitVauxoo(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.env = os.environ.copy()
        self.original_work_dir = os.getcwd()
        self.tmp_dir = tempfile.mkdtemp(suffix='_pre_commit_vauxoo')
        os.chdir(self.tmp_dir)
        self.runner = CliRunner()
        src_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'resources')
        self.create_dummy_repo(src_path, self.tmp_dir)
        self.maxDiff = None

    def create_dummy_repo(self, src_path, dest_path):
        subprocess.call(["git", "init", "--initial-branch=main", dest_path])
        dest_subpath = os.path.join(dest_path, os.path.basename(src_path))
        shutil.copytree(src_path, dest_subpath)
        subprocess.call(["git", "add", dest_subpath])

    def tearDown(self):
        super().tearDown()
        # change to original work dir
        if os.path.isdir(self.original_work_dir):
            os.chdir(self.original_work_dir)
        # Cleanup temporary files
        if os.path.isdir(self.tmp_dir) and self.tmp_dir != '/':
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_basic(self):
        self.env['INCLUDE_LINT'] = 'resources'
        self.env['PRECOMMIT_AUTOFIX'] = '1'
        result = self.runner.invoke(main, [], env=self.env)
        self.assertEqual(result.output, '')
        self.assertEqual(result.exit_code, 0)

    def test_chdir(self):
        self.runner = CliRunner()
        self.env['PRECOMMIT_AUTOFIX'] = '1'
        os.chdir("resources")
        result = self.runner.invoke(main, [], env=self.env)

        self.assertEqual(result.output, '')
        self.assertEqual(result.exit_code, 0)

    def test_exclude_lint_path(self):
        self.runner = CliRunner()
        self.env['PRECOMMIT_AUTOFIX'] = '1'
        self.env['EXCLUDE_LINT'] = 'module_example1/models'
        os.chdir("resources")
        result = self.runner.invoke(main, [], env=self.env)

        self.assertEqual(result.output, '')
        self.assertEqual(result.exit_code, 0)

    def test_disable_lints(self):
        self.runner = CliRunner()
        self.env['DISABLE_PYLINT_CHECKS'] = 'import-error'
        os.chdir("resources")
        result = self.runner.invoke(main, [], env=self.env)

        self.assertEqual(result.output, '')
        self.assertEqual(result.exit_code, 0)

    def test_exclude_autofix(self):
        self.runner = CliRunner()
        self.env['PRECOMMIT_AUTOFIX'] = '1'
        self.env['EXCLUDE_AUTOFIX'] = 'module_example1/demo/'
        os.chdir("resources")
        result = self.runner.invoke(main, [], env=self.env)

        self.assertEqual(result.output, '')
        self.assertEqual(result.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
