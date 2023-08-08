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
        strcsv = ",".join(strcsv)
    strcsv = strcsv and strcsv.strip() or ""
    if not strcsv:
        return ()
    items = ()
    for item in strcsv.split(","):
        item = item.strip()
        if lower:
            item = item.lower()
        items += (item,)
    return items


class CSVChoice(click.Choice):
    envvar_list_splitter = ","

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name += " CSV"

    def convert(self, value, param, ctx):
        values = ()
        # case_sensitive parameter is not compatible with click 6.6
        # So we can do it manually here since that we are transforming it
        for v in strcsv2tuple(value, lower=True):
            values += (super().convert(v, param, ctx),)
        return values


class CSVStringParamType(click.types.StringParamType):
    envvar_list_splitter = ","

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name += " CSV"

    def convert(self, value, param, ctx):
        values = ()
        for v in strcsv2tuple(value):
            values += (super().convert(v, param, ctx),)
        return values


class CSVPath(click.Path):
    envvar_list_splitter = ","

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name += " CSV"

    def convert(self, value, param, ctx):
        values = ()
        repo_dirname = pre_commit_vauxoo.get_repo()
        for v in strcsv2tuple(value):
            try:
                new_value = super().convert(v, param, ctx)
            except click.exceptions.BadParameter:
                # The envvar are using path based on root repo path
                new_value = os.path.join(repo_dirname, v)
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


def precommit_hooks_type_callback(ctx, param, value):
    """If value is 'all' so all the option will be assigned
    If value has prefix '-' so that option will be removed
    value = 'all,-fix' will return 'mandatory,optional,experimental'
    """
    values = merge_tuples(ctx, param, value)
    values = set(values)
    all_values = {i for i in param.type.choices if not i.startswith("-") and not i == "all"}
    if "all" in values:
        values -= {"all"}
        values |= all_values
    for v in values.copy():
        if v.startswith("-"):
            values -= {v, v[1:]}
    return tuple(values)


new_extra_kwargs = {}
try:
    if tuple(map(int, click.__version__.split("."))) >= (7, 0):
        # It is only compatible for click >= 7.0 but it is not a big deal if it is not enabled
        # For record, dockerv image is using click 6.6 version
        new_extra_kwargs["show_envvar"] = True
except (TypeError, ValueError, AttributeError):  # pylint: disable=except-pass
    pass

monkey_patch_make_context()


PRECOMMIT_HOOKS_TYPE = ["mandatory", "optional", "fix", "experimental"]
PRECOMMIT_HOOKS_TYPE += ["all"] + ["-%s" % i for i in PRECOMMIT_HOOKS_TYPE]


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
    "--no-overwrite",
    envvar="PRECOMMIT_NO_OVERWRITE_CONFIG_FILES",
    type=click.BOOL,
    is_flag=True,
    default=False,
    show_default=True,
    help="Overwrite configuration files. "
    "\f\n*If True, existing configuration files into the project will be overwritten. "
    "\f\n*If False, then current files will be used, if they exist.",
    **new_extra_kwargs,
)
@click.option(
    "--fail-optional",
    envvar="PRECOMMIT_FAIL_OPTIONAL",
    type=click.BOOL,
    default=False,
    is_flag=True,
    show_default=True,
    help="Change the exit_code for 'optional' precommit-hooks-type."
    "\f\n*If this flag is enabled so the exit_code will be -1 (error) if 'optional' fails."
    "\f\n*If it is disabled (by default), exit_code will be 0 (successful) even if 'optional' fails.",
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
    "--pylint-disable-checks",
    "-d",
    type=CSVStringParamType(),
    callback=merge_tuples,
    envvar="PYLINT_DISABLE_CHECKS",
    help="Pylint checks to disable, separated by commas.",
    **new_extra_kwargs,
)
@click.option(
    "--oca-hooks-disable-checks",
    type=CSVStringParamType(),
    callback=merge_tuples,
    envvar="OCA_HOOKS_DISABLE_CHECKS",
    help="OCA Hooks checks to disable, separated by commas.",
    **new_extra_kwargs,
)
@click.option(
    "--skip-string-normalization",
    "-S",
    envvar="BLACK_SKIP_STRING_NORMALIZATION",
    is_flag=True,
    default=False,
    show_default=True,
    help="If '-t fix' is enabled, "
    "don't normalize string quotes or prefixes '' -> \"\""
    "\f\nThis parameter is related to 'black' hook",
    **new_extra_kwargs,
)
@click.option(
    "--precommit-hooks-type",
    "-t",
    type=CSVChoice(PRECOMMIT_HOOKS_TYPE),
    default=["all", "-fix"],
    multiple=True,
    callback=precommit_hooks_type_callback,
    show_default=True,
    envvar="PRECOMMIT_HOOKS_TYPE",
    help="Pre-commit configuration file to run hooks, separated by commas. "
    "\f\nprefix '-' means that the option will be removed. "
    "\f\n*Mandatory: Stable hooks that needs to be fixed (Affecting build status). "
    "\f\n*Optional: Optional hooks that could be fixed later. "
    "(No affects build status almost '--fail-optional' is set). "
    "\f\n*Experimental: Experimental hooks that only to test. (No affects build status). "
    "\f\n*Fix: Hooks auto fixing source code (Affects build status). "
    "\f\n*All: All configuration files to run hooks. ",
    **new_extra_kwargs,
)
@click.option(
    "--install",
    type=click.BOOL,
    is_flag=True,
    default=False,
    help="Install the pre-commit script"
    "\f\nUsing this option a '.git/hooks/pre-commit' will be created"
    "\f\nNow your command 'git commit' will run 'pre-commit-vauxoo' before to commit",
    **new_extra_kwargs,
)
@click.option(
    "--version",
    type=click.BOOL,
    is_flag=True,
    default=False,
    help="Show the version of this package",
    **new_extra_kwargs,
)
@click.option(
    "--odoo-version",
    envvar="VERSION",
    type=click.STRING,
    help="Odoo version used for the repository.",
    **new_extra_kwargs,
)
def main(*args, **kwargs):
    """pre-commit-vauxoo run pre-commit with custom validations and configuration files"""
    version = kwargs.pop("version", None)
    if version:
        pre_commit_vauxoo.show_version()
        return
    pre_commit_vauxoo.main(*args, **kwargs)
