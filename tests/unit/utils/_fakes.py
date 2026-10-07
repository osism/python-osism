# SPDX-License-Identifier: Apache-2.0

"""Adapt a name -> result fake to the expressions evaluate_request sends."""

import ast
import re


def by_name(resolve):
    """Answer "'x' in vars" and "vars['x']" from resolve(x); pass the rest."""

    def inner(expr):
        match = re.fullmatch(r"vars\[(.*)\]", expr)
        if match:
            return resolve(ast.literal_eval(match.group(1)))
        match = re.fullmatch(r"('.*'|\".*\") in vars", expr)
        if match:
            name = ast.literal_eval(match.group(1))
            result = resolve(name)
            absent = f"AnsibleUndefinedVariable: '{name}' is undefined"
            return {"value": result.get("error") != absent}
        return resolve(expr)

    return inner
