# SPDX-License-Identifier: Apache-2.0

"""config_db table coverage report for the SONiC E2E golden set.

This is a reporting tool, not a gate: it is not invoked from
sonic_golden_test.sh, and the golden comparison (tests/e2e/compare.py)
remains the only check that actually fails a run. It exists so the "N of M
config_db tables covered" claim made when the golden set is extended can be
re-derived by anyone, at any time, instead of only having existed as an
ad-hoc one-off script run once during development.

It works in two independent steps:

1. Derive the set of tables the generator can emit by grepping
   osism/tasks/conductor/sonic/ (excluding the generated schema package,
   _generated/, which is data rather than emission logic) for direct
   ``config["TABLE"]``/``cfg["TABLE"]`` assignments -- including a nested
   item assignment such as ``config["ACL_TABLE"]["SSH_ONLY"] = ...`` or a
   ``.update(...)`` call, but not a mere read such as
   ``"x" in config["VERSIONS"]``. This is a static, syntactic approximation
   of "tables the generator can populate", not a guarantee every branch
   that reaches it is exercised.
2. Collect the set of tables that are non-empty in at least one file under
   tests/e2e/golden/*.json.

The report prints both counts and, if any emitted table is never non-empty
across the golden set, lists them and exits 1.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_DIR = REPO_ROOT / "osism" / "tasks" / "conductor" / "sonic"
GOLDEN_DIR = REPO_ROOT / "tests" / "e2e" / "golden"

# Matches config["TABLE"] or cfg["TABLE"], optionally followed by one or
# more ["key"]/[expr] accessors, then either an assignment ("=" but not
# "==") or a .update(...) call -- i.e. the table is a write target, not
# merely read.
_TABLE_ASSIGNMENT_RE = re.compile(
    r'(?:config|cfg)\["([A-Z][A-Z0-9_]*)"\](?:\[[^\]]*\])*\s*(?:=(?!=)|\.update\()'
)


def emitted_tables(generator_dir=GENERATOR_DIR):
    """Tables the generator can emit, derived from source assignments."""
    tables = set()
    for path in sorted(Path(generator_dir).rglob("*.py")):
        if "_generated" in path.parts:
            continue
        for line in path.read_text().splitlines():
            if line.lstrip().startswith("#"):
                continue
            for match in _TABLE_ASSIGNMENT_RE.finditer(line):
                tables.add(match.group(1))
    return tables


def covered_tables(golden_dir=GOLDEN_DIR):
    """Tables that are non-empty in at least one golden file."""
    import json

    tables = set()
    for path in sorted(Path(golden_dir).glob("*.json")):
        config = json.loads(path.read_text())
        for table, value in config.items():
            if value:
                tables.add(table)
    return tables


def main(argv=None):
    emitted = emitted_tables()
    covered = covered_tables()
    missing = sorted(emitted - covered)

    print(f"generator emits {len(emitted)} tables; {len(covered)} non-empty")
    if missing:
        print("not covered by any golden file:")
        for table in missing:
            print(f"  {table}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
