# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.20251208.0] - 2025-12-08

### Changed
- Add `--stuck-retry 1` to all openstack-image-manager calls to reduce temporary issues with the Hetzner Objectstore by automatically retrying stuck image downloads

### Dependencies
- fastapi 0.123.0 → 0.124.8

## [v0.20251205.0] - 2025-12-05

### Added
- `manage server clean` command for cleaning up problematic servers (stuck in BUILD status for more than 2 hours or in ERROR status)
- `manage loadbalancer list` command to list loadbalancers with PENDING_CREATE, PENDING_UPDATE, ERROR provisioning status or ERROR operating status
- `manage loadbalancer reset` command to reset loadbalancers stuck in PENDING_UPDATE or ERROR status and trigger failover
- `manage loadbalancer delete` command to delete loadbalancers stuck in PENDING_CREATE status
- `manage amphora restore` command to restore amphorae in ERROR state by triggering failover
- `manage amphora rotate` command to rotate amphorae older than 30 days by triggering loadbalancer failover
- `manage volume repair` command to repair volumes stuck in DETACHING, CREATING, ERROR_DELETING, or DELETING states
- Magnum and Manila queue patterns to RabbitMQ 3 to 4 migration command (magnum-conductor, manila-data, manila-scheduler, manila-share)
- `--cloud` parameter to `manage server list`, `manage server clean`, `manage server migrate`, and `manage volume list` commands for consistent OpenStack connection handling
- Initial CHANGELOG.md with history of notable changes

### Changed
- Manage commands now use `setup_cloud_environment()` and `cleanup_cloud_environment()` for OpenStack connections, ensuring proper cloud configuration with secure credential handling from vault
- SONiC port speed override now distinguishes between explicitly set NetBox speeds (always takes precedence) and derived speeds from port type (only used if port config has no speed)
- NetBox speed values are now properly converted from kbps to Mbps for SONiC configuration
- Migration check command now dynamically discovers all vhosts from queue data instead of hardcoding "/" and "/openstack"

### Fixed
- SONiC port speed override when explicitly set in NetBox was being ignored when port config file had a speed configured
- Queue count display in migrate check showing incorrect counts when queues existed in vhosts other than "/" and "/openstack"

### Removed
- Changelog generation script moved to osism/release repository

### Dependencies
- celery 5.5.3 → 5.6.0
- community.docker 5.0.2 → 5.0.3
- fastapi 0.122.0 → 0.123.8
- ghcr.io/astral-sh/uv 0.9.13 → 0.9.15
- kombu 5.5.4 → 5.6.1
- openstack-image-manager 0.20251128.0 → 0.20251201.0

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

## [v0.20251029.0] - 2025-10-29

### Added
- Support for custom CONFIG DB VERSION override via `config_version` in `sonic_parameters` custom field

### Changed
- Port speed is now used as fallback for `valid_speeds` when not configured in port config
- Optimized SONIC configuration generation performance by eliminating N+1 query problems and implementing bulk fetching strategies
- Further optimized SONIC configuration generation with global caches for metalbox devices and VIP addresses

### Fixed
- Validation of 6th column in port config to prevent non-numeric values (like autoneg on/off) from being incorrectly parsed as valid_speeds

## [v0.20251026.0] - 2025-10-26

### Fixed
- AS4625-54T port detection now correctly extracts port numbers from alias format `Eth1(Port1)` using the existing `_extract_port_number_from_alias()` helper function instead of an inline regex that failed on non-standard alias formats

## [v0.20251022.0] - 2025-10-22

### Added
- Configurable Celery worker concurrency via `OSISM_CELERY_CONCURRENCY` environment variable with intelligent default based on CPU count (min of cpu_count, 4)
- Support for 400G to 4x100G breakout ports with 8 lanes in SONiC configuration
- Support for unencrypted secrets.yml files as development mode fallback

## [v0.20251021.0] - 2025-10-21

### Added
- `sync ceph-keys` command for synchronizing Ceph keys
- `--create-application-credential` / `--nocreate-application-credential` parameter to project create command
- Cloudpod flavor definitions

### Changed
- Use new object storage URL (`nbg1.your-objectstorage.com/osism`) for Cluster API, Gardener, Gardenlinux, and Octavia image management
- Use `registry.osism.cloud` cache for container base image
- Sync ironic maintenance state unconditionally with all netboxes during ironic sync to prevent inconsistencies

### Dependencies
- ansible-runner 2.4.1 → 2.4.2
- fastapi 0.118.0 → 0.119.1
- ghcr.io/astral-sh/uv 0.8.23 → 0.9.4
- hiredis 3.2.1 → 3.3.0
- openstack-flavor-manager 0.20250918.0 → 0.20251021.0
- openstack-image-manager 0.20250912.0 → 0.20251020.0
- sqlmodel 0.0.25 → 0.0.27
- uvicorn 0.37.0 → 0.38.0

## [v0.20251012.0] - 2025-10-12

### Added
- Cloudpod collections (cloudpod-infrastructure, cloudpod-openstack, cloudpod-ceph) for deployment orchestration
- `--show-tree` parameter to the apply command to display execution tree for collections without additional output
- Command to manage special ClusterAPI Gardener images (`manage image clusterapi gardener`)
- `--user` and `--user-domain` parameters to server list command to filter servers by user
- Additional ID columns (User ID, Domain, Project ID) to server list command output based on filter flags
- OpenStack stress testing command (`openstack stress`)
- Project management commands (`manage project create` and `manage project sync`)

### Changed
- Octavia deployment now waits for Nova deployment to complete
- Updated supported ClusterAPI Kubernetes images from 1.31, 1.32, 1.33 to 1.32, 1.33, 1.34

