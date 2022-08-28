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


import contextlib
import os
import subprocess

import click

from pre_commit_vauxoo import pre_commit_vauxoo


def source_variables():
    # Overwrite os.environ with variables.sh file only if it was not already defined
    try:
        repo_dirname = pre_commit_vauxoo.get_repo()
    except subprocess.CalledProcessError:
        return
    envdict = pre_commit_vauxoo.envfile2envdict(repo_dirname)
    os.environ.update({var: value for var, value in envdict.items() if var not in os.environ})


@contextlib.contextmanager
def env_clear():
    """Clear environment variables after finished the method"""
    old_environ = os.environ.copy()
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old_environ)


def monkey_patch_make_context():
    """monkey patch to run source variables.sh before to parse the click.options"""
    original_make_context = click.core.BaseCommand.make_context

    def custom_make_context(*args, **kwargs):
        with env_clear():
            source_variables()
            return original_make_context(*args, **kwargs)

    click.core.BaseCommand.make_context = custom_make_context


def strcsv2tuple(strcsv, lower=False):
    if isinstance(strcsv, tuple):
        # Crazy!! but click==8.0.1 is sending "value" transformed
        strcsv = ','.join(strcsv)
    strcsv = strcsv and strcsv.strip() or ""
    if not strcsv:
        return ()
    items = ()
    for item in strcsv.split(','):
        item = item.strip()
        if lower:
            item = item.lower()
        items += (item,)
    return items


class CSVChoice(click.Choice):
    envvar_list_splitter = ','

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name += ' CSV'

    def convert(self, value, param, ctx):
        values = ()
        # case_sensitive parameter is not compatible with click 6.6
        # So we can do it manually here since that we are transforming it
        for v in strcsv2tuple(value, lower=True):
            values += (super().convert(v, param, ctx),)
        return values


class CSVPath(click.Path):
    envvar_list_splitter = ','

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name += ' CSV'

    def convert(self, value, param, ctx):
        values = ()
        for v in strcsv2tuple(value):
            try:
                new_value = super().convert(v, param, ctx)
            except click.exceptions.BadParameter:
                # The envvar are using path based on root repo path
                new_value = os.path.join(pre_commit_vauxoo.get_repo(), v)
                new_value = super().convert(new_value, param, ctx)
            values += (new_value,)
        return values


def merge_tuples(ctx, param, value):
    """Convert (('value1', 'value2'), ('value3')) to ('value1', 'value2', 'value3')
    It is useful for csv separated by commas parameters but using multiple number of args
    """
    if value is None:
        return value
    values = ()
    for v in value:
        if not isinstance(v, tuple):
            v = (v,)
        values += v
    return values


new_extra_kwargs = {}
try:
    if tuple(map(int, click.__version__.split('.'))) >= (7, 0):
        # It is only compatible for click >= 7.0 but it is not a big deal if it is not enabled
        # For record, dockerv image is using click 6.6 version
        new_extra_kwargs["show_envvar"] = True
except (TypeError, ValueError, AttributeError):  # pylint: disable=except-pass
    pass

monkey_patch_make_context()


@click.command()
# click 6.6 used in dockerv doesn't support to use envvar for click.argument :(
# More info https://github.com/pallets/click/issues/714 workaround using option instead.
@click.option(
    "--paths",
    "-p",
    multiple=True,
    envvar="INCLUDE_LINT",
    type=CSVPath(exists=True),
    callback=merge_tuples,
    default=["."],
    show_default=True,
    help="PATHS are the specific filenames to run hooks on separated by commas.",
    **new_extra_kwargs,
)
@click.option(
    "--overwrite",
    "-w",
    envvar="PRECOMMIT_OVERWRITE_CONFIG_FILES",
    default=True,
    show_default=True,
    help="Overwrite configuration files. "
    "\f\n*If True, existing configuration files into the project will be overwritten. "
    "\f\n*If False, then current files will be used, if they exist.",
    **new_extra_kwargs,
)
@click.option(
    "--exclude-autofix",
    "-x",
    type=CSVPath(exists=True),
    multiple=True,
    callback=merge_tuples,
    envvar="EXCLUDE_AUTOFIX",
    help="Exclude paths on which to run the autofix pre-commit configuration, separated by commas",
    **new_extra_kwargs,
)
@click.option(
    "--exclude-lint",
    "-l",
    type=CSVPath(exists=True),
    multiple=True,
    callback=merge_tuples,
    envvar="EXCLUDE_LINT",
    help="Paths to exclude checks, separated by commas.",
    **new_extra_kwargs,
)
@click.option(
    "--disable-pylint-checks",
    '-d',
    type=str,
    callback=merge_tuples,
    envvar="DISABLE_PYLINT_CHECKS",
    help="Pylint checks to disable, separated by commas.",
    **new_extra_kwargs,
)
@click.option(
    "--autofix",
    "-f",
    envvar="PRECOMMIT_AUTOFIX",
    is_flag=True,
    default=False,
    show_default=True,
    help="Run pre-commit with autofix configuration to change the source code."
    "\f\nOverwrite '-t mandatory,optional,fix'",
    **new_extra_kwargs,
)
@click.option(
    "--precommit-hooks-type",
    "-t",
    type=CSVChoice(["mandatory", "optional", "fix", "all"]),
    default=["mandatory", "optional"],
    multiple=True,
    callback=merge_tuples,
    show_default=True,
    envvar="PRECOMMIT_HOOKS_TYPE",
    help="Pre-commit configuration file to run hooks, separated by commas. "
    "\f\n*Mandatory: Stable hooks that needs to be fixed (Affecting build status). "
    "\f\n*Optional: Optional hooks that could be fixed later. (No affects build status). "
    "\f\n*Fix: Hooks auto fixing source code (Affects build status). "
    "\f\n*All: All configuration files to run hooks. ",
    **new_extra_kwargs,
)
def main(paths, overwrite, exclude_autofix, exclude_lint, disable_pylint_checks, autofix, precommit_hooks_type):
    """pre-commit-vauxoo run pre-commit with custom validations and configuration files"""
    pre_commit_vauxoo.main(
        paths, overwrite, exclude_autofix, exclude_lint, disable_pylint_checks, autofix, precommit_hooks_type
    )
