import ast
import glob
import logging
import os
import pathlib
import posixpath
import re
import shutil
import stat
import subprocess
import sys

import copier

from . import __version__, logging_colored

_logger = logging.getLogger("pre-commit-vauxoo")

re_export = re.compile(
    r"^(?P<export>export|EXPORT)( )+"
    r"(?P<variable>[\w]*)[ ]*[\=][ ]*[\"\']{0,1}"
    r"(?P<value>[\w\.\-\_/\$\{\}\:,\(\)\#\* ]*)[\"\']{0,1}",
    re.MULTILINE,
)

CFG_SUBFOLDER = ".config"

# Compatibility "generations": higher means newer tool versions and more aggressive autofixes.
# LINT_COMPAT_LATEST is the ceiling, meaning "whatever is newest, forever".
LINT_COMPAT_LATEST = 1000000
LINT_COMPAT_DEFAULT = 10
# Tools whose generation can be pinned independently through --compatibility-override.
# Only the names carry meaning here: unlike the positional vector this replaced, adding or
# dropping a tool never shifts what the other ones mean, so this tuple is free to grow.
LINT_COMPAT_TOOLS = (
    "black_autoflake",
    "flake8",
    "oca_hooks",
    "pre_commit",
    "prettier",
    "pylint",
)


def full_norm_path(path):
    return os.path.normpath(
        os.path.realpath(pathlib.Path(pathlib.Path(os.path.expandvars(path.strip())).expanduser()).resolve())
    )


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
    repo_root = full_norm_path(repo_root.strip())
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
        with pathlib.Path(path).open() as manifest:
            try:
                if not ast.literal_eval(manifest.read()).get("installable", True):
                    results.add(posixpath.join(pathlib.Path(os.path.relpath(path, start=src_path)).parent, ""))
            except (ValueError, TypeError, SyntaxError, AttributeError):
                _logger.info("Unable to parse manifest at %s. Considering it installable", path)

    return results


def parse_generation(value, hint):
    """Convert a single user-supplied generation token into an int.

    Both '0' and 'latest' mean "do not pin anything". '0' is kept as an alias because it is
    what the 'variables.sh' files already deployed across the client repos use, so upgrading
    this package must not force them to edit anything.
    """
    value = (value or "").strip().lower()
    if not value:
        return None
    if value == "latest":
        return LINT_COMPAT_LATEST
    if not value.isdigit():
        raise ValueError(
            "Invalid compatibility generation %r in %s. Expected a positive integer or 'latest' "
            "(e.g. 10, 20, 30, latest)." % (value, hint)
        )
    # 0 is the historical spelling of "latest"; normalize it so callers only compare integers
    return int(value) or LINT_COMPAT_LATEST


def parse_compatibility_overrides(overrides):
    """Parse ('pylint=10', 'prettier=30') into {'pylint': 10, 'prettier': 30}.

    Overrides are keyed by tool name on purpose: a typo fails loudly here instead of silently
    pinning the wrong tool, which is exactly what the positional vector could not detect.
    """
    if isinstance(overrides, str):
        overrides = overrides.split(",")
    parsed = {}
    for override in overrides or ():
        override = override.strip()
        if not override:
            continue
        tool, sep, generation = override.partition("=")
        tool = tool.strip().lower()
        if not sep:
            raise ValueError("Invalid compatibility override %r. Expected the format 'tool=generation'." % override)
        if tool not in LINT_COMPAT_TOOLS:
            raise ValueError(
                "Unknown tool %r in compatibility override. Valid tools: %s" % (tool, ", ".join(LINT_COMPAT_TOOLS))
            )
        parsed[tool] = parse_generation(generation, "compatibility override %r" % override)
    return parsed


def parse_compatibility_version(value, overrides=(), verbose=True):
    """Resolve the compatibility generation to apply to each linter.

    A single generation drives every tool because the thresholds spread over 'cfg/*.jinja' are
    independent and monotonic ('>= 20' stays true at 30), so one number already expresses every
    combination that gets used in practice. '--compatibility-override' stays available for the
    rare case where a single tool must lag behind or run ahead of the rest.

    The legacy dotted vector ('20.20.20.20') is still accepted so no repository breaks on
    upgrade. A vector mixing generations collapses to its lowest one, which is the conservative
    reading matching what the option was created for: the smallest possible diff.
    """
    value = (value or "").strip()
    is_legacy_vector = "." in value
    if is_legacy_vector:
        generations = {parse_generation(part, "compatibility version %r" % value) for part in value.split(".")}
        # A vector shorter than the tool list used to leave the trailing tools unpinned; collapsing
        # to the minimum keeps those tools on the generation the author actually asked for.
        generation = min(generations - {None}, default=None)
    else:
        generation = parse_generation(value, "compatibility version")
    if generation is None:
        generation = LINT_COMPAT_DEFAULT
    if is_legacy_vector and verbose:
        _logger.warning(
            "LINT_COMPATIBILITY_VERSION=%s uses the deprecated dotted format. "
            "Replace it with the single value %s (use --compatibility-override for per-tool pinning).",
            value,
            "latest" if generation == LINT_COMPAT_LATEST else generation,
        )
    compatibility = dict.fromkeys(LINT_COMPAT_TOOLS, generation)
    compatibility.update(parse_compatibility_overrides(overrides))
    if verbose:
        for tool, tool_generation in sorted(compatibility.items()):
            if tool_generation != LINT_COMPAT_LATEST:
                _logger.info("Using compatibility generation %s for %s", tool_generation, tool)
    return compatibility