### Fixed
- Removed duplicate designate entry from cloudpod-openstack collection

### Dependencies
- ansible-core 2.19.2 → 2.19.3
- community.docker 4.8.0 → 4.8.1
- ghcr.io/astral-sh/uv 0.8.22 → 0.8.23

## [v0.20251004.0] - 2025-10-04

### Added
- Arguments field to ansible execution tracking for capturing ansible-playbook command-line arguments in execution log records
- Host extraction from Ansible output using regex pattern matching for complete audit trail

### Changed
- Ansible execution logging now includes command-line arguments passed to ansible-playbook
- Host list in execution records is now populated from actual Ansible output instead of empty placeholder

### Dependencies
- community.docker 4.7.0 → 4.8.0

## [v0.20251003.0] - 2025-10-03

### Changed
- Track all Ansible play executions in `/share/ansible-execution-history.json` with timestamp, runtime version, hosts, and result status

### Dependencies
- axios 1.11.0 → 1.12.2
- fastapi 0.116.2 → 0.118.0
- ghcr.io/astral-sh/uv 0.8.18 → 0.8.22
- paramiko 3.5.1 → 4.0.0
- pyyaml 6.0.2 → 6.0.3
- uvicorn 0.35.0 → 0.37.0

## [v0.20250919.0] - 2025-09-19

### Changed
- Add os_purpose to image template metadata

### Dependencies
- fastapi 0.116.1 → 0.116.2
- ghcr.io/astral-sh/uv 0.8.17 → 0.8.18
- netbox-manager 0.20250825.0 → 0.20250915.0
- openstack-flavor-manager 0.20250912.0 → 0.20250918.0
- sqlmodel 0.0.24 → 0.0.25

## [v0.20250914.0] - 2025-09-14

### Added
- Accton-AS9726-32D to list of supported SONiC HWSKUs

### Changed
- Ubuntu CAPI image management now supports current, past and future Ubuntu LTS versions (regex pattern updated to match all even-numbered Ubuntu versions)

### Dependencies
- actions/setup-python v5 → v6
- ansible-core 2.19.1 → 2.19.2
- deepdiff 8.6.0 → 8.6.1
- ghcr.io/astral-sh/uv 0.8.13 → 0.8.17
- openstack-flavor-manager 0.20250827.0 → 0.20250912.0
- openstack-image-manager 0.20250827.0 → 0.20250912.0
- openstacksdk 4.7.0 → 4.7.1
- redfish 3.3.1 → 3.3.3

## [v0.20250902.0] - 2025-09-02

### Added
- Pagination to nodes page with 10 items per page, Previous/Next navigation, smart page number display with ellipsis, and auto-reset to page 1 when filters change

### Fixed
- Missing `check_task_lock_and_exit` function in conductor utils that caused AttributeError in `osism.tasks.conductor.sync_ironic` task

### Dependencies
- lucide-react 0.541.0 → 0.542.0

## [v0.20250827.0] - 2025-08-27

### Added
- Cloud profile password support to image manager with automatic loading from encrypted secrets.yml
- Garden Linux image management command (`osism manage image gardenlinux`)
- Local flavor definitions file with SCS mandatory flavors
- Task lock/unlock functionality to prevent new task execution with `osism lock`, `osism unlock`, and `osism lock status` commands
- Redis-based task locking mechanism with metadata storage (user, timestamp, reason)
- Lock checks at all main Celery task entry points and worker startup
- Command-level lock checks for immediate user feedback when tasks are locked

### Changed
- Cloud authentication now uses file-based approach with temporary secure.yml instead of environment variables
- Extracted cloud configuration logic into reusable helper functions for OpenStack tasks
- Applied cloud authentication to flavor_manager task
- Default flavor definitions changed from 'scs' to 'local'
- Default lock user changed from current system user to "dragon"
- Added *.swp to .gitignore

### Fixed
- Password values are now properly converted to strings in cloud authentication
- Garden Linux image build date handling uses actual dates instead of null placeholder
- Removed leftover ignore_env parameter from ImageOctavia command

### Dependencies
- openstack-image-manager 0.20250508.0 → 0.20250827.0
- openstack-flavor-manager 0.20250413.0 → 0.20250827.0
- prompt-toolkit 3.0.51 → 3.0.52
- @types/react 19.1.11 → 19.1.12
- @types/react-dom 19.1.7 → 19.1.8

## [v0.20250826.0] - 2025-08-26

### Changed
- Migrate Renovate config from `fileMatch` to `managerFilePatterns`

### Fixed
- Alignment in the baremetal nodes table in the frontend

### Dependencies
- ansible-core 2.19.0 → 2.19.1
- ara 1.7.2 → 1.7.3
- netbox-manager 0.20250823.0 → 0.20250825.0
- @types/node 22.17.2 → 22.18.0

I'll now create the merged changelog entry based on the batch provided:

## [v0.20250824.1] - 2025-08-24

### Added
- Name-based sorting with reversible direction (A-Z/Z-A) for the nodes list in frontend
- Created_at and updated_at timestamp display in baremetal nodes list

### Changed
- Improved baremetal nodes layout using CSS Grid for consistent column alignment
- Moved Power and Provision status badges to header row (right-aligned)
- Removed resource class field from node information display

### Fixed
- Baremetal node IDs now correctly use attribute access for OpenStack SDK Resource objects instead of dict access

## [v0.20250824.0] - 2025-08-24

