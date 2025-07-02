ARG PYTHON_VERSION=3.13.3
ARG ALPINE_VERSION=3.21
ARG IMAGE=registry.osism.tech/dockerhub/python

FROM ${IMAGE}:${PYTHON_VERSION}-alpine${ALPINE_VERSION}

ENV PYTHONWARNINGS="ignore::UserWarning"

COPY . /src
COPY --from=ghcr.io/astral-sh/uv:0.7.19 /uv /usr/local/bin/uv

COPY files/data  /data
COPY files/change.sh /change.sh
COPY files/run-ansible-console.sh /run-ansible-console.sh
COPY requirements.yml /ansible/requirements.yml

ENV CLUSTERSHELL_CFGDIR=/etc/clustershell/
COPY files/clustershell/clush.conf /etc/clustershell/clush.conf
COPY files/clustershell/groups.conf /etc/clustershell/groups.conf

COPY files/sonic/port_config/ /etc/sonic/port_config/
COPY files/sonic/config_db.json /etc/sonic/config_db.json

COPY files/netbox-manager/settings.toml /usr/local/config/settings.toml

COPY files/redfishMockupCreate.py /

RUN apk add --no-cache bash

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN <<EOF
set -e
set -x

# install required packages
apk add --no-cache --virtual .build-deps \
  build-base \
  gcc \
  linux-headers \
  musl-dev \
  openldap-dev
apk add --no-cache \
  git \
  less \
  openssh-client \
  procps \
  tini \
  cdrkit

# install python packages
uv pip install --no-cache --system -r /src/requirements.txt
uv pip install --no-cache --system -r /src/requirements.ansible.txt
uv pip install --no-cache --system -r /src/requirements.openstack-image-manager.txt
uv pip install --no-cache --system -r /src/requirements.openstack-flavor-manager.txt
uv pip install --no-cache --system -r /src/requirements.netbox-manager.txt

# required by redfishMockupCreate.py
uv pip install --no-cache --system "redfish==3.3.1"

# install python-osism
uv pip install --no-cache --system /src

# install ansible collections
mkdir -p /ansible/logs
ansible-galaxy collection install -v -f -r /ansible/requirements.yml -p /usr/share/ansible/collections
ansible-galaxy collection install -v -f -r /usr/local/lib/python*/site-packages/netbox_manager/requirements.yml -p /usr/share/ansible/collections
ln -s /usr/share/ansible/collections /ansible/collections

# copy image definitions for the openstack-image-manager
git clone --depth 1 https://github.com/osism/openstack-image-manager.git /openstack-image-manager
mkdir -p /etc/images
ln -s /opt/configuration/environments/openstack /etc/openstack
cp /openstack-image-manager/etc/images/* /etc/images
rm -rf /openstack-image-manager

# install openstack-project-manager
git clone --depth 1 https://github.com/osism/openstack-project-manager.git /openstack-project-manager
uv pip install --no-cache --system -r /openstack-project-manager/requirements.txt
rm -rf /openstack-project-manager/.git

# install openstack-simple-stress
git clone --depth 1 https://github.com/osism/openstack-simple-stress.git /openstack-simple-stress
uv pip install --no-cache --system -r /openstack-simple-stress/requirements.txt
rm -rf /osism/openstack-simple-stress/.git

# install openstack-resource-manager
git clone --depth 1 https://github.com/osism/openstack-resource-manager.git /openstack-resource-manager
rm -rf /openstack-resource-manager/.git

# add tests
git clone --depth 1 https://github.com/osism/tests.git /tests
rm -rf /tests/.git

# prepare use of clustershell
ln -s /ansible/inventory/clustershell /etc/clustershell/groups.d

# create /etc/sonic/export directory
mkdir -p /etc/sonic/export

# cleanup
apk del .build-deps
rm -rf \
  /src \
  /tmp/* \
  /usr/share/doc/* \
  /usr/share/man/* \
  /var/tmp/*

uv pip install --no-cache --system pyclean==3.0.0
pyclean /usr
uv pip uninstall --system pyclean
EOF

ENTRYPOINT ["/sbin/tini", "--"]
