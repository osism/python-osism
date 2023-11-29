# SPDX-License-Identifier: Apache-2.0

import functools
from threading import RLock

from celery import Celery
import kombu.utils

from osism import settings
from osism.tasks import Config, run_ansible_in_environment

# https://github.com/celery/kombu/issues/1804
if not getattr(kombu.utils.cached_property, "lock", None):
    setattr(
        kombu.utils.cached_property,
        "lock",
        functools.cached_property(lambda _: RLock()),
    )
    # Must call __set_name__ here since this cached property is not defined in the context of a class
    # Refer to https://docs.python.org/3/reference/datamodel.html#object.__set_name__
    kombu.utils.cached_property.lock.__set_name__(kombu.utils.cached_property, "lock")

app = Celery("ansible")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        settings.GATHER_FACTS_SCHEDULE, gather_facts.s(), expires=10
    )


@app.task(bind=True, name="osism.tasks.ansible.gather_facts")
def gather_facts(self, publish=True):
    return run_ansible_in_environment(
        self.request.id, "osism-ansible", "generic", "facts", [], publish, False
    )


@app.task(bind=True, name="osism.tasks.ansible.run")
def run(
    self,
    environment,
    playbook,
    arguments,
    publish=True,
    locking=False,
    auto_release_time=3600,
):
    return run_ansible_in_environment(
        self.request.id,
        "osism-ansible",
        environment,
        playbook,
        arguments,
        publish,
        locking,
        auto_release_time,
    )