### Added
- Real-time Events tab with Redis-based event streaming for Baremetal events
- WebSocket endpoint `/v1/events/openstack` for real-time streaming of all OpenStack events
- WebSocket connection manager with support for event filtering by service type, event type, and resource name
- WebSocket connection with custom useWebSocket hook for event streaming
- RabbitMQ listener support for multiple OpenStack services (Nova, Neutron, Cinder, Glance, Keystone, Ironic)
- Real-time event broadcasting from RabbitMQ notifications to WebSocket clients
- Redis-based event bridge for cross-container communication
- Event filtering by event types and node names
- UI components for events: EventsList, EventsFilters, ConnectionStatus
- Event pause/resume, auto-reconnection, and live event counters
- TypeScript types for OpenStack and Baremetal events
- WebSocket CORS headers and Redis pub/sub integration
- Maintenance state filter (All/Active/Maintenance) to baremetal nodes page
- Health check endpoint at `/api/health` for frontend service
- Runtime configuration endpoint at `/api/config` for dynamic environment variable reading

### Changed
- Default API URL for frontend changed from `http://localhost:8000` to `http://api:8000`
- Frontend API URL environment variable renamed from `NEXT_PUBLIC_API_URL` to `NEXT_PUBLIC_OSISM_API_URL`
- Frontend now supports runtime API URL configuration via `/api/config` endpoint
- Node.js base image updated from v18 to v22 in frontend Containerfile
- PostCSS configuration updated to use `@tailwindcss/postcss` plugin (preparation for Tailwind CSS 4)

### Fixed
- Made `uuid` and `maintenance` fields optional in BaremetalNode model to handle incomplete data
- Improved null safety in node search filtering logic to prevent client-side errors

### Removed
- Recent Nodes section from frontend landing page

### Dependencies
- @tailwindcss/postcss 4.1.12 (new)
- @tanstack/react-query 5.84.2 → 5.85.5
- @types/node 20.19.10 → 22.17.2
- @types/react 19.1.9 → 19.1.11
- date-fns 4.1.0 (new)
- eslint 9.33.0 → 9.34.0
- eslint-config-next 15.4.6 → 15.5.0
- lucide-react 0.539.0 → 0.541.0
- next 15.4.6 → 15.5.0
- tailwindcss 3.4.17 → 4.0.0
- websockets 15.0.1 (new)

## [v0.20250823.0] - 2025-08-23

### Added
- IPv4 address support for SONiC switch port configuration with automatic address assignment from NetBox
- `manage baremetal burnin` command to trigger burn-in of baremetal nodes with CPU, memory, and disk stress tests
- `baremetal burnin` alias command for convenience
- `manage baremetal maintenance set` and `manage baremetal maintenance unset` commands
- Support for "clean failed" state in Ironic sync to recover nodes from failed burn-in
- 4x10G breakout mode for SONiC interface configuration
- `/v1/baremetal/nodes` API endpoint returning all Ironic-managed baremetal nodes
- Transfer role IPv4 interfaces included in BGP neighbor configuration with dual-stack support
- Next.js frontend application with dashboard, nodes, and services pages, including API integration and Docker configuration

### Changed
- SONiC IPv4 interface configuration now uses proper scope and family parameters instead of admin_status
- Output of `openstack.baremetal_node_list` task returns full node objects instead of formatted dict
- BGP detection excludes interfaces with direct IPv4 addresses (non-transfer role)
- BGP neighbor configuration sets v6only=false for transfer role IPv4 interfaces
- Skip ipv6_unicast BGP configuration for transfer role IPv4 interfaces
- Reverted support for multiple IPv4 addresses per interface in NetBox integration, returning to single IPv4 address behavior

### Fixed
- Generated SONiC configuration now includes VERSION database entry and base interface entries
- NETBOX_TOKEN is now always converted to string type to prevent type errors
- Port speed detection for 4x25G breakout mode (was incorrectly checking for 50000 instead of 25000)

### Dependencies
- cliff 4.10.0 → 4.11.0
- community.docker 4.6.2 → 4.7.0
- keystoneauth1 5.11.1 → 5.12.0
- netbox-manager 0.20250803.0 → 0.20250823.0
- react 19.1.0 → 19.1.1
- react-dom 19.1.0 → 19.1.1
- sushy 5.7.0 → 5.7.1
- uv 0.8.4 → 0.8.13

## [v0.20250804.0] - 2025-08-04

### Added
- `osism baremetal deploy` command for deploying baremetal infrastructure
- `osism baremetal list` command for listing baremetal nodes
- `osism baremetal ping` command for connectivity testing
- `osism baremetal undeploy` command for removing baremetal deployments
- `osism sonic list` command to display SONiC switches with name, OOB IP, primary IP, HWSKU, version, and provision state

### Changed
- Centralize SSH known_hosts file management to `/share/known_hosts` across compose, console, container, log, and sonic commands
- Filter out underscore-prefixed keys in SONiC device configuration context
- Use psql table format for `sonic list` command output

### Fixed
- Remove duplicate SSH known_hosts cleanup log messages
- ssh-keygen availability check that failed with exit code 1 due to `ssh-keygen --help` returning non-zero

### Dependencies
- netbox-manager 0.20250622.1 → 0.20250803.0

## [v0.20250709.0] - 2025-07-09

### Added
- SONiC ZTP (Zero Touch Provisioning) command for status check, enable, and disable operations
- SONiC reboot command for remotely rebooting switches
- SONiC factory reset command using ONIE uninstall mode with safety confirmation
- SONiC show command for executing arbitrary show commands on switches
- SONiC console command for interactive SSH access to switches
- SONiC backup command for configuration backup without modifications
- SONiC load command to load configuration without service restart
- SONiC reload command to load configuration with service restart
- Unified Metalbox IP lookup for DNS and NTP server configuration in SONiC
- DNS_NAMESERVER configuration support for SONiC switches
- Automatic provision_state update to 'ztp' in NetBox after SONiC factory reset

