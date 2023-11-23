import ast
import glob
import logging
import os
import posixpath
import re
import shutil
import subprocess
import sys

from . import __version__, logging_colored

_logger = logging.getLogger("pre-commit-vauxoo")

re_export = re.compile(
    r"^(?P<export>export|EXPORT)( )+"
    + r"(?P<variable>[\w]*)[ ]*[\=][ ]*[\"\']{0,1}"
    + r"(?P<value>[\w\.\-\_/\$\{\}\:,\(\)\#\* ]*)[\"\']{0,1}",
    re.M,
)


def full_norm_path(path):
    return os.path.normpath(os.path.realpath(os.path.abspath(os.path.expanduser(os.path.expandvars(path.strip())))))


def get_is_ci():
    if os.environ.get("CI_JOB_ID"):
        return (True, "gitlab")
    if os.environ.get("GITHUB_RUN_ID"):
        return (True, "github")
    if os.environ.get("TRAVIS"):
        return (True, "travis")
    if os.environ.get("CI"):
        return (True, "unknown")
    return (False, "")


def get_repo():
    repo_root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode(sys.stdout.encoding).strip()
    repo_root = full_norm_path(repo_root)
    return repo_root


def get_files(path):
    ls_files = subprocess.check_output(["git", "ls-files", "--", path]).decode(sys.stdout.encoding).strip()
    ls_files = ls_files.splitlines()
    return ls_files


def git_cwd():
    """When the command is invoked from a subdirectory, show
    the path of the current directory relative to the top-level
    directory.
    Return "." if it is the top-level
    """
    res = subprocess.check_output(["git", "rev-parse", "--show-prefix", "."]).decode(sys.stdout.encoding).strip()
    git_path_rel = res.splitlines()[0].rstrip("/" + os.sep)
    return git_path_rel


def get_uninstallable_modules(src_path) -> set:
    """Find all odoo modules that are set as not installable. They must have a key 'installable' with a False value
    in order to be considered not installable.

    :return: A set of strings, each one representing the relative path (from repo dir) to an uninstallable module.
    """
    results = set()
    for path in glob.glob(os.path.join(src_path, "*/__manifest__.py")):
        with open(path) as manifest:
            try:
                if not ast.literal_eval(manifest.read()).get("installable", True):
                    results.add(posixpath.join(os.path.dirname(os.path.relpath(path, start=src_path)), ""))
            except (ValueError, TypeError, SyntaxError, AttributeError):
                _logger.info("Unable to parse manifest at %s. Considering it installable", path)

    return results


