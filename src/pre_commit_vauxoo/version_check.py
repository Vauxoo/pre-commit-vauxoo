"""Warn when a newer pre-commit-vauxoo release is published on PyPI.

The answer is cached inside the pre-commit cache directory (the same one the
pre-commit framework already creates) so PyPI is queried at most once a day.
Every failure here is silent by design: the check is a courtesy, never a reason
to slow down or stop a run.
"""

import json
import logging
import os
import pathlib
import shlex
import site
import sys
import time
import urllib.request

from packaging.version import InvalidVersion, Version
from pre_commit.store import Store

from . import __version__

_logger = logging.getLogger("pre-commit-vauxoo")

PACKAGE_NAME = "pre-commit-vauxoo"
PYPI_JSON_URL = "https://pypi.org/pypi/%s/json"
CACHE_FILENAME = "pre-commit-vauxoo-version.json"
CHECK_INTERVAL = 24 * 60 * 60  # Seconds between two queries to PyPI
REQUEST_TIMEOUT = 5  # Seconds to wait for PyPI before giving up
SKIP_ENVVAR = "PRE_COMMIT_VAUXOO_SKIP_VERSION_CHECK"
IS_WINDOWS = os.name == "nt"


def get_cache_path():
    """Path of the cache file, inside the directory used by the pre-commit framework

    Store is the one resolving PRE_COMMIT_HOME and XDG_CACHE_HOME, so the file
    lands next to the rest of the pre-commit cache without this module having to
    repeat those rules and drift from them.
    """
    return os.path.join(Store.get_default_directory(), CACHE_FILENAME)


def read_cache(cache_path):
    """Return (timestamp of the last query, latest version seen) from the cache file

    A missing or corrupted cache is reported as "never queried".
    """
    try:
        with pathlib.Path(cache_path).open(encoding="UTF-8") as cache_file:
            cache = json.load(cache_file)
        return float(cache["last_check"]), cache["latest_version"]
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0, None


def write_cache(cache_path, last_check, latest_version):
    try:
        cache_file_path = pathlib.Path(cache_path)
        cache_file_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_file_path.open("w", encoding="UTF-8") as cache_file:
            json.dump({"last_check": last_check, "latest_version": latest_version}, cache_file)
    except OSError as exc:
        _logger.debug("Could not write the version cache %s: %s", cache_path, exc)


def latest_valid_version(releases):
    """Newest usable version from the "releases" section of the PyPI json api

    The invalid ones are skipped: versions that are not PEP 440, pre-releases and
    development releases, and the ones with no file left to install because they
    were yanked or never uploaded.
    """
    latest_version = None
    for version_str, release_files in releases.items():
        try:
            version = Version(version_str)
        except InvalidVersion:
            continue
        if version.is_prerelease or version.is_devrelease:
            continue
        if not release_files or all(release_file.get("yanked") for release_file in release_files):
            continue
        if latest_version is None or version > latest_version:
            latest_version = version
    return str(latest_version) if latest_version is not None else None


def fetch_latest_version():
    url = PYPI_JSON_URL % PACKAGE_NAME
    # The scheme is the https of the constant above, nothing here comes from the outside
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:  # ruff: ignore[suspicious-url-open-usage]
        payload = json.load(response)
    return latest_valid_version(payload.get("releases") or {})


def get_latest_version(now=None):
    """Latest version published on PyPI, or None when it could not be known

    PyPI is queried at most once every CHECK_INTERVAL, the value recorded in the
    cache is reused meanwhile. A failed query is recorded too, so an offline
    machine pays the timeout once a day instead of once per run.
    """
    if os.environ.get(SKIP_ENVVAR):
        return None
    now = time.time() if now is None else now
    cache_path = get_cache_path()
    last_check, cached_version = read_cache(cache_path)
    if now - last_check < CHECK_INTERVAL:
        return cached_version
    try:
        latest_version = fetch_latest_version()
    except Exception as exc:  # pylint: disable=broad-except
        _logger.debug("Could not check the latest %s version on PyPI: %s", PACKAGE_NAME, exc)
        latest_version = None
    latest_version = latest_version or cached_version
    write_cache(cache_path, now, latest_version)
    return latest_version


def get_package_dir():
    """Directory holding this package, the site-packages of the installation in use"""
    return str(pathlib.Path(__file__).resolve().parent.parent)


def get_user_site_dirs():
    """Directories pip installs into with --user, empty when they cannot be resolved"""
    try:
        user_site = site.getusersitepackages()
    except Exception:  # pylint: disable=broad-except
        return []
    return [user_site] if isinstance(user_site, str) else list(user_site or [])


def in_virtualenv():
    return sys.prefix != sys.base_prefix


def is_writable_install():
    return os.access(get_package_dir(), os.W_OK)


def get_python_executable():
    return sys.executable or "python3"


def is_user_install():
    """True when the package was installed with 'pip install --user'

    pip refuses to update such an installation without the flag, so the command
    suggested has to carry it exactly when the installation has it. A virtualenv
    never does: pip rejects --user inside one.
    """
    if in_virtualenv():
        return False
    package_dir = get_package_dir()
    return any(package_dir == os.path.realpath(path) for path in get_user_site_dirs())


def quote_executable(path):
    """Quote the interpreter for the shell the command is going to be pasted into

    shlex quotes for a posix shell, and it would wrap a windows path in single
    quotes because of its backslashes, which cmd does not understand.
    """
    if IS_WINDOWS:
        return f'"{path}"' if " " in path else path
    return shlex.quote(path)


def get_update_command():
    """pip command that updates this very installation

    The interpreter is the one currently running instead of a bare 'python',
    which in a machine with several interpreters (pyenv, a virtualenv, the one
    from the system) would update a different installation than the one warning.
    The flags follow where the package really lives: --user for a per-user
    installation and sudo when its directory is not writable, which windows has
    no equivalent for.
    """
    python_bin = quote_executable(get_python_executable())
    if is_user_install():
        return f"{python_bin} -m pip install --user -U {PACKAGE_NAME}"
    if not IS_WINDOWS and not in_virtualenv() and not is_writable_install():
        return f"sudo {python_bin} -m pip install -U {PACKAGE_NAME}"
    return f"{python_bin} -m pip install -U {PACKAGE_NAME}"


def outdated_version_message():
    """Message to display when the installed version is older than the one on PyPI

    Empty string when it is up to date or when PyPI could not be reached.
    """
    latest_version = get_latest_version()
    if not latest_version:
        return ""
    try:
        if Version(latest_version) <= Version(__version__):
            return ""
    except InvalidVersion:
        return ""
    return (
        f"{PACKAGE_NAME} {__version__} is outdated, {latest_version} is available. "
        f"Update it with `{get_update_command()}`"
    )
