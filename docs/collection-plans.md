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
