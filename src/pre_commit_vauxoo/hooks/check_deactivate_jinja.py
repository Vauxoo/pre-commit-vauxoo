#!/usr/bin/env python3

# Hooks are using print directly
# pylint: disable=print-used

import json
import os
import platform
import re
import sys

from jinja2 import Environment, Template, meta
from pgsanity import pgsanity

INSTANCE_TYPES = ["test", "develop", "updates"]
VALID_VARIABLES = {"instance_type"}


def check_deactivate(fname_deactivate, instance_types=None):
    if instance_types is None:
        instance_types = INSTANCE_TYPES
    with open(fname_deactivate) as f_deactivate:
        deactivate_content = f_deactivate.read()
    jinja_tmpl = Template(deactivate_content)
    res = True
    for instance_type in instance_types:
        json_content = jinja_tmpl.render(instance_type=instance_type)
        try:
            json_obj = json.loads(json_content)
        except json.decoder.JSONDecodeError as json_e:
            json_line_error = "\n".join(json_content.splitlines()[json_e.lineno - 2 : json_e.lineno])  # noqa: E203
            print(
                "%s->json instance_type=%s - %s\n%s\njson content:\n%s"
                % (fname_deactivate, instance_type, json_e.msg, json_line_error, json_content)
            )
            res = False
            continue

        sql = ";\n".join(json_obj.values()) + ";"
        try:
            res, msg = pgsanity.check_string(sql)
        except OSError as oserr:
            res = False
            if platform.system() == "Darwin":
                # MACOSX
                msg = "'brew install postgresql'"
            elif os.name == "posix":
                # LINUX
                msg = "'apt install -y libecpg-dev'"
            else:
                # WINDOWS
                msg = "Install postgresql and add to PATH the PGBIN folder"
            print("%s - %s" % (oserr, msg))
            # Return instead of continue because the package is not installed
            return res
        if not res:
            error_re = re.search(r"^line (\d+): ([^/]+)", msg)
            if error_re:
                sql_lineno, only_msg = error_re.groups()
                sql_lineno = int(sql_lineno)
            sql_line_error = "\n".join(sql.splitlines()[sql_lineno - 1 : sql_lineno])  # noqa: E203
            print(
                "%s->json->sql instance_type=%s - %s\n\t%s\nsql content:\n%s"
                % (fname_deactivate, instance_type, only_msg, sql_line_error, sql)
            )
            return res
        env = Environment()
        parsed_content = env.parse(deactivate_content)
        invalid_variables = meta.find_undeclared_variables(parsed_content) - VALID_VARIABLES
        if invalid_variables:
            print(
                "%s - There are invalid variables: (%s). Expected: (%s)"
                % (fname_deactivate, ", ".join(invalid_variables), ", ".join(VALID_VARIABLES))
            )
            return False

    return res


def main():
    global_res = True
    for fname in sys.argv[1:]:
        res = check_deactivate(fname)
        if not res:
            global_res = False
    if not global_res:
        sys.exit(1)


if __name__ == "__main__":
    main()
