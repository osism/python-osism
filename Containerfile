ARG PYTHON_VERSION=3.9
FROM python:${PYTHON_VERSION} as builder

COPY . /src

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      gcc \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /wheels \
    && python3 -m pip --no-cache-dir install -U 'pip==21.3.1' \
    && python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /src/requirements.txt

ARG PYTHON_VERSION=3.9
FROM python:${PYTHON_VERSION}

COPY --from=builder /wheels /wheels
COPY . /src

RUN python3 -m pip --no-cache-dir install -U 'pip==21.3.1' \
    && python3 -m pip install --no-index --find-links=/wheels -r /src/requirements.txt \
    && python3 -m pip install --no-index /src

LABEL "org.opencontainers.image.documentation"="https://docs.osism.tech" \
      "org.opencontainers.image.licenses"="ASL 2.0" \
      "org.opencontainers.image.source"="https://github.com/osism/python-osism" \
      "org.opencontainers.image.url"="https://www.osism.tech" \
      "org.opencontainers.image.vendor"="OSISM GmbH"
