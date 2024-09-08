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
    tags: []
    versions:
      - version: "v{{ image_version }}"
        url: "{{ image_url }}"
        checksum: "{{ image_checksum }}"
        build_date: {{ image_builddate }}

"""