# copy_cfg_files has too many "for-if" sentences
# because it is a switch-case dummy logic
# TODO: Migrate this method to use configuration files with jinja template
# pylint: disable=too-complex
def copy_cfg_files(
    precommit_config_dir,
    repo_dirname,
    no_overwrite,
    exclude_lint,
    pylint_disable_checks,
    oca_hooks_disable_checks,
    ruff_disable_checks,
    exclude_autofix,
    skip_string_normalization,
    odoo_version,
    py_version,
    is_project_for_apps,
    compatibility_version,
    compatibility_override,
):
    """Copy configuration files from the package's cfg directory into a hidden
    folder at the root of the repository.

    This isolates the configuration files so they are not version-controlled in each
    project repository, avoiding the need to update ``.gitignore`` for every new
    tool.
    """
    # Destination directory inside the repository
    cfg_dir = os.path.join(repo_dirname, CFG_SUBFOLDER)
    pathlib.Path(cfg_dir).mkdir(exist_ok=True, parents=True)

    exclude_lint_regex = ""
    exclude_autofix_regex = ""
    if exclude_lint:
        exclude_lint_regex = "(%s)|" % "|".join([
            re.escape(exclude_path.strip()) for exclude_path in exclude_lint if exclude_path and exclude_path.strip()
        ])
    if exclude_autofix:
        exclude_autofix_regex = "(%s)|" % "|".join([
            re.escape(exclude_path.strip())
            for exclude_path in exclude_autofix
            if exclude_path and exclude_path.strip()
        ])
    _logger.info("Copying configuration files 'cp -rnT %s/ %s/", precommit_config_dir, cfg_dir)
    if no_overwrite:
        # Use the custom files defined in the repo
        _logger.warning("Using custom files")
        return
    lint_compat = parse_compatibility_version(compatibility_version, compatibility_override)
    data = {
        "exclude_autofix_regex": exclude_autofix_regex,
        "exclude_lint_regex": exclude_lint_regex,
        "is_project_for_apps": is_project_for_apps,
        "oca_hooks_disable_checks": oca_hooks_disable_checks,
        "odoo_version": odoo_version,
        "py_version": py_version,
        "pylint_disable_checks": pylint_disable_checks,
        "ruff_disable_checks": ruff_disable_checks,
        "skip_string_normalization": skip_string_normalization,
        "lint_compat": lint_compat,
        # Exposed as its own flag because copier evaluates it inside the file names of the
        # autofix templates, where an inline threshold would be unreadable and would duplicate
        # the one condition that decides whether ruff replaces black/autoflake/isort.
        "use_ruff": lint_compat["black_autoflake"] >= 30,
    }

    copier.run_copy(
        src_path=precommit_config_dir,
        dst_path=cfg_dir,
        data=data,
        unsafe=True,
        defaults=True,
        overwrite=not no_overwrite,
        quiet=True,
    )

    # .editorconfig must live at the repo root because prettier (and most
    # editors) always search for it there with no CLI flag to override the
    # path.  Move it out of the hidden subfolder after copier places it.
    if pathlib.Path(editorconfig_src := os.path.join(cfg_dir, ".editorconfig")).is_file():
        shutil.move(editorconfig_src, os.path.join(repo_dirname, ".editorconfig"))

    # .isort.cfg must live at the repo root because the parameter config
    # change the order of third-party packages
    if pathlib.Path(isort_src := os.path.join(cfg_dir, ".isort.cfg")).is_file():
        shutil.move(isort_src, os.path.join(repo_dirname, ".isort.cfg"))

    if exclude_autofix:
        _logger.info("Applying EXCLUDE_AUTOFIX=%s", exclude_autofix)
    if exclude_lint:
        _logger.info("Applying EXCLUDE_LINT=%s", exclude_lint)
    if pylint_disable_checks:
        _logger.info("Disabling pylint checks (PYLINT_DISABLE_CHECKS): %s", pylint_disable_checks)
    if oca_hooks_disable_checks:
        _logger.info("Disabling oca hooks checks (OCA_HOOKS_DISABLE_CHECKS): %s", oca_hooks_disable_checks)
    if ruff_disable_checks:
        _logger.info("Disabling ruff checks (RUFF_DISABLE_CHECKS): %s", ruff_disable_checks)
    if skip_string_normalization:
        _logger.info("Skip string normalization")
    if odoo_version:
        _logger.info("Using odoo_version=%s", odoo_version)
    if py_version:
        _logger.info("Using py_version=%s", py_version)
    if is_project_for_apps:
        _logger.info("Enabling checks for Odoo Apps")


