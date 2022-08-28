import logging
import os
import re
import subprocess
import sys

from . import logging_colored

_logger = logging.getLogger("pre-commit-vauxoo")

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
    precommit_config_dir, repo_dirname, overwrite, exclude_lint, disable_pylint_checks, exclude_autofix
):
    exclude_lint_regex = ""
    exclude_autofix_regex = ""
    if exclude_lint:
        exclude_lint_regex = "(%s)|" % "|".join(
            [re.escape(exclude_path.strip()) for exclude_path in exclude_lint if exclude_path and exclude_path.strip()]
        )
    if exclude_autofix:
        exclude_autofix_regex = "(%s)|" % "|".join(
            [
                re.escape(exclude_path.strip())
                for exclude_path in exclude_autofix
                if exclude_path and exclude_path.strip()
            ]
        )
    _logger.info("Copying configuration files 'cp -rnT %s/ %s/", precommit_config_dir, repo_dirname)
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
            _logger.warning("Using custom file %s", dst)
            continue
        with open(src, "r") as fsrc, open(dst, "w") as fdst:
            for line in fsrc:
                if fname.startswith(".pre-commit-config") and "# EXCLUDE_LINT" in line:
                    line = ""
                    if exclude_lint:
                        _logger.info("Applying EXCLUDE_LINT=%s to %s", exclude_lint, dst)
                        line += "    %s\n" % exclude_lint_regex
                    if fname == ".pre-commit-config-autofix.yaml" and exclude_autofix:
                        _logger.info("Applying EXCLUDE_AUTOFIX=%s to %s", exclude_autofix, dst)
                        line += "    %s\n" % exclude_autofix_regex
                if disable_pylint_checks and fname.startswith(".pre-commit-config") and "--disable=R0000" in line:
                    line = line.replace("R0000", ','.join(disable_pylint_checks))
                fdst.write(line)


def envfile2envdict(repo_dirname, source_file="variables.sh", no_overwrite_environ=True):
    """Simulate load the Vauxoo standard file 'source variables.sh' command in python
    return dictionary {environment_variable: value}
    """
    envdict = {}
    source_file_path = os.path.join(repo_dirname, source_file)
    if not os.path.isfile(source_file_path):
        _logger.info("Skipping 'source %s' file because it was not found", source_file_path)
        return envdict
    with open(source_file_path) as f_source_file:
        _logger.info("Running 'source %s'", source_file_path)
        for line in f_source_file:
            line_match = re_export.match(line)
            if not line_match:
                continue
            if no_overwrite_environ and line_match["variable"] in os.environ:
                continue
            envdict.update({line_match["variable"]: line_match["value"]})
    return envdict


def subprocess_call(command, *args, **kwargs):
    cmd_str = ' '.join(command)
    _logger.debug("Running command: %s", cmd_str)
    return subprocess.call(command, *args, **kwargs)