### Changed
- Refactor sonic command to dedicated module (`osism.commands.sonic`)
- Refactor sonic commands into separate `load` and `reload` subcommands for better clarity
- Renamed `manage sonic` commands to `sonic` (e.g., `osism manage sonic backup` → `osism sonic backup`)
- Renamed API endpoint `/v1/switches` to `/v1/sonic`
- ZTP command now uses positional action argument (`status`, `enable`, `disable`) instead of `--enable`/`--disable` flags
- ZTP status check now uses `show ztp status` instead of `sudo config ztp status`
- Show command parameter is now optional to display available commands when omitted
- Centralize Redlock creation with output suppression via new `utils.create_redlock()` method
- Improve pottery logger output suppression in `create_redlock` by setting logger level to CRITICAL
- Suppressed paramiko logging messages in sonic commands

### Dependencies
- cryptography 45.0.4 → 45.0.5
- fastapi 0.115.14 → 0.116.0
- ghcr.io/astral-sh/uv 0.7.17 → 0.7.19
- transitions 0.9.2 → 0.9.3

## [v0.20250701.0] - 2025-07-01

### Added
- Redfish management command `osism manage redfish list` supporting EthernetInterfaces, NetworkAdapters, and NetworkDeviceFunctions resource types
- Configurable Redfish connection timeout via `REDFISH_TIMEOUT` environment variable
- Script `redfishMockupCreate.py` for creating Redfish mockups from live systems
- `--format` parameter to `osism manage redfish list` command supporting table (default) and JSON output formats
- `--column` parameter to `osism manage redfish list` command for dynamic column selection in both table and JSON output
- Integrated NetBox local_context_data as default variables in baremetal playbook generation
- Added osism.commons.operator role to baremetal bootstrap playbook

### Changed
- Refactored `sync_ironic` by extracting node attributes preparation into separate `_prepare_node_attributes` method
- Improved error handling in conductor configuration when resolving image and network IDs
- Simplified Redfish EthernetInterfaces output by removing unused fields (full_duplex, auto_neg, vlan, vlans, state)
- Removed status column from redfish list output for network adapters and device functions
- Refactored redfish column filtering with centralized column mapping management
- Skip UUID resolution for image URLs in conductor configuration, allowing external HTTP image sources for Ironic deployments

### Fixed
- Improved error handling in `_get_network_device_functions` for NetworkAdapter processing
- Removed redundant instance_info restore during baremetal undeploy

### Dependencies
- ghcr.io/astral-sh/uv 0.7.16 → 0.7.17
- redfish 3.3.1 (new)
- validators 0.35.0 (new)

## [v0.20250628.0] - 2025-06-28

### Changed
- Refactored API endpoints with proper error handling, HTTP exception handling, Pydantic Field descriptions, and OpenAPI documentation
- Extracted device search logic into reusable `find_device_by_identifier` function in API
- Added structured logging configuration with proper logger hierarchy for API server
- Configured CORS middleware with specific allowed methods and headers
- Moved `playbooks.py` and `enums.py` from `osism.core` to `osism.data` package

### Fixed
- Fixed TypeError in `switches_ztp_complete` by converting RecordSet to list before indexing

### Removed
- Removed unused `osism/actions` module
- Removed unused `osism/plugins` module
- Removed `osism/core` package (moved contents to `osism/data`)

### Dependencies
- uvicorn 0.34.3 → 0.35.0
- ghcr.io/astral-sh/uv 0.7.15 → 0.7.16

## [v0.20250627.0] - 2025-06-27

### Added
- New `manage sonic` command for SONiC switch configuration management via SSH
- Support for Eth(Port) alias format in SONiC port alias mapping (e.g., Eth1(Port1) → Ethernet0)
- Accton-AS4625-54T to supported SONiC HWSKUs list
- POST `/v1/switches/{identifier}/ztp/complete` endpoint for SONiC ZTP completion with provision state update
- Global NTP parameters configuration for SONiC switches
- Device-specific NTP server assignment for SONiC switches based on OOB network connection
- Breakout owner and port metadata fields to SONiC breakout port configurations
- `--flush-cache` parameter to `osism sync inventory` command to force cache flush during synchronization

### Changed
- API endpoints now include `/v1` prefix (e.g., `/meters/sink` → `/v1/meters/sink`)
- SONiC interface to alias conversion now uses port config for accurate alias generation
- Replace HWSKU with serial number as identifier in `/v1/switches/{identifier}/ztp/complete` endpoint for simpler device lookup
- Remove loopback BGP neighbors from SONiC configuration generation to prevent routing issues

### Fixed
- SONiC port channel peer type detection for single device configurations now correctly identifies internal peers
- SONiC spine group detection for single device config generation now considers all spine/superspine devices
- Baremetal ports are now always created during Ironic sync, not only for PXE boot interfaces

### Removed
- netmiko dependency (no longer needed)

### Dependencies
- ghcr.io/astral-sh/uv 0.7.13 → 0.7.15
- netbox-manager 0.20250621.0 → 0.20250622.1
- paramiko 3.5.0 → 3.5.1
- fastapi 0.115.13 → 0.115.14

## [v0.20250621.0] - 2025-06-21

