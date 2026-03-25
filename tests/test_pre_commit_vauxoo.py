from __future__ import annotations

import logging
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
from configparser import ConfigParser
from contextlib import contextmanager, redirect_stdout
from distutils.dir_util import copy_tree  # pylint:disable=deprecated-module
from io import StringIO
from pathlib import Path

import pytest
from click.testing import CliRunner
from pylint.lint import Run
from yaml import Loader, load

from pre_commit_vauxoo.cli import main
from pre_commit_vauxoo.hooks.check_commit_msg import (
    check_commit_messages_since_version,
    check_commit_msg_file,
    get_invalid_commit_messages,
    resolve_commit_message_base_ref,
    validate_commit_message_header,
)

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


@pytest.fixture(
    params=[None, "0.0.0.0.0.0.0.0", "10.10.10.10.10.10.10.10", "20.20.20.20.20.20.20.20", "30.30.30.30.30.30.30.30"]
)
def env_mode(request, monkeypatch):
    if request.param is None:
        monkeypatch.delenv("LINT_COMPATIBILITY_VERSION", raising=False)
    else:
        monkeypatch.setenv("LINT_COMPATIBILITY_VERSION", request.param)
    return request.param


@pytest.mark.usefixtures("env_mode")
class TestPreCommitVauxoo:
    def strip_ansi(self, text: str) -> str:
        return ANSI_ESCAPE_RE.sub("", text)

    def setup_method(self, method):
        self.old_environ = os.environ.copy()
        self.original_work_dir = os.getcwd()
        self.tmp_dir = os.path.realpath(tempfile.mkdtemp(suffix="_pre_commit_vauxoo"))
        os.chdir(self.tmp_dir)
        self.runner = CliRunner()
        src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "resources")
        self.create_dummy_repo(src_path, self.tmp_dir)
        self.maxDiff = None
        os.environ["EXCLUDE_AUTOFIX"] = "module_autofix1/"

    def create_dummy_repo(self, src_path, dest_path):
        copy_tree(src_path, dest_path)
        subprocess.check_call(["git", "init", dest_path, "--initial-branch=main"])
        # Notice we needed a previous os.chdir to repository directory
        subprocess.check_call(["git", "add", "-A"])

    def teardown_method(self, method):
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
    def custom_assert_logs(self, module, level, expected_logs, caplog):
        level_no = getattr(logging, level)

        with caplog.at_level(level_no, logger=module):
            yield
        formatted_logs = {
            self.strip_ansi(f"{record.levelname}:{record.name}:{record.getMessage()}")
            for record in caplog.records
            if record.name == module
        }
        diff = set(expected_logs) - formatted_logs
        assert not diff, f"Logs expected not raised {diff}"

    def get_pylint_messages(self):
        output = StringIO()
        with redirect_stdout(output):
            try:
                Run(
                    [
                        "--load-plugins=pylint.extensions.docstyle,pylint.extensions.mccabe,pylint_odoo",
                        "--list-msgs",
                    ]
                )
            except SystemExit as ex:
                assert not ex.code, "There was an error obtaining messages from pylint"

        output.seek(0)
        output = output.read()
        return set(re.findall(r"^:([a-z\-]+)", output, re.MULTILINE))

    def test_basic(self, caplog):
        os.environ["INCLUDE_LINT"] = os.path.join(self.tmp_dir, "module_example1")
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        result = self.runner.invoke(main, [])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        with open(os.path.join(self.tmp_dir, "pyproject.toml")) as f_pyproject:
            assert "skip-string-normalization=false" in f_pyproject.read(), "Skip string normalization not set"

    def test_chdir(self, caplog):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.chdir("module_autofix1")
        expected_logs = ["WARNING:pre-commit-vauxoo:Running in current directory 'module_autofix1'"]
        self.runner.invoke(main, [])
        with self.custom_assert_logs("pre-commit-vauxoo", level="WARNING", expected_logs=expected_logs, caplog=caplog):
            result = self.runner.invoke(main, [])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)

    def test_exclude_lint_path(self, caplog):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.environ["BLACK_SKIP_STRING_NORMALIZATION"] = "false"
        os.environ["EXCLUDE_LINT"] = "module_example1/models,module_warnings1/"
        result = self.runner.invoke(main, [])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        with open(os.path.join(self.tmp_dir, "pyproject.toml")) as f_pyproject:
            f_content = f_pyproject.read()
        assert "skip-string-normalization=false" in f_content, "Skip string normalization not set"

    def test_disable_lints(self, caplog):
        os.environ["DISABLE_PYLINT_CHECKS"] = "import-error"
        result = self.runner.invoke(main, [])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        with open(os.path.join(self.tmp_dir, ".pylintrc")) as f_pylintrc:
            f_content = f_pylintrc.read()
        assert "import-error," in f_content, "import-error was not disabled"

    def test_exclude_autofix(self, caplog):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.environ["EXCLUDE_AUTOFIX"] = "module_example1/demo/,module_autofix1/,module_warnings1/"
        os.environ["BLACK_SKIP_STRING_NORMALIZATION"] = "true"
        result = self.runner.invoke(main, [])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        with open(os.path.join(self.tmp_dir, "pyproject.toml")) as f_pyproject:
            assert "skip-string-normalization=true" in f_pyproject.read(), "Skip string normalization not set"

    def test_fail_warning(self, caplog):
        os.environ["PRECOMMIT_FAIL_OPTIONAL"] = "1"
        # Only optional
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "optional"
        expected_logs = ["ERROR:pre-commit-vauxoo:Optional checks failed"]
        with self.custom_assert_logs("pre-commit-vauxoo", level="ERROR", expected_logs=expected_logs, caplog=caplog):
            result = self.runner.invoke(main, [])
        assert result.exit_code == 1, "Exited without error"

    def test_rm_options(self, caplog):
        # Only mandatory
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all,-optional,-fix,-experimental"
        expected_logs = ["INFO:pre-commit-vauxoo:Mandatory checks passed!"]
        with self.custom_assert_logs("pre-commit-vauxoo", level="INFO", expected_logs=expected_logs, caplog=caplog):
            result = self.runner.invoke(main, [])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)

    def test_install_git_hook_pre_commit(self, caplog):
        git_hook_pre_commit = os.path.join(self.tmp_dir, ".git", "hooks", "pre-commit")
        assert not os.path.isfile(git_hook_pre_commit), "File created before to install it"
        result = self.runner.invoke(main, ["--install"])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        assert os.path.isfile(git_hook_pre_commit), "File not created"
        with open(git_hook_pre_commit) as f_git_hook_pre_commit:
            assert "pre-commit-vauxoo" in f_git_hook_pre_commit.read(), "File pre-commit not generated correctly"
        os.environ["NOLINT"] = "1"
        exit_code = subprocess.call(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@vauxoo.com",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--allow-empty",
                "-m",
                "[FIX] module_example1: testing",
            ]
        )
        assert not exit_code, "Exited with error_code %s" % exit_code

    def test_commit_msg_valid_single_module(self):
        commit_msg_path = os.path.join(self.tmp_dir, ".git", "COMMIT_EDITMSG")
        with open(commit_msg_path, "w", encoding="utf-8") as commit_msg:
            commit_msg.write("[FIX] module_example1: correct typo\n\nBody\n")

        assert check_commit_msg_file(commit_msg_path, repo_root=self.tmp_dir)

    def test_commit_msg_valid_multiple_modules(self):
        commit_msg_path = os.path.join(self.tmp_dir, ".git", "COMMIT_EDITMSG")
        with open(commit_msg_path, "w", encoding="utf-8") as commit_msg:
            commit_msg.write("[IMP] module_example1, module_warnings1: improve shared logic\n")

        assert check_commit_msg_file(commit_msg_path, repo_root=self.tmp_dir)

    def test_commit_msg_valid_multiple_tags(self):
        errors = validate_commit_message_header(
            "[MIG,FIX] module_example1: migrate and fix behavior", repo_root=self.tmp_dir
        )
        assert not errors

    def test_commit_msg_valid_multiple_tags_with_slash(self):
        errors = validate_commit_message_header(
            "[REM/MOV] module_example1: move deprecated code", repo_root=self.tmp_dir
        )
        assert not errors

    def test_commit_msg_valid_multiple_modules_with_slash(self):
        errors = validate_commit_message_header(
            "[IMP] module_example1/module_warnings1: improve shared logic", repo_root=self.tmp_dir
        )
        assert not errors

    def test_commit_msg_invalid_unknown_module(self):
        errors = validate_commit_message_header("[FIX] missing_module: fix bug", repo_root=self.tmp_dir)
        assert any("Unknown module or file target(s): missing_module" in error for error in errors)
        assert any("Use one or more targets separated by ',' or '/'." in error for error in errors)

    def test_commit_msg_invalid_format(self):
        errors = validate_commit_message_header("module_example1: fix bug", repo_root=self.tmp_dir)
        assert errors[:3] == [
            "Invalid commit message header.",
            "Expected format: [TAG] module_name[,module_name2]: concise summary",
            "You can also use multiple tags or targets separated by ',' or '/'.",
        ]
        assert errors[3].startswith("Allowed tags are:")
        assert "[FIX] bug fixes" in errors[3]

    def test_commit_msg_invalid_tag_help(self):
        errors = validate_commit_message_header("[BAD] module_example1: fix bug", repo_root=self.tmp_dir)
        assert any("Invalid tag(s): [BAD]." in error for error in errors)
        invalid_tag_error = next(error for error in errors if "Invalid tag(s): [BAD]." in error)
        assert "Use one or more tags separated by ',' or '/'." in invalid_tag_error
        assert "[FIX] bug fixes" in invalid_tag_error
        assert "[IMP] incremental improvements to existing behavior" in invalid_tag_error
        assert "[MIG] migrating a module or project changes to another Odoo version" in invalid_tag_error
        assert "[REF] refactoring existing code without changing expected behavior" in invalid_tag_error

    def test_commit_msg_valid_mig_tag(self):
        errors = validate_commit_message_header("[MIG] module_example1: migrate to 18.0", repo_root=self.tmp_dir)
        assert not errors

    def test_commit_msg_valid_global_target(self):
        errors = validate_commit_message_header("[MOV] *: move shared logic to base module", repo_root=self.tmp_dir)
        assert not errors

    def test_commit_msg_valid_file_target(self):
        file_target = os.path.join(self.tmp_dir, "custom_script.py")
        with open(file_target, "w", encoding="utf-8") as target_fd:
            target_fd.write("print('hello')\n")
        errors = validate_commit_message_header(
            "[MIG] custom_script.py: adjust package metadata", repo_root=self.tmp_dir
        )
        assert not errors

    def test_commit_msg_valid_merge_without_target(self):
        errors = validate_commit_message_header(
            "[MERGE] Forward-port changes from 16.0 to 18.0 up to 94948e424",
            repo_root=self.tmp_dir,
        )
        assert not errors

    def test_commit_msg_invalid_composite_merge_still_requires_target(self):
        errors = validate_commit_message_header("[MERGE/FIX] some automatic text", repo_root=self.tmp_dir)
        assert errors[:3] == [
            "Invalid commit message header.",
            "Expected format: [TAG] module_name[,module_name2]: concise summary",
            "You can also use multiple tags or targets separated by ',' or '/'.",
        ]
        assert errors[3].startswith("Allowed tags are:")

    def test_resolve_commit_message_base_ref_prefers_stable_remote_url(self):
        subprocess.check_call(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@vauxoo.com",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--allow-empty",
                "-m",
                "[FIX] module_example1: initial baseline",
            ]
        )
        subprocess.check_call(["git", "branch", "18.0"])
        subprocess.check_call(["git", "remote", "add", "origin", "git@example.com:project.git"])
        subprocess.check_call(["git", "remote", "add", "devremote", "git@example.com:dev/project.git"])
        subprocess.check_call(["git", "update-ref", "refs/remotes/origin/18.0", "HEAD"])
        subprocess.check_call(["git", "update-ref", "refs/remotes/devremote/18.0", "HEAD"])

        assert resolve_commit_message_base_ref("18.0") == "origin/18.0"

    def test_resolve_commit_message_base_ref_falls_back_to_local_branch(self):
        subprocess.check_call(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@vauxoo.com",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--allow-empty",
                "-m",
                "[FIX] module_example1: initial baseline",
            ]
        )
        subprocess.check_call(["git", "branch", "18.0"])
        subprocess.check_call(["git", "remote", "add", "origin", "git@example.com:dev/project.git"])
        subprocess.check_call(["git", "update-ref", "refs/remotes/origin/18.0", "HEAD"])

        assert resolve_commit_message_base_ref("18.0") == "18.0"

    def test_get_invalid_commit_messages_since_base(self):
        subprocess.check_call(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@vauxoo.com",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--allow-empty",
                "-m",
                "[FIX] module_example1: initial baseline",
            ]
        )
        subprocess.check_call(["git", "branch", "18.0"])
        with open(os.path.join(self.tmp_dir, "custom_file.txt"), "w", encoding="utf-8") as custom_fd:
            custom_fd.write("content\n")
        subprocess.check_call(["git", "add", "custom_file.txt"])
        subprocess.check_call(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@vauxoo.com",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-m",
                "[BAD] custom_file.txt: invalid tag",
            ]
        )

        invalid_commits = get_invalid_commit_messages("18.0", self.tmp_dir)
        assert len(invalid_commits) == 1
        assert invalid_commits[0]["subject"] == "[BAD] custom_file.txt: invalid tag"

    def test_commit_msg_hook_is_in_optional_config(self):
        self.runner.invoke(main, ["--only-cp-cfg"])
        with open(os.path.join(self.tmp_dir, ".pre-commit-config.yaml"), encoding="utf-8") as mandatory_cfg:
            mandatory_content = mandatory_cfg.read()
        with open(os.path.join(self.tmp_dir, ".pre-commit-config-optional.yaml"), encoding="utf-8") as optional_cfg:
            optional_content = optional_cfg.read()

        assert "vx-check-commit-msg" not in mandatory_content
        assert "vx-check-commit-msg" not in optional_content
        assert "vx-check-commit-log" in optional_content

    def test_check_commit_messages_since_version_passes_without_version(self):
        assert check_commit_messages_since_version(repo_root=self.tmp_dir, version="") is True

    def test_autofixes(self, caplog):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.environ["EXCLUDE_AUTOFIX"] = ""
        expected_logs = ["ERROR:pre-commit-vauxoo:Autofix checks reformatted"]
        with self.custom_assert_logs("pre-commit-vauxoo", level="ERROR", expected_logs=expected_logs, caplog=caplog):
            result = self.runner.invoke(main, [])
        assert result.exit_code == 1, "Exited without error"

    def test_uninstallable(self, caplog):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        uninstallable_path = os.path.join(self.tmp_dir, "module_uninstallable")
        result = self.runner.invoke(main, ["-p", uninstallable_path])
        assert (
            not result.exit_code
        ), "Uninstallable module should not have been linted. " "Exited with error %s - %s" % (result, result.output)

    def test_exclude_only_uninstallable(self, caplog):
        repo_path = posixpath.join(self.tmp_dir, "repo")
        repo_sub_path = posixpath.join(self.tmp_dir, "repo_sub")

        os.mkdir(repo_path)
        os.mkdir(repo_sub_path)

        with open(os.path.join(repo_path, "__manifest__.py"), "w") as manifest:
            manifest.write("{'installable': False}")

        self.runner.invoke(main, [])
        with open(os.path.join(self.tmp_dir, ".pre-commit-config.yaml")) as config_fd:
            config = load(config_fd, Loader)

        pattern = re.compile(config["exclude"])
        assert pattern.search(posixpath.join(repo_path, "models", "res_partner.py"))
        assert pattern.search(posixpath.join(repo_sub_path, "wizard", "invoice_send.py")) is None

    def test_disable_oca_hooks(self, caplog):
        expected_disabled = {"random-msg1", "random-msg2"}
        os.environ["OCA_HOOKS_DISABLE_CHECKS"] = ",".join(expected_disabled)
        self.runner.invoke(main, [])
        oca_hooks_cfg_paths = [
            Path(self.tmp_dir) / ".oca_hooks.cfg",
            Path(self.tmp_dir) / ".oca_hooks-autofix.cfg",
        ]
        for oca_hooks_cfg_path in oca_hooks_cfg_paths:
            config = ConfigParser(inline_comment_prefixes=("#", ";"))
            config.read(oca_hooks_cfg_path)
            disable_raw = config.get("MESSAGES_CONTROL", "disable")
            disabled = {item.strip(", ") for item in disable_raw.replace("\n", "").split(",") if item.strip()}
            assert expected_disabled.issubset(
                disabled
            ), f"random-msg was supposed to be disabled for {oca_hooks_cfg_path} through the corresponding environment variable"

    def test_valid_pylintrc_messages(self, caplog):
        self.runner.invoke(main, ["--only-cp-cfg"])
        pylint_messages = self.get_pylint_messages()
        rc_files = [
            os.path.abspath(os.path.join(self.tmp_dir, pylintrc)) for pylintrc in [".pylintrc", ".pylintrc-optional"]
        ]
        for rc_file in rc_files:
            config = ConfigParser(inline_comment_prefixes=("#", ";"))
            config.read(rc_file)
            for action in ["enable", "disable"]:
                if "all" in config["MESSAGES CONTROL"][action].split(","):
                    continue
                messages = [val.strip() for val in config["MESSAGES CONTROL"][action].split(",")]
                messages_set = set()
                for message in messages:
                    assert message in pylint_messages, f"{message} in {rc_file} is not a valid message"
                    assert message not in messages_set, f"Duplicate '{message}' in {rc_file}"
                    messages_set.add(message)

    def test_special_char_filename(self, caplog):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "mandatory"
        fname_wrong = os.path.join(self.tmp_dir, "module_example1", "leéme.rst")
        with open(fname_wrong, "w"):
            pass
        subprocess.check_call(["git", "add", "-A"])
        expected_logs = ["ERROR:pre-commit-vauxoo:Mandatory checks failed"]
        with self.custom_assert_logs("pre-commit-vauxoo", level="ERROR", expected_logs=expected_logs, caplog=caplog):
            result = self.runner.invoke(main, [])
        assert result.exit_code == 1, "Exited without error"

    def test_special_char_dirname(self, caplog):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "mandatory"
        dirname_wrong = os.path.join(self.tmp_dir, "module_example1", "moisé")
        os.mkdir(dirname_wrong)
        fname = os.path.join(dirname_wrong, "empty_file.txt")
        with open(fname, "w"):
            pass
        subprocess.check_call(["git", "add", "-A"])
        expected_logs = ["ERROR:pre-commit-vauxoo:Mandatory checks failed"]
        with self.custom_assert_logs("pre-commit-vauxoo", level="ERROR", expected_logs=expected_logs, caplog=caplog):
            result = self.runner.invoke(main, [])
        assert result.exit_code == 1, "Exited without error"

    def test_apps_checks_disable(self, caplog):
        os.environ["PRECOMMIT_IS_PROJECT_FOR_APPS"] = "True"
        self.runner.invoke(main, [])
        with open(os.path.join(self.tmp_dir, ".pylintrc")) as pylintrc:
            f_content = pylintrc.read()
        assert "category-allowed-app" not in f_content, "app check disabled for a project for apps"

        os.environ["PRECOMMIT_IS_PROJECT_FOR_APPS"] = "False"
        self.runner.invoke(main, [])
        with open(os.path.join(self.tmp_dir, ".pylintrc")) as pylintrc:
            f_content = pylintrc.read()
        assert "category-allowed-app" in f_content, "app check enabled for a project for non apps"

        os.environ.pop("PRECOMMIT_IS_PROJECT_FOR_APPS")
        self.runner.invoke(main, [])
        with open(os.path.join(self.tmp_dir, ".pylintrc")) as pylintrc:
            f_content = pylintrc.read()
        assert "category-allowed-app" in f_content, "app check enabled for a project for non apps (default value)"
