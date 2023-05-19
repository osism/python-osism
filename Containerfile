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
    && python3 -m pip --no-cache-dir install -U 'pip==23.1.2' \
    && python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /src/requirements.txt \
    && python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /src/requirements.ansible.txt \
    && python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /src/requirements.openstack-image-manager.txt \
    && git clone --depth 1 https://github.com/osism/openstack-project-manager.git /openstack-project-manager \
    && python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /openstack-project-manager/requirements.txt \
    && git clone --depth 1 https://github.com/osism/openstack-simple-stress.git /openstack-simple-stress \
    && python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /openstack-simple-stress/requirements.txt

ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim as osism

COPY --from=builder /wheels /wheels
COPY . /src
COPY files/change.sh /change.sh
COPY files/run-ansible-console.sh /run-ansible-console.sh
COPY requirements.yml /ansible/requirements.yml

ENV CLUSTERSHELL_CFGDIR=/etc/clustershell/
COPY files/clustershell/clush.conf /etc/clustershell/clush.conf
COPY files/clustershell/groups.conf /etc/clustershell/groups.conf

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        openssh-client \
        procps \
    && python3 -m pip --no-cache-dir install -U 'pip==23.1.2' \
    && python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /src/requirements.txt \
    && python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /src/requirements.ansible.txt \
    && python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /src/requirements.openstack-image-manager.txt \
    && python3 -m pip --no-cache-dir install --no-index /src \
    && ansible-galaxy collection install -v -f -r /ansible/requirements.yml -p /usr/share/ansible/collections \
    && ln -s /usr/share/ansible/collections /ansible/collections \
    && git clone --depth 1 https://github.com/osism/mappings /mappings \
    && apt-get clean \
    && rm -rf /var/cache/apt /var/lib/apt/lists/* /tmp/* /var/tmp/* \
    && mkdir -p /ansible/logs \
    && git clone --depth 1 https://github.com/osism/openstack-image-manager.git /openstack-image-manager \
    && mkdir -p /etc/images \
    && ln -s /opt/configuration/environments/openstack /etc/openstack \
    && cp /openstack-image-manager/etc/images/* /etc/images \
    && rm -rf /openstack-image-manager \
    && git clone --depth 1 https://github.com/osism/openstack-project-manager.git /openstack-project-manager \
    && python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /openstack-project-manager/requirements.txt \
    && git clone --depth 1 https://github.com/osism/openstack-simple-stress.git /openstack-simple-stress \
    && python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /openstack-simple-stress/requirements.txt \
    && ln -s /ansible/inventory/clustershell /etc/clustershell/groups.d

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
