# python-osism

[![Quay](https://img.shields.io/badge/Quay-osism%2Fosism-blue.svg)](https://quay.io/repository/osism/osism)
[![PyPi version](https://badgen.net/pypi/v/osism/)](https://pypi.org/project/osism/)
[![PyPi license](https://badgen.net/pypi/license/osism/)](https://pypi.org/project/osism/)
[![Documentation](https://img.shields.io/static/v1?label=&message=documentation&color=blue)](https://osism.tech/docs/references/cli)

## Running unit tests

Install development dependencies and run the full unit test suite:

```
pipenv install --dev
pipenv run pytest
```

Run a single test module:

```
pipenv run pytest tests/unit/test_smoke.py
```

## Running integration tests

The integration tests in `tests/integration/` exercise the Celery/Redis task
core (broker, queue routing, worker, result backend, Redis streams and locks)
end-to-end. They require a reachable Redis and start a Celery worker from the
same virtualenv; they are skipped automatically when Redis is not running.

```
docker run -d -p 6379:6379 redis:7-alpine
REDIS_HOST=localhost REDIS_DB=15 pipenv run pytest tests/integration
```

> **Warning:** The suite mutates live state on the configured Redis. Most keys
> are per-run (UUID-based), but some are fixed global names on the selected
> `REDIS_DB`: the task-lock test reads, writes and removes `osism:task_lock`,
> and the vault test removes `ansible_vault_password` — which a real deployment
> cannot recover, since no other copy of it exists on the system. Always point
> the suite at a disposable Redis (such as the throwaway container above).
>
> To make that hard to get wrong, the suite refuses to run against `REDIS_DB=0`,
> the database a deployment uses. Set `REDIS_DB` to a spare database as shown
> above, or `OSISM_ALLOW_DEFAULT_REDIS_DB=1` if the Redis itself is disposable.
> `REDIS_DB` moves the direct client, the Celery broker and the result backend
> together.

## Running the SONiC E2E golden test

The end-to-end test in `tests/e2e/` provisions NetBox with a docker compose
stack, seeds it from the fixtures in `tests/e2e/scenario/`, generates the SONiC
`config_db.json` files and compares them against the goldens in
`tests/e2e/golden/`. Besides the development dependencies it needs docker with
the compose plugin, `openssl`, and a `netbox-manager` checkout for the seeding
CLI — a sibling directory by default, `NETBOX_MANAGER_DIR` otherwise.

```
pipenv install --dev
make sonic-e2e
```

A cold run takes roughly ten minutes, most of it starting NetBox. To iterate
without paying that each time, bring the stack up separately and leave it
running:

```
make sonic-e2e-up      # start NetBox and leave it up; sonic-e2e reuses it
make sonic-e2e-down    # stop it again and remove its volumes
```

After an intentional generator change, rewrite the goldens and review the diff
before committing it. Regeneration deliberately refuses to run against a stack
left over from an earlier run, because applying the fixtures over a populated
database can produce goldens that CI — which always starts fresh — would not
reproduce:

```
make sonic-e2e-down
make sonic-e2e-regen
```

How much of the generated config the golden set actually covers is reported
separately, because nothing in CI reports it:

```
make sonic-e2e-coverage
```

That compares the `config_db` tables the generator can emit against the tables
that are non-empty in at least one golden, and names any that no golden covers.
It exits non-zero while that list is non-empty, so it is worth running after
adding a scenario to confirm the new tables landed. It gates nothing on its own
— the golden comparison above is the only check that fails a run.

`tests/e2e/sonic_golden_test.sh` documents the remaining environment overrides
(`NETBOX_PORT`, `KEEP_STACK`, `SEED_PARALLEL` and the regeneration escape
hatch).

> **Warning:** Seeding applies *every* file under
> `tests/e2e/scenario/resources/`, tracked or not, so a stray file there joins
> the fixture set — which either breaks the run or silently changes the
> goldens. Check that directory with `git status --ignored` before regenerating
> or debugging a mismatch.
