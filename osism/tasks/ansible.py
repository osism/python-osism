# SPDX-License-Identifier: Apache-2.0

from celery import Celery
from loguru import logger

from osism import settings, utils
from osism.tasks import Config, run_ansible_in_environment

app = Celery("ansible")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    lock = utils.create_redlock(
        key="lock_osism_tasks_ansible_setup_periodic_tasks",
    )
    if settings.GATHER_FACTS_SCHEDULE > 0 and lock.acquire(timeout=10):
        sender.add_periodic_task(
            settings.GATHER_FACTS_SCHEDULE, gather_facts.s(), expires=10
        )


def dispatch_kolla_facts():
    """Queue a fact gather in the kolla-ansible runtime, if that runtime exists.

    ansible-core 2.19 namespaces fact-cache entries per schema (`s1_<host>`), so
    a runtime above 2.19 cannot read entries a runtime below it wrote. kolla
    consumes the cache *exclusively* -- OSISM does not run kolla's site.yml, and
    split-kolla-ansible-site.py forces `gather_facts: false` on every emitted
    play -- so whenever kolla-ansible and osism-ansible sit on opposite sides of
    2.19, kolla starves unless its own runtime writes the cache. /ansible/kolla-facts.yml
    is that writer.

    Guarded, because the kolla-ansible container is the only consumer of the
    kolla-ansible queue and is `enable_kolla_ansible`-gated: dispatching on a
    manager without it would leave a task in redis on every run, forever.

    The check has to happen HERE, in a worker, rather than in
    setup_periodic_tasks: /interface is not mounted into the beat container, so
    MAP_ROLE2RUNTIME is empty there and the guard would never pass.
    """
    from osism.data.playbooks import MAP_ROLE2RUNTIME
    from osism.tasks import kolla

    if "kolla-ansible" not in MAP_ROLE2RUNTIME:
        logger.info(
            "kolla-ansible runtime not available, skipping the kolla fact gather"
        )
        return None

    return kolla.run.delay("kolla", "facts", [], auto_release_time=3600)


@app.task(bind=True, name="osism.tasks.ansible.gather_facts")
def gather_facts(self, publish=True):
    result = run_ansible_in_environment(
        self.request.id, "osism-ansible", "generic", "facts", [], publish, False
    )
    # The generic gather only ever fills osism-ansible's own cache generation.
    dispatch_kolla_facts()
    return result


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
    # Check if tasks are locked before execution
    utils.check_task_lock_and_exit()

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


@app.task(bind=True, name="osism.tasks.ansible.noop")
def noop(self):
    return True