### Added
- Save instance_info on baremetal undeploy to preserve deployment parameters
- Maintenance mode detection to baremetal deploy command
- `manage dnsmasq` command to apply dnsmasq role in infrastructure environment
- `manage ironic` and `manage sonic` command aliases for sync operations
- Device-specific sync support to SONiC sync command (`osism sync sonic <device>`)
- `--diff/--no-diff` parameter to SONiC sync command to show configuration differences
- First-time configuration hints to SONiC sync output when no previous config exists
- Real-time device progress output to SONiC sync command
- Diff checking to SONiC configuration export functions with detailed logging
- Configuration diff saved to NetBox device journal when changes are detected
- Hostname symlinks when exporting SONiC configurations with serial number identifiers
- Configurable identifier (hostname or serial number) for SONiC ZTP export file naming via SONIC_EXPORT_IDENTIFIER setting
- Accton-AS5835-54X port configuration for SONiC
- Optional valid_speeds column support for SONiC port configuration files
- Management interfaces (mgmtTenGigE) to Accton-AS7326-56X and Accton-AS7726-32X port configs
- Management interfaces (tenGigE33/34) to Accton-AS9716-32D port config
- ZTP mode configuration (inband/out-of-band, IPv4/IPv6) to default SONiC config
- TELEMETRY gnmi section to default SONiC config
- MGMT_PORT eth0 configuration to default SONiC config
- ROUTE_REDISTRIBUTE configuration for connected routes to BGP
- Superspine device role to supported SONiC device roles
- Group-based AS calculation for interconnected spine/superspine switches using BFS algorithm
- Port channel (LAG) support to SONiC configuration generation with PORTCHANNEL, PORTCHANNEL_INTERFACE, and PORTCHANNEL_MEMBER sections
- InterfaceCache class with thread-local storage for device interfaces in SONiC configuration
- Device-specific port configuration mapping for interface name conversion
- Global caching for NTP servers and port configurations to reduce API calls
- Comprehensive breakout port detection and handling with device-specific logic
- Cache management functions for clearing caches during sync operations
- New `connections.py` module with centralized connection detection helpers for SONiC
- Port Channel device support to SONiC peer type detection

### Changed
- Refactor SONiC conductor module into modular subdirectory structure with separate files for constants, device helpers, interface conversion, BGP, config generation, exporting, and sync operations
- SONiC configuration storage from config context to device local context in NetBox
- Configuration files are now only written when content has actually changed
- Refactored SONiC connection detection to use NetBox's connected_endpoints API instead of legacy cable-based detection
- SONiC export identifier default changed from hostname to serial-number
- BGP neighbors are now configured on port channel interfaces instead of individual member interfaces
- Set BGP peer_type to internal for neighbors with matching AS numbers (enables automatic iBGP vs eBGP detection)
- Set BGP `always_compare_med` to true in base SONiC configuration
- Add `intf_naming_mode: standard` to SONiC device metadata configuration
- Add `default_config_profile` and `frr_mgmt_framework_config` to DEVICE_METADATA
- BGP max_ebgp_paths and max_ibgp_paths increased from 1 to 2 in default SONiC config
- Added ibgp_equal_cluster_length setting to BGP address families
- SONiC port channel fast_rate setting from "false" to "true" for improved LACP convergence
- Sorted and reorganized keys in `files/sonic/config_db.json`
- Moved static DEVICE_METADATA to `files/sonic/config_db.json`
- Updated Accton-AS5835-54T port config with valid_speeds column and corrected index values
- Updated Accton-AS7326-56X port config with valid_speeds column, 0-based indexing, and corrected alias naming
- Updated Accton-AS7726-32X port config with valid_speeds column
- Updated Accton-AS9716-32D port config with valid_speeds and fec columns

### Removed
- SONiC database version configuration (VERSIONS.DATABASE) from generated config
- REQUIRED_CONFIG_SECTIONS constant from SONiC conductor (sections are now handled dynamically)

### Dependencies
- deepdiff (new dependency for configuration comparison)
- fastapi 0.115.12 → 0.115.13
- netbox-manager 0.20250529.1 → 0.20250621.0

## [v0.20250616.0] - 2025-06-16

### Added
- New `sync sonic` command for SONiC configuration preparation
- SONiC port configuration files for Edgecore switches:
  - Accton-AS5835-54T (48x10G + 6x100G ports)
  - Accton-AS7326-56X (48x25G + 8x100G ports)
  - Accton-AS7726-32X (32x100G ports)
  - Accton-AS9716-32D (32x400G ports)
- `get_port_config` method for parsing SONiC HWSKU configuration files
- Task output streaming to ironic sync command with `--task-timeout` option
- SONiC device filtering based on NETBOX_FILTER_CONDUCTOR_SONIC, device roles, 'managed-by-osism' tag, and HWSKU configuration
- SONiC config.json generation with DEVICE_METADATA, PORT, LOOPBACK, and FEATURE sections
- Helper functions for device metadata extraction (platform, hostname, MAC address)
- SONiC version support with DEFAULT_SONIC_VERSION constant and VERSIONS section
- NetBox config context storage for generated SONiC configurations
- Dynamic admin_status based on interface cable connections in NetBox
- Management interface (eth0) configuration with OOB IP address
- Comprehensive VLAN configuration support including VLAN, VLAN_MEMBER, and VLAN_INTERFACE sections
- Support for tagged/untagged VLANs and VLAN interfaces (SVIs) with multiple IP addresses
- Loopback interface configuration generation from NetBox virtual interfaces with IPv4/IPv6 support
- NetBox to SONiC interface name conversion with speed-based port multipliers
- Breakout port support with automatic detection and BREAKOUT_CFG/BREAKOUT_PORTS generation
- Base configuration template support using /etc/sonic/config_db.json
- IPv6 link-local only mode configuration for connected non-management interfaces
- BGP configuration support:
  - BGP_GLOBALS with router_id from device primary IP
  - Automatic local ASN calculation from IPv4 addresses
  - BGP_GLOBALS_AF_NETWORK for Loopback0 devices
  - BGP_NEIGHBOR for connected interfaces with external peer type
  - Dual BGP neighbor configuration with interface-based and IP-based entries
  - Address family configuration for IPv4 and IPv6 unicast
