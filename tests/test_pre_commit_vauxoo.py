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
        self.old_environ = os.environ.copy()
        self.original_work_dir = os.getcwd()
        self.tmp_dir = tempfile.mkdtemp(suffix="_pre_commit_vauxoo")
        os.chdir(self.tmp_dir)
        self.runner = CliRunner()
        src_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), "..", "resources")
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
        os.chdir(self.original_work_dir)
        # Cleanup temporary files
        if os.path.isdir(self.tmp_dir) and self.tmp_dir != "/":
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        # reset environment variables
        os.environ.clear()
        os.environ.update(self.old_environ)

    def test_basic(self):
        os.environ["INCLUDE_LINT"] = "resources"
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 0, "Exited with error %s" % result)
        with open(os.path.join(self.tmp_dir, "pyproject.toml"), "r") as f_pyproject:
            self.assertIn("skip-string-normalization=false", f_pyproject, "Skip string normalization not set")

    def test_chdir(self):
        self.runner = CliRunner()
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.chdir("resources")
        result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 0, "Exited with error %s" % result)

    def test_exclude_lint_path(self):
        self.runner = CliRunner()
        os.chdir("resources")
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.environ["BLACK_SKIP_STRING_NORMALIZATION"] = "false"
        os.environ["EXCLUDE_LINT"] = "resources/module_example1/models"
        result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 0, "Exited with error %s" % result)
        with open(os.path.join(self.tmp_dir, "pyproject.toml"), "r") as f_pyproject:
            self.assertIn("skip-string-normalization=false", f_pyproject, "Skip string normalization not set")

    def test_disable_lints(self):
        self.runner = CliRunner()
        os.environ["DISABLE_PYLINT_CHECKS"] = "import-error"
        result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 0, "Exited with error %s" % result)

    def test_exclude_autofix(self):
        self.runner = CliRunner()
        os.chdir("resources")
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.environ["EXCLUDE_AUTOFIX"] = "resources/module_example1/demo/"
        os.environ["BLACK_SKIP_STRING_NORMALIZATION"] = "true"
        result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 0, "Exited with error %s" % result)
        with open(os.path.join(self.tmp_dir, "pyproject.toml"), "r") as f_pyproject:
            self.assertIn("skip-string-normalization=true", f_pyproject, "Skip string normalization not set")

    def test_fail_warning(self):
        os.environ["PRECOMMIT_FAIL_OPTIONAL"] = "1"
        # Only optional
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "optional"
        result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 1, "Exited without error")

    def test_rm_options(self):
        # Only mandatory
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all,-optional,-fix,-experimental"
        result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 0, "Exited with error %s" % result)

    def test_install_git_hook_pre_commit(self):
        """Test .git/hooks/pre-commit script"""
        git_hook_pre_commit = os.path.join(self.tmp_dir, ".git", "hooks", "pre-commit")
        self.assertFalse(os.path.isfile(git_hook_pre_commit), "File created before to install it")
        result = self.runner.invoke(main, ["--install"])
        self.assertEqual(result.exit_code, 0, "Exited with error %s" % result)
        self.assertTrue(os.path.isfile(git_hook_pre_commit), "File not created")
        with open(git_hook_pre_commit, "r") as f_git_hook_pre_commit:
            self.assertIn("pre-commit-vauxoo", f_git_hook_pre_commit.read(), "File pre-commit not generated correctly")
        os.environ["NOLINT"] = "0"
        exit_code = subprocess.call(
            [
                "git",
                "-c",
                "user.name='Test'",
                "-c",
                "user.email=test@vauxoo.com",
                "commit",
                "--allow-empty",
                "-am",
                "testing",
            ]
        )
        self.assertEqual(exit_code, 0, "Exited with error_code %s" % exit_code)


if __name__ == "__main__":
    unittest.main()