def envfile2envdict(repo_dirname, source_file="variables.sh", no_overwrite_environ=True):
    """Simulate load the Vauxoo standard file 'source variables.sh' command in python
    return dictionary {environment_variable: value}
    """
    envdict = {}
    source_file_path = os.path.join(repo_dirname, source_file)
    if not pathlib.Path(source_file_path).is_file():
        _logger.info("Skipping 'source %s' file because it was not found", source_file)
        return envdict
    with pathlib.Path(source_file_path).open() as f_source_file:
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


def install_git_hook(src_path, dest_path, replacements):
    hook_content = pathlib.Path(src_path).read_text(encoding="utf-8")
    for placeholder, value in replacements.items():
        hook_content = hook_content.replace(placeholder, value)
    pathlib.Path(dest_path).write_text(hook_content, encoding="utf-8")
    pathlib.Path(dest_path).chmod(os.stat(dest_path).st_mode | stat.S_IXUSR)


def resolve_console_script(script_name):
    script_path = os.path.join(pathlib.Path(sys.executable).parent, script_name)
    if pathlib.Path(script_path).is_file():
        return script_path
    return shutil.which(script_name) or script_name


# There are a lot of if validations in this method. It is expected for now.
# pylint: disable=too-complex
def main(
    paths,
    no_overwrite,
    exclude_autofix,
    exclude_lint,
    pylint_disable_checks,
    oca_hooks_disable_checks,
    ruff_disable_checks,
    precommit_hooks_type,
    fail_optional,
    install,
    skip_string_normalization,
    odoo_version,
    py_version,
    is_project_for_apps,
    only_cp_cfg,
    compatibility_version,
    compatibility_override,
    do_exit=True,
):
    show_version()
    repo_dirname = get_repo()
    cwd = git_cwd()

    root_dir = full_norm_path(str(pathlib.Path(__file__).parent))

    if install:
        git_hook_pre_commit_src = os.path.join(root_dir, "git_hook_pre_commit")
        git_hook_pre_commit_dest = os.path.join(repo_dirname, ".git", "hooks", "pre-commit")
        pre_commit_vauxoo_bin = resolve_console_script("pre-commit-vauxoo")
        _logger.info("pre-commit installed at %s", git_hook_pre_commit_dest)
        install_git_hook(
            git_hook_pre_commit_src,
            git_hook_pre_commit_dest,
            {"__PRE_COMMIT_VAUXOO_BIN__": pre_commit_vauxoo_bin},
        )
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
        ruff_disable_checks,
        exclude_autofix,
        skip_string_normalization,
        odoo_version,
        py_version,
        is_project_for_apps,
        compatibility_version,
        compatibility_override,
    )
    if only_cp_cfg:
        _logger.info("Only copied configuration files. Exiting now.")
        return
    _logger.info("Installing pre-commit hooks")
    cmd = ["pre-commit", "install-hooks", "--color=always"]
    # Paths to the pre‑commit configuration files inside the hidden folder
    cfg_dir = os.path.join(repo_dirname, CFG_SUBFOLDER)
    pre_commit_cfg_mandatory = os.path.join(cfg_dir, ".pre-commit-config.yaml")
    pre_commit_cfg_optional = os.path.join(cfg_dir, ".pre-commit-config-optional.yaml")
    pre_commit_cfg_autofix = os.path.join(cfg_dir, ".pre-commit-config-autofix.yaml")
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
        _logger.warning("Running in current directory '%s'", pathlib.Path(cwd).name)
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
                    subprocess
                    .check_output(["git", "--no-pager", "diff", "--no-ext-diff", "--color=always"])
                    .decode(sys.stdout.encoding)
                    .strip()[:2000]
                )
                msg_info = {
                    "ci_name": is_ci[1],
                    "py_version": "%s.%s" % (sys.version_info.major, sys.version_info.minor),
                    "package_version": __version__,
                    "odoo_version": odoo_version or "STABLE_BRANCH",
                    "repo_name": pathlib.Path(repo_dirname).name,
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
        status_optional = subprocess_call(cmd + ["-c", pre_commit_cfg_optional])
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
        summary_msg.append(f"| {test_name:<28}{outcome}")
    summary_msg.append("+" + "=" * 39)
    _logger.info("Tests summary\n%s", "\n".join(summary_msg))


def show_version():
    _logger.info("Version\npre-commit-vauxoo %s\nPython %s", __version__, sys.version)


if __name__ == "__main__":
    main()
