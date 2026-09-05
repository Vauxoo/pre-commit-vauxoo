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

from distutils.dir_util import copy_tree  # pylint:disable=deprecated-module

import pytest
from click.testing import CliRunner
from jinja2 import Environment, FileSystemLoader
from pylint.config.config_initialization import _config_initialization
from pylint.lint import PyLinter, Run
from yaml import Loader, load

from pre_commit_vauxoo import pre_commit_vauxoo
from pre_commit_vauxoo.cli import main
from pre_commit_vauxoo.hooks.check_commit_msg import (
    check_commit_messages_since_version,
    check_commit_msg_file,
    get_invalid_commit_messages,
    resolve_commit_message_base_ref,
    validate_commit_message_header,
)
from pre_commit_vauxoo.pre_commit_vauxoo import (
    CFG_SUBFOLDER,
    SCOPE_LAST_COMMIT,
    SCOPE_LAST_COMMITS,
    get_scope_files,
    parse_matrix_compatibility,
)

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


# ODOO checks from ruff-odoo (see the .ruff*.toml.jinja templates)
# Version-dependent gating is now handled by ruff-odoo's internal logic via --odoo-version;
# all version-scoped checks are always in select/ignore lists, ruff filters them at runtime
VERSIONED_MANDATORY_CHECKS = {
    "deprecated-inselect-operator",
    "deprecated-name-get",
    "manifest-summary-multiline",
    "no-raise-unlink",
    "prefer-env-attribute",  # deprecated-self-cr, autofixable but mandatory (see .ruff.toml)
}
# The translation-* family was optional in pylint-odoo so it keeps running as optional
VERSIONED_OPTIONAL_CHECKS = {
    "translation-contains-variable",
    "translation-format-interpolation",
    "translation-format-truncated",
    "translation-fstring-interpolation",
    "translation-too-few-args",
    "translation-too-many-args",
    "translation-unsupported-format",
}
VERSIONED_AUTOFIX_CHECKS = {"deprecated-self-cr", "prefer-env-translation", "translation-not-lazy"}
RUFF_TOML_FILENAMES = (".ruff.toml", ".ruff-optional.toml", ".ruff-experimental.toml", ".ruff-autofix.toml")


@pytest.fixture(
    name="ruff_odoo_version_use_case",
    params=[
        # odoo_version, expected checks in .ruff.toml (should be all regardless of version),
        # expected autofix ignored checks (none: ODW8161/ODW8165/ODW8301 gating is handled
        # internally by ruff-odoo via --odoo-version, so they are never in the ignore list)
        (None, VERSIONED_MANDATORY_CHECKS, set()),
        ("master", VERSIONED_MANDATORY_CHECKS, set()),
        ("13.0", VERSIONED_MANDATORY_CHECKS, set()),
        ("14.0", VERSIONED_MANDATORY_CHECKS, set()),
        ("15.0", VERSIONED_MANDATORY_CHECKS, set()),
        ("17.0", VERSIONED_MANDATORY_CHECKS, set()),
        ("saas-18.2", VERSIONED_MANDATORY_CHECKS, set()),
        ("19.0", VERSIONED_MANDATORY_CHECKS, set()),
        ("20.0", VERSIONED_MANDATORY_CHECKS, set()),
    ],
    ids=lambda use_case: "odoo-%s" % (use_case[0] or "none"),
)
def fixture_ruff_odoo_version_use_case(request):
    return request.param


