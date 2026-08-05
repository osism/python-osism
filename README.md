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
