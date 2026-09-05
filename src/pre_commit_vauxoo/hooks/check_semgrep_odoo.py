#!/usr/bin/env python3
"""Run the semgrep rules generated into .config over the files given.

semgrep is declared as a dependency of the hook, not of this package, so it is only
installed in the environment pre-commit builds for it. It also needs python 3.10 and
does not publish a wheel for every platform, so this entry point treats a missing
semgrep as "nothing to check" instead of an error: the checks it runs are experimental
and must never be the reason a run fails.
"""

import os
import pathlib
import shutil
import subprocess
import sys

CONFIG_FILENAME = os.path.join(".config", ".semgrep-experimental.yml")


def semgrep_executable():
    """The semgrep of this environment, and only then whatever the PATH holds

    pre-commit builds an environment per hook, so the interpreter running this script
    is the one its additional_dependencies were installed next to.
    """
    candidate = pathlib.Path(sys.executable).parent / "semgrep"
    if candidate.is_file():
        return str(candidate)
    return shutil.which("semgrep")


def main(argv=None):
    paths = list(sys.argv[1:] if argv is None else argv)
    if not paths:
        return 0

    config = pathlib.Path(CONFIG_FILENAME)
    if not config.is_file():
        print(f"Skipping the semgrep checks because {CONFIG_FILENAME} was not generated")
        return 0

    semgrep = semgrep_executable()
    if not semgrep:
        print(
            "Skipping the semgrep checks because semgrep is not installed. "
            "It requires python 3.10 and does not ship a wheel for every platform"
        )
        return 0

    command = [
        semgrep,
        # No --error on purpose: a finding is reported and the build is left alone,
        # the same way the experimental ruff checks run with --exit-zero
        "--quiet",
        "--metrics=off",
        "--disable-version-check",
        # Without it the id is prefixed with the path the rules were loaded from
        "--no-rewrite-rule-ids",
        "--config",
        str(config),
    ]
    # Given a terminal, semgrep prints its banner even under --quiet, and pre-commit
    # runs the hook once per batch of files, so a single run printed it four times.
    # The pipes below take the terminal away; --force-color asks for the colour back,
    # since it is the piping that turned it off.
    if sys.stdout.isatty():
        command.append("--force-color")
    command.extend(paths)

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    sys.stdout.write(result.stdout)
    sys.stderr.write(
        "".join(
            line
            for line in result.stderr.splitlines(keepends=True)
            # semgrep fails to install a segfault handler on macOS and says so on
            # every run. It is noise from its runtime, not a result of the scan
            if not line.startswith(("Failed to register segfault", "Failed to register unwind"))
        )
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
