# SPDX-License-Identifier: Apache-2.0

"""Gate on the golden set covering every config_db table the generator emits.

tests/e2e/coverage.py is the human-facing report; this is the check that
actually fails. It lives in the unit suite rather than in the E2E job because
it needs neither NetBox nor a generated config -- only the generator source
and the committed goldens -- so it costs milliseconds and runs on every
change, instead of only when the E2E job's file matcher fires.

What it catches is the one coverage failure nothing else does: a newly
emitted table that arrives with no golden. Coverage going the other way (a
table that had a golden becoming empty) already fails the golden comparison,
because the golden file itself changes.
"""

from tests.e2e.coverage import covered_tables, emitted_tables


def test_every_emitted_table_has_golden_coverage():
    missing = sorted(emitted_tables() - covered_tables())

    assert not missing, (
        "the generator can emit these config_db tables, but they are empty in "
        "every file under tests/e2e/golden/: " + ", ".join(missing) + ". Seed a "
        "device that populates them under tests/e2e/scenario/resources/ and "
        "rewrite the goldens with `make sonic-e2e-regen`, or -- if the table "
        "cannot be reached by any fixture -- exclude it here with a comment "
        "saying why."
    )
