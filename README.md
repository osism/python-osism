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