def copy_cfg_files(
    precommit_config_dir,
    repo_dirname,
    no_overwrite,
    exclude_lint,
    pylint_disable_checks,
    oca_hooks_disable_checks,
    exclude_autofix,
    skip_string_normalization,
    odoo_version,
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
        src = os.path.join(precommit_config_dir, fname)
        if not os.path.isfile(src):
            # if it is not a file skip
            continue
        dst = os.path.join(repo_dirname, fname)
        if no_overwrite and os.path.isfile(dst):
            # Use the custom files defined in the repo
            _logger.warning("Using custom file %s", dst)
            continue
        with open(src) as fsrc, open(dst, "w") as fdst:
            for line in fsrc:
                if fname.startswith(".pre-commit-config") and "# EXCLUDE_LINT" in line:
                    line = ""
                    if exclude_lint:
                        _logger.info("Applying EXCLUDE_LINT=%s to %s", exclude_lint, dst)
                        line += "    %s\n" % exclude_lint_regex
                    if fname == ".pre-commit-config-autofix.yaml" and exclude_autofix:
                        _logger.info("Applying EXCLUDE_AUTOFIX=%s to %s", exclude_autofix, dst)
                        line += "    %s\n" % exclude_autofix_regex
                if pylint_disable_checks and fname.startswith(".pre-commit-config") and "--disable=R0000" in line:
                    _logger.info(
                        "Disabling the following pylint checks (PYLINT_DISABLE_CHECKS): %s", pylint_disable_checks
                    )
                    line = line.replace("R0000", ",".join(pylint_disable_checks))
                if oca_hooks_disable_checks and fname.startswith(".oca_hooks.cfg") and "disable=" in line:
                    _logger.info(
                        "Disabling the following oca hooks checks (OCA_HOOKS_DISABLE_CHECKS): %s",
                        oca_hooks_disable_checks,
                    )
                    line = line.replace("\n", f',{",".join(oca_hooks_disable_checks)}\n')
                if fname == "pyproject.toml" and line.startswith("skip-string-normalization"):
                    line = "skip-string-normalization=%s\n" % (skip_string_normalization and "true" or "false")
                if fname.startswith(".pylintrc"):
                    if "# External scripts odoo_lint replace" in line and odoo_version:
                        line += "valid-odoo-version=%s\n" % odoo_version
                fdst.write(line)


def envfile2envdict(repo_dirname, source_file="variables.sh", no_overwrite_environ=True):
    """Simulate load the Vauxoo standard file 'source variables.sh' command in python
    return dictionary {environment_variable: value}
    """
    envdict = {}
    source_file_path = os.path.join(repo_dirname, source_file)
    if not os.path.isfile(source_file_path):
        _logger.info("Skipping 'source %s' file because it was not found", source_file)
        return envdict
    with open(source_file_path) as f_source_file:
        _logger.info("Running 'source %s'", source_file)
        for line in f_source_file:
            line_match = re_export.match(line)
            if not line_match:
                continue
            line_match = line_match.groupdict()  # py3.5 comp
            if no_overwrite_environ and line_match["variable"] in os.environ:
                continue
            envdict.update({line_match["variable"]: line_match["value"]})
    return envdict


def subprocess_call(command, *args, **kwargs):
    cmd_str = " ".join(command)
    _logger.debug("Running command: %s", cmd_str)
    return subprocess.call(command, *args, **kwargs)


# There are a lot of if validations in this method. It is expected for now.
# pylint: disable=too-complex
def main(
    paths,
    no_overwrite,
    exclude_autofix,
    exclude_lint,
    pylint_disable_checks,
    oca_hooks_disable_checks,
    precommit_hooks_type,
    fail_optional,
    install,
    skip_string_normalization,
    odoo_version,
    do_exit=True,
):
    show_version()
    repo_dirname = get_repo()
    cwd = git_cwd()

    root_dir = full_norm_path(os.path.dirname(__file__))

    if install:
        git_hook_pre_commit_src = os.path.join(root_dir, "git_hook_pre_commit")
        git_hook_pre_commit_dest = os.path.join(repo_dirname, ".git", "hooks", "pre-commit")
        _logger.info("pre-commit installed at %s", git_hook_pre_commit_dest)
        shutil.copy(git_hook_pre_commit_src, git_hook_pre_commit_dest)
        if do_exit:
            sys.exit(0)
        return

    precommit_config_dir = os.path.join(root_dir, "cfg")
    uninstallable_modules = get_uninstallable_modules(repo_dirname)
    exclude_lint += tuple(uninstallable_modules)

    copy_cfg_files(
        precommit_config_dir,
        repo_dirname,
        no_overwrite,
        exclude_lint,
        pylint_disable_checks,
        oca_hooks_disable_checks,
        exclude_autofix,
        skip_string_normalization,
        odoo_version,
    )
    _logger.info("Installing pre-commit hooks")
    cmd = ["pre-commit", "install-hooks", "--color=always"]
    pre_commit_cfg_mandatory = os.path.join(repo_dirname, ".pre-commit-config.yaml")
    pre_commit_cfg_optional = os.path.join(repo_dirname, ".pre-commit-config-optional.yaml")
    pre_commit_cfg_autofix = os.path.join(repo_dirname, ".pre-commit-config-autofix.yaml")
    if "mandatory" in precommit_hooks_type:
        subprocess_call(cmd + ["-c", pre_commit_cfg_mandatory])
    if "optional" in precommit_hooks_type:
        subprocess_call(cmd + ["-c", pre_commit_cfg_optional])
    if "fix" in precommit_hooks_type:
        subprocess_call(cmd + ["-c", pre_commit_cfg_autofix])

    status = 0
    cmd = ["pre-commit", "run", "--color=always"]
    if cwd != ".":
        if paths:
            _logger.warning(
                "Ignored path configured '%s'. Use 'cd %s' and run the same command again to use configured path",
                ",".join(paths),
                repo_dirname,
            )
        _logger.warning("Running in current directory '%s'", os.path.basename(cwd))
        files = get_files(os.path.join(repo_dirname, cwd))
        if not files:
            raise UserWarning("Not files detected in current path %s" % cwd)
        cmd.extend(["--files"] + files)
    elif paths and paths != (".",):
        _logger.info("Running only for INCLUDE_LINT=%s", paths)
        included_files = []
        for included_path in paths:
            included_files += get_files(included_path) or (included_path,)
        cmd.extend(["--files"] + included_files)
    else:
        cmd.append("--all")
    all_status = {}

    if "fix" in precommit_hooks_type:
        _logger.info("%s AUTOFIX CHECKS %s", "-" * 25, "-" * 25)
        _logger.info("Running autofix checks (affect status build but you can autofix them locally)")
        autofix_status = subprocess_call(cmd + ["-c", pre_commit_cfg_autofix])
        status += autofix_status
        test_name = "Autofix checks"
        all_status[test_name] = {"status": autofix_status}
        if autofix_status:
            _logger.error("%s reformatted", test_name)
            is_ci = get_is_ci()
            if is_ci[0]:
                # Similar to https://github.com/pre-commit/pre-commit/blob/3fe38df/pre_commit/commands/run.py#L306
                # But using a custom message related to pre-commit-vauxoo instead of pre-commit
                # and limit the output
                diff = (
                    subprocess.check_output(["git", "--no-pager", "diff", "--no-ext-diff", "--color=always"])
                    .decode(sys.stdout.encoding)
                    .strip()[:2000]
                )
                msg_info = {
                    "ci_name": is_ci[1],
                    "py_version": "%s.%s" % (sys.version_info.major, sys.version_info.minor),
                    "package_version": __version__,
                    "odoo_version": odoo_version or "STABLE_BRANCH",
                    "repo_name": os.path.basename(repo_dirname),
                    "diff": diff,
                }
                _logger.error(
                    "%(ci_name)s shows this error but you need to fix it locally\n"
                    "1. Install/Upgrade the package in your environment as you usually do it:\n"
                    "e.g. `python%(py_version)s -m "
                    "pip install --force-reinstall -U pre-commit-vauxoo==%(package_version)s`\n"
                    "Or using 'sudo'\n"
                    "e.g. `sudo python%(py_version)s -m "
                    "pip install --force-reinstall -U pre-commit-vauxoo==%(package_version)s`\n"
                    "Or using '--user'\n"
                    "e.g. `python%(py_version)s -m "
                    "pip install --user --force-reinstall -U pre-commit-vauxoo==%(package_version)s`\n"
                    "Or using virtualenv\n"
                    "e.g. `source YOUR_VENV/bin/activate && "
                    "pip install --force-reinstall -U pre-commit-vauxoo==%(package_version)s`\n"
                    "Also, check your `python --version` and `pre-commit-vauxoo --version` "
                    "is matching it could get different results\n"
                    "2. Pull the last changes to your repository locally\n"
                    "`git pull origin %(odoo_version)s`\n"
                    "3. Run `pre-commit-vauxoo` command into the root path of your repository\n"
                    "Using a subfolder could get different results\n"
                    "`cd %(repo_name)s && pre-commit-vauxoo`\n"
                    "4. Run `git commit ...` and `git push ...`\n\n"
                    "All changes made by hooks:\n%(diff)s",
                    msg_info,
                )
            all_status[test_name]["level"] = logging.ERROR
            all_status[test_name]["status_msg"] = "Reformatted"
        else:
            _logger.info("%s passed!", test_name)
            all_status[test_name]["level"] = logging.INFO
            all_status[test_name]["status_msg"] = "Passed"
        _logger.info("-" * 66)

    if "mandatory" in precommit_hooks_type:
        _logger.info("%s MANDATORY CHECKS %s", "*" * 25, "*" * 25)
        _logger.info("Running mandatory checks (affect status build)")
        mandatory_status = subprocess_call(cmd + ["-c", pre_commit_cfg_mandatory])
        status += mandatory_status
        test_name = "Mandatory checks"
        all_status[test_name] = {"status": mandatory_status}
        if mandatory_status:
            _logger.error("%s failed", test_name)
            all_status[test_name]["level"] = logging.ERROR
            all_status[test_name]["status_msg"] = "Failed"
        else:
            _logger.info("%s passed!", test_name)
            all_status[test_name]["level"] = logging.INFO
            all_status[test_name]["status_msg"] = "Passed"

    if "optional" in precommit_hooks_type:
        _logger.info("*" * 68)
        _logger.info("%s OPTIONAL CHECKS %s", "~" * 25, "~" * 25)
        _logger.info("Running optional checks (does not affect status build)")
        status_optional = subprocess_call(cmd + ["-c", os.path.join(repo_dirname, pre_commit_cfg_optional)])
        test_name = "Optional checks"
        all_status[test_name] = {"status": status_optional}
        if status_optional and fail_optional:
            _logger.error("Optional checks failed")
            all_status[test_name]["level"] = logging.ERROR
            all_status[test_name]["status_msg"] = "Failed"
            status += status_optional
        elif status_optional:
            _logger.warning("Optional checks failed")
            all_status[test_name]["level"] = logging.WARNING
            all_status[test_name]["status_msg"] = "Failed"
        else:
            _logger.info("Optional checks passed!")
            all_status[test_name]["level"] = logging.INFO
            all_status[test_name]["status_msg"] = "Passed"
        _logger.info("~" * 67)

    print_summary(all_status)
    if do_exit:
        sys.exit(status)


def print_summary(all_status):
    summary_msg = ["+" + "=" * 39]
    summary_msg.append("|  Tests summary:")
    summary_msg.append("|" + "-" * 39)
    for test_name, test_result in all_status.items():
        outcome = (
            logging_colored.colorized_msg(test_result["status_msg"], test_result["level"])
            if test_result["status"]
            else logging_colored.colorized_msg(test_result["status_msg"], test_result["level"])
        )
        summary_msg.append("| {:<28}{}".format(test_name, outcome))
    summary_msg.append("+" + "=" * 39)
    _logger.info("Tests summary\n%s", "\n".join(summary_msg))


def show_version():
    _logger.info("Version\npre-commit-vauxoo %s\nPython %s", __version__, sys.version)


if __name__ == "__main__":
    main()
