"""Module that contains the command line app.

Why does this file exist, and why not put this in __main__?

  You might be tempted to import things from __main__ later, but that will cause
  problems: the code will get executed twice:

  - When you run `python -mpre_commit_vauxoo` python will execute
    ``__main__.py`` as a script. That means there won't be any
    ``pre_commit_vauxoo.__main__`` in ``sys.modules``.
  - When you import __main__ it will get executed again (as a module) because
    there's no ``pre_commit_vauxoo.__main__`` in ``sys.modules``.

  Also see (1) from http://click.pocoo.org/5/setuptools/#setuptools-integration
"""
import os

import click

from pre_commit_vauxoo import pre_commit_vauxoo


def strcsv2tuple(strcsv, is_path=False):
    if not strcsv:
        return ()
    items = []
    for item in strcsv.strip().split(','):
        item = item.strip()
        if is_path and not os.path.exists(item):
            raise UserWarning("Path '%s' does not exist" % item)
        items.append(item)
    return list(items)


@click.command()
@click.argument("PATHS", type=click.Path(exists=True), nargs=-1)
@click.option(
    "--overwrite",
    "-w",
    envvar="PRECOMMIT_OVERWRITE_CONFIG_FILES",
    default=True,
    show_default=True,
    help="Overwrite configuration files. "
    "If True, existing configuration files into the project will be overwritten. "
    "If False, then current files will be used, if they exist. "
    "Use environment variable PRECOMMIT_OVERWRITE_CONFIG_FILES separated by commas",
)
@click.option(
    "--exclude-autofix",
    "-x",
    type=click.Path(exists=True),
    multiple=True,
    help="Exclude paths on which to run the autofix pre-commit configuration"
    "Use environment variable EXCLUDE_AUTOFIX separated by commas",
)
@click.option(
    "--exclude-lint",
    "-l",
    type=click.Path(exists=True),
    multiple=True,
    help="Paths to exclude checks. Use environment variable EXCLUDE_LINT separated by commas.",
)
@click.option(
    "--disable-pylint-checks",
    '-d',
    type=str,
    envvar="DISABLE_PYLINT_CHECKS",
    metavar='<columns>',
    help="Pylint checks to disable, separated by commas. Use environment variable DISABLE_PYLINT_CHECKS.",
)
@click.option(
    "--autofix",
    "-f",
    envvar="PRECOMMIT_AUTOFIX",
    is_flag=True,
    default=False,
    help="Run pre-commit with autofix configuration to change the source code. "
    "Overwrite -c option to '-c mandatory -c optional -c fix' "
    "Use environment variable PRECOMMIT_AUTOFIX",
)
# TODO: Check callback to validates duplicated and --autofix or -c all conflicts
@click.option(
    "--config",
    "-c",
    type=click.Choice(["mandatory", "optional", "fix", "all"], case_sensitive=False),
    default=["mandatory", "optional"],
    show_default=True,
    multiple=True,
    help="Pre-commit configuration file to run hooks. "
    "*Mandatory: Stable hooks that needs to be fixed (Affecting build status). "
    "*Optional: Optional hooks that could be fixed later. (No affects build status). "
    "*Fix: Hooks auto fixing source code (Affects build status). "
    "*All: All configuration files to run hooks",
)
def main(paths, overwrite, exclude_autofix, exclude_lint, disable_pylint_checks, autofix, config):
    """PATHS are the specific filenames to run hooks on.
    Also, it can be defined using environment variable
    INCLUDE_LINT separated by commas
    [default: Current directory]
    """
    if not paths:
        try:
            paths = strcsv2tuple(os.environ.get('INCLUDE_LINT'), is_path=True)
        except UserWarning as uwe:
            raise click.BadParameter("'[PATHS]...': %s from environment variable 'INCLUDE_LINT'." % uwe)

    if not exclude_autofix:
        try:
            exclude_autofix = strcsv2tuple(os.environ.get('EXCLUDE_AUTOFIX'), is_path=True)
        except UserWarning as uwe:
            raise click.BadParameter("'[--exclude-autofix]...': %s from environment variable 'EXCLUDE_AUTOFIX'." % uwe)

    if not exclude_lint:
        try:
            exclude_lint = strcsv2tuple(os.environ.get('EXCLUDE_LINT'), is_path=True)
        except UserWarning as uwe:
            raise click.BadParameter("'[--exclude-lint]...': %s from environment variable 'EXCLUDE_LINT'." % uwe)

    disable_pylint_checks = strcsv2tuple(disable_pylint_checks)
    pre_commit_vauxoo.main(paths, overwrite, exclude_autofix, exclude_lint, disable_pylint_checks, autofix, config)