- Port type to speed mapping covering RJ45, optical, CX4, and virtual types (100Mbps to 400Gbps)
- Default port parameters (adv_speeds, autoneg, link_training, unreliable_los)
- NTP_SERVER configuration from manager and metalbox devices
- SONiC configuration export to local files with configurable directory, prefix, and suffix
- Bootstrap playbook generation for baremetal node config drives

### Changed
- Refactored task output streaming into helper functions in `osism.utils` (`fetch_task_output`, `push_task_output`, `finish_task_output`)
- Standardized "NetBox" capitalization in comments and logging messages
- Refactored SONiC functionality into dedicated sonic.py module
- PORT entries in SONiC configuration are now naturally sorted
- Extracted get_device_oob_ip() to shared netbox.py module
- Renamed `NETBOX_FILTER_CONDUCTOR` to `NETBOX_FILTER_CONDUCTOR_IRONIC` for clarity
- Renamed `get_nb_device_query_list()` to `get_nb_device_query_list_ironic()` for consistency
- SONiC configuration generation now preserves existing config_db.json sections
- Management-only interfaces are now excluded from connected interface detection
- SONiC port aliases now use correct NetBox-style notation based on port speed and breakout status

### Fixed
- Use device.role instead of device.device_role for NetBox API compatibility
- DEFAULT_SONIC_ROLES names corrected to match NetBox slug format
- NetBox oob_ip usage to handle direct CIDR notation return value from pynetbox

### Dependencies
- community.docker 4.6.0 → 4.6.1
- ghcr.io/astral-sh/uv 0.7.11 → 0.7.13
- keystoneauth1 5.11.0 → 5.11.1
- kubernetes 32.0.1 → 33.1.0
- cdrkit added to container image for config drive generation

## [v0.20250605.0] - 2025-06-05

### Added
- Validate docker version command for checking Docker versions across nodes
- STDIN support for vault password set command, enabling piping passwords directly (e.g., `echo password | osism vault password set`)
- Templating support for Ironic driver passwords from NetBox secrets using `remote_board_password`
- Templating support for Ironic driver usernames from NetBox secrets using `remote_board_username`
- Resolution of `image_source` names to UUIDs in conductor config, following the same pattern as deploy_kernel and deploy_ramdisk

### Changed
- Refactored conductor.py into smaller focused modules (config.py, netbox.py, ironic.py, utils.py) for better maintainability
- **BREAKING:** Baremetal deploy/undeploy commands now use positional arguments instead of `--name` parameter (e.g., `osism baremetal deploy <node>` instead of `osism baremetal deploy --name <node>`)
- Image name to UUID conversion in conductor config now skips values that are already valid UUIDs, reducing unnecessary API calls

### Fixed
- AttributeError when NetBox device secrets field is None
- deep_decrypt now properly handles None values and list/array structures

### Dependencies
- ghcr.io/astral-sh/uv 0.7.9 → 0.7.11
- openstacksdk 4.5.0 → 4.6.0

## [v0.20250602.0] - 2025-06-02

### Changed
- Reduce the reconciler sync timeout to 300 seconds
- Allow to change task timeout via OSISM_TASK_TIMEOUT environment variable
- Suppress "Registering Redlock" log messages during Ansible task locking

### Dependencies
- celery 5.5.2 → 5.5.3
- kombu 5.5.3 → 5.5.4
- uvicorn 0.34.2 → 0.34.3
- ghcr.io/astral-sh/uv 0.7.8 → 0.7.9

## [v0.20250530.0] - 2025-05-30

### Added
- Command to list baremetal nodes (`manage baremetal list`)
- Command to deploy baremetal nodes (`manage baremetal deploy`)
- Command to undeploy baremetal nodes (`manage baremetal undeploy`)
- Metadata (netplan_parameters, frr_parameters) to baremetal node sync from NetBox
- NetBox task to get addresses by device and interface

### Changed
- NetBox manage command now uses the netbox-manager's new 'run' subcommand

### Fixed
- Typo in baremetal deploy/undeploy confirmation messages

### Dependencies
- netbox-manager 0.20250525.0 → 0.20250529.1
- setuptools 80.8.0 → 80.9.0

## [v0.20250525.0] - 2025-05-25

### Added
- Cold migration support for `osism manage compute migrate` command, automatically migrating instances in SHUTOFF state with automatic resize confirmation
- New `--no-cold-migration` parameter to skip cold migration and preserve previous behavior
- New `osism manage compute migration list` command to list and filter migrations by host, server, user, project, status, type, and date range
- New `sync netbox` command (placeholder for future implementation)

### Changed
- Renamed internal task `sync_netbox_with_ironic` to `sync_ironic` for clarity
- Renamed `NETBOX_FILTER_LIST` to `NETBOX_FILTER_CONDUCTOR` for configuration clarity
- Updated warning in `--no-wait` parameter description to note that cold migrated instance resizes will not be confirmed
- Improved migration status messages to show migration type (live/cold)
- Add Redis locks to prevent duplicate periodic task registration when multiple workers start up
- Make periodic inventory reconciler configurable (set `INVENTORY_RECONCILER_SCHEDULE = 0` to disable)
- Make periodic ansible facts gathering configurable (set `GATHER_FACTS_SCHEDULE = 0` to disable)
- Add missing type annotations to LogConfig in API module
- Cleanup ansible requirements, removing unused collections

### Removed
- pydantic from direct requirements (now pulled in as transitive dependency)

