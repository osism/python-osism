ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION} as builder

COPY . /src

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      gcc \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /wheels \
    && python3 -m pip --no-cache-dir install -U 'pip==22.3.1' \
    && python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /src/requirements.txt \
    && python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /src/requirements.ansible.txt \
    && git clone --depth 1 https://github.com/osism/openstack-project-manager.git /openstack-project-manager \
    && python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /openstack-project-manager/requirements.txt

ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim as osism

COPY --from=builder /wheels /wheels
COPY . /src
COPY files/change.sh /change.sh
COPY files/run-ansible-console.sh /run-ansible-console.sh

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        openssh-client \
        procps \
    && python3 -m pip --no-cache-dir install -U 'pip==22.3.1' \
    && python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /src/requirements.txt \
    && python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /src/requirements.ansible.txt \
    && python3 -m pip --no-cache-dir install --no-index /src \
    && git clone --depth 1 https://github.com/osism/mappings /mappings \
    && apt-get clean \
    && rm -rf /var/cache/apt /var/lib/apt/lists/* /tmp/* /var/tmp/* \
    && mkdir -p /ansible/logs \
    && git clone --depth 1 https://github.com/osism/openstack-image-manager.git /openstack-image-manager \
    && mkdir -p /etc/images \
    && cp /openstack-image-manager/etc/images/* /etc/images \
    && rm -rf /openstack-image-manager \
    && git clone --depth 1 https://github.com/osism/openstack-project-manager.git /openstack-project-manager \
    && python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /openstack-project-manager/requirements.txt

LABEL "org.opencontainers.image.documentation"="https://docs.osism.tech" \
      "org.opencontainers.image.licenses"="ASL 2.0" \
      "org.opencontainers.image.source"="https://github.com/osism/python-osism" \
      "org.opencontainers.image.url"="https://www.osism.tech" \
      "org.opencontainers.image.vendor"="OSISM GmbH"

FROM osism as osism-netbox

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      git \
      git-annex \
    && mkdir -p \
      /import \
    && git clone https://github.com/netbox-community/devicetype-library /devicetype-library \
    && apt-get clean \
    && rm -rf /var/cache/apt /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY files/import/* /import
