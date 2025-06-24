# SPDX-License-Identifier: Apache-2.0

"""Constants and mappings for SONiC configuration."""

# Default AS prefix for local ASN calculation
DEFAULT_LOCAL_AS_PREFIX = 4200

# Default SONiC device roles
DEFAULT_SONIC_ROLES = [
    "accessleaf",
    "borderleaf",
    "computeleaf",
    "dataleaf",
    "leaf",
    "serviceleaf",
    "spine",
    "storageleaf",
    "superspine",
    "switch",
    "transferleaf",
]

# Default SONiC version
DEFAULT_SONIC_VERSION = "4.5.0"

# Port type to speed mapping (in Mbps)
PORT_TYPE_TO_SPEED_MAP = {
    # RJ45/BASE-T Types
    "100base-tx": 100,  # 100Mbps RJ45
    "1000base-t": 1000,  # 1G RJ45
    "2.5gbase-t": 2500,  # 2.5G RJ45
    "5gbase-t": 5000,  # 5G RJ45
    "10gbase-t": 10000,  # 10G RJ45
    # CX4
    "10gbase-cx4": 10000,  # 10G CX4
    # 1G Optical
    "1000base-x-gbic": 1000,  # 1G GBIC
    "1000base-x-sfp": 1000,  # 1G SFP
    # 10G Optical
    "10gbase-x-sfpp": 10000,  # 10G SFP+
    "10gbase-x-xfp": 10000,  # 10G XFP
    "10gbase-x-xenpak": 10000,  # 10G XENPAK
    "10gbase-x-x2": 10000,  # 10G X2
    # 25G Optical
    "25gbase-x-sfp28": 25000,  # 25G SFP28
    # 40G Optical
    "40gbase-x-qsfpp": 40000,  # 40G QSFP+
    # 50G Optical
    "50gbase-x-sfp28": 50000,  # 50G SFP28
    # 100G Optical
    "100gbase-x-cfp": 100000,  # 100G CFP
    "100gbase-x-cfp2": 100000,  # 100G CFP2
    "100gbase-x-cfp4": 100000,  # 100G CFP4
    "100gbase-x-cpak": 100000,  # 100G CPAK
    "100gbase-x-qsfp28": 100000,  # 100G QSFP28
    # 200G Optical
    "200gbase-x-cfp2": 200000,  # 200G CFP2
    "200gbase-x-qsfp56": 200000,  # 200G QSFP56
    # 400G Optical
    "400gbase-x-qsfpdd": 400000,  # 400G QSFP-DD
    "400gbase-x-osfp": 400000,  # 400G OSFP
    # Virtual interface
    "virtual": 0,  # Virtual interface (no physical speed)
}

# High speed ports that use 4x multiplier (lanes)
HIGH_SPEED_PORTS = {100000, 200000, 400000, 800000}  # 100G, 200G, 400G, 800G in Mbps

# Path to SONiC port configuration files
PORT_CONFIG_PATH = "/etc/sonic/port_config"

# List of supported HWSKUs
SUPPORTED_HWSKUS = [
    "Accton-AS4625-54T",
    "Accton-AS5835-54T",
    "Accton-AS5835-54X",
    "Accton-AS7326-56X",
    "Accton-AS7726-32X",
    "Accton-AS9716-32D",
]
