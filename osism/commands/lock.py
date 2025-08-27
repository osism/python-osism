# SPDX-License-Identifier: Apache-2.0

from cliff.command import Command
from loguru import logger

from osism import utils


class Lock(Command):
    """Lock task execution to prevent new tasks from starting"""

    def get_parser(self, prog_name):
        parser = super(Lock, self).get_parser(prog_name)
        parser.add_argument(
            "--user",
            help="User name to associate with the lock (defaults to dragon)",
        )
        parser.add_argument("--reason", help="Reason for locking tasks")
        return parser

    def take_action(self, parsed_args):
        user = parsed_args.user or "dragon"
        reason = parsed_args.reason

        # Check if already locked
        lock_info = utils.is_task_locked()
        if lock_info and lock_info.get("locked"):
            existing_user = lock_info.get("user", "unknown")
            existing_timestamp = lock_info.get("timestamp", "unknown")
            existing_reason = lock_info.get("reason")
            logger.warning(
                f"Tasks are already locked by {existing_user} at {existing_timestamp}"
            )
            if existing_reason:
                logger.warning(f"Existing reason: {existing_reason}")
            return

        # Set the lock
        if utils.set_task_lock(user, reason):
            logger.info(f"Tasks locked by {user}")
            if reason:
                logger.info(f"Reason: {reason}")
            logger.info("New tasks will be prevented from starting")
            logger.info("Running tasks will continue normally")
            logger.info("Use 'osism unlock' to remove the lock")
        else:
            logger.error("Failed to set task lock")
            return 1


class Unlock(Command):
    """Unlock task execution to allow new tasks to start"""

    def take_action(self, parsed_args):
        # Check if currently locked
        lock_info = utils.is_task_locked()
        if not lock_info or not lock_info.get("locked"):
            logger.info("Tasks are not currently locked")
            return

        existing_user = lock_info.get("user", "unknown")
        existing_timestamp = lock_info.get("timestamp", "unknown")
        existing_reason = lock_info.get("reason")

        # Remove the lock
        if utils.remove_task_lock():
            logger.info(
                f"Task lock removed (was set by {existing_user} at {existing_timestamp})"
            )
            if existing_reason:
                logger.info(f"Previous reason: {existing_reason}")
            logger.info("New tasks can now be started")
        else:
            logger.error("Failed to remove task lock")
            return 1


class LockStatus(Command):
    """Show current task lock status"""

    def take_action(self, parsed_args):
        lock_info = utils.is_task_locked()
        if lock_info and lock_info.get("locked"):
            user = lock_info.get("user", "unknown")
            timestamp = lock_info.get("timestamp", "unknown")
            reason = lock_info.get("reason")
            logger.info(f"Tasks are LOCKED by {user} at {timestamp}")
            if reason:
                logger.info(f"Reason: {reason}")
        else:
            logger.info("Tasks are UNLOCKED")
