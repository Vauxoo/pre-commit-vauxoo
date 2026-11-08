from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pre_commit_vauxoo.hooks.check_tests_imported import check_module, get_imported_modules, main

NOT_IMPORTED = "[test-file-not-imported]"
WITHOUT_TESTS = "[tests-folder-without-tests]"


def create_module(root, files, name="module_tested", manifest="__manifest__.py"):
    """Create the Odoo module ``name`` in ``root`` with ``files`` ({relative path: content})"""
    module_path = root / name
    module_path.mkdir()
    (module_path / manifest).write_text("{'name': 'Tested', 'license': 'LGPL-3'}\n")
    (module_path / "__init__.py").write_text("")
    for relative_path, content in files.items():
        path = module_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content))
    return module_path


@pytest.fixture(name="repo")
def fixture_repo(tmp_path, monkeypatch):
    """The hook receives the paths relative to the root of the repository, its working directory"""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    "init_content",
    [
        pytest.param("from . import test_a, test_b\n", id="single-line"),
        pytest.param("from . import test_a\nfrom . import test_b\n", id="one-per-line"),
        pytest.param(
            """\
            from . import (
                test_a,
                test_b,
            )
            """,
            id="multi-line-parenthesized",
        ),
        pytest.param("from .test_a import TestA\nfrom .test_b.common import TestB\n", id="from-submodule"),
        pytest.param(
            "from odoo.addons.module_tested.tests import test_a\n"
            "from odoo.addons.module_tested.tests.test_b import TestB\n",
            id="absolute",
        ),
        pytest.param(
            """\
            try:
                from . import test_a, test_b
            except ImportError:
                pass
            """,
            id="nested-in-try",
        ),
    ],
)
def test_all_imported(repo, init_content):
    module_path = create_module(
        repo,
        {
            "tests/__init__.py": init_content,
            "tests/common.py": "",
            "tests/test_a.py": "",
            # A test package is collected by Odoo the same as a test file
            "tests/test_b/__init__.py": "",
        },
    )
    assert not check_module(module_path)
    assert not main([str(module_path / "tests" / "test_a.py")])


def test_file_not_imported(repo, capsys):
    module_path = create_module(
        repo,
        {
            "tests/__init__.py": "from . import test_a\nfrom .common import TestCommon\n",
            "tests/common.py": "",
            "tests/test_a.py": "",
            "tests/test_b.py": "",
            "tests/test_c/__init__.py": "",
        },
    )
    assert main([str(module_path / "__manifest__.py")]) == 1
    output = capsys.readouterr().out.splitlines()
    assert output == [
        "module_tested/tests/test_b.py - %s It is not imported by module_tested/tests/__init__.py, so Odoo never "
        'runs its tests. Add "from . import test_b"' % NOT_IMPORTED,
        "module_tested/tests/test_c - %s It is not imported by module_tested/tests/__init__.py, so Odoo never "
        'runs its tests. Add "from . import test_c"' % NOT_IMPORTED,
    ]


def test_no_test_file_imported(repo):
    """None of the test files is imported: Odoo runs 0 tests of the module"""
    module_path = create_module(
        repo,
        {"tests/__init__.py": "# Tests for module_tested\n", "tests/test_a.py": "", "tests/test_b.py": ""},
    )
    messages = check_module(module_path)
    assert len(messages) == 3
    assert messages[0].startswith("module_tested/tests/test_a.py - %s" % NOT_IMPORTED)
    assert messages[1].startswith("module_tested/tests/test_b.py - %s" % NOT_IMPORTED)
    assert messages[2] == (
        "module_tested/tests/__init__.py - %s No test file is imported, so Odoo runs 0 tests of module_tested."
        % WITHOUT_TESTS
    )


def test_no_init(repo):
    """Without __init__.py the folder is not a package, so Odoo does not even import it"""
    module_path = create_module(repo, {"tests/test_a.py": ""})
    messages = check_module(module_path)
    assert messages[0].startswith("module_tested/tests/test_a.py - %s" % NOT_IMPORTED)
    assert messages[1] == (
        "module_tested/tests - %s No test file is imported, so Odoo runs 0 tests of module_tested." % WITHOUT_TESTS
    )


@pytest.mark.parametrize(
    "files",
    [
        pytest.param({"tests/__init__.py": "# Tests for module_tested\n"}, id="only-init"),
        pytest.param({"tests/__init__.py": "from . import common\n", "tests/common.py": ""}, id="only-common"),
        pytest.param({"tests/data/file.csv": "id\n"}, id="only-data"),
    ],
)
def test_folder_without_tests(repo, files):
    module_path = create_module(repo, files)
    assert check_module(module_path) == [
        "module_tested/tests - %s There is no test_*.py file in the folder, so Odoo runs 0 tests of module_tested."
        % WITHOUT_TESTS
    ]


def test_module_without_tests_folder(repo):
    module_path = create_module(repo, {"models/__init__.py": ""})
    assert not check_module(module_path)
    assert not main([str(module_path / "__manifest__.py"), str(module_path / "models" / "__init__.py")])


def test_openerp_manifest(repo):
    module_path = create_module(repo, {"tests/__init__.py": "", "tests/test_a.py": ""}, manifest="__openerp__.py")
    assert main([str(module_path / "tests" / "__init__.py")]) == 1


def test_not_a_module(repo):
    """A tests folder outside of an Odoo module, e.g. the one of a python package, is not checked"""
    tests_path = repo / "tests"
    tests_path.mkdir()
    (tests_path / "test_a.py").write_text("")
    assert not main([str(tests_path / "test_a.py")])


def test_manifest_above_the_repository(tmp_path, monkeypatch):
    """Only the folders of the repository are modules, even if the repository lives in one"""
    module_path = create_module(tmp_path, {"repo/tests/test_a.py": ""})
    monkeypatch.chdir(module_path / "repo")
    assert not main(["tests/test_a.py"])


def test_module_checked_once(repo, capsys):
    module_path = create_module(repo, {"tests/__init__.py": "", "tests/test_a.py": ""})
    fnames = [str(module_path / name) for name in ("__manifest__.py", "tests/__init__.py", "tests/test_a.py")]
    assert main(fnames) == 1
    assert len(capsys.readouterr().out.splitlines()) == 2


def test_syntax_error(repo):
    module_path = create_module(repo, {"tests/__init__.py": "from . import\n", "tests/test_a.py": ""})
    messages = check_module(module_path)
    assert len(messages) == 1
    assert messages[0].startswith("module_tested/tests/__init__.py:1 - Unable to parse the file")


def test_dynamic_imports_not_resolved(repo):
    """The imports are not executed: the ones made at runtime are not seen (documented limit)"""
    module_path = create_module(
        repo,
        {
            "tests/__init__.py": "import importlib\n\nimportlib.import_module('.test_a', __name__)\nfrom . import *\n",
            "tests/test_a.py": "",
        },
    )
    init_path = module_path / "tests" / "__init__.py"
    assert get_imported_modules(init_path, "module_tested") == {"*"}
    assert check_module(module_path)[0].startswith("module_tested/tests/test_a.py - %s" % NOT_IMPORTED)


def test_other_module_imports_ignored(repo):
    """Importing the tests of another module does not import the ones of this module"""
    module_path = create_module(
        repo,
        {
            "tests/__init__.py": "from odoo.addons.other_module.tests import test_a\n",
            "tests/test_a.py": "",
        },
    )
    assert get_imported_modules(Path(module_path, "tests", "__init__.py"), "module_tested") == set()
    assert check_module(module_path)[0].startswith("module_tested/tests/test_a.py - %s" % NOT_IMPORTED)
