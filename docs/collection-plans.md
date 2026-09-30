# Collection execution plans

Collections use four explicit nodes from `osism.data.plans`:

- `Run(name)` executes a role.
- `Sequence(*steps)` completes each step before starting the next.
- `Parallel(*steps)` schedules sibling steps concurrently.
- `Select(key, alternatives)` substitutes one complete execution plan.

For example, a replacement prerequisite with shared consumers is expressed as:

```python
Sequence(
    Select("bootstrap", {
        "old": Run("common"),
        "new": Parallel(Run("logs"), Run("toolbox")),
    }),
    Parallel(Run("consumer-a"), Run("consumer-b")),
)
```

Deployment policy supplies the selection values separately. OpenStack 2025.2
and later select Valkey; earlier releases select Redis. This is collection
membership policy, not a restriction on applying either role individually.

All requested collection plans are resolved and validated before any collection
is submitted. Missing or unknown selections fail; unselected subtrees disappear
entirely. There is no implicit promotion of children past an excluded parent.
`--show-tree` renders the same resolved plan that execution uses, including its
sequence and parallel boundaries.

Sequences compile to Celery chains and parallel blocks to Celery groups. A
parallel block followed by another sequence step is a completion barrier
(Celery can implement this as a chord). Role signatures are immutable so results
from earlier steps are not injected into subsequent task arguments.

The initial catalog conversion preserves the previous execution topology:
parents preceded their children and sibling roles were already Celery groups.
Actual overlap depends on workers and task behavior. Unit tests verify selection
and canvas ordering; they do not establish that Ansible roles are safe under
concurrent execution. Changing a collection's concurrency requires deployment
validation separately from changing this representation.

## Ceph selection in nutshell

`nutshell` selects its complete Ceph workflow using the OSISM release:

| OSISM release | Backend |
| --- | --- |
| Below 11 | ceph-ansible |
| 11 and later | cephadm |
| `latest` | cephadm |

The OSISM release is read from `--osism-version`, then `OSISM_VERSION`, then
`manager_version` in `/opt/configuration/environments/manager/configuration.yml`.
Missing or invalid releases stop dispatch. Collections without a Ceph selector,
and individual roles, do not read this source. The existing `collection-ceph`
and `cloudpod-ceph` collections retain their ceph-ansible workflows.

The OpenStack release still independently chooses Redis or Valkey. Both release
options must precede the collection name, because later arguments are passed to
Ansible:

```console
osism apply --osism-version latest --openstack-version 2026.1 --show-tree nutshell
```

The Ceph default is a greenfield deployment policy, not a migration procedure.
For an existing ceph-ansible cluster, explicitly retain its backend:

```console
osism apply --ceph-backend ceph-ansible nutshell
```

`--ceph-backend` overrides the OSISM default and avoids the OSISM release lookup.
It does not change the cluster's configuration or migrate it. Cephadm's workflow
sets up the client before driving the orchestrator, distributes keys after pools,
and deploys RGW before starting the Kolla RGW integration and other consumers.
Ceph-environment roles advertised by osism-ansible use that runtime; the
ceph-ansible roles continue to use their existing runtime.
