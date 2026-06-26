# SPDX-License-Identifier: Apache-2.0

import json
import subprocess

from cliff.command import Command
from loguru import logger
from redis.exceptions import RedisError

from osism import utils
from osism.utils.inventory import get_hosts_from_inventory, get_inventory_path


class Facts(Command):
    """Reset (clear) the cached Ansible facts.

    By default the whole fact cache is flushed. Use ``--limit`` to clear
    only the facts of selected hosts or groups. The command does not
    gather new facts; the cache is rebuilt on the next Ansible run that
    collects facts.
    """

    def get_parser(self, prog_name):
        parser = super(Facts, self).get_parser(prog_name)
        parser.add_argument(
            "-l",
            "--limit",
            type=str,
            help="Limit the reset to selected hosts or groups (Ansible host pattern)",
        )
        return parser

    def take_action(self, parsed_args):
        if parsed_args.limit is not None and not parsed_args.limit.strip():
            logger.error("--limit must not be empty.")
            return 1
        if parsed_args.limit:
            return self._reset_limited(parsed_args.limit)
        return self._reset_all()

    def _reset_all(self):
        removed = 0
        try:
            cursor = 0
            while True:
                cursor, batch = utils.redis.scan(
                    cursor, match="ansible_facts*", count=100
                )
                if batch:
                    utils.redis.delete(*batch)
                    removed += len(batch)
                if cursor == 0:
                    break
        except RedisError as exc:
            logger.error(f"Failed to reset Ansible fact cache: {exc}")
            return 1

        logger.info(f"Removed cached facts for {removed} host(s)")
        return 0

    def _reset_limited(self, limit):
        try:
            result = subprocess.run(
                [
                    "ansible-inventory",
                    "-i",
                    get_inventory_path("/ansible/inventory/hosts.yml"),
                    "--list",
                    "--limit",
                    limit,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error(
                    f"Error loading inventory (rc={result.returncode}): "
                    f"{result.stderr}"
                )
                return 1
        except subprocess.TimeoutExpired:
            logger.error("Timeout loading inventory.")
            return 1

        try:
            inventory = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            logger.error(f"Failed to parse inventory output: {exc}")
            return 1

        hosts = get_hosts_from_inventory(inventory)

        if not hosts:
            logger.warning("No hosts matched the given limit.")
            return 0

        keys = [f"ansible_facts{host}" for host in hosts]
        try:
            deleted = utils.redis.delete(*keys)
        except RedisError as exc:
            logger.error(f"Failed to reset Ansible fact cache: {exc}")
            return 1

        logger.info(f"Removed cached facts for {deleted} host(s)")
        return 0
