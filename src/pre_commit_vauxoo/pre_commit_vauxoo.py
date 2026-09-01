import ast
import glob
import logging
import math
import os
import pathlib
import posixpath
import re
import shutil
import stat
import subprocess
import sys

import copier

from . import __version__, logging_colored, version_check

_logger = logging.getLogger("pre-commit-vauxoo")

re_export = re.compile(
    r"^(?P<export>export|EXPORT)( )+"
    r"(?P<variable>[\w]*)[ ]*[\=][ ]*[\"\']{0,1}"
    r"(?P<value>[\w\.\-\_/\$\{\}\:,\(\)\#\* ]*)[\"\']{0,1}",
    re.MULTILINE,
)

# Matches the "check-name,  # ruff CODE1,CODE2" annotations used in the .pylintrc*.jinja
# templates to document the pylint checks migrated to ruff
re_pylint_check_ruff_codes = re.compile(
    r"^\s*(?P<check>[a-z][\w-]*),?\s+#\s*ruff\s+(?P<codes>[A-Z]+\d+(?:,[A-Z]+\d+)*)",
    re.MULTILINE,
)

CFG_SUBFOLDER = ".config"

# Scope of files to run the hooks on (--all, --last-commit and --diff)
# The templates that depend on ruff live in a folder whose name is the condition
# itself, so copier renders the matching one and skips the other subtree entirely.
# It keeps the plain names on the files, which is what has to be opened and edited.
CFG_RUFF_SUBFOLDER = "{% if use_ruff %}ruff{% endif %}"
CFG_NO_RUFF_SUBFOLDER = "{% if not use_ruff %}no_ruff{% endif %}"
CFG_RENDERED_SUBFOLDERS = ("ruff", "no_ruff")

SCOPE_ALL = "all"
SCOPE_LAST_COMMIT = "last-commit"
SCOPE_LAST_COMMITS = "last-commits"
SCOPE_DIFF = "diff"
# Exported to the hooks: the commit message one declares "always_run: true", so the
# scope is the only way it can validate the same commits the file hooks check
SCOPE_ENVVAR = "PRECOMMIT_SCOPE"
# The base revision "--last-commits" was given explicitly, if it was. Exported so
# the commit message hook counts from the same place the file scope does
BASE_REF_ENVVAR = "PRECOMMIT_BASE_REF"
# Where the stable branch lives, when nobody says. A remote named "stb" is the
# convention across the repositories that have one and it has never been wrong,
# including where the URL alone points elsewhere: ircodoo keeps its stable at
# ircanada/ircodoo while a vauxoo/ircodoo mirror is also configured
STABLE_REMOTE_NAME = "stb"
STABLE_URL_NAMESPACE = "vauxoo/"

TOOLS_ORDER = (
    "prettier_matrix_value",
    "oca_hooks_matrix_value",
    "eslint_matrix_value",
    "black_autoflake_matrix_value",
    "pre_commit_matrix_value",
    "pylint_matrix_value",
    "flake8_matrix_value",
)
DEFAULT_MAX_COMPATIBILITY = 1000000
DEFAULT_MIN_COMPATIBILITY = 10

# ruff "target-version" mapped from the odoo version (VERSION) using the python
# version shipped for each odoo serie:
#   20.0 -> 3.14, 19.0/18.0 -> 3.12, 17.0/16.0 -> 3.10, 15.0/14.0 -> 3.8,
#   13.0/12.0 -> 3.6 (clamped to py37 since ruff doesn't support py36)
# Intermediate saas versions jump to the next odoo serie (saas-13.5 -> 14.0 -> py38)
# Odoo versions newer than the mapping (or undefined) use the latest python version
# since it is a new odoo serie without a python version defined yet
# (min_odoo_version, py_target_version) evaluated in descending order
ODOO_VERSION_TO_PY_TARGET_VERSION = (
    (20.0, "py314"),
    (18.0, "py312"),
    (16.0, "py310"),
    (14.0, "py38"),
    (0.0, "py37"),  # odoo <= 13.0 uses python 3.6 but ruff doesn't support less than py37
)
DEFAULT_PY_TARGET_VERSION = ODOO_VERSION_TO_PY_TARGET_VERSION[0][1]