@pytest.fixture(
    name="ruff_py_target_use_case",
    params=[
        # CLI extra arguments, expected ruff target-version
        ([], "py314"),  # No version defined uses the latest python version of the mapping
        (["--odoo-version", "12.0"], "py37"),  # odoo 12.0/13.0 use python 3.6 but ruff min is py37
        (["--odoo-version", "13.0"], "py37"),
        (["--odoo-version", "saas-13.5"], "py38"),  # saas jumps to the next odoo serie (14.0)
        (["--odoo-version", "14.0"], "py38"),
        (["--odoo-version", "15.0"], "py38"),
        (["--odoo-version", "16.0"], "py310"),
        (["--odoo-version", "17.0"], "py310"),
        (["--odoo-version", "saas-17.4"], "py312"),  # saas jumps to the next odoo serie (18.0)
        (["--odoo-version", "18.0"], "py312"),
        (["--odoo-version", "19.0"], "py312"),
        (["--odoo-version", "20.0"], "py314"),
        (["--odoo-version", "21.0"], "py314"),  # Newer than the mapping uses the latest python version
    ],
    ids=lambda use_case: (
        "%s-%s"
        % (
            "-".join(arg for arg in use_case[0] if not arg.startswith("--")) or "default",
            use_case[1],
        )
    ),
)
def fixture_ruff_py_target_use_case(request):
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
        # "resources/module_example1/models/markupsafe_sanitized.py" sanitizes the value so the
        # markupsafe XSS check must not be raised for it: it is whitelisted from the
        # "allowed_calls" of ".bandit-optional.yml" and, once ruff replaces bandit, from the
        # "allowed-markup-calls" of ".ruff-optional.toml"
        if self.uses_ruff():
            assert "unsafe-markup-use" not in output, (
                "unsafe-markup-use was raised for the sanitized Markup() call\n%s" % output
            )
        else:
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
        hook_content = Path(git_hook_pre_commit).read_text()
        assert "pre-commit-vauxoo" in hook_content, "File pre-commit not generated correctly"
        assert "--diff" in hook_content, "The git hook is not checking only the changes to be committed"
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

    def commit(self, message, allow_empty=True):
        cmd = [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@vauxoo.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            message,
        ]
        if allow_empty:
            cmd.insert(-2, "--allow-empty")
        subprocess.check_call(cmd)

    def add_remote(self, name, url, version="18.0"):
        subprocess.check_call(["git", "remote", "add", name, url])
        subprocess.check_call(["git", "update-ref", f"refs/remotes/{name}/{version}", "HEAD"])

    def test_base_ref_given_explicitly_wins(self, capsys):
        """What CI passes, because inferring is the wrong thing to do there"""
        self.commit("[FIX] module_example1: initial baseline")
        self.add_remote("stb", "git@example.com:vauxoo/project.git")
        os.environ[pre_commit_vauxoo.BASE_REF_ENVVAR] = "stb/18.0"

        assert resolve_commit_message_base_ref("19.0", scope=SCOPE_LAST_COMMITS) == "stb/18.0"
        # Reported before the run, not after: it decides what gets checked
        assert "given explicitly" in capsys.readouterr().out

    def test_base_ref_given_explicitly_must_exist(self):
        self.commit("[FIX] module_example1: initial baseline")
        os.environ[pre_commit_vauxoo.BASE_REF_ENVVAR] = "stb/does-not-exist"

        with pytest.raises(UserWarning, match="does not exist"):
            resolve_commit_message_base_ref("18.0", scope=SCOPE_LAST_COMMITS)

    def test_stable_remote_beats_the_vauxoo_namespace(self, capsys):
        """A vauxoo URL is not proof of stable: ircodoo keeps its own at ircanada"""
        self.commit("[FIX] module_example1: initial baseline")
        self.add_remote("stb", "git@example.com:ircanada/project.git")
        self.add_remote("nhomar", "git@git.vauxoo.com:vauxoo/project.git")
        self.add_remote("dev", "git@example.com:vauxoo-dev/project.git")

        assert resolve_commit_message_base_ref("18.0", scope=SCOPE_LAST_COMMITS) == "stb/18.0"
        assert "skipping the dev fork dev" in capsys.readouterr().out

    def test_vauxoo_namespace_beats_any_other_remote(self):
        """Without a stb remote the namespace decides, so oca never wins by name"""
        self.commit("[FIX] module_example1: initial baseline")
        self.add_remote("oca", "git@example.com:OCA/project.git")
        self.add_remote("vauxoo", "git@example.com:Vauxoo/project.git")

        assert resolve_commit_message_base_ref("18.0", scope=SCOPE_LAST_COMMITS) == "vauxoo/18.0"

    def test_only_dev_remotes_refuses_without_a_terminal(self):
        """It would ask, but CI has nobody to answer and must not hang on a prompt"""
        self.commit("[FIX] module_example1: initial baseline")
        self.add_remote("dev", "git@example.com:vauxoo-dev/project.git")
        self.add_remote("other", "git@example.com:someone-dev/project.git")

        with pytest.raises(UserWarning, match="--last-commits=REMOTE/BRANCH"):
            resolve_commit_message_base_ref("18.0", scope=SCOPE_LAST_COMMITS)

    def test_resolve_commit_message_base_ref_last_commit_scope(self):
        self.commit("[FIX] module_example1: initial baseline")
        self.commit("[FIX] module_example1: second one")
        subprocess.check_call(["git", "branch", "18.0"])

        assert resolve_commit_message_base_ref("18.0", scope=SCOPE_LAST_COMMIT) == "HEAD~1"

    def test_resolve_commit_message_base_ref_last_commit_scope_without_parent(self):
        self.commit("[FIX] module_example1: initial baseline")
        subprocess.check_call(["git", "branch", "18.0"])

        # The root commit has no parent, so the stable branch answers instead
        assert resolve_commit_message_base_ref("18.0", scope=SCOPE_LAST_COMMIT) == "18.0"

    def test_last_commits_scope_reports_every_file_since_stable(self):
        self.commit("[FIX] module_example1: initial baseline")
        subprocess.check_call(["git", "branch", "18.0"])
        for name in ("first.txt", "second.txt"):
            Path(os.path.join(self.tmp_dir, name)).write_text("content\n", encoding="utf-8")
            subprocess.check_call(["git", "add", name])
            self.commit(f"[ADD] {name}: new file", allow_empty=False)
        os.environ["VERSION"] = "18.0"

        assert get_scope_files(SCOPE_LAST_COMMITS, self.tmp_dir) == ["first.txt", "second.txt"]
        # The last commit alone only reports its own file
        assert get_scope_files(SCOPE_LAST_COMMIT, self.tmp_dir) == ["second.txt"]

    def test_last_commits_scope_validates_every_commit_message(self, capsys):
        self.commit("[FIX] module_example1: initial baseline")
        subprocess.check_call(["git", "branch", "18.0"])
        self.commit("[BAD] module_example1: invalid tag")
        self.commit("[FIX] module_example1: valid one")

        # capsys and not redirect_stdout: a StringIO leaves sys.stdout.encoding as None
        # and the git output decoding of the hook fails on it
        assert not check_commit_messages_since_version(
            repo_root=self.tmp_dir, version="18.0", scope=SCOPE_LAST_COMMITS
        )
        assert "[BAD] module_example1: invalid tag" in capsys.readouterr().out

        # The last commit scope only looks at HEAD, which is a valid one
        assert check_commit_messages_since_version(repo_root=self.tmp_dir, version="18.0", scope=SCOPE_LAST_COMMIT)

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
        # manifest-required-author (ODC8101) and invalid-commit (ODE8102) come from pylint-odoo,
        # dangerous-default-value (B006) comes from pylint and print-used (T201) runs as optional.
        # translation-required has no ruff equivalent so it should not add any ruff code
        expected_ruff_codes = {"B006", "ODC8101", "ODE8102", "T201"}
        ruff_toml_filenames = RUFF_TOML_FILENAMES
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

    @staticmethod
    def uses_ruff():
        """The compatibility matrix enables ruff, so the checks migrated to it run from ruff"""
        return (
            parse_matrix_compatibility(os.environ.get("LINT_COMPATIBILITY_VERSION"), verbose=False)[
                "black_autoflake_matrix_value"
            ]
            >= 30
        )

    def skip_if_no_ruff(self):
        if not self.uses_ruff():
            pytest.skip("Requires BLACK_AUTOFLAKE_MATRIX_VALUE >= 30")

    def test_ruff_odoo_version_checks(self, ruff_odoo_version_use_case, caplog):
        """All version-scoped ODOO checks are always in select/ignore lists in templates;
        ruff-odoo's internal logic via --odoo-version handles version gating at runtime"""
        self.skip_if_no_ruff()
        cfg_subfolder = Path(self.tmp_dir) / CFG_SUBFOLDER
        os.environ.pop("VERSION", None)
        odoo_version, expected_selected, expected_ignored = ruff_odoo_version_use_case
        argv = ["--only-cp-cfg"] + (["--odoo-version", odoo_version] if odoo_version else [])
        result = self.runner.invoke(main, argv)
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        with (cfg_subfolder / ".ruff.toml").open("rb") as f_ruff_toml:
            selected = set(tomllib.load(f_ruff_toml)["lint"]["select"])
        assert selected & VERSIONED_MANDATORY_CHECKS == expected_selected, (
            f"Wrong version-scoped checks selected in .ruff.toml for odoo version {odoo_version}"
        )
        with (cfg_subfolder / ".ruff-optional.toml").open("rb") as f_ruff_toml:
            selected_optional = set(tomllib.load(f_ruff_toml)["lint"]["select"])
        assert selected_optional & VERSIONED_OPTIONAL_CHECKS == VERSIONED_OPTIONAL_CHECKS, (
            f"Wrong version-scoped checks selected in .ruff-optional.toml for odoo version {odoo_version}"
        )
        with (cfg_subfolder / ".ruff-autofix.toml").open("rb") as f_ruff_toml:
            ignored = set(tomllib.load(f_ruff_toml)["lint"]["ignore"])
        assert ignored & VERSIONED_AUTOFIX_CHECKS == expected_ignored, (
            f"Wrong version-dependent ignores in .ruff-autofix.toml for odoo version {odoo_version}"
        )

    def test_ruff_odoo_options(self, caplog):
        """The [lint.odoo] options must have the same values configured for the
        pylint-odoo checks replaced by ruff-odoo (see the [ODOOLINT] section of .pylintrc*)"""
        self.skip_if_no_ruff()
        cfg_subfolder = Path(self.tmp_dir) / CFG_SUBFOLDER
        os.environ.pop("VERSION", None)
        result = self.runner.invoke(main, ["--only-cp-cfg", "--odoo-version", "17.0"])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        with (cfg_subfolder / ".ruff.toml").open("rb") as f_ruff_toml:
            data = tomllib.load(f_ruff_toml)
        odoo_options = data["lint"]["odoo"]
        assert odoo_options["odoo-version"] == "17.0", "Wrong odoo-version in .ruff.toml"
        # Same empty default of the pylint-odoo options so both checks are inert
        assert odoo_options["category-allowed"] == [], "Wrong category-allowed in .ruff.toml"
        assert odoo_options["odoo-required-files"] == [], "Wrong odoo-required-files in .ruff.toml"
        expected_checks = {"category-allowed", "missing-odoo-file"}
        assert expected_checks.issubset(set(data["lint"]["select"])), (
            "The checks using the [lint.odoo] options are not selected in .ruff.toml"
        )
        # manifest-version-format was an optional pylint-odoo check so it uses the odoo-version
        # option (the pylint "valid-odoo-version" one) from the optional configuration
        with (cfg_subfolder / ".ruff-optional.toml").open("rb") as f_ruff_toml:
            data_optional = tomllib.load(f_ruff_toml)
        assert data_optional["lint"]["odoo"]["odoo-version"] == "17.0", "Wrong odoo-version in .ruff-optional.toml"
        assert "manifest-version-format" in set(data_optional["lint"]["select"]), (
            "manifest-version-format is not selected in .ruff-optional.toml"
        )
        # license-allowed and manifest-required-author were optional pylint-odoo checks configured
        # from the [ODOOLINT] section of .pylintrc-optional, so the ruff-odoo ones must keep the
        # same values from the optional configuration
        odoo_options_optional = data_optional["lint"]["odoo"]
        pylintrc_optional = ConfigParser(inline_comment_prefixes=("#", ";"))
        pylintrc_optional.read(cfg_subfolder / ".pylintrc-optional")
        for ruff_option, pylint_option in (
            ("license-allowed", "license-allowed"),
            ("manifest-required-authors", "manifest-required-authors"),
        ):
            expected_values = [
                value.strip()
                for value in pylintrc_optional.get("ODOOLINT", pylint_option).replace("\n", "").split(",")
                if value.strip()
            ]
            assert odoo_options_optional[ruff_option] == expected_values, (
                f"The [lint.odoo] {ruff_option} of .ruff-optional.toml is not the [ODOOLINT] "
                f"{pylint_option} of .pylintrc-optional"
            )
        # manifest-deprecated-key is not configured: the ruff-odoo default already reports the
        # [ODOOLINT] manifest-deprecated-keys values gating qweb by the odoo-version option
        assert "manifest-deprecated-keys" not in odoo_options_optional, (
            "manifest-deprecated-keys should not be configured in .ruff-optional.toml"
        )
        expected_optional_checks = {"license-allowed", "manifest-required-author", "manifest-deprecated-key"}
        assert expected_optional_checks.issubset(set(data_optional["lint"]["select"])), (
            "The checks using the [lint.odoo] options are not selected in .ruff-optional.toml"
        )

    def test_ruff_checks_by_name(self, caplog):
        """The ruff checks must be configured by name (e.g. "no-search-all") and never by
        code (e.g. "ODW8163") to keep the same names used in the .pylintrc* configuration

        Only the linter prefixes without a name equivalent (e.g. "E", "W", "F", "OAPP") are
        allowed. Selecting the checks by name requires the "preview" mode enabled and an
        unknown name is only warned by ruff (not selected) so it needs to be checked here
        """
        self.skip_if_no_ruff()
        cfg_subfolder = Path(self.tmp_dir) / CFG_SUBFOLDER
        os.environ.pop("VERSION", None)
        result = self.runner.invoke(main, ["--only-cp-cfg", "--odoo-version", "17.0"])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        for ruff_toml_filename in RUFF_TOML_FILENAMES:
            with (cfg_subfolder / ruff_toml_filename).open("rb") as f_ruff_toml:
                data = tomllib.load(f_ruff_toml)
            assert data["preview"], (
                f"The preview mode is required to select the checks by name in {ruff_toml_filename}"
            )
            checks = data["lint"].get("select", []) + data["lint"]["ignore"]
            for per_file_checks in data["lint"].get("per-file-ignores", {}).values():
                checks += per_file_checks
            codes = [check for check in checks if re.match(r"^[A-Z]+\d+$", check)]
            assert not codes, f"The checks {codes} should be configured by name in {ruff_toml_filename}"

    def test_ruff_py_target_version(self, ruff_py_target_use_case, caplog):
        """The ruff target-version must be mapped from the odoo version
        (VERSION or --odoo-version)"""
        self.skip_if_no_ruff()
        cfg_subfolder = Path(self.tmp_dir) / CFG_SUBFOLDER
        os.environ.pop("VERSION", None)
        argv, expected_py_target = ruff_py_target_use_case
        result = self.runner.invoke(main, ["--only-cp-cfg"] + argv)
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        for ruff_toml_filename in RUFF_TOML_FILENAMES:
            with (cfg_subfolder / ruff_toml_filename).open("rb") as f_ruff_toml:
                py_target = tomllib.load(f_ruff_toml)["target-version"]
            assert py_target == expected_py_target, f"Wrong target-version in {ruff_toml_filename} for {argv}"

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
        (["(unnecessary-ellipsis)"], "unnecessary-placeholder"),
        (["(trailing-comma-tuple)"], "trailing-comma-on-bare-tuple"),
        (["(use-yield-from)"], "yield-in-for-loop"),
        (["(expression-not-assigned)"], "useless-expression"),
    ]
    # "ambiguous-variable-name" (E741) is not listed here on purpose: the optional flake8 did
    # report it before the ruff migration and now no level does, since "l" for "line" is used
    # everywhere and the IDE fonts do tell "1" and "l" apart
    RUFF_OPTIONAL_USE_CASES_EXPECTED = [
        (["(print-used)"], "print"),
        (["(implicit-str-concat)"], "single-line-implicit-string-concatenation"),
        (["(redundant-u-string-prefix)"], "unicode-kind-prefix"),
        (["(use-implicit-booleaness-not-comparison-to-string)"], "compare-to-empty-string"),
        (["(too-complex)"], "complex-structure"),
        (["E242"], "tab-after-comma"),
        (["B008"], "function-call-in-default-argument"),
        (["B011"], "assert-false"),
        (["(bad-docstring-quotes)"], "triple-single-quotes"),
        (["(use-dict-literal)"], "unnecessary-collection-call"),
    ]
    # The whole flake8-bandit family is ignored under "**/tests/**", so its use cases can not be
    # asserted from the file above -- that one has to live in "tests/data/" to stay out of the
    # autofixes. They get their own fixture at the repository root instead.
    RUFF_OPTIONAL_BANDIT_USE_CASES_EXPECTED = [
        # pylint-odoo reported the "except: pass" handler as except-pass, ruff reports it as the
        # flake8-bandit try-except-pass (the ruff-odoo except-pass is deprecated in favor of it)
        (["(except-pass)"], "try-except-pass"),
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
        use_ruff = self.uses_ruff()
        # The mandatory use cases can not live in "resources/" since the other tests
        # expect the mandatory checks passing for the resources modules
        mandatory_cases_fname = "ruff_mandatory_use_cases.py"
        mandatory_cases_src = TEST_PATH / "data_ruff" / "ruff_mandatory_use_cases.txt"
        shutil.copy(mandatory_cases_src, Path(self.tmp_dir) / mandatory_cases_fname)
        # Same reasoning for the bandit cases, which additionally can not sit under "tests/"
        optional_bandit_cases_fname = "ruff_optional_bandit_use_cases.py"
        optional_bandit_cases_src = TEST_PATH / "data_ruff" / "ruff_optional_bandit_use_cases.txt"
        shutil.copy(optional_bandit_cases_src, Path(self.tmp_dir) / optional_bandit_cases_fname)
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
            (
                self.RUFF_OPTIONAL_BANDIT_USE_CASES_EXPECTED,
                ".pre-commit-config-optional.yaml",
                ["flake8", "pylint_odoo"],
                optional_bandit_cases_fname,
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

    def assert_apps_checks_enabled(self, enabled, msg):
        use_ruff = self.uses_ruff()
        cfg_subfolder = Path(self.tmp_dir) / CFG_SUBFOLDER
        pylintrc_content = (cfg_subfolder / ".pylintrc").read_text()
        if not use_ruff:
            assert ("category-allowed-app" not in pylintrc_content) == enabled, msg
            return
        # With ruff the app checks are always disabled from pylint (migrated to OAPP*)
        assert "category-allowed-app" in pylintrc_content, msg
        with (cfg_subfolder / ".ruff.toml").open("rb") as f_ruff_toml:
            ruff_lint = tomllib.load(f_ruff_toml)["lint"]
        apps_checks = {"category-allowed-app", "manifest-required-key-app", "missing-odoo-file-app"}
        assert (apps_checks <= set(ruff_lint["select"])) == enabled, msg
        assert ("OAPP" in ruff_lint["ignore"]) != enabled, msg
        with (cfg_subfolder / ".ruff-autofix.toml").open("rb") as f_ruff_toml:
            autofix_ignore = tomllib.load(f_ruff_toml)["lint"]["ignore"]
        assert ("OAPP" in autofix_ignore) != enabled, msg

    def test_apps_checks_disable(self, caplog):
        os.environ["PRECOMMIT_IS_PROJECT_FOR_APPS"] = "True"
        self.runner.invoke(main, [])
        self.assert_apps_checks_enabled(True, "app checks disabled for a project for apps")

        os.environ["PRECOMMIT_IS_PROJECT_FOR_APPS"] = "False"
        self.runner.invoke(main, [])
        self.assert_apps_checks_enabled(False, "app checks enabled for a project for non apps")

        os.environ.pop("PRECOMMIT_IS_PROJECT_FOR_APPS")
        self.runner.invoke(main, [])
        self.assert_apps_checks_enabled(False, "app checks enabled for a project for non apps (default value)")

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

    def git_call(self, *args):
        subprocess.check_call(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@vauxoo.com",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=self.tmp_dir,
        )

    def git_commit_all(self, message="[FIX] module_example1: testing"):
        self.git_call("add", "-A")
        self.git_call("commit", "-q", "-m", message)

    def write_file(self, relpath, content="# comment\n"):
        fname = Path(self.tmp_dir) / relpath
        with fname.open("a", encoding="utf-8") as f_content:
            f_content.write(content)
        return relpath

    def invoke_scope(self, monkeypatch, argv):
        """Invoke the CLI without running the real hooks

        The configuration files and the hooks are not needed to check which files are
        sent to "pre-commit run", so they are stubbed to keep these tests fast
        """
        commands = []

        def stub_subprocess_call(command, *args, **kwargs):
            commands.append(command)
            return 0

        monkeypatch.setattr(pre_commit_vauxoo, "subprocess_call", stub_subprocess_call)
        monkeypatch.setattr(pre_commit_vauxoo, "copy_cfg_files", lambda *args, **kwargs: None)
        result = self.runner.invoke(main, argv)
        run_commands = [command for command in commands if command[:2] == ["pre-commit", "run"]]
        return result, run_commands

    def scope_files(self, run_command):
        """Files sent to "pre-commit run" relative to the repository or None if it runs '--all'"""
        if "--files" not in run_command:
            return None
        files = run_command[run_command.index("--files") + 1 : run_command.index("-c")]
        # "as_posix" is required since that windows separates the paths with "\"
        return sorted(Path(os.path.relpath(fname, self.tmp_dir)).as_posix() for fname in files)

    def test_scope_default_is_all(self, monkeypatch):
        """Running the command without a scope keeps checking the whole repository"""
        self.git_commit_all()
        self.write_file("module_example1/__init__.py")
        result, run_commands = self.invoke_scope(monkeypatch, [])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        assert run_commands, "The hooks were not run"
        for run_command in run_commands:
            assert "--all" in run_command, "The default scope is not the whole repository"
            assert self.scope_files(run_command) is None, "The default scope is limiting the files"

    def test_scope_last_commit(self, monkeypatch):
        """'--last-commit' only checks the files of the last commit"""
        self.git_commit_all()
        self.write_file("module_example1/models/models.py")
        self.git_commit_all("[FIX] module_example1: last commit change")
        # Changes not committed are not part of the last commit
        self.write_file("module_warnings1/models/models.py")
        result, run_commands = self.invoke_scope(monkeypatch, ["--last-commit"])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        assert run_commands, "The hooks were not run"
        for run_command in run_commands:
            assert self.scope_files(run_command) == ["module_example1/models/models.py"], (
                "'--last-commit' is not checking the files of the last commit"
            )

    def test_scope_diff(self, monkeypatch):
        """'--diff' checks the staged, unstaged and untracked changes but not the committed ones"""
        self.git_commit_all()
        unstaged = self.write_file("module_example1/models/models.py")
        staged = self.write_file("module_warnings1/models/models.py")
        self.git_call("add", staged)
        untracked = self.write_file("module_example1/new_file.py")
        result, run_commands = self.invoke_scope(monkeypatch, ["--diff"])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        assert run_commands, "The hooks were not run"
        for run_command in run_commands:
            assert self.scope_files(run_command) == sorted([unstaged, staged, untracked]), (
                "'--diff' is not checking the staged, unstaged and untracked changes"
            )

    def test_scope_diff_without_changes(self, monkeypatch, caplog):
        """'--diff' without changes does not run the hooks at all"""
        self.git_commit_all()
        expected_logs = ["WARNING:pre-commit-vauxoo:There are no files to check for '--diff'. Nothing to do."]
        with self.custom_assert_logs("pre-commit-vauxoo", level="WARNING", expected_logs=expected_logs, caplog=caplog):
            result, run_commands = self.invoke_scope(monkeypatch, ["--diff"])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        assert not run_commands, "The hooks were run without files to check"

    def test_scope_paths_precedence(self, monkeypatch, caplog):
        """'-p/--paths' has precedence over the scope parameters"""
        self.git_commit_all()
        self.write_file("module_warnings1/models/models.py")
        expected_logs = [
            "WARNING:pre-commit-vauxoo:Conflicting parameters: '--diff' is ignored "
            "since that '-p/--paths' has precedence over it"
        ]
        with self.custom_assert_logs("pre-commit-vauxoo", level="WARNING", expected_logs=expected_logs, caplog=caplog):
            result, run_commands = self.invoke_scope(monkeypatch, ["--diff", "-p", "module_example1"])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        assert run_commands, "The hooks were not run"
        for run_command in run_commands:
            files = self.scope_files(run_command)
            assert "module_example1/__init__.py" in files, "'-p/--paths' is not checking its own files"
            assert "module_warnings1/models/models.py" not in files, "'--diff' was not ignored"

    def test_scope_from_subdirectory(self, monkeypatch, caplog):
        """The scope has precedence over the current directory checking the whole repository"""
        self.git_commit_all()
        changed = self.write_file("module_warnings1/models/models.py")
        self.git_commit_all("[FIX] module_warnings1: last commit change")
        expected_logs = [
            "WARNING:pre-commit-vauxoo:Running '--last-commit' for the whole repository "
            "even if the current directory is 'module_example1'"
        ]
        with self.chdir("module_example1"):
            with self.custom_assert_logs(
                "pre-commit-vauxoo", level="WARNING", expected_logs=expected_logs, caplog=caplog
            ):
                result, run_commands = self.invoke_scope(monkeypatch, ["--last-commit"])
        assert not result.exit_code, "Exited with error %s - %s" % (result, result.output)
        assert run_commands, "The hooks were not run"
        for run_command in run_commands:
            assert self.scope_files(run_command) == [changed], "The current directory has precedence over the scope"
