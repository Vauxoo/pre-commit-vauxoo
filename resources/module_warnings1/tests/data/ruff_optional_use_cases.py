"""Use cases of the optional checks migrated from pylint/flake8+bugbear to ruff.

Each case must be reported:
 - before the ruff migration: by "pylint optional checks" or "flake8 + bugbear optional checks"
 - after the ruff migration: by "ruff optional checks" (see .config/.ruff-optional.toml)

It is stored under "tests/data/" since that path is excluded from the autofixes
so the use cases are not autofixed before being reported by the linters.
The cases must not be reported by any mandatory check.
"""

import datetime

# implicit-str-concat (pylint) -> single-line-implicit-string-concatenation (ruff ISC001)
IMPLICIT_CONCAT = "implicit" "concatenation"

# redundant-u-string-prefix (pylint) -> unicode-kind-prefix (ruff UP025)
UNICODE_PREFIX = u"unicode prefix"

# E242 tab after ',' (flake8) -> tab-after-comma (ruff E242)
TAB_AFTER_COMMA = ("first",	"second")


def print_use_case(value):
    # print-used (pylint) -> print (ruff T201)
    print(value)


def except_pass_use_case(value):
    # except-pass (pylint) -> try-except-pass (ruff S110)
    try:
        value = int(value)
    except ValueError:
        pass
    return value


def compare_empty_string_use_case(name):
    # use-implicit-booleaness-not-comparison-to-string (pylint) -> compare-to-empty-string (ruff PLC1901)
    if name == "":
        return "empty"
    return name


def ambiguous_variable_use_case(items):
    # E741 ambiguous variable name (flake8) -> ambiguous-variable-name (ruff E741)
    total = 0
    for l in items:  # pylint: disable=invalid-name
        total += l
    return total


def function_call_default_use_case(when=datetime.datetime.now()):
    # B008 (flake8-bugbear) -> function-call-in-default-argument (ruff B008)
    return when


def assert_false_use_case():
    # B011 (flake8-bugbear) -> assert-false (ruff B011)
    assert False, "assert False use case"


def too_complex_use_case(number):
    # too-complex (pylint mccabe max-complexity=15) -> complex-structure (ruff C901)
    total = 0
    if number % 2:
        total += 2
    if number % 3:
        total += 3
    if number % 5:
        total += 5
    if number % 7:
        total += 7
    if number % 11:
        total += 11
    if number % 13:
        total += 13
    if number % 17:
        total += 17
    if number % 19:
        total += 19
    if number % 23:
        total += 23
    if number % 29:
        total += 29
    if number % 31:
        total += 31
    if number % 37:
        total += 37
    if number % 41:
        total += 41
    if number % 43:
        total += 43
    if number % 47:
        total += 47
    if number % 53:
        total += 53
    return total