### Dependencies
- ansible-core 2.18.5 → 2.18.6
- cliff 4.9.1 → 4.10.0
- cloud.common 4.0.0 → 4.1.0
- community.general 10.6.0 → 10.7.0
- ghcr.io/astral-sh/uv 0.7.6 → 0.7.8
- hiredis 3.1.1 → 3.2.1
- keystoneauth1 5.10.0 → 5.11.0
- kubernetes.core 5.2.0 → 5.3.0
- netbox-manager 0.20250508.0 → 0.20250525.0
- pydantic 1.10.22 → 2.11.4
- pynetbox 7.4.1 → 7.5.0
- setuptools 80.4.0 → 80.8.0
- sqlalchemy 2.0.40 → 2.0.41
- sushy 5.5.0 → 5.6.0
- uv 0.7.3 → 0.7.8

## [v0.20250514.0] - 2025-05-14

### Added
- New `netbox` command as an nbcli wrapper with support for info, search, filter, and shell console types
- Added `nbcli` to requirements for NetBox CLI support

### Changed
- Renamed environment variable `OSISM_CONDUCTOR_NETBOX_FILTER_LIST` to `NETBOX_FILTER_LIST` for conductor configuration
- Renamed `netbox ping` command to `get versions netbox`
- Renamed logger name from `mycoolapp` to `osism` in API logging configuration
- Improved task logging by adding descriptive labels to task IDs for better traceability
- Added support for `NETBOX_URL` as alternative environment variable for `NETBOX_API`
- Use container image cache (`registry.osism.tech/dockerhub/python`) as base image
- Allow override of ironic parameters in NetBox using custom field `ironic_parameters` with recursive merge and vault decryption support
- Updated supported Cluster API Kubernetes images to versions 1.31, 1.32, and 1.33 (removed 1.30)
- Refactored conductor tasks to use dedicated functions (`get_configuration()` and `get_nb_device_query_list()`) instead of initializing in worker process init
- Increased Redlock auto-release time from 60 to 600 seconds and acquire timeout from 20 to 120 seconds for Ironic sync

### Fixed
- Fixed handling of NETBOX_FILTER_LIST environment variable by moving query list generation to a dedicated function
- Fixed null pointer exception when device.oob_ip is None during Ironic sync

### Removed
- Removed `netbox sync` command
- Removed `sync_inventory_with_netbox` reconciler task
- Removed `nornir` and `nornir-ansible` from requirements (never integrated)
- Removed usage of deprecated NetBox custom fields `oob_type`, `oob_address`, and `oob_port`

### Dependencies
- community.grafana 2.1.0 → 2.2.0
- deepdiff 8.4.2 → 8.5.0
- hiredis 3.1.0 → 3.1.1
- jc 1.25.4 → 1.25.5
- netbox-manager v0.20250314.0 → 0.20250508.0
- openstack-image-manager 0.20250423.0 → 0.20250508.0
- python 3.13.2 → 3.13.3
- setuptools 80.3.1 → 80.4.0
- uv 0.7.2 → 0.7.3

## [v0.20250505.0] - 2025-05-05

### Changed
- Netbox/Ironic sync no longer creates Nova flavors for baremetal nodes since Nova is not used for baremetal provisioning

### Dependencies
- celery 5.5.1 → 5.5.2
- community.crypto 2.26.0 → 2.26.1
- community.docker 4.5.2 → 4.6.0
- ghcr.io/astral-sh/uv 0.6.16 → 0.7.2
- setuptools 79.0.1 → 80.3.1

## [v0.20250425.0] - 2025-04-25

### Added
- Configuration parameter for a list of NetBox filters to define subsets of devices for Ironic synchronization
- Option to list all volumes of a specific project or domain
- Option to list all servers of a specific project or domain
- Support for updating multiple NetBox instances via `NETBOX_SECONDARIES` environment variable

### Changed
- Always use a cloud profile when managing the Octavia image
- NetBox API initialization is no longer performed on startup events, using a centralized connection helper instead

### Dependencies
- ansible-core 2.18.4 → 2.18.5
- ansible.netcommon 7.2.0 → 8.0.0
- ansible.utils 5.1.2 → 6.0.0
- celery 5.5.0 → 5.5.1
- community.general 10.5.0 → 10.6.0
- ghcr.io/astral-sh/uv 0.6.12 → 0.6.16
- kombu 5.5.2 → 5.5.3
- openstack-flavor-manager 0.20250314.0 → 0.20250413.0
- openstack-image-manager 0.20250407.0 → 0.20250423.0
- openstacksdk 4.4.0 → 4.5.0
- prompt-toolkit 3.0.50 → 3.0.51
- pydantic 1.10.21 → 1.10.22
- setuptools 78.1.0 → 79.0.1
- uvicorn 0.34.0 → 0.34.2

## [v0.20250407.0] - 2025-04-07

### Added
- Add openstack-core collection for streamlined OpenStack deployment
- Add CAPI 1.32 image support

### Changed
- Revise the Netbox Ironic integration with new synchronization approach and simplified state management
- Run letsencrypt after the loadbalancer in deployment sequence

### Fixed
- Allow power state to be None during removal of nodes from ironic
- Remove `redfish_port` from netbox/ironic sync as the redfish driver does not have this attribute

### Removed
- Remove CAPI 1.29 image support
- Remove `manage_device.py` and `manage_interface.py` action modules (functionality moved to tasks)

### Dependencies
- celery 5.4.0 → 5.5.0
- ghcr.io/astral-sh/uv 0.6.11 → 0.6.12
- kubernetes.core 5.1.0 → 5.2.0
- openstack-image-manager 0.20250314.0 → 0.20250407.0

## [v0.20250331.0] - 2025-03-31

### Added
- Stress validation playbook to osism-ansible environment

### Changed
- Switch container base image from Debian slim to Alpine
- Refactor to use centralized netbox, redis, and openstack connections from utils module
- Remove netbox image build and SBOM push from build playbook

