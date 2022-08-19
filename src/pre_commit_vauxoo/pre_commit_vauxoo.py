#!/usr/bin/env python
import logging
import os
import re
import subprocess
import sys

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger(__name__)


re_export = re.compile(
    r"^(?P<export>export|EXPORT)( )+"
    + r"(?P<variable>[\w]*)[ ]*[\=][ ]*[\"\']{0,1}"
    + r"(?P<value>[\w\.\-\_/\$\{\}\:,\(\)\#\* ]*)[\"\']{0,1}",
    re.M,
)


def get_repo():
    repo_root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode(sys.stdout.encoding).strip()
    repo_root = os.path.abspath(os.path.realpath(repo_root))
    return repo_root


def get_files(path):
    ls_files = subprocess.check_output(["git", "ls-files", "--", path]).decode(sys.stdout.encoding).strip()
    ls_files = ls_files.splitlines()
    return ls_files


def copy_cfg_files(
    precommit_config_dir, repo_dirname, overwrite, exclude_lint, disable_pylint_checks
):
    exclude_regex = ""
    if exclude_lint:
        exclude_regex = "(%s)|" % "|".join(
            [
                re.escape(exclude_path.strip())
                for exclude_path in exclude_lint.split(",")
                if exclude_path and exclude_path.strip()
            ]
        )
    for fname in os.listdir(precommit_config_dir):
        if not fname.startswith(".") and fname != "pyproject.toml":
            # all configuration files are hidden
            continue
        src = os.path.join(precommit_config_dir, fname)
        if not os.path.isfile(src):
            # if it is not a file skip
            continue
        dst = os.path.join(repo_dirname, fname)
        if not overwrite and os.path.isfile(dst):
            # Use the custom files defined in the repo
            _logger.info("Use custom file %s", dst)
            continue
        _logger.info("Copying %s to %s", src, dst)
        with open(src, "r") as fsrc, open(dst, "w") as fdst:
            for line in fsrc:
                if (
                    exclude_lint
                    and fname.startswith(".pre-commit-config")
                    and "# EXCLUDE_LINT" in line
                ):
                    _logger.info("Apply EXCLUDE_LINT=%s to %s", exclude_lint, dst)
                    line = "    %s\n" % exclude_regex
                if (
                    disable_pylint_checks
                    and fname.startswith(".pre-commit-config")
                    and "--disable=R0000" in line
                ):
                    line = line.replace("R0000", disable_pylint_checks)
                fdst.write(line)


def envfile2envdict(repo_dirname, source_file="variables.sh"):
    """Simulate load the Vauxoo standard file 'source variables.sh' command in python
    return dictionary {environment_variable: value}
    """
    source_file_path = os.path.join(repo_dirname, source_file)
    if not os.path.isfile(source_file_path):
        _logger.info("Skip 'source %s' file not found" % source_file_path)
        return []
    envdict = {}
    with open(source_file_path) as f_source_file:
        _logger.info("Running 'source %s'" % source_file_path)
        for line in f_source_file:
            line_match = re_export.match(line)
            if not line_match:
                continue
            envdict.update({line_match["variable"]: line_match["value"]})
    return envdict


def main(argv=None, exit=True):
    repo_dirname = get_repo()
    cwd = os.path.abspath(os.path.realpath(os.getcwd()))

    envdict = envfile2envdict(repo_dirname)
    os.environ.update(envdict)

    # Get the configuration files but you can use custom ones so set "0"
    overwrite = os.environ.get("PRECOMMIT_OVERWRITE_CONFIG_FILES", "1") == "1"
    # Exclude paths to lint
    exclude_lint = os.environ.get("EXCLUDE_LINT", "")
    # Disable pylint checks
    disable_pylint_checks = os.environ.get("DISABLE_PYLINT_CHECKS", "")
    # Enable .pre-commit-config-autofix.yaml configuration file
    enable_auto_fix = os.environ.get("PRECOMMIT_AUTOFIX", "") == "1"
    root_dir = os.path.dirname(os.path.abspath(__file__))
    precommit_config_dir = os.path.join(root_dir, "cfg")

    copy_cfg_files(
        precommit_config_dir,
        repo_dirname,
        overwrite,
        exclude_lint,
        disable_pylint_checks,
    )

    _logger.info("Installing pre-commit hooks")
    cmd = ["pre-commit", "install-hooks", "--color=always"]
    subprocess.call(cmd)
    subprocess.call(cmd + ["-c", os.path.join(repo_dirname, ".pre-commit-config-optional.yaml")])

    status = 0
    cmd = ["pre-commit", "run", "--color=always"]
    if cwd != repo_dirname:
        cwd_short = os.path.relpath(cwd, repo_dirname)
        _logger.info("Running only for sub-path '%s'" % cwd_short)
        files = get_files(cwd)
        if not files:
            raise UserWarning("Not files detected in current path %s" % cwd_short)
        cmd.extend(["--files"] + files)
    else:
        cmd.append("--all")
    if enable_auto_fix:
        _logger.info("%s AUTOFIX CHECKS %s", "-" * 25, "-" * 25)
        _logger.info(
            "Running autofix checks (affect status build but you can autofix them locally)"
        )
        status += subprocess.call(cmd + ["-c", os.path.join(repo_dirname, ".pre-commit-config-autofix.yaml")])
        _logger.info("-" * 100)
    _logger.info("%s MANDATORY CHECKS %s", "*" * 25, "*" * 25)
    _logger.info("Running mandatory checks (affect status build)")
    status += subprocess.call(cmd)
    _logger.info("*" * 100)
    _logger.info("%s OPTIONAL CHECKS %s", "~" * 25, "~" * 25)
    _logger.info("Running optional checks (does not affect status build)")
    subprocess.call(cmd + ["-c", os.path.join(repo_dirname, ".pre-commit-config-optional.yaml")])
    _logger.info("~" * 100)
    if exit:
        sys.exit(0 if status == 0 else 1)


if __name__ == "__main__":
    main()
