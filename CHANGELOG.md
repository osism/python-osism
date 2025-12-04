# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.20251202.0] - 2025-12-02

### Added
- New `osism migrate rabbitmq3to4` command to assist with RabbitMQ 3 to 4 migration, including subcommands for listing, deleting classic queues, checking migration status, and preparing the openstack vhost with quorum queue defaults
- New `osism status database` command to check MariaDB Galera Cluster status with extended metrics including flow control, transaction statistics, cluster member info, and general MariaDB metrics
- New `osism status messaging` command to check RabbitMQ Cluster status across all nodes with optional hostname filtering
- Support for `event.sample` queue pattern in ceilometer for the migrate command

### Changed
- Moved `validate database` and `validate messaging` commands to `status database` and `status messaging` respectively
- Extended `status messaging` command to check all RabbitMQ nodes instead of only the first one
- Listener queues now use RabbitMQ's configured default queue type instead of forcing classic queues, enabling compatibility with quorum queues in RabbitMQ 4
- Renamed generic queue pattern key to "notifications" in migrate command for clarity
- Refactored RabbitMQ connection code into shared `osism/utils/rabbitmq.py` module

### Fixed
- Improved migration detection in `migrate rabbitmq3to4 check` with vhost-specific queue counting for more accurate status reporting

## [v0.20251130.1] - 2025-11-30

### Fixed
- Sync versions command now correctly uses openstack_version from SBOM instead of CLI argument default value

## [v0.20251130.0] - 2025-11-30

### Added
- New `osism sync versions [kolla]` command for synchronizing Kolla version information from SBOM container images to the configuration repository
- Support for `--release` parameter to sync Kolla versions from a specific OSISM release by fetching version data from the release repository
- Configurable URLs for the release repository (`--release-repository-url`) and SBOM image base path (`--sbom-image-base`)
- Dry-run mode (`--dry-run`) for previewing version synchronization without writing files
- Skopeo dependency added to container image for extracting SBOM data without requiring Docker

### Changed
- Improved SBOM image path detection to properly handle release versions by stripping 'v' prefix from version tags and detecting date patterns (YYYYMMDD) in version strings

## [v0.20251128.0] - 2025-11-28

### Dependencies
- fastapi 0.121.3 → 0.122.0
- ghcr.io/astral-sh/uv 0.9.11 → 0.9.13
- openstack-flavor-manager 0.20251101.0 → 0.20251128.0
- openstack-image-manager 0.20251109.0 → 0.20251128.0
- openstacksdk 4.7.1 → 4.8.0
- sushy 5.8.0 → 5.9.0

## [v0.20251126.2] - 2025-11-26

### Added
- Periodic exchange discovery to connect to new exchanges dynamically in the listener service
  - Background thread checks for new exchanges every 60 seconds
  - Consumer restarts automatically when new exchanges are found
  - Discovery stops automatically once all configured exchanges are available

### Fixed
- RabbitMQ 4 compatibility by using passive exchange declarations
  - Listener now waits for OpenStack services to create exchanges instead of creating them itself
  - Prevents PRECONDITION_FAILED errors when listener starts before other services
  - Removed legacy fallback that could create exchanges with wrong properties

## [v0.20251126.1] - 2025-11-25

### Changed
- Reverted Redis/Celery reliability improvements that were introduced to prevent task loss, restoring previous simpler configuration

## [v0.20251126.0] - 2025-11-25

### Added
- Shared session management for NetBox connections to prevent file descriptor exhaustion
- Robust exception handling for NetBox tasks with timeout resilience (handles ConnectTimeout, Timeout, ConnectionError, RequestException)
- Redis/Celery reliability improvements with configurable options:
  - Visibility timeout (12h) to prevent task redelivery while running
  - Task acknowledgement after completion with requeue on worker crash
  - Broker heartbeat for faster connection problem detection
  - Exponential backoff retry for Redis client
  - Configurable task time limits (24h hard, 23h soft)
- New environment variables: CELERY_VISIBILITY_TIMEOUT, CELERY_BROKER_HEARTBEAT, CELERY_TASK_TIME_LIMIT, CELERY_TASK_SOFT_TIME_LIMIT, CELERY_BROKER_POOL_LIMIT, CELERY_REDIS_MAX_CONNECTIONS, REDIS_SOCKET_TIMEOUT, REDIS_SOCKET_CONNECT_TIMEOUT, REDIS_HEALTH_CHECK_INTERVAL

### Changed
- NetBox sync lock error handling now returns success/failure status and reports failed devices at sync completion
- Worker prefetch multiplier set to 1 to prevent task hoarding

### Fixed
- File descriptor exhaustion in NetBox connections by implementing NetBoxSessionManager with connection pooling
- TypeError in sync_ironic caused by missing request_id parameter in push_task_output calls
- Format strings missing f-prefix in lock acquisition error messages
- task_track_started configuration from tuple (True,) to boolean True

### Dependencies
- cliff 4.11.0 → 4.12.0
- fastapi 0.121.1 → 0.121.3
- netbox-manager 0.20251029.0 → 0.20251120.0
- sushy 5.7.1 → 5.8.0

## [v0.20251123.0] - 2025-11-23

