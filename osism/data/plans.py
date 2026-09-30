# SPDX-License-Identifier: Apache-2.0

"""Collection execution plans, independent of Celery and deployment policy."""

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Run:
    name: str

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("A role must have a nonempty name")


@dataclass(frozen=True, init=False)
class Sequence:
    steps: tuple

    def __init__(self, *steps):
        object.__setattr__(self, "steps", tuple(steps))


@dataclass(frozen=True, init=False)
class Parallel:
    steps: tuple

    def __init__(self, *steps):
        object.__setattr__(self, "steps", tuple(steps))


@dataclass(frozen=True)
class Select:
    key: str
    alternatives: Mapping

    def __post_init__(self):
        if not self.key or not self.alternatives:
            raise ValueError("A selection needs a key and alternatives")
        # Do not retain the caller's mutable dictionary.
        from types import MappingProxyType

        object.__setattr__(
            self, "alternatives", MappingProxyType(dict(self.alternatives))
        )


class PlanError(ValueError):
    """A collection cannot be resolved into an executable plan."""


def selection_keys(plan):
    """Inspect all alternatives without consulting deployment facts."""
    if isinstance(plan, Select):
        return {plan.key}.union(
            *(selection_keys(p) for p in plan.alternatives.values())
        )
    if isinstance(plan, (Sequence, Parallel)):
        return set().union(*(selection_keys(p) for p in plan.steps))
    if isinstance(plan, Run):
        return set()
    raise PlanError(f"Expected execution plan, got {type(plan).__name__}")


def resolve(plan, selections):
    """Choose complete subplans and validate before any tasks are created.

    Unknown or missing selections fail closed. Unselected subtrees disappear
    entirely; their children are never promoted into the surrounding plan.
    """
    if isinstance(plan, Select):
        value = selections.get(plan.key)
        if value not in plan.alternatives:
            raise PlanError(
                f"Selection {plan.key!r} is {value!r}; "
                f"expected one of {', '.join(plan.alternatives)}"
            )
        return resolve(plan.alternatives[value], selections)
    if isinstance(plan, (Sequence, Parallel)):
        if not plan.steps:
            raise PlanError(f"{type(plan).__name__} must contain at least one step")
        return type(plan)(*(resolve(step, selections) for step in plan.steps))
    if isinstance(plan, Run):
        return plan
    raise PlanError(f"Expected execution plan, got {type(plan).__name__}")


def selections_for_openstack(release):
    """Collection policy, rather than playbook availability."""
    if release is None:
        raise PlanError("The kvs_backend selection requires an OpenStack release")
    return {"kvs_backend": "valkey" if release >= (2025, 2) else "redis"}
