# Collector documents used as parser fixtures

Each file is one raw document as printed by a collector
(`osism/utils/hardware/remote_linux.py`, `remote_sonic.py`) and consumed by
the `parse_*` modules.

## Provenance

| File | Origin | Device |
| --- | --- | --- |
| `linux-connectx4.json` | captured | Node with an Intel I350 (`igb`) and a Mellanox ConnectX-4 Lx (`mlx5_core`) on 25G passive copper cables, Ubuntu 24.04 |
| `linux-bcm57414.json` | captured | Node with a Broadcom BCM57414 (`bnxt_en`) on 25G passive copper cables, an Intel X710 10GBASE-T (`i40e`) and the USB host interface of its BMC |
| `linux-82599.json` | captured | Node with an Intel 82599ES (`ixgbe`) on 10G, cabled with 25G passive copper cables, and the USB host interface of its BMC |
| `sonic-enterprise.json` | captured | Accton AS7726-32X with Enterprise SONiC 4.5.2: QSFP28 cages broken out into 4x25G and 4x10G with passive copper cables, 100G SR4 optics with diagnostics, empty cages. Keys of `LLDP_ENTRY_TABLE` with the MAC address of the neighbour |
| `sonic-enterprise-4.4.json` | captured | The second leaf of the same pair with Enterprise SONiC 4.4.1. Keys of `LLDP_ENTRY_TABLE` without MAC address |
| `linux-mellanox.json` | synthetic | Node with a bond, an optical module with diagnostics and an empty cage |
| `sonic-synthetic.json` | synthetic | Switch `leaf-1a`, the cable peer of `linux-mellanox.json` in the tests of the report commands |
| `linux-intel.json` | synthetic | Node with a multi-lane optical module and a CMIS module |
| `linux-broadcom.json` | synthetic | Node without `lspci`, `devlink` and `lldpctl` |
| `linux-mellanox-vf-ib.json` | synthetic | Node with SR-IOV virtual functions and an InfiniBand port |
| `sonic-community.json` | synthetic | Switch with the field names of community SONiC, a CMIS module, and without version file, EEPROM table and firmware status |

### Captured files

A captured file was collected from a device of a running deployment and
then changed in two ways:

- It is anonymized. Host names, MAC addresses, IP addresses, serial numbers
  and VLAN IDs are replaced. The same value is replaced by the same
  replacement in all files, so the two ends of a cable still point at each
  other: `leaf-1` sees `node-1` on the port that `node-1` sees `leaf-1` on.
  `linux-connectx4.json` is `node-1`, `linux-82599.json` is `node-5`, and
  `linux-bcm57414.json` is a node whose host name, `deploy-1`, is not its
  device name. The switches are `leaf-1` and `leaf-2`.
- It is reduced. A switch document keeps a selection of its ports, and the
  `ip link` output of a node keeps the physical ports and `lo`.

Vendor names, part numbers, firmware versions, key names and the structure
of the output are as captured.

### Synthetic files

A synthetic file was written by hand from the documented output formats of
the tools involved (`ip -j link`, `ethtool`, `lldpctl -f json`,
`sonic-db-dump`). Host names, MAC addresses and serial numbers are made up.
It covers what no capture exists for yet, and is only as good as that
documentation.

## Adding a capture

The hardware reports write the raw documents they collected with
`--dump-raw DIR`, one `<device>.json` per device:

    osism report transceiver --dump-raw /tmp/capture compute-042 leaf-1a

A capture contains host names, MAC and IP addresses and serial numbers of
the deployment it came from. Replace them before committing it,
consistently with the files that are already here, and say in the table
above what the file was captured from.
