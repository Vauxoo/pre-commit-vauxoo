#!/usr/bin/env python3
"""Report the tests of an Odoo module that Odoo never collects.

Odoo only runs the test modules imported by ``<module>/tests/__init__.py``: the
loader imports the ``tests`` package and keeps its submodules named ``test_*``
(see ``_get_tests_modules`` in ``odoo/tests/loader.py``). A ``tests/test_*.py``
file missing from that ``__init__.py`` is not an error for Odoo, its tests are
simply never run and the build stays green. When no test module is imported at
all, Odoo runs 0 tests of the module and only logs a WARNING.

Two checks are reported for every module (a folder with a manifest) owning a
``tests`` folder:

- ``test-file-not-imported``: a ``tests/test_*.py`` file, or a ``tests/test_*``
  package, that ``tests/__init__.py`` does not import.
- ``tests-folder-without-tests``: a ``tests`` folder from which Odoo collects no
  test module at all, either because it has none or because none is imported.
  Such a folder makes the reader believe the module is tested.

The imports are read with ``ast``, never executed, so the dynamic ones
(``importlib``, ``__import__``, ``from . import *``) are not resolved and the
files they load are reported as not imported. The test methods are not counted
either: an imported file without any ``test_*`` method is not reported.
"""

import ast
import os
import pathlib
import sys

MANIFEST_NAMES = ("__manifest__.py", "__openerp__.py")
TESTS_FOLDER = "tests"
TEST_PREFIX = "test_"


def get_module_path(fname, root_path):
    """Return the folder of the Odoo module owning ``fname``, or None if there is none

    Only the folders inside ``root_path`` are considered, never the ones above the repository
    """
    path = pathlib.Path(fname).resolve()
    for folder in (path, *path.parents):
        if folder != root_path and root_path not in folder.parents:
            break
        if folder.is_dir() and any((folder / manifest).is_file() for manifest in MANIFEST_NAMES):
            return folder
    return None


def relpath(path):
    """Return ``path`` relative to the working directory, with "/" as separator in every OS"""
    return pathlib.Path(os.path.relpath(path, pathlib.Path.cwd().resolve())).as_posix()


def get_test_modules(tests_path):
    """Return the test modules found in the ``tests`` folder as {name: path}

    Odoo collects both the ``test_*.py`` files and the ``test_*`` packages
    """
    test_modules = {}
    for entry in tests_path.iterdir():
        if not entry.name.startswith(TEST_PREFIX):
            continue
        if entry.is_file() and entry.suffix == ".py":
            test_modules[entry.stem] = entry
        elif entry.is_dir() and (entry / "__init__.py").is_file():
            test_modules[entry.name] = entry
    return test_modules


def get_imported_modules(init_path, module_name):
    """Return the names of the submodules of the ``tests`` package imported by its ``__init__.py``

    Supported: ``from . import a, b`` (multi-line parenthesized too), ``from .a import X``
    and the absolute ``from odoo.addons.<module>.tests import a`` and
    ``from odoo.addons.<module>.tests.a import X``.
    The imports nested in ``if`` or ``try`` blocks count as imported.
    Raise SyntaxError if the file can not be parsed.
    """
    tree = ast.parse(init_path.read_bytes(), filename=str(init_path))
    absolute_package = "odoo.addons.%s.%s" % (module_name, TESTS_FOLDER)
    imported = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level == 1:
            relative_module = node.module
        elif not node.level and node.module and (node.module + ".").startswith(absolute_package + "."):
            relative_module = node.module.removeprefix(absolute_package).lstrip(".")
        else:
            continue
        if relative_module:
            # "from .a import X" or "from .a.b import X" import the submodule "a"
            imported.add(relative_module.split(".")[0])
        else:
            # "from . import a, b"
            imported.update(alias.name for alias in node.names)
    return imported


def check_module(module_path):
    """Return the messages reporting the tests of ``module_path`` that Odoo never collects"""
    tests_path = module_path / TESTS_FOLDER
    if not tests_path.is_dir():
        return []
    rel_tests_path = relpath(tests_path)
    test_modules = get_test_modules(tests_path)
    if not test_modules:
        return [
            "%s - [tests-folder-without-tests] There is no %s*.py file in the folder, so Odoo runs 0 tests of %s."
            % (rel_tests_path, TEST_PREFIX, module_path.name)
        ]
    init_path = tests_path / "__init__.py"
    rel_init_path = relpath(init_path)
    if init_path.is_file():
        try:
            imported = get_imported_modules(init_path, module_path.name)
        except SyntaxError as syntax_error:
            return ["%s:%s - Unable to parse the file: %s" % (rel_init_path, syntax_error.lineno, syntax_error.msg)]
    else:
        imported = set()
    messages = [
        '%s - [test-file-not-imported] It is not imported by %s, so Odoo never runs its tests. Add "from . import %s"'
        % (relpath(test_modules[test_module]), rel_init_path, test_module)
        for test_module in sorted(test_modules.keys() - imported)
    ]
    if not test_modules.keys() & imported:
        messages.append(
            "%s - [tests-folder-without-tests] No test file is imported, so Odoo runs 0 tests of %s."
            % (rel_init_path if init_path.is_file() else rel_tests_path, module_path.name)
        )
    return messages


def main(argv=None):
    """Check the modules owning the files received, each one only once"""
    if argv is None:
        argv = sys.argv[1:]
    root_path = pathlib.Path.cwd().resolve()
    module_paths = {get_module_path(fname, root_path) for fname in argv}
    messages = []
    for module_path in sorted(module_path for module_path in module_paths if module_path):
        messages.extend(check_module(module_path))
    for message in messages:
        print(message)
    return 1 if messages else 0


if __name__ == "__main__":
    sys.exit(main())