re_odoo_version_number = re.compile(r"(?P<version>\d+(?:\.\d+)?)")


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


def git_output(git_args, repo_dirname):
    """Run a read-only git command from the root of the repository

    Running it from the root makes the output paths relative to it and independent of
    the current directory, which could even limit the files reported (e.g. "git ls-files")

    The stderr is captured instead of inherited so a failure expected by the caller
    (e.g. a repository without commits) does not print a confusing git error
    """
    output = subprocess.check_output(["git"] + git_args, cwd=repo_dirname, stderr=subprocess.PIPE).decode(
        sys.stdout.encoding
    )
    return [line for line in output.splitlines() if line]


def get_last_commit_files(repo_dirname):
    """Files added or modified by the last commit (HEAD)

    "--root" reports the whole content of an initial commit instead of nothing and
    "-m --first-parent" makes a merge commit report the changes it merged, instead of
    the empty list a merge reports by default
    """
    return git_output(
        [
            "diff-tree",
            "-r",
            "-m",
            "--root",
            "--first-parent",
            "--no-commit-id",
            "--name-only",
            "--diff-filter=d",
            "HEAD",
        ],
        repo_dirname,
    )


def git_ref_exists(ref_name, cwd=None):
    return not subprocess.call(["git", "show-ref", "--verify", "--quiet", ref_name], cwd=cwd)


