import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from distutils.dir_util import copy_tree  # pylint:disable=deprecated-module

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
        src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "resources")
        self.create_dummy_repo(src_path, self.tmp_dir)
        self.maxDiff = None
        os.environ["EXCLUDE_AUTOFIX"] = "module_autofix1"

    def create_dummy_repo(self, src_path, dest_path):
        copy_tree(src_path, dest_path)
        subprocess.check_call(["git", "init", dest_path])
        # Notice we needed a previous os.chdir to repository directory
        subprocess.check_call(["git", "add", "-A"])

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

    @contextmanager
    def chdir(self, directory):
        original_dir = os.getcwd()
        try:
            os.chdir(directory)
            yield
        finally:
            os.chdir(original_dir)

    @contextmanager
    def custom_assert_logs(self, module, level, expected_logs):
        if (sys.version_info.major, sys.version_info.minor) >= (3, 4):
            with self.assertLogs(module, level=level) as logs:
                yield
            logger = logging.getLogger(module)
            level_no = getattr(logging, level)
            for log in logs.output:
                logger.log(level_no, log)
            diff = set(expected_logs) - set(logs.output)
            self.assertFalse(diff, "Logs expected not raised %s" % diff)
        else:
            # bypassing for dual compatibility with py<3.4
            yield

    def test_basic(self):
        os.environ["INCLUDE_LINT"] = os.path.join(self.tmp_dir, "module_example1")
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 0, "Exited with error %s - %s" % (result, result.output))
        with open(os.path.join(self.tmp_dir, "pyproject.toml"), "r") as f_pyproject:
            self.assertIn("skip-string-normalization=false", f_pyproject, "Skip string normalization not set")

    def test_chdir(self):
        self.runner = CliRunner()
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.chdir("module_autofix1")
        expected_logs = ["WARNING:pre-commit-vauxoo:Running in current directory 'module_autofix1'"]
        result = self.runner.invoke(main, [])
        with self.custom_assert_logs("pre-commit-vauxoo", level="WARNING", expected_logs=expected_logs):
            result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 0, "Exited with error %s - %s" % (result, result.output))

    def test_exclude_lint_path(self):
        self.runner = CliRunner()

        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.environ["BLACK_SKIP_STRING_NORMALIZATION"] = "false"
        os.environ["EXCLUDE_LINT"] = "module_example1/models"
        result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 0, "Exited with error %s - %s" % (result, result.output))
        with open(os.path.join(self.tmp_dir, "pyproject.toml"), "r") as f_pyproject:
            f_content = f_pyproject.read()
        self.assertIn("skip-string-normalization=false", f_content, "Skip string normalization not set")

    def test_disable_lints(self):
        self.runner = CliRunner()
        os.environ["DISABLE_PYLINT_CHECKS"] = "import-error"
        result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 0, "Exited with error %s - %s" % (result, result.output))
        with open(os.path.join(self.tmp_dir, ".pylintrc"), "r") as f_pylintrc:
            f_content = f_pylintrc.read()
        self.assertIn("import-error,", f_content, "import-error was not disabled")

    def test_exclude_autofix(self):
        self.runner = CliRunner()

        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.environ["EXCLUDE_AUTOFIX"] = "module_example1/demo/"
        os.environ["BLACK_SKIP_STRING_NORMALIZATION"] = "true"
        result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 0, "Exited with error %s - %s" % (result, result.output))
        with open(os.path.join(self.tmp_dir, "pyproject.toml"), "r") as f_pyproject:
            self.assertIn("skip-string-normalization=true", f_pyproject, "Skip string normalization not set")

    def test_fail_warning(self):
        os.environ["PRECOMMIT_FAIL_OPTIONAL"] = "1"
        # Only optional
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "optional"
        expected_logs = ["ERROR:pre-commit-vauxoo:Optional checks failed"]
        with self.custom_assert_logs("pre-commit-vauxoo", level="ERROR", expected_logs=expected_logs):
            result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 1, "Exited without error")

    def test_rm_options(self):
        # Only mandatory
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all,-optional,-fix,-experimental"
        expected_logs = ["INFO:pre-commit-vauxoo:Mandatory checks passed!"]
        with self.custom_assert_logs("pre-commit-vauxoo", level="INFO", expected_logs=expected_logs):
            result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 0, "Exited with error %s - %s" % (result, result.output))

    def test_install_git_hook_pre_commit(self):
        """Test .git/hooks/pre-commit script"""
        git_hook_pre_commit = os.path.join(self.tmp_dir, ".git", "hooks", "pre-commit")
        self.assertFalse(os.path.isfile(git_hook_pre_commit), "File created before to install it")
        result = self.runner.invoke(main, ["--install"])
        self.assertEqual(result.exit_code, 0, "Exited with error %s - %s" % (result, result.output))
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

    def test_autofixes(self):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.environ["EXCLUDE_AUTOFIX"] = ""
        expected_logs = ["ERROR:pre-commit-vauxoo:Autofix checks reformatted"]
        with self.custom_assert_logs("pre-commit-vauxoo", level="ERROR", expected_logs=expected_logs):
            result = self.runner.invoke(main, [])
        self.assertEqual(result.exit_code, 1, "Exited without error")

    def test_uninstallable(self):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        uninstallable_path = os.path.join(self.tmp_dir, "module_uninstallable")
        result = self.runner.invoke(main, ["-p", uninstallable_path])
        self.assertEqual(
            result.exit_code,
            0,
            "Uninstallable module should not have been linted. Exited with error %s - %s" % (result, result.output),
        )


if __name__ == "__main__":
    unittest.main()