### Added
- `--check` parameter for `sync netbox` command to test connectivity to all configured NetBox instances
- `--list` parameter for `sync netbox` command to display all configured NetBox instances
- API connectivity checks for `sync netbox` and `sync ironic` commands with early exit on failure
- Two-stage connectivity check for NetBox (reachability then authentication)
- Progress logging during NetBox connectivity checks
- Optional `NETBOX_NAME` and `NETBOX_SITE` metadata fields for secondary NetBox instances
- Redis-based semaphore for limiting concurrent NetBox connections (configurable via `NETBOX_MAX_CONNECTIONS`)
- Timeout support for NetBox API connections

### Changed
- Renamed `--netbox-filter` parameter to `--filter` with support for filtering by name, site, or URL
- Renamed `--force-update` parameter to `--force` for `sync ironic` command
- NetBox filter now applies to both primary and secondary instances before connectivity checks
- Improved error handling for NetBox state changes with unified locking and increased timeouts
- Convert Ironic power state `None` to `n/a` for clearer user feedback

### Fixed
- Race conditions in NetBox state changes with unified lock keys per device
- Missing imports and `TimeoutHTTPAdapter` class definition for NetBox connections

### Dependencies
- community.docker 4.8.2 → 5.0.2

## [v0.20251122.0] - 2025-11-22

### Added
- New `sync netbox` command to synchronize Ironic node states to NetBox with optional URL filtering via `--netbox-filter` parameter
- `ensure_known_hosts_file()` utility function in `osism/utils/ssh.py` to automatically create `/share/known_hosts` file if missing

### Changed
- Split `sync ironic` command into two separate commands: `sync ironic` (NetBox → Ironic) and `sync netbox` (Ironic → NetBox)
- Renamed `netbox show` command to `netbox dump`
- Limit Ansible Vault decryption to Custom Fields only in sync ironic instead of all node attributes

### Fixed
- Missing `/share/known_hosts` initialization in SSH commands causing failures in new installations
- Strip whitespace from NETBOX_TOKEN to prevent authentication issues

### Removed
- `--flush-cache` parameter from inventory reconciler sync command

### Dependencies
- ghcr.io/astral-sh/uv 0.9.7 → 0.9.11

## [v0.20251120.0] - 2025-11-19

### Added
- New `baremetal clean` command to erase storage devices on baremetal nodes
- New `baremetal provide` command to move nodes from manageable to available state
- `--all` parameter for `baremetal clean` command with `--yes-i-really-really-mean-it` safety confirmation
- `--all` parameter for `baremetal provide` command to process all manageable nodes
- Device Role column to `baremetal list` command output, fetched from NetBox

## [v0.20251115.0] - 2025-11-15

### Added
- `--ironic` parameter to `baremetal dump` command to show actual deployment state from Ironic instead of NetBox, enabling comparison between planned and deployed configurations

### Changed
- Updated gardenlinux from 1877.6 to 1877.7
- Moved redfish dependency from Containerfile to project requirements

### Dependencies
- openstack-image-manager v0.20251020.0 → v0.20251109.0
- redfish 3.3.3 → 3.3.4 (now in project requirements)
- cachetools 6.2.1 → 6.2.2
- certifi 2025.10.5 → 2025.11.12
- prettytable 3.16.0 → 3.17.0
- pynacl 1.6.0 → 1.6.1
- pytest 9.0.0 → 9.0.1

## [v0.20251110.0] - 2025-11-10

### Added
- New `osism netbox show` command for displaying device information from NetBox with support for custom field parameters and field filtering
- Device Role column to `sonic list` command output for better visibility into switch roles
- VRF support to SONiC configuration generator including VRF table extraction and interface/port channel assignments
- `sonic dump` command to output NetBox config context as JSON for a specified SONiC switch
- `baremetal dump` command to output deployment playbook for a given baremetal node
- BGP configuration for VLAN interfaces with FHRP (First Hop Redundancy Protocol) support
- Detection of untagged VLAN members to route BGP peering over VLAN interfaces instead of physical interfaces

### Changed
- Refactored Collections definitions in `osism/data/enums.py` to use Role class instead of nested lists for improved readability and maintainability
- Provision state in `sonic list` now reads from NetBox custom field instead of deriving from device status
- Updated supported Garden Linux version from 1877.2 to 1877.6
- Physical interfaces that are untagged VLAN members are now excluded from BGP_NEIGHBOR and BGP_NEIGHBOR_AF configurations

### Fixed
- SONiC 400G to 4x100G breakout detection for SONiC format interfaces (Ethernet0, Ethernet2, Ethernet4, Ethernet6)

### Dependencies
- jc 1.25.5 → 1.25.6

## [v0.20251104.0] - 2025-11-04

### Added
- Cloudpod flavors to the manage flavors command
- Automatic `kolla_action_stop_ignore_missing=true` for kolla-ansible stop actions

### Dependencies
- community.docker 4.8.1 → 4.8.2
- fastapi 0.119.1 → 0.120.4
- huey 2.5.3 → 2.5.4
- netbox-manager 0.20250915.0 → 0.20251029.0
- openstack-flavor-manager 0.20251021.0 → 0.20251101.0
- uv 0.9.4 → 0.9.7

## [v0.20251101.0] - 2025-11-01

### Dependencies
- eslint 9.34.0 → 9.39.0