# There are a lot of if validations in this method. It is expected for now.
# pylint: disable=too-complex
def main(
    include_lint,
    overwrite,
    exclude_autofix,
    exclude_lint,
    disable_pylint_checks,
    autofix,
    precommit_hooks_type,
    do_exit=True,
):
    repo_dirname = get_repo()
    cwd = os.path.abspath(os.path.realpath(os.getcwd()))

    root_dir = os.path.abspath(os.path.dirname(__file__))

    precommit_config_dir = os.path.join(root_dir, "cfg")

    copy_cfg_files(
        precommit_config_dir,
        repo_dirname,
        overwrite,
        exclude_lint,
        disable_pylint_checks,
        exclude_autofix,
    )
    if autofix:
        precommit_hooks_type = ("mandatory", "optional", "fix")
    elif not precommit_hooks_type:
        precommit_hooks_type = ("mandatory", "optional")

    _logger.info("Installing pre-commit hooks")
    cmd = ["pre-commit", "install-hooks", "--color=always"]
    pre_commit_cfg_mandatory = os.path.join(repo_dirname, ".pre-commit-config.yaml")
    pre_commit_cfg_optional = os.path.join(repo_dirname, ".pre-commit-config-optional.yaml")
    pre_commit_cfg_autofix = os.path.join(repo_dirname, ".pre-commit-config-autofix.yaml")
    if "mandatory" in precommit_hooks_type or 'all' in precommit_hooks_type:
        subprocess_call(cmd + ["-c", pre_commit_cfg_mandatory])
    if "optional" in precommit_hooks_type or 'all' in precommit_hooks_type:
        subprocess_call(cmd + ["-c", pre_commit_cfg_optional])
    if "fix" in precommit_hooks_type or 'all' in precommit_hooks_type:
        subprocess_call(cmd + ["-c", pre_commit_cfg_autofix])

    status = 0
    cmd = ["pre-commit", "run", "--color=always"]
    if cwd != repo_dirname:
        cwd_short = os.path.relpath(cwd, repo_dirname)
        if include_lint:
            _logger.warning(
                "Ignored path configured '%s'. Use 'cd %s' and run the same command again to use configured path",
                ','.join(include_lint),
                repo_dirname,
            )
        _logger.warning("Running in current directory '%s'", cwd_short)
        files = get_files(cwd)
        if not files:
            raise UserWarning("Not files detected in current path %s" % cwd_short)
        cmd.extend(["--files"] + files)
    elif include_lint:
        _logger.info("Running only for INCLUDE_LINT=%s", include_lint)
        included_files = []
        for included_path in include_lint:
            included_files += get_files(included_path) or (included_path,)
        cmd.extend(["--files"] + included_files)
    else:
        cmd.append("--all")
    all_status = {}

    if "fix" in precommit_hooks_type or 'all' in precommit_hooks_type:
        _logger.info("%s AUTOFIX CHECKS %s", "-" * 25, "-" * 25)
        _logger.info("Running autofix checks (affect status build but you can autofix them locally)")
        autofix_status = subprocess_call(cmd + ["-c", pre_commit_cfg_autofix])
        status += autofix_status
        test_name = 'Autofix checks'
        all_status[test_name] = {'status': autofix_status}
        if autofix_status != 0:
            _logger.error("%s reformatted", test_name)
            all_status[test_name]['level'] = logging.ERROR
            all_status[test_name]['status_msg'] = "Reformatted"
        else:
            _logger.info("%s passed!", test_name)
            all_status[test_name]['level'] = logging.INFO
            all_status[test_name]['status_msg'] = "Passed"
        _logger.info("-" * 66)

    if "mandatory" in precommit_hooks_type or 'all' in precommit_hooks_type:
        _logger.info("%s MANDATORY CHECKS %s", "*" * 25, "*" * 25)
        _logger.info("Running mandatory checks (affect status build)")
        mandatory_status = subprocess_call(cmd + ["-c", pre_commit_cfg_mandatory])
        status += mandatory_status
        test_name = 'Mandatory checks'
        all_status[test_name] = {'status': mandatory_status}
        if status != 0:
            _logger.error("%s failed", test_name)
            all_status[test_name]['level'] = logging.ERROR
            all_status[test_name]['status_msg'] = "Failed"
        else:
            _logger.info("%s passed!", test_name)
            all_status[test_name]['level'] = logging.INFO
            all_status[test_name]['status_msg'] = "Passed"

    if "optional" in precommit_hooks_type or 'all' in precommit_hooks_type:
        _logger.info("*" * 68)
        _logger.info("%s OPTIONAL CHECKS %s", "~" * 25, "~" * 25)
        _logger.info("Running optional checks (does not affect status build)")
        status_optional = subprocess_call(cmd + ["-c", os.path.join(repo_dirname, pre_commit_cfg_optional)])
        test_name = 'Optional checks'
        all_status[test_name] = {'status': status_optional}
        if status_optional != 0:
            _logger.warning("Optional checks failed")
            all_status[test_name]['level'] = logging.WARNING
            all_status[test_name]['status_msg'] = "Failed"
        else:
            _logger.info("Optional checks passed!")
            all_status[test_name]['level'] = logging.INFO
            all_status[test_name]['status_msg'] = "Passed"
        _logger.info("~" * 67)

    print_summary(all_status)
    if do_exit:
        sys.exit(0 if status == 0 else 1)


def print_summary(all_status):
    summary_msg = ["+" + "=" * 39]
    summary_msg.append("|  Tests summary:")
    summary_msg.append("|" + "-" * 39)
    for test_name, test_result in all_status.items():
        outcome = (
            logging_colored.colorized_msg(test_result['status_msg'], test_result['level'])
            if test_result['status'] != 0
            else logging_colored.colorized_msg(test_result['status_msg'], test_result['level'])
        )
        summary_msg.append("| {:<28}{}".format(test_name, outcome))
    summary_msg.append("+" + "=" * 39)
    _logger.info("Tests summary\n%s", '\n'.join(summary_msg))


if __name__ == "__main__":
    main()
