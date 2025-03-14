ARG PYTHON_VERSION=3.12.3
FROM python:${PYTHON_VERSION}-slim AS builder

COPY . /src

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN <<EOF
set -e
set -x

# install required packages
apt-get update
apt-get install -y --no-install-recommends \
  build-essential \
  gcc \
  git \
  libldap2-dev \
  libsasl2-dev

# install python packages
mkdir /wheels
python3 -m pip --no-cache-dir install -U 'pip==25.0.1'
python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /src/requirements.txt
python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /src/requirements.ansible.txt
python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /src/requirements.openstack-image-manager.txt
python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /src/requirements.openstack-flavor-manager.txt
python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /src/requirements.netbox-manager.txt

# install openstack-project-manager
git clone --depth 1 https://github.com/osism/openstack-project-manager.git /openstack-project-manager
python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /openstack-project-manager/requirements.txt
rm -rf /openstack-project-manager/.git

# install openstack-simple-stress
git clone --depth 1 https://github.com/osism/openstack-simple-stress.git /openstack-simple-stress
python3 -m pip wheel --no-cache-dir --wheel-dir=/wheels -r /openstack-simple-stress/requirements.txt
rm -rf /osism/openstack-simple-stress/.git
EOF

FROM python:${PYTHON_VERSION}-slim AS osism

ENV PYTHONWARNINGS="ignore::UserWarning"

COPY --from=builder /wheels /wheels

COPY . /src

COPY files/data  /data
COPY files/change.sh /change.sh
COPY files/run-ansible-console.sh /run-ansible-console.sh
COPY requirements.yml /ansible/requirements.yml

ENV CLUSTERSHELL_CFGDIR=/etc/clustershell/
COPY files/clustershell/clush.conf /etc/clustershell/clush.conf
COPY files/clustershell/groups.conf /etc/clustershell/groups.conf

COPY files/netbox-manager/settings.toml /usr/local/config/settings.toml

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN <<EOF
set -e
set -x

# install required packages
apt-get update
apt-get install -y --no-install-recommends \
  git \
  less \
  openssh-client \
  procps \
  tini

# install python packages
python3 -m pip --no-cache-dir install -U 'pip==25.0.1'
python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /src/requirements.txt
python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /src/requirements.ansible.txt
python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /src/requirements.openstack-image-manager.txt
python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /src/requirements.openstack-flavor-manager.txt
python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /src/requirements.netbox-manager.txt

# install python-osism
python3 -m pip --no-cache-dir install --no-index /src

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
python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /openstack-project-manager/requirements.txt
rm -rf /openstack-project-manager/.git

# install openstack-simple-stress
git clone --depth 1 https://github.com/osism/openstack-simple-stress.git /openstack-simple-stress
python3 -m pip --no-cache-dir install --no-index --find-links=/wheels -r /openstack-simple-stress/requirements.txt
rm -rf /osism/openstack-simple-stress/.git

# install openstack-resource-manager
git clone --depth 1 https://github.com/osism/openstack-resource-manager.git /openstack-resource-manager
rm -rf /openstack-resource-manager/.git

# add tests
git clone --depth 1 https://github.com/osism/tests.git /tests
rm -rf /tests/.git

# prepare use of clustershell
ln -s /ansible/inventory/clustershell /etc/clustershell/groups.d

# cleanup
apt-get clean
rm -rf \
  /src \
  /tmp/* \
  /usr/share/doc/* \
  /usr/share/man/* \
  /var/lib/apt/lists/* \
  /var/tmp/*

pip3 install --no-cache-dir pyclean==3.0.0
pyclean /usr
pip3 uninstall -y pyclean
EOF

ENTRYPOINT ["/usr/bin/tini", "--"]
