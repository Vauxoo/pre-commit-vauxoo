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
from io import StringIO
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

import pytest
from click.testing import CliRunner
from distutils.dir_util import copy_tree  # pylint:disable=deprecated-module
from jinja2 import Environment, FileSystemLoader
from pylint.config.config_initialization import _config_initialization
from pylint.lint import PyLinter, Run
from yaml import Loader, load

from pre_commit_vauxoo.cli import main
from pre_commit_vauxoo.hooks.check_commit_msg import (
    check_commit_messages_since_version,
    check_commit_msg_file,
    get_invalid_commit_messages,
    resolve_commit_message_base_ref,
    validate_commit_message_header,
)
from pre_commit_vauxoo.pre_commit_vauxoo import CFG_SUBFOLDER, parse_matrix_compatibility

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src" / "pre_commit_vauxoo" / "cfg"
TEST_PATH = Path(__file__).resolve().parents[0]


@pytest.fixture(
    params=[None, "0.0.0.0.0.0.0.0", "10.10.10.10.10.10.10.10", "20.20.20.20.20.20.20.20", "30.30.30.30.30.30.30.30"]
)
def env_mode(request, monkeypatch):
    if request.param is None:
        monkeypatch.delenv("LINT_COMPATIBILITY_VERSION", raising=False)
    else:
        monkeypatch.setenv("LINT_COMPATIBILITY_VERSION", request.param)
    return request.param


def render_template(odoo_version: str, template_name: str) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))
    template = env.get_template(template_name)
    return template.render(odoo_version=odoo_version)


