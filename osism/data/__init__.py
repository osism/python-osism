# SPDX-License-Identifier: Apache-2.0

TEMPLATE_IMAGE_OCTAVIA = """---
images:
  - name: OpenStack Octavia Amphora
    enable: true
    shortname: amphora
    format: qcow2
    login: ubuntu
    min_disk: 2
    min_ram: 512
    status: active
    visibility: private
    multi: false
    meta:
      architecture: x86_64
      hw_disk_bus: scsi
      hw_rng_model: virtio
      hw_scsi_model: virtio-scsi
      hw_watchdog_action: reset
      hypervisor_type: qemu
      os_distro: ubuntu
      replace_frequency: quarterly
      uuid_validity: last-1
      provided_until: none
      os_purpose: network
    tags:
      - amphora
    versions:
      - version: "{{ image_version }}"
        url: "{{ image_url }}"
        checksum: "{{ image_checksum }}"
        build_date: {{ image_builddate }}

"""

TEMPLATE_IMAGE_CLUSTERAPI = """---
images:
  - name: ubuntu-capi-image
    enable: true
    keep: true
    separator: "-"
    format: qcow2
    login: ubuntu
    min_disk: 20
    min_ram: 512
    status: active
    visibility: public
    multi: false
    meta:
      architecture: x86_64
      hw_disk_bus: scsi
      hw_rng_model: virtio
      hw_scsi_model: virtio-scsi
      hw_watchdog_action: reset
      hypervisor_type: qemu
      os_distro: ubuntu
      replace_frequency: never
      uuid_validity: none
      provided_until: none
      os_purpose: k8snode
    tags: []
    versions:
      - version: "v{{ image_version }}"
        url: "{{ image_url }}"
        checksum: "{{ image_checksum }}"
        build_date: {{ image_builddate }}

"""

TEMPLATE_IMAGE_GARDENLINUX = """---
images:
  - name: garden-linux-image
    enable: true
    keep: true
    separator: "-"
    format: qcow2
    login: garden
    min_disk: 20
    min_ram: 512
    status: active
    visibility: public
    multi: false
    meta:
      architecture: x86_64
      hw_disk_bus: scsi
      hw_rng_model: virtio
      hw_scsi_model: virtio-scsi
      hw_watchdog_action: reset
      hypervisor_type: qemu
      os_distro: debian
      replace_frequency: never
      uuid_validity: none
      provided_until: none
      os_purpose: k8snode
    tags: []
    versions:
      - version: "{{ image_version }}"
        url: "{{ image_url }}"
        checksum: "{{ image_checksum }}"
        build_date: {{ image_builddate }}

"""

TEMPLATE_IMAGE_CLUSTERAPI_GARDENER = """---
images:
  - name: ubuntu-capi-image-gardener
    enable: true
    keep: true
    separator: "-"
    format: qcow2
    login: ubuntu
    min_disk: 20
    min_ram: 512
    status: active
    visibility: public
    multi: false
    meta:
      architecture: x86_64
      hw_disk_bus: scsi
      hw_rng_model: virtio
      hw_scsi_model: virtio-scsi
      hw_watchdog_action: reset
      hypervisor_type: qemu
      os_distro: ubuntu
      replace_frequency: never
      uuid_validity: none
      provided_until: none
      os_purpose: k8snode
    tags: []
    versions:
      - version: "v{{ image_version }}"
        url: "{{ image_url }}"
        checksum: "{{ image_checksum }}"
        build_date: {{ image_builddate }}

"""