### Fixed
- Fix tini entrypoint path for Alpine image (`/sbin/tini` instead of `/usr/bin/tini`)

### Dependencies
- ansible.netcommon 7.1.0 → 7.2.0
- kombu 5.5.1 → 5.5.2
- pytest-testinfra 10.1.1 → 10.2.2
- uv 0.6.10 → 0.6.11

## [v0.20250326.0] - 2025-03-26

### Added
- `--parallel` parameter to netbox manage command for parallel file processing
- `--delete` parameter to `manage images` command for deleting images
- `--no-wait` parameter to image and flavor management commands

### Changed
- Refactored image and flavor manager to use Celery tasks instead of subprocess calls
- Switched container build from pip to uv package manager
- Upgraded Python version from 3.12 to 3.13
- Simplified Containerfile by removing multi-stage build

### Fixed
- `--limit` parameter in netbox manage command now works correctly
- Removed unnecessary kombu workaround (fix included in kombu 5.5)

### Removed
- Old `netbox` command (deprecated `netbox:Run` class)

### Dependencies
- ansible-core 2.18.3 → 2.18.4
- ansible-runner 2.4.0 → 2.4.1
- community.docker 4.5.1 → 4.5.2
- community.general 10.4.0 → 10.5.0
- community.mysql 3.12.0 → 3.13.0
- deepdiff 8.3.0 → 8.4.2
- fastapi 0.115.11 → 0.115.12
- huey 2.5.2 → 2.5.3
- kombu 5.5.0 → 5.5.1
- pottery 3.0.0 → 3.0.1
- setuptools 76.0.0 → 78.1.0
- uv 0.6.9 → 0.6.10

## [v0.20250314.0] - 2025-03-14

### Added
- Integration with netbox-manager for NetBox device and configuration management

### Changed
- Replace NetBox subcommands with netbox-manager package

### Removed
- NetBox import script (`files/import/main.py`)
- NetBox action modules (check_configuration, deploy_configuration, diff_configuration, generate_configuration)
- NetBox CLI subcommands (manage, generate, deploy, diff, check, reconcile, import, sync, disable, enable, init, connect)
- osism-netbox Docker image stage from Containerfile

### Dependencies
- kombu 5.4.2 → 5.5.0
- openstack-flavor-manager 0.20241216.0 → 0.20250314.0
- openstack-image-manager 0.20241216.0 → 0.20250314.0
- openstacksdk 4.2.0 → 4.4.0

## [v0.20250312.0] - 2025-03-12

### Added
- REST API endpoint for baremetal notifications at `/notifications/baremetal` to allow sending baremetal notifications to another osism manager
- `OSISM_API_URL` setting for configuring remote notification forwarding
- `BaremetalEvents` class for handling baremetal notification events with structured handler lookup

### Changed
- Refactored notification handling in listener service to use reusable `BaremetalEvents` class instead of inline event handling
- Notifications can now be forwarded to a remote OSISM API with retry logic (up to 3 attempts with exponential backoff)

### Dependencies
- ansible-core 2.18.2 → 2.18.3
- cliff 4.8.0 → 4.9.1
- community.crypto 2.24.0 → 2.26.0
- community.docker 4.3.1 → 4.5.1
- community.general 10.3.0 → 10.4.0
- deepdiff 8.2.0 → 8.3.0
- fastapi 0.115.7 → 0.115.11
- jinja2 3.1.5 → 3.1.6
- keystoneauth1 5.9.1 → 5.10.0
- kubernetes 32.0.0 → 32.0.1
- netbox.netbox 3.20.0 → 3.21.0
- pip 25.0 → 25.0.1
- setuptools 75.8.0 → 76.0.0
- sqlmodel 0.0.22 → 0.0.24
- sushy 5.4.0 → 5.5.0

## [v0.20250219.0] - 2025-02-19

### Changed
- Use dtrack.osism.tech instead of osism.dtrack.regio.digital for Dependency-Track server

### Dependencies
- ansible-core 2.18.1 → 2.18.2
- clustershell 1.9.2 → 1.9.3
- community.crypto 2.22.3 → 2.24.0
- community.docker 4.2.0 → 4.3.1
- community.general 10.1.0 → 10.3.0
- community.mysql 3.11.0 → 3.12.0
- containers.podman 1.16.2 → 1.16.3
- deepdiff 8.1.1 → 8.2.0
- dtrack-auditor 1.4.0 → 1.5.0
- fastapi 0.115.6 → 0.115.7
- gitpython 3.1.43 → 3.1.44
- jinja2 3.1.4 → 3.1.5
- kubernetes 31.0.0 → 32.0.0
- kubernetes.core 5.0.0 → 5.1.0
- nornir 3.4.1 → 3.5.0
- openstack.cloud 2.3.1 → 2.4.1
- pip 24.3.1 → 25.0
- prompt-toolkit 3.0.48 → 3.0.50
- pydantic 1.10.19 → 1.10.21
- setuptools 75.6.0 → 75.8.0
- sushy 5.3.0 → 5.4.0

## [v0.20241219.2] - 2024-12-19

### Removed
- netbox-manager dependency due to incompatible Ansible version requirements across container images

## [v0.20241219.1] - 2024-12-19

### Fixed
- Wait for PyPI script now correctly handles grep exit code and version prefix stripping

## [v0.20241219.0] - 2024-12-19

### Added
- netbox-manager to requirements for NetBox management functionality

### Changed
- PyPI version check now uses curl and jq instead of pip for faster and more reliable package availability verification

### Dependencies
- community.rabbitmq 1.3.0 → 1.4.0
- openstack.cloud 2.3.0 → 2.3.1