@pytest.mark.usefixtures("env_mode")
class TestPreCommitVauxoo:
    def strip_ansi(self, text: str) -> str:
        return ANSI_ESCAPE_RE.sub("", text)

    def setup_method(self, method):
        self.old_environ = os.environ.copy()
        self.original_work_dir = Path.cwd()
        self.tmp_dir = os.path.realpath(tempfile.mkdtemp(suffix="_pre_commit_vauxoo"))
        os.chdir(self.tmp_dir)
        self.runner = CliRunner()
        self.src_path = os.path.join(Path(Path(os.path.realpath(__file__)).parent).parent, "resources")
        self.create_dummy_repo(self.src_path, self.tmp_dir)
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
        if Path(self.tmp_dir).is_dir() and self.tmp_dir != "/":
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        # reset environment variables
        os.environ.clear()
        os.environ.update(self.old_environ)

    @contextmanager
    def chdir(self, directory):
        original_dir = Path.cwd()
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
                Run([
                    "--load-plugins=pylint.extensions.docstyle,pylint.extensions.mccabe,pylint_odoo",
                    "--list-msgs",
                ])
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
        with Path(os.path.join(self.tmp_dir, CFG_SUBFOLDER, "pyproject.toml")).open() as f_pyproject:
            assert "skip-string-normalization=false" in f_pyproject.read(), "Skip string normalization not set"

    def test_chdir(self, caplog):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all,-fix"
        os.chdir("module_autofix1")
        expected_logs = ["WARNING:pre-commit-vauxoo:Running in current directory 'module_autofix1'"]
        self.runner.invoke(main, [])
        with self.custom_assert_logs("pre-commit-vauxoo", level="WARNING", expected_logs=expected_logs, caplog=caplog):
            self.runner.invoke(main, [])

    def test_exclude_lint_path(self, caplog):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.environ["BLACK_SKIP_STRING_NORMALIZATION"] = "false"
        os.environ["EXCLUDE_LINT"] = "module_example1/models,module_warnings1/"
        result = self.runner.invoke(main, [])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        f_content = Path(os.path.join(self.tmp_dir, CFG_SUBFOLDER, "pyproject.toml")).read_text()
        assert "skip-string-normalization=false" in f_content, "Skip string normalization not set"

    def test_disable_lints(self, caplog):
        os.environ["DISABLE_PYLINT_CHECKS"] = "import-error"
        result = self.runner.invoke(main, [])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        f_content = Path(os.path.join(self.tmp_dir, CFG_SUBFOLDER, ".pylintrc")).read_text()
        assert "import-error," in f_content, "import-error was not disabled"

    def test_exclude_autofix(self, caplog):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.environ["EXCLUDE_AUTOFIX"] = "module_example1/demo/,module_autofix1/,module_warnings1/"
        os.environ["BLACK_SKIP_STRING_NORMALIZATION"] = "true"
        result = self.runner.invoke(main, [])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        with Path(os.path.join(self.tmp_dir, CFG_SUBFOLDER, "pyproject.toml")).open() as f_pyproject:
            assert "skip-string-normalization=true" in f_pyproject.read(), "Skip string normalization not set"

    def test_fail_warning(self, caplog, capfd):
        os.environ["PRECOMMIT_FAIL_OPTIONAL"] = "1"
        # Only optional
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "optional"
        expected_logs = ["ERROR:pre-commit-vauxoo:Optional checks failed"]
        with self.custom_assert_logs("pre-commit-vauxoo", level="ERROR", expected_logs=expected_logs, caplog=caplog):
            result = self.runner.invoke(main, [])
        assert result.exit_code == 1, "Exited without error"
        output = self.strip_ansi(capfd.readouterr().out)
        # "resources/module_example1/models/markupsafe_sanitized.py" sanitizes the value
        # so B704:markupsafe_markup_xss must not be raised for it, it is defined
        # from the "allowed_calls" of the ".bandit-optional.yml" configuration file
        bandit_passed = re.search(r"^bandit optional\.+Passed$", output, re.MULTILINE)
        assert bandit_passed, "bandit optional did not pass\n%s" % output

    def test_rm_options(self, caplog):
        # Only mandatory
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all,-optional,-fix,-experimental"
        expected_logs = ["INFO:pre-commit-vauxoo:Mandatory checks passed!"]
        with self.custom_assert_logs("pre-commit-vauxoo", level="INFO", expected_logs=expected_logs, caplog=caplog):
            result = self.runner.invoke(main, [])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)

    def test_install_git_hook_pre_commit(self, caplog):
        git_hook_pre_commit = os.path.join(self.tmp_dir, ".git", "hooks", "pre-commit")
        assert not Path(git_hook_pre_commit).is_file(), "File created before to install it"
        result = self.runner.invoke(main, ["--install"])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        assert Path(git_hook_pre_commit).is_file(), "File not created"
        with Path(git_hook_pre_commit).open() as f_git_hook_pre_commit:
            assert "pre-commit-vauxoo" in f_git_hook_pre_commit.read(), "File pre-commit not generated correctly"
        os.environ["NOLINT"] = "1"
        exit_code = subprocess.call([
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
        ])
        assert not exit_code, "Exited with error_code %s" % exit_code

    def test_commit_msg_valid_single_module(self):
        commit_msg_path = os.path.join(self.tmp_dir, ".git", "COMMIT_EDITMSG")
        Path(commit_msg_path).write_text("[FIX] module_example1: correct typo\n\nBody\n", encoding="utf-8")

        assert check_commit_msg_file(commit_msg_path, repo_root=self.tmp_dir)

    def test_commit_msg_valid_multiple_modules(self):
        commit_msg_path = os.path.join(self.tmp_dir, ".git", "COMMIT_EDITMSG")
        Path(commit_msg_path).write_text(
            "[IMP] module_example1, module_warnings1: improve shared logic\n", encoding="utf-8"
        )

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
        Path(file_target).write_text("print('hello')\n", encoding="utf-8")
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
        subprocess.check_call([
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
        ])
        subprocess.check_call(["git", "branch", "18.0"])
        subprocess.check_call(["git", "remote", "add", "origin", "git@example.com:project.git"])
        subprocess.check_call(["git", "remote", "add", "devremote", "git@example.com:dev/project.git"])
        subprocess.check_call(["git", "update-ref", "refs/remotes/origin/18.0", "HEAD"])
        subprocess.check_call(["git", "update-ref", "refs/remotes/devremote/18.0", "HEAD"])

        assert resolve_commit_message_base_ref("18.0") == "origin/18.0"

    def test_resolve_commit_message_base_ref_falls_back_to_local_branch(self):
        subprocess.check_call([
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
        ])
        subprocess.check_call(["git", "branch", "18.0"])
        subprocess.check_call(["git", "remote", "add", "origin", "git@example.com:dev/project.git"])
        subprocess.check_call(["git", "update-ref", "refs/remotes/origin/18.0", "HEAD"])

        assert resolve_commit_message_base_ref("18.0") == "18.0"

    def test_get_invalid_commit_messages_since_base(self):
        subprocess.check_call([
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
        ])
        subprocess.check_call(["git", "branch", "18.0"])
        Path(os.path.join(self.tmp_dir, "custom_file.txt")).write_text("content\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "custom_file.txt"])
        subprocess.check_call([
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
        ])

        invalid_commits = get_invalid_commit_messages("18.0", self.tmp_dir)
        assert len(invalid_commits) == 1
        assert invalid_commits[0]["subject"] == "[BAD] custom_file.txt: invalid tag"

    def test_commit_msg_hook_is_in_optional_config(self):
        self.runner.invoke(main, ["--only-cp-cfg"])
        cfg_subfolder = Path(self.tmp_dir) / CFG_SUBFOLDER
        mandatory_content = (cfg_subfolder / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        optional_content = (cfg_subfolder / ".pre-commit-config-optional.yaml").read_text(encoding="utf-8")

        assert "vx-check-commit-msg" not in mandatory_content
        assert "vx-check-commit-msg" not in optional_content
        assert "vx-check-commit-log" in optional_content

    def test_check_commit_messages_since_version_passes_without_version(self):
        assert check_commit_messages_since_version(repo_root=self.tmp_dir, version="") is True

    def test_autofixes(self, caplog):
        # Remove the 'index' from diff since that it changes for each test and strip spaces or tabs
        index_re = re.compile(r"^index [0-9a-fA-F]+\.\.[0-9a-fA-F]+.*\n|[ \t]+$", flags=re.MULTILINE)
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        os.environ["EXCLUDE_AUTOFIX"] = ""
        expected_logs = ["ERROR:pre-commit-vauxoo:Autofix checks reformatted"]
        with self.custom_assert_logs("pre-commit-vauxoo", level="ERROR", expected_logs=expected_logs, caplog=caplog):
            result = self.runner.invoke(main, [])
        assert result.exit_code == 1, "Exited without error"
        result = subprocess.run(["git", "diff", self.tmp_dir], capture_output=True, text=True, check=False)
        diff_output = index_re.sub("", result.stdout)
        black_autoflake_matrix_value = parse_matrix_compatibility(
            os.environ.get("LINT_COMPATIBILITY_VERSION"), verbose=False
        )["black_autoflake_matrix_value"]
        if black_autoflake_matrix_value <= 10:
            # Few autofixes 10
            diff_module_autofix_expected_path = TEST_PATH / "diffs" / "module_autofix1_expected_10.diff"
        elif black_autoflake_matrix_value <= 20:
            # More autofixes 20
            diff_module_autofix_expected_path = TEST_PATH / "diffs" / "module_autofix1_expected_20.diff"
        else:
            # More autofixes 30
            diff_module_autofix_expected_path = TEST_PATH / "diffs" / "module_autofix1_expected_30.diff"
        diff_module_autofix_expected = index_re.sub("", diff_module_autofix_expected_path.read_text())
        # diff_module_autofix_expected_path.write_text(diff_output)  # Uncomment to update the diff files
        assert diff_output == diff_module_autofix_expected, "Autofixes applied different to expected"

    def test_uninstallable(self, caplog):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "all"
        uninstallable_path = os.path.join(self.tmp_dir, "module_uninstallable")
        result = self.runner.invoke(main, ["-p", uninstallable_path])
        assert not result.exit_code, "Uninstallable module should not have been linted. Exited with error %s - %s" % (
            result,
            result.output,
        )

    def test_exclude_only_uninstallable(self, caplog):
        repo_path = posixpath.join(self.tmp_dir, "repo")
        repo_sub_path = posixpath.join(self.tmp_dir, "repo_sub")

        Path(repo_path).mkdir()
        Path(repo_sub_path).mkdir()

        Path(os.path.join(repo_path, "__manifest__.py")).write_text("{'installable': False}")

        self.runner.invoke(main, [])
        with Path(os.path.join(self.tmp_dir, CFG_SUBFOLDER, ".pre-commit-config.yaml")).open() as config_fd:
            config = load(config_fd, Loader)

        pattern = re.compile(config["exclude"])
        assert pattern.search(posixpath.join(repo_path, "models", "res_partner.py"))
        assert pattern.search(posixpath.join(repo_sub_path, "wizard", "invoice_send.py")) is None

    def test_disable_oca_hooks(self, caplog):
        expected_disabled = {"random-msg1", "random-msg2"}
        os.environ["OCA_HOOKS_DISABLE_CHECKS"] = ",".join(expected_disabled)
        self.runner.invoke(main, [])
        oca_hooks_cfg_paths = [
            Path(self.tmp_dir) / CFG_SUBFOLDER / ".oca_hooks.cfg",
            Path(self.tmp_dir) / CFG_SUBFOLDER / ".oca_hooks-autofix.cfg",
        ]
        for oca_hooks_cfg_path in oca_hooks_cfg_paths:
            config = ConfigParser(inline_comment_prefixes=("#", ";"))
            config.read(oca_hooks_cfg_path)
            disable_raw = config.get("MESSAGES_CONTROL", "disable")
            disabled = {item.strip(", ") for item in disable_raw.replace("\n", "").split(",") if item.strip()}
            assert expected_disabled.issubset(disabled), (
                f"random-msg was supposed to be disabled for {oca_hooks_cfg_path} through the corresponding environment variable"
            )

    def test_oca_hooks_optional_config(self, caplog):
        self.runner.invoke(main, ["--only-cp-cfg"])
        with (Path(self.tmp_dir) / CFG_SUBFOLDER / ".pre-commit-config-optional.yaml").open() as config_fd:
            config = load(config_fd, Loader)
        oca_hooks = [hook for repo in config["repos"] for hook in repo["hooks"] if hook["id"].startswith("oca-checks")]
        assert oca_hooks, "Expected oca-checks hooks in the optional configuration"
        for hook in oca_hooks:
            assert f"--config={CFG_SUBFOLDER}/.oca_hooks.cfg" in hook.get("args", []), (
                f"{hook['id']} should read the generated .oca_hooks.cfg to honor the disabled checks"
            )

    def test_disable_ruff_checks(self, caplog):
        if (
            parse_matrix_compatibility(os.environ.get("LINT_COMPATIBILITY_VERSION"), verbose=False)[
                "black_autoflake_matrix_value"
            ]
            < 30
        ):
            pytest.skip("Requires BLACK_AUTOFLAKE_MATRIX_VALUE >= 30")
        self.runner.invoke(main, ["--only-cp-cfg"])
        ruff_toml = Path(self.tmp_dir) / CFG_SUBFOLDER / ".ruff-autofix.toml"
        with ruff_toml.open("rb") as f_ruff_toml:
            data = tomllib.load(f_ruff_toml)
            original_ignore = set(data["lint"]["ignore"])
            assert "print" not in data["lint"]["ignore"], (
                "print (T201) should not be in ruff ignore when RUFF_DISABLE_CHECKS is not set"
            )
            os.environ["RUFF_DISABLE_CHECKS"] = "print"
            self.runner.invoke(main, ["--only-cp-cfg"])
            f_ruff_toml.seek(0)
            data = tomllib.load(f_ruff_toml)
            disable_ignore = set(data["lint"]["ignore"])
            diff = disable_ignore - original_ignore
            assert {"print"} == diff, "print (T201) should be in ruff ignore when RUFF_DISABLE_CHECKS is set"

    def test_disable_pylint_checks_migrated_to_ruff(self, caplog):
        if (
            parse_matrix_compatibility(os.environ.get("LINT_COMPATIBILITY_VERSION"), verbose=False)[
                "black_autoflake_matrix_value"
            ]
            < 30
        ):
            pytest.skip("Requires BLACK_AUTOFLAKE_MATRIX_VALUE >= 30")
        # manifest-required-author (ODOO008) and invalid-commit (ODOO017) come from pylint-odoo,
        # dangerous-default-value (B006) comes from pylint and print-used (T201) runs as optional.
        # translation-required has no ruff equivalent so it should not add any ruff code
        expected_ruff_codes = {"B006", "ODOO008", "ODOO017", "T201"}
        ruff_toml_filenames = [".ruff.toml", ".ruff-optional.toml", ".ruff-autofix.toml"]
        cfg_subfolder = Path(self.tmp_dir) / CFG_SUBFOLDER
        self.runner.invoke(main, ["--only-cp-cfg"])
        for ruff_toml_filename in ruff_toml_filenames:
            with (cfg_subfolder / ruff_toml_filename).open("rb") as f_ruff_toml:
                ruff_ignore = set(tomllib.load(f_ruff_toml)["lint"]["ignore"])
            assert not expected_ruff_codes & ruff_ignore, (
                f"The ruff codes should not be in {ruff_toml_filename} ignore when PYLINT_DISABLE_CHECKS is not set"
            )
        os.environ["PYLINT_DISABLE_CHECKS"] = (
            "manifest-required-author,invalid-commit,dangerous-default-value,print-used,translation-required"
        )
        self.runner.invoke(main, ["--only-cp-cfg"])
        for ruff_toml_filename in ruff_toml_filenames:
            with (cfg_subfolder / ruff_toml_filename).open("rb") as f_ruff_toml:
                ruff_ignore = set(tomllib.load(f_ruff_toml)["lint"]["ignore"])
            assert expected_ruff_codes.issubset(ruff_ignore), (
                f"The ruff equivalent of the pylint checks should be in {ruff_toml_filename} ignore "
                "when PYLINT_DISABLE_CHECKS is set"
            )

    # Use cases expected to be reported by the same check before the ruff migration
    # (pylint "(symbol)" and flake8 " CODE " markers) and after it (ruff "rule-name:" marker)
    RUFF_MANDATORY_USE_CASES_EXPECTED = [
        (["F401", "(unused-import)"], "unused-import"),
        (["(duplicate-value)"], "duplicate-value"),
        (["(global-statement)"], "global-statement"),
        (["F821", "(undefined-variable)"], "undefined-name"),
        (["E711", "(singleton-comparison)"], "none-comparison"),
        (["E722", "(bare-except)"], "bare-except"),
        (["(dangerous-default-value)"], "mutable-argument-default"),
        (["(eval-used)"], "suspicious-eval-usage"),
        (["(no-else-return)"], "superfluous-else-return"),
        (["E731", "(unnecessary-lambda-assignment)"], "lambda-assignment"),
        (["(consider-iterating-dictionary)"], "in-dict-keys"),
        (["(super-with-arguments)"], "super-call-with-parameters"),
        (["(logging-not-lazy)"], "logging-percent-format"),
        (["(consider-merging-isinstance)"], "duplicate-isinstance-call"),
        (["(too-many-format-args)"], "percent-format-positional-count-mismatch"),
        # except-pass was optional in pylint-odoo but the ruff-odoo ODOO004 check
        # runs as mandatory so there are no old mandatory markers to expect
        ([], "except-pass"),
    ]
    RUFF_OPTIONAL_USE_CASES_EXPECTED = [
        (["(print-used)"], "print"),
        (["(implicit-str-concat)"], "single-line-implicit-string-concatenation"),
        (["(redundant-u-string-prefix)"], "unicode-kind-prefix"),
        (["(use-implicit-booleaness-not-comparison-to-string)"], "compare-to-empty-string"),
        (["(too-complex)"], "complex-structure"),
        (["E741"], "ambiguous-variable-name"),
        (["E242"], "tab-after-comma"),
        (["B008"], "function-call-in-default-argument"),
        (["B011"], "assert-false"),
        (["(bad-docstring-quotes)"], "triple-single-quotes"),
        (["(use-dict-literal)"], "unnecessary-collection-call"),
    ]

    def run_precommit_hooks(self, hook_ids, config_file, filename):
        output = ""
        for hook_id in hook_ids:
            result = subprocess.run(
                ["pre-commit", "run", hook_id, "-c", os.path.join(CFG_SUBFOLDER, config_file), "--files", filename],
                capture_output=True,
                text=True,
                check=False,
                cwd=self.tmp_dir,
            )
            output += result.stdout + result.stderr
        return self.strip_ansi(output)

    def test_ruff_use_cases(self, caplog):
        """The use cases must be reported by the equivalent checks before the ruff
        migration (pylint and flake8+bugbear) and after it (ruff)"""
        result = self.runner.invoke(main, ["--only-cp-cfg"])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        use_ruff = (
            parse_matrix_compatibility(os.environ.get("LINT_COMPATIBILITY_VERSION"), verbose=False)[
                "black_autoflake_matrix_value"
            ]
            >= 30
        )
        # The mandatory use cases can not live in "resources/" since the other tests
        # expect the mandatory checks passing for the resources modules
        mandatory_cases_fname = "ruff_mandatory_use_cases.py"
        mandatory_cases_src = TEST_PATH / "data_ruff" / "ruff_mandatory_use_cases.txt"
        shutil.copy(mandatory_cases_src, Path(self.tmp_dir) / mandatory_cases_fname)
        subprocess.check_call(["git", "add", "-A"])
        optional_cases_fname = posixpath.join("module_warnings1", "tests", "data", "ruff_optional_use_cases.py")
        for expected_use_cases, config_file, old_hook_ids, fname in [
            (
                self.RUFF_MANDATORY_USE_CASES_EXPECTED,
                ".pre-commit-config.yaml",
                ["flake8", "pylint_odoo"],
                mandatory_cases_fname,
            ),
            (
                self.RUFF_OPTIONAL_USE_CASES_EXPECTED,
                ".pre-commit-config-optional.yaml",
                ["flake8", "pylint_odoo"],
                optional_cases_fname,
            ),
        ]:
            hook_ids = ["ruff-check"] if use_ruff else old_hook_ids
            output = self.run_precommit_hooks(hook_ids, config_file, fname)
            for old_markers, ruff_marker in expected_use_cases:
                if use_ruff:
                    assert "%s:" % ruff_marker in output, "'%s' was not reported by ruff for %s\n%s" % (
                        ruff_marker,
                        fname,
                        output,
                    )
                else:
                    for old_marker in old_markers:
                        assert old_marker in output, "'%s' was not reported by pylint/flake8 for %s\n%s" % (
                            old_marker,
                            fname,
                            output,
                        )

    def test_valid_pylintrc_messages(self, caplog):
        self.runner.invoke(main, ["--only-cp-cfg"])
        pylint_messages = self.get_pylint_messages()
        rc_files = [
            Path(os.path.join(self.tmp_dir, CFG_SUBFOLDER, pylintrc)).resolve()
            for pylintrc in [".pylintrc", ".pylintrc-optional"]
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
        with Path(fname_wrong).open("w"):
            pass
        subprocess.check_call(["git", "add", "-A"])
        expected_logs = ["ERROR:pre-commit-vauxoo:Mandatory checks failed"]
        with self.custom_assert_logs("pre-commit-vauxoo", level="ERROR", expected_logs=expected_logs, caplog=caplog):
            result = self.runner.invoke(main, [])
        assert result.exit_code == 1, "Exited without error"

    def test_special_char_dirname(self, caplog):
        os.environ["PRECOMMIT_HOOKS_TYPE"] = "mandatory"
        dirname_wrong = os.path.join(self.tmp_dir, "module_example1", "moisé")
        Path(dirname_wrong).mkdir()
        fname = os.path.join(dirname_wrong, "empty_file.txt")
        with Path(fname).open("w"):
            pass
        subprocess.check_call(["git", "add", "-A"])
        expected_logs = ["ERROR:pre-commit-vauxoo:Mandatory checks failed"]
        with self.custom_assert_logs("pre-commit-vauxoo", level="ERROR", expected_logs=expected_logs, caplog=caplog):
            result = self.runner.invoke(main, [])
        assert result.exit_code == 1, "Exited without error"

    def test_apps_checks_disable(self, caplog):
        os.environ["PRECOMMIT_IS_PROJECT_FOR_APPS"] = "True"
        self.runner.invoke(main, [])
        f_content = Path(os.path.join(self.tmp_dir, CFG_SUBFOLDER, ".pylintrc")).read_text()
        assert "category-allowed-app" not in f_content, "app check disabled for a project for apps"

        os.environ["PRECOMMIT_IS_PROJECT_FOR_APPS"] = "False"
        self.runner.invoke(main, [])
        f_content = Path(os.path.join(self.tmp_dir, CFG_SUBFOLDER, ".pylintrc")).read_text()
        assert "category-allowed-app" in f_content, "app check enabled for a project for non apps"

        os.environ.pop("PRECOMMIT_IS_PROJECT_FOR_APPS")
        self.runner.invoke(main, [])
        f_content = Path(os.path.join(self.tmp_dir, CFG_SUBFOLDER, ".pylintrc")).read_text()
        assert "category-allowed-app" in f_content, "app check enabled for a project for non apps (default value)"

    @pytest.mark.parametrize(
        ("odoo_version", "expected_deprecated_modules"),
        [
            ("13.0", "openerp.osv,pdb,pudb,ipdb,bs4"),
            ("20.0", "openerp.osv,pdb,pudb,ipdb,bs4,pytz"),
        ],
    )
    def test_deprecated_modules_config(self, odoo_version, expected_deprecated_modules):
        result = self.runner.invoke(main, ["--only-cp-cfg", "--odoo-version", odoo_version])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)

        expected_by_file = {
            ".pylintrc": set(expected_deprecated_modules.split(",")) - {"openerp.osv"},
        }
        for pylintrc, expected_modules in expected_by_file.items():
            config = ConfigParser(inline_comment_prefixes=("#", ";"))
            config.read(os.path.join(self.tmp_dir, CFG_SUBFOLDER, pylintrc))
            deprecated_modules = {
                item.strip()
                for item in config.get("IMPORTS", "deprecated-modules").replace("\n", "").split(",")
                if item.strip()
            }
            assert expected_modules.issubset(deprecated_modules)

        config = ConfigParser(inline_comment_prefixes=("#", ";"))
        config.read(os.path.join(self.tmp_dir, CFG_SUBFOLDER, ".pylintrc"))
        enabled = {
            item.strip() for item in config["MESSAGES CONTROL"]["disable"].replace("\n", "").split(",") if item.strip()
        }
        assert "deprecated-module" not in enabled

    @pytest.mark.parametrize(
        "version,manifest_deprecated_keys",
        [
            ("14.0", ["active", "description"]),
            ("15.0", ["active", "description"]),
            ("16.0", ["active", "description", "qweb"]),
            ("17.0", ["active", "description", "qweb"]),
        ],
    )
    def test_pylint_cfg(self, version, manifest_deprecated_keys, tmp_path):
        cfg_content = render_template(version, ".pylintrc-optional.jinja")
        cfg_file = tmp_path / ".pylintrc-optional"
        cfg_file.write_text(cfg_content, encoding="utf-8")

        linter = PyLinter()
        linter.load_default_plugins()
        _config_initialization(linter, [], config_file=cfg_file)
        assert linter.is_message_enabled("manifest-deprecated-key"), "'manifest-deprecated-key' check not enabled"
        assert manifest_deprecated_keys == linter.config.manifest_deprecated_keys, (
            f"{version} should be manifest-deprecated-keys={','.join(manifest_deprecated_keys)}"
        )