TEMPLATE_KOLLA_VERSIONS = """---
kolla_aodh_version: "{{ versions['aodh']|default(openstack_version) }}"
kolla_barbican_version: "{{ versions['barbican']|default(openstack_version) }}"
kolla_ceilometer_version: "{{ versions['ceilometer']|default(openstack_version) }}"
kolla_cinder_version: "{{ versions['cinder']|default(openstack_version) }}"
kolla_cloudkitty_version: "{{ versions['cloudkitty']|default(openstack_version) }}"
kolla_common_version: "{{ versions['kolla_toolbox']|default(openstack_version) }}"
kolla_cron_version: "{{ versions['cron']|default(openstack_version) }}"
kolla_designate_version: "{{ versions['designate']|default(openstack_version) }}"
kolla_dnsmasq_version: "{{ versions['dnsmasq']|default(openstack_version) }}"
kolla_fluentd_version: "{{ versions['fluentd']|default(openstack_version) }}"
kolla_glance_version: "{{ versions['glance']|default(openstack_version) }}"
kolla_gnocchi_version: "{{ versions['gnocchi']|default(openstack_version) }}"
kolla_grafana_version: "{{ versions['grafana']|default(openstack_version) }}"
kolla_haproxy_version: "{{ versions['haproxy']|default(openstack_version) }}"
kolla_haproxy_ssh_version: "{{ versions['haproxy_ssh']|default(openstack_version) }}"
kolla_horizon_version: "{{ versions['horizon']|default(openstack_version) }}"
kolla_ironic_inspector_version: "{{ versions['ironic_inspector']|default(openstack_version) }}"
kolla_ironic_version: "{{ versions['ironic']|default(openstack_version) }}"
kolla_iscsid_version: "{{ versions['iscsid']|default(openstack_version) }}"
kolla_keepalived_version: "{{ versions['keepalived']|default(openstack_version) }}"
kolla_keystone_version: "{{ versions['keystone']|default(openstack_version) }}"
kolla_magnum_version: "{{ versions['magnum']|default(openstack_version) }}"
kolla_manila_version: "{{ versions['manila']|default(openstack_version) }}"
kolla_mariadb_version: "{{ versions['mariadb']|default(openstack_version) }}"
kolla_memcached_version: "{{ versions['memcached']|default(openstack_version) }}"
kolla_multipathd_version: "{{ versions['multipathd']|default(openstack_version) }}"
kolla_neutron_version: "{{ versions['neutron']|default(openstack_version) }}"
kolla_nova_version: "{{ versions['nova']|default(openstack_version) }}"
kolla_octavia_version: "{{ versions['octavia']|default(openstack_version) }}"
kolla_opensearch_version: "{{ versions['opensearch']|default(openstack_version) }}"
kolla_openvswitch_version: "{{ versions['openvswitch']|default(openstack_version) }}"
kolla_ovn_version: "{{ versions['ovn']|default(openstack_version) }}"
kolla_placement_version: "{{ versions['placement']|default(openstack_version) }}"
kolla_prometheus_version: "{{ versions['prometheus']|default(openstack_version) }}"
kolla_proxysql_version: "{{ versions['proxysql']|default(openstack_version) }}"
kolla_rabbitmq_version: "{{ versions['rabbitmq']|default(openstack_version) }}"
kolla_redis_version: "{{ versions['redis']|default(openstack_version) }}"
kolla_skyline_version: "{{ versions['skyline']|default(openstack_version) }}"
kolla_tgtd_version: "{{ versions['tgtd']|default(openstack_version) }}"
kolla_watcher_version: "{{ versions['watcher']|default(openstack_version) }}"

kolla_nova_libvirt_version: "{{ versions['nova_libvirt']|default(openstack_version) }}"
kolla_opensearch_dashboards_version: "{{ versions['opensearch_dashboards']|default(openstack_version) }}"
kolla_skyline_console_version: "{{ versions['skyline_console']|default(openstack_version) }}"

kolla_prometheus_alertmanager_version: "{{ versions['prometheus_alertmanager']|default(openstack_version) }}"
kolla_prometheus_blackbox_exporter_version: "{{ versions['prometheus_blackbox_exporter']|default(openstack_version) }}"
kolla_prometheus_cadvisor_version: "{{ versions['prometheus_cadvisor']|default(openstack_version) }}"
kolla_prometheus_elasticsearch_exporter_version: "{{ versions['prometheus_elasticsearch_exporter']|default(openstack_version) }}"
kolla_prometheus_libvirt_exporter_version: "{{ versions['prometheus_libvirt_exporter']|default(openstack_version) }}"
kolla_prometheus_memcached_exporter_version: "{{ versions['prometheus_memcached_exporter']|default(openstack_version) }}"
kolla_prometheus_mysqld_exporter_version: "{{ versions['prometheus_mysqld_exporter']|default(openstack_version) }}"
kolla_prometheus_node_exporter_version: "{{ versions['prometheus_node_exporter']|default(openstack_version) }}"
kolla_prometheus_openstack_exporter_version: "{{ versions['prometheus_openstack_exporter']|default(openstack_version) }}"
kolla_ironic_prometheus_exporter_version: "{{ versions['ironic']|default(openstack_version) }}"

kolla_letsencrypt_lego_version: "{{ versions['letsencrypt_lego']|default(openstack_version) }}"
kolla_letsencrypt_webserver_version: "{{ versions['letsencrypt_webserver']|default(openstack_version) }}"
"""
