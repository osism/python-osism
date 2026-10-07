# SPDX-License-Identifier: Apache-2.0

from datetime import datetime
import pprint
import re
import subprocess
import sys
import json

from cliff.command import Command
from loguru import logger
from tabulate import tabulate

from osism import settings, utils
from osism.utils import fact_cache
from osism.utils.hostvars import HostvarsError, Row, effective_rows
from osism.utils.inventory import get_hosts_from_inventory, get_inventory_path
from osism.utils.render import list_environments


class VersionsManager(Command):
    def get_parser(self, prog_name):
        parser = super(VersionsManager, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        import docker

        client = docker.from_env()

        data = []

        for cname in ["osism-ansible", "ceph-ansible", "kolla-ansible"]:
            try:
                container = client.containers.get(cname)
                version = container.labels["org.opencontainers.image.version"]

                if cname == "ceph-ansible":
                    mrelease = container.labels["de.osism.release.ceph"]
                elif cname == "kolla-ansible":
                    mrelease = container.labels["de.osism.release.openstack"]
                else:
                    mrelease = ""

                data.append([cname, version, mrelease])
            except docker.errors.NotFound:
                pass

        result = tabulate(
            data, headers=["Module", "OSISM version", "Module release"], tablefmt="psql"
        )
        print(result)


class Tasks(Command):
    def get_parser(self, prog_name):
        parser = super(Tasks, self).get_parser(prog_name)
        parser.add_argument(
            "--status", default="all", help="Status of the tasks to list"
        )
        return parser

    def take_action(self, parsed_args):
        from celery import Celery
        from osism.tasks import Config

        status = parsed_args.status

        app = Celery("task")
        app.config_from_object(Config)

        i = app.control.inspect()

        table = []

        task_status = "ACTIVE"
        for worker, tasks in i.active().items():
            for task in tasks:
                time_start = datetime.fromtimestamp(task["time_start"])
                table.append(
                    [
                        worker,
                        task["id"],
                        task["name"],
                        task_status,
                        time_start,
                        task["args"],
                    ]
                )

        task_status = "SCHEDULED"
        for worker, tasks in i.scheduled().items():
            for task in tasks:
                time_start = datetime.fromtimestamp(task["time_start"])
                table.append(
                    [
                        worker,
                        task["id"],
                        task["name"],
                        task_status,
                        time_start,
                        task["args"],
                    ]
                )

        print(
            tabulate(
                table,
                headers=["Worker", "ID", "Name", "Status", "Start time", "Arguments"],
                tablefmt="psql",
            )
        )


# The rendered path looks the name up; it is never templated.
VARIABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class Hostvars(Command):
    def get_parser(self, prog_name):
        parser = super(Hostvars, self).get_parser(prog_name)
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Hostname (as the host is known in Ansible inventory)",
        )
        parser.add_argument(
            "variable",
            nargs="?",
            type=str,
            help="Name of a variable to show",
        )
        environments = list_environments()
        available = (
            ", ".join(environments)
            if environments
            else f"(none found under {settings.ENVIRONMENTS_DIRECTORY})"
        )
        parser.add_argument(
            "--environment",
            type=str,
            help="Render with this environment only. Available: " + available,
        )
        parser.add_argument(
            "--raw",
            default=False,
            help="Show values as defined, without rendering templates",
            action="store_true",
        )
        parser.add_argument(
            "--show-secrets",
            default=False,
            help="Show values that are secrets or derived from secrets",
            action="store_true",
        )
        parser.add_argument(
            "--format",
            choices=["table", "value", "json"],
            default="table",
            help="Output format (default: table)",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        variable = parsed_args.variable

        if (
            not parsed_args.raw
            and variable is not None
            and not VARIABLE_NAME.fullmatch(variable)
        ):
            logger.error(
                f"not a valid variable name: {variable} "
                "(letters, digits and underscores, not starting with a digit)"
            )
            return 1

        inventory_path = get_inventory_path(
            "/ansible/inventory/hosts.yml", prefer_minified=False
        )
        try:
            result = subprocess.check_output(
                ["ansible-inventory", "-i", inventory_path, "--host", host],
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            logger.error(f"Host {host} not found in inventory.")
            return 1

        raw_hostvars = json.loads(result)

        if parsed_args.raw:
            return self._take_raw(parsed_args, host, variable, raw_hostvars)

        try:
            vault_password = utils.get_ansible_vault_password()
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(
                f"Cannot render: vault password unavailable ({type(exc).__name__}); "
                "use --raw to see values as defined."
            )
            return 1

        try:
            all_raw_hostvars = json.loads(
                subprocess.check_output(
                    ["ansible-inventory", "-i", inventory_path, "--list"],
                    stderr=subprocess.DEVNULL,
                )
            )["_meta"]["hostvars"]
        except (subprocess.CalledProcessError, ValueError, KeyError):
            logger.error("Cannot render: the inventory could not be listed.")
            return 1

        facts = fact_cache.get_host_facts(utils.redis, host)

        try:
            rows = effective_rows(
                host,
                variable,
                parsed_args.environment,
                parsed_args.show_secrets,
                inventory_path=inventory_path,
                vault_password=vault_password,
                facts=facts,
                raw_hostvars=raw_hostvars,
                all_raw_hostvars=all_raw_hostvars,
            )
        except HostvarsError as exc:
            logger.error(str(exc))
            return 1

        return self._output(parsed_args, host, variable, rows)

    def _take_raw(self, parsed_args, host, variable, data):
        if parsed_args.format != "table":
            if variable and variable not in data:
                rows = []
            else:
                names = [variable] if variable else list(data)
                rows = [
                    Row(host, name, None, data[name], False, [], False)
                    for name in names
                ]
            return self._output(parsed_args, host, variable, rows)

        table = []

        if variable:
            if variable in data:
                row = pprint.pformat(data[variable], indent=2, width=60, compact=True)
                table.append([host, variable, row])
            else:
                logger.error(f"Variable {variable} not found in inventory for {host}.")
        else:
            for variable in data:
                row = pprint.pformat(data[variable], indent=2, width=60, compact=True)
                table.append([host, variable, row])

        if table:
            print(
                tabulate(table, headers=["Host", "Variable", "Value"], tablefmt="grid")
            )

        return

    def _output(self, parsed_args, host, variable, rows):
        fmt = parsed_args.format

        if fmt == "json":
            print(
                json.dumps(
                    [
                        {
                            "host": r.host,
                            "variable": r.variable,
                            "environment": r.environment,
                            "value": r.value,
                            "masked": r.masked,
                            "notes": r.notes,
                        }
                        for r in rows
                    ],
                    default=str,
                )
            )
            return 1 if variable and any(r.failed for r in rows) else None

        if fmt == "value":
            if not variable:
                logger.error("--format value requires a variable name.")
                return 1
            if not rows:
                return None
            if len(rows) > 1:
                names = ", ".join(r.environment or "default" for r in rows)
                logger.error(
                    f"ambiguous: environments differ ({names}); pass --environment"
                )
                return 1
            row = rows[0]
            if row.masked:
                reasons = "; ".join(
                    n.removeprefix("masked: ")
                    for n in row.notes
                    if n.startswith("masked: ")
                )
                logger.error(f"value is masked ({reasons}); pass --show-secrets")
                return 1
            if row.failed:
                for note in row.notes:
                    print(note, file=sys.stderr)
                return 1
            print(row.value if isinstance(row.value, str) else json.dumps(row.value))
            return None

        if not rows:
            if variable:
                logger.error(f"Variable {variable} not found in inventory for {host}.")
            return None

        table = []
        for r in rows:
            label = f"{r.variable} [{r.environment}]" if r.environment else r.variable
            value = (
                "***"
                if r.masked
                else pprint.pformat(r.value, indent=2, width=60, compact=True)
            )
            table.append([r.host, label, value, "\n".join(r.notes)])
        print(
            tabulate(
                table, headers=["Host", "Variable", "Value", "Notes"], tablefmt="grid"
            )
        )
        return 1 if variable and any(r.failed for r in rows) else None


class Facts(Command):
    def get_parser(self, prog_name):
        parser = super(Facts, self).get_parser(prog_name)
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Hostname (as the host is known in Ansible inventory)",
        )
        parser.add_argument(
            "fact",
            nargs="?",
            type=str,
            help="Name of a fact to show",
        )
        parser.add_argument(
            "--no-cache",
            default=False,
            help="Do not use facts from the cache",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        fact = parsed_args.fact
        cache = not parsed_args.no_cache

        data = fact_cache.get_host_facts(utils.redis, host)
        if data:
            table = []

            if fact:
                if fact in data:
                    row = pprint.pformat(data[fact], indent=2, width=60, compact=True)
                    table.append([host, fact, row])
                else:
                    logger.error(f"Fact {fact} not found in cache for {host}.")
            else:
                for fact in data:
                    row = pprint.pformat(data[fact], indent=2, width=60, compact=True)
                    if fact in [
                        "ansible_ssh_host_key_dsa_public",
                        "ansible_ssh_host_key_ecdsa_public",
                        "ansible_ssh_host_key_ed25519_public",
                        "ansible_ssh_host_key_rsa_public",
                    ]:
                        row = f"{row[0:40]}..."
                    table.append([host, fact, row])

            if table:
                print(
                    tabulate(table, headers=["Host", "Fact", "Value"], tablefmt="grid")
                )
        else:
            logger.error(f"No facts found in cache for {host}.")

        return


class Hosts(Command):
    def get_parser(self, prog_name):
        parser = super(Hosts, self).get_parser(prog_name)
        parser.add_argument(
            "-l",
            "--limit",
            type=str,
            help="Limit selected hosts to an additional pattern",
        )
        return parser

    def take_action(self, parsed_args):
        try:
            inventory_path = get_inventory_path("/ansible/inventory/hosts.yml")
            command = [f"ansible-inventory -i {inventory_path} --list"]
            if parsed_args.limit:
                command.append(f"--limit {parsed_args.limit}")

            result = subprocess.check_output(
                " ".join(command),
                shell=True,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            logger.error("Error loading inventory.")
            return 1

        data = json.loads(result)
        table = []

        for host in get_hosts_from_inventory(data):
            table.append([host])

        if table:
            print(tabulate(table, headers=["Host"], tablefmt="psql"))

        return


# Printed once by kolla-mariadb-backup-host.yml: the host the backup runs on
# (empty if none) and the host each shard resolved.
BACKUP_HOST_PATTERN = re.compile(r"mariadb_backup_host=([^\s\"]*) resolved=([^\s\"]*)")


class MariadbBackupHost(Command):
    """Show the host that 'osism apply mariadb-backup' writes archives to.

    The value is resolved by the mariadb role itself, in a read-only play on
    the kolla-ansible worker, because its default, the shard grouping it
    depends on and the usual override are all outside the inventory.
    """

    def get_parser(self, prog_name):
        parser = super(MariadbBackupHost, self).get_parser(prog_name)
        parser.add_argument(
            "--format",
            default="table",
            choices=["table", "script"],
            help="Output type; script prints the bare host name",
        )
        parser.add_argument(
            "--timeout",
            default=300,
            type=int,
            help="Seconds to wait for the play",
        )
        return parser

    def take_action(self, parsed_args):
        from celery.exceptions import TimeoutError as CeleryTimeoutError

        from osism.tasks import AnsibleFailure, kolla

        utils.check_task_lock_and_exit()

        t = kolla.run.delay("kolla", "mariadb-backup-host", [], publish=False)
        try:
            output = t.get(timeout=parsed_args.timeout)
        except AnsibleFailure as exc:
            logger.error(
                f"{exc}. 'osism apply -e kolla mariadb-backup-host' shows "
                "the full output."
            )
            return 1
        except CeleryTimeoutError:
            logger.error(f"Timeout while waiting for task {t.task_id}.")
            # Unsubscribe now; left pending, the result is released during
            # interpreter shutdown and Celery prints a traceback.
            t.forget()
            return 1

        match = BACKUP_HOST_PATTERN.search(output)
        if not match:
            logger.error("The play did not report a backup host.")
            return 1

        hosts = [host for host in match.group(1).split(",") if host]
        if not hosts:
            # kolla skips the backup silently in this case.
            resolved = match.group(2).replace(",", ", ")
            logger.error(
                f"No backup would be taken: no resolved backup host "
                f"({resolved}) is in the default MariaDB shard."
            )
            return 1

        if parsed_args.format == "script":
            print("\n".join(hosts))
        else:
            print(
                tabulate([[host] for host in hosts], headers=["Host"], tablefmt="psql")
            )

        return


class States(Command):
    def get_parser(self, prog_name):
        parser = super(States, self).get_parser(prog_name)
        parser.add_argument(
            "host",
            nargs=1,
            type=str,
            help="Hostname (as the host is known in Ansible inventory)",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]

        data = fact_cache.get_host_facts(utils.redis, host)
        if data:
            table = []

            if "ansible_local" in data and "osism" in data["ansible_local"]:
                for local_fact in data["ansible_local"]["osism"]:
                    if local_fact != "bootstrap":
                        local_data = data["ansible_local"]["osism"][local_fact]
                        table.append(
                            [local_fact, local_data["state"], local_data["timestamp"]]
                        )

                if table:
                    print(
                        tabulate(
                            table,
                            headers=["Role", "State", "Timestamp"],
                            tablefmt="psql",
                        )
                    )

        return