def git_rev_exists(revision, cwd=None):
    """Whether a revision is resolvable, for the ones "show-ref --verify" can not check

    "HEAD~1" is not a ref, so it needs "rev-parse" instead: it does not exist on a
    repository whose only commit is the root one.
    """
    return not subprocess.call(
        ["git", "rev-parse", "--verify", "--quiet", revision],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def get_git_remotes_with_urls(cwd=None):
    remote_names = subprocess.check_output(["git", "remote"], cwd=cwd).decode(sys.stdout.encoding).splitlines()
    remotes = {}
    for remote_name in remote_names:
        remote_url = (
            subprocess
            .check_output(["git", "config", "--get", f"remote.{remote_name}.url"], cwd=cwd)
            .decode(sys.stdout.encoding)
            .strip()
        )
        remotes[remote_name] = remote_url
    return remotes


def stable_remote_candidates(version, cwd=None):
    """The remotes that could hold the stable branch, best first

    A dev fork is skipped: it is where the branch being validated lives, so its copy
    of stable is the stale one. What is left is ordered by how reliably it names the
    stable: the "stb" remote first, then the vauxoo namespace, then "origin", and only
    then alphabetically, so the answer never depends on the order git happens to list.
    """
    candidates = []
    for remote_name, remote_url in get_git_remotes_with_urls(cwd=cwd).items():
        if "dev" in remote_url.lower():
            continue
        if not git_ref_exists(f"refs/remotes/{remote_name}/{version}", cwd=cwd):
            continue
        if remote_name == STABLE_REMOTE_NAME:
            rank = 0
        elif STABLE_URL_NAMESPACE in remote_url.lower():
            rank = 1
        elif remote_name == "origin":
            rank = 2
        else:
            rank = 3
        candidates.append((rank, remote_name, f"{remote_name}/{version}", remote_url))
    return sorted(candidates)


def ask_for_stable_ref(version, cwd=None):
    """Every remote is a dev fork, so the answer has to come from whoever is running

    Only asked interactively. A run with no terminal -- CI is the reason this option
    exists -- gets told what to pass instead of hanging on a prompt nobody will answer.
    """
    remotes = get_git_remotes_with_urls(cwd=cwd)
    listed = ", ".join(f"{name} ({url})" for name, url in remotes.items()) or "none"
    unanswerable = UserWarning(
        "Every remote configured is a dev fork, so the stable branch can not be "
        "inferred, and there is nobody to ask. Pass it explicitly with "
        "--last-commits=REMOTE/BRANCH. Remotes: %s" % listed
    )
    if sys.stdin is None or not sys.stdin.isatty():
        raise unanswerable
    print("Every remote configured is a dev fork, so the stable branch can not be inferred.")
    print(f"Remotes: {listed}")
    try:
        return input(f"Which remote/branch should the commits be counted from? [<remote>/{version}] ").strip()
    except EOFError:
        # A terminal that answers nothing, which is every runner that fakes one
        raise unanswerable from None


def infer_stable_ref(version, cwd=None):
    """Where the stable branch is, when nobody said

    Kept apart from the resolution above so each one answers a single question, and
    neither grows the pile of exits the repository's own checks refuse.
    """
    remotes = get_git_remotes_with_urls(cwd=cwd)
    skipped = [name for name, url in remotes.items() if "dev" in url.lower()]
    candidates = stable_remote_candidates(version, cwd=cwd)
    if candidates:
        _rank, _remote_name, base_ref, remote_url = candidates[0]
        detail = f" (skipping the dev fork{'s' if len(skipped) > 1 else ''} {', '.join(skipped)})" if skipped else ""
        print(f"Counting commits from {base_ref}, inferred from {remote_url}{detail}")
        return base_ref

    if git_ref_exists(f"refs/heads/{version}", cwd=cwd):
        print(f"Counting commits from the local branch {version}")
        return version

    # Only when every remote is a dev fork is there nothing left to infer from. A
    # checkout holding a single remote that simply lacks the branch -- which is what
    # CI clones look like -- keeps skipping quietly, the way it always did
    if remotes and len(skipped) == len(remotes):
        answer = ask_for_stable_ref(version, cwd=cwd)
        if not git_rev_exists(answer, cwd=cwd):
            raise UserWarning(f"The base revision {answer} does not exist")
        print(f"Counting commits from {answer}")
        return answer

    print(f"Skipping commit message validation because stable ref {version} was not found")
    return ""


def resolve_commit_message_base_ref(version, scope=None, cwd=None):
    """The revision the commits to validate are counted from

    The file scopes ask this too, so both halves always cover the same commits.

    * An explicit "--last-commits=REMOTE/BRANCH" wins, and is the answer for CI, where
      guessing is the wrong thing to do at all.
    * "--last-commit" only added or modified files in HEAD, so only the message of
      HEAD is validated, which is the "HEAD~1..HEAD" range.
    * Otherwise the stable branch is inferred, and the choice is reported before the
      hooks run, because it decides what gets checked.
    """
    if scope is None:
        scope = os.environ.get(SCOPE_ENVVAR, "").strip()

    explicit = os.environ.get(BASE_REF_ENVVAR, "").strip()
    if explicit and scope != SCOPE_LAST_COMMIT:
        if not git_rev_exists(explicit, cwd=cwd):
            raise UserWarning(f"The base revision {explicit} given to --last-commits does not exist")
        print(f"Counting commits from {explicit}, given explicitly")
        return explicit

    if scope == SCOPE_LAST_COMMIT:
        if git_rev_exists("HEAD~1", cwd=cwd):
            return "HEAD~1"
        print("HEAD has no parent, falling back to the stable branch for commit message validation")

    if not version:
        return ""

    return infer_stable_ref(version, cwd=cwd)


def get_last_commits_files(repo_dirname):
    """Files added or modified by every commit since the stable branch named by VERSION

    The base revision is resolved by the same helper the commit message hook uses, so
    both halves of the check always cover the same commits: the stable branch as the
    non-dev remote has it, or the local branch when no remote does.

    The three dot range reports what HEAD introduced since it forked from stable, so
    commits pushed to stable in the meantime are not reported as belonging here.
    """
    version = os.environ.get("VERSION", "").strip()
    base_ref = resolve_commit_message_base_ref(version, scope=SCOPE_LAST_COMMITS, cwd=repo_dirname)
    if not base_ref:
        return []
    return git_output(["diff", "--name-only", "--diff-filter=d", f"{base_ref}...HEAD"], repo_dirname)


def get_diff_files(repo_dirname):
    """Files with changes not committed yet: staged, unstaged and untracked

    "git diff HEAD" reports the tracked files changed no matter if they were added to
    the index or not, so only the untracked files need the extra "git ls-files" call
    """
    files = git_output(["diff", "--name-only", "--diff-filter=d", "HEAD"], repo_dirname)
    files += git_output(["ls-files", "--others", "--exclude-standard"], repo_dirname)
    return files


def get_scope_files(scope, repo_dirname):
    """Files to run the hooks on for the given scope, relative to the root of the repository

    The deleted files are excluded ("--diff-filter=d" and the untracked files always exist)
    since a file that is gone can not be checked at all
    """
    get_files_meth = {
        SCOPE_LAST_COMMIT: get_last_commit_files,
        SCOPE_LAST_COMMITS: get_last_commits_files,
        SCOPE_DIFF: get_diff_files,
    }[scope]
    try:
        files = get_files_meth(repo_dirname)
    except subprocess.CalledProcessError as git_error:
        # e.g. a repository without commits at all, so there is no HEAD to compare with
        _logger.warning("Unable to get the files for '--%s'. Is it a repository without commits?", scope)
        _logger.debug("git error: %s", (git_error.stderr or b"").decode(sys.stdout.encoding).strip())
        return []
    return sorted(set(files))


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


def parse_matrix_compatibility(matrix_compatibility_string, verbose=True):
    value = matrix_compatibility_string
    matrix = {}

    parts = value.split(".") if value else []
    values = tuple(int(p) for p in parts)

    for idx, tool in enumerate(TOOLS_ORDER):
        try:
            if not matrix_compatibility_string:
                value = DEFAULT_MIN_COMPATIBILITY  # consistent with default from CLI
            else:
                value = values[idx] if values[idx] else DEFAULT_MAX_COMPATIBILITY
        except IndexError:
            value = DEFAULT_MAX_COMPATIBILITY
        if verbose and value != DEFAULT_MAX_COMPATIBILITY:
            _logger.info("Using %s=%s from compatibility version position #%s", tool, value, idx + 1)
        matrix[tool] = value
    return matrix


def parse_odoo_version_number(odoo_version):
    """Parse the odoo version string (VERSION or --odoo-version) as a comparable number
    e.g. "17.0" -> 17.0 and "saas-17.2" -> 17.2

    Return None for empty or unparseable values (e.g. "master") so the templates keep
    all the version-dependent checks enabled, the same behavior of pylint-odoo when the
    valid-odoo-version option was not defined or was invalid
    """
    version_match = re_odoo_version_number.search(str(odoo_version or ""))
    if not version_match:
        return None
    return float(version_match["version"])


def get_py_target_version(odoo_version_number):
    """Get the ruff "target-version" value mapped from the odoo version
    (VERSION or --odoo-version)

    Intermediate saas versions use the python version of the next odoo serie
    (e.g. saas-13.5 -> 14.0 -> py38) and undefined or newer odoo versions than the
    known mapping use the latest python version of the list
    """
    if odoo_version_number:
        odoo_serie = math.ceil(odoo_version_number)
        for odoo_min_version, py_target_version in ODOO_VERSION_TO_PY_TARGET_VERSION:
            if odoo_serie >= odoo_min_version:
                return py_target_version
    return DEFAULT_PY_TARGET_VERSION


def extend_ruff_checks_from_pylint(precommit_config_dir, pylint_disable_checks, ruff_disable_checks, use_ruff):
    """Extend ruff_disable_checks with the ruff equivalent of the PYLINT_DISABLE_CHECKS names

    The .pylintrc*.jinja templates document each pylint check migrated to ruff using a
    "check-name,  # ruff CODE1,CODE2" comment so reuse those annotations to keep disabling
    the same checks from ruff without needing to configure RUFF_DISABLE_CHECKS
    """
    ruff_disable_checks = tuple(ruff_disable_checks or ())
    if not use_ruff or not pylint_disable_checks:
        return ruff_disable_checks
    pylint2ruff = {}
    # Both folders are read: a check migrated to ruff is annotated where it is still
    # listed for pylint, which for the optional ones is the no_ruff template only
    pylintrc_paths = (
        pathlib.Path(precommit_config_dir) / subfolder / pylintrc_filename
        for subfolder in (CFG_RUFF_SUBFOLDER, CFG_NO_RUFF_SUBFOLDER)
        for pylintrc_filename in (".pylintrc.jinja", ".pylintrc-optional.jinja")
    )
    for pylintrc_path in pylintrc_paths:
        if not pylintrc_path.is_file():
            continue
        for check_match in re_pylint_check_ruff_codes.finditer(pylintrc_path.read_text(encoding="utf-8")):
            codes = pylint2ruff.get(check_match["check"], ())
            pylint2ruff[check_match["check"]] = codes + tuple(
                code for code in check_match["codes"].split(",") if code not in codes
            )
    ruff_checks = ()
    for pylint_check in pylint_disable_checks:
        ruff_checks += tuple(
            code
            for code in pylint2ruff.get(pylint_check, ())
            if code not in ruff_disable_checks and code not in ruff_checks
        )
    if ruff_checks:
        _logger.info(
            "Disabling the ruff equivalent of the pylint checks (PYLINT_DISABLE_CHECKS): %s",
            ",".join(ruff_checks),
        )
    return ruff_disable_checks + ruff_checks


# copy_cfg_files has too many "for-if" sentences
# because it is a switch-case dummy logic
# TODO: Migrate this method to use configuration files with jinja template
def copy_cfg_files(  # ruff: ignore[complex-structure]
    precommit_config_dir,
    repo_dirname,
    no_overwrite,
    exclude_lint,
    pylint_disable_checks,
    oca_hooks_disable_checks,
    ruff_disable_checks,
    additional_builtins,
    exclude_autofix,
    skip_string_normalization,
    odoo_version,
    is_project_for_apps,
    compatibility_version,
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
    matrix_compatibility = parse_matrix_compatibility(compatibility_version)
    use_ruff = (matrix_compatibility.get("black_autoflake_matrix_value") or 0) >= 30
    ruff_disable_checks = extend_ruff_checks_from_pylint(
        precommit_config_dir, pylint_disable_checks, ruff_disable_checks, use_ruff
    )
    odoo_version_number = parse_odoo_version_number(odoo_version)
    py_target_version = get_py_target_version(odoo_version_number)
    # python version for the .pylintrc* "py-version" option (e.g. "py310" -> "3.10")
    py_version = "%s.%s" % (py_target_version[2], py_target_version[3:])
    data = {
        "exclude_autofix_regex": exclude_autofix_regex,
        "exclude_lint_regex": exclude_lint_regex,
        "is_project_for_apps": is_project_for_apps,
        "oca_hooks_disable_checks": oca_hooks_disable_checks,
        "odoo_version": odoo_version,
        "odoo_version_number": odoo_version_number,
        "py_target_version": py_target_version,
        "py_version": py_version,
        "pylint_disable_checks": pylint_disable_checks,
        "ruff_disable_checks": ruff_disable_checks,
        "additional_builtins": additional_builtins,
        "skip_string_normalization": skip_string_normalization,
        **matrix_compatibility,
        "use_ruff": use_ruff,
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

    # copier renders the folder whose condition matched as a subfolder of the
    # destination, so its files have to be moved up to where every tool expects them.
    # Written over the destination instead of renamed onto it: a rename swaps the
    # inode, and whoever kept the previous file open across a second run -- copier
    # itself rewrites in place -- would go on reading the content of the first one.
    for rendered_subfolder in CFG_RENDERED_SUBFOLDERS:
        subfolder_path = pathlib.Path(cfg_dir) / rendered_subfolder
        if not subfolder_path.is_dir():
            continue
        for cfg_file in subfolder_path.iterdir():
            pathlib.Path(cfg_dir, cfg_file.name).write_bytes(cfg_file.read_bytes())
            cfg_file.unlink()
        subfolder_path.rmdir()

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
    if additional_builtins:
        _logger.info("Treating as builtins (LINT_ADDITIONAL_BUILTINS): %s", additional_builtins)
    if skip_string_normalization:
        _logger.info("Skip string normalization")
    if odoo_version:
        _logger.info("Using odoo_version=%s", odoo_version)
    _logger.info("Using py_version=%s mapped from the odoo version", py_version)
    if use_ruff:
        _logger.info("Using ruff target-version=%s", py_target_version)
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
def main(  # ruff: ignore[complex-structure]
    paths,
    scope,
    last_commits,
    no_overwrite,
    exclude_autofix,
    exclude_lint,
    pylint_disable_checks,
    oca_hooks_disable_checks,
    ruff_disable_checks,
    additional_builtins,
    precommit_hooks_type,
    fail_optional,
    install,
    skip_string_normalization,
    odoo_version,
    is_project_for_apps,
    only_cp_cfg,
    compatibility_version,
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
        additional_builtins,
        exclude_autofix,
        skip_string_normalization,
        odoo_version,
        is_project_for_apps,
        compatibility_version,
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
    custom_paths = bool(paths) and paths != (".",)
    if custom_paths and scope != SCOPE_ALL:
        _logger.warning(
            "Conflicting parameters: '--%s' is ignored since that '-p/--paths' has precedence over it",
            scope,
        )
        scope = SCOPE_ALL
    # "--last-commits" carries its own scope, and its value when it was given one
    if last_commits is not None:
        scope = SCOPE_LAST_COMMITS
        if last_commits:
            os.environ[BASE_REF_ENVVAR] = last_commits
    # The commit message hook declares "always_run: true", so this is what tells it to
    # validate the messages of the very commits whose files are being checked
    os.environ[SCOPE_ENVVAR] = scope
    if scope != SCOPE_ALL:
        # The scope has precedence over the current directory so it always checks the
        # files of the whole repository even if the command is invoked from a subdirectory
        if cwd != ".":
            _logger.warning(
                "Running '--%s' for the whole repository even if the current directory is '%s'",
                scope,
                pathlib.Path(cwd).name,
            )
        scope_files = get_scope_files(scope, repo_dirname)
        if not scope_files:
            _logger.warning("There are no files to check for '--%s'. Nothing to do.", scope)
            if do_exit:
                sys.exit(0)
            return
        _logger.info("Running only for the %d file(s) of '--%s'", len(scope_files), scope)
        # The absolute path is required to be independent of the current directory and
        # it is normalized since that git always reports the files separated by "/"
        cmd.extend([
            "--files",
            *(os.path.normpath(os.path.join(repo_dirname, scope_file)) for scope_file in scope_files),
        ])
    elif cwd != ".":
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
    elif custom_paths:
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
    warn_outdated_version()
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
    warn_outdated_version()


def warn_outdated_version():
    """Print a yellow warning when a newer version was released on PyPI"""
    outdated_msg = version_check.outdated_version_message()
    if outdated_msg:
        _logger.warning(logging_colored.colorized_msg(outdated_msg, logging.WARNING))


if __name__ == "__main__":
    main()
