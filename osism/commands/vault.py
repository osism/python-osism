# SPDX-License-Identifier: Apache-2.0

# NOTE: This is a first step to make Ansible Vault usable via OSISM workers.
#       It's not ready in that form yet.

import glob
import os
import subprocess
import sys

from cliff.command import Command
from loguru import logger

from osism import utils


class SetPassword(Command):
    keyfile = "/share/ansible_vault_password.key"

    def get_parser(self, prog_name):
        parser = super(SetPassword, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        from cryptography.fernet import Fernet
        from prompt_toolkit import prompt

        if os.path.isfile(self.keyfile):
            with open(self.keyfile, "r") as fp:
                key = fp.read()
        else:
            key = Fernet.generate_key()
            with open(self.keyfile, "w+") as fp:
                fp.write(key.decode("utf-8"))

        f = Fernet(key)

        # Check if password is being piped from STDIN
        if not sys.stdin.isatty():
            ansible_vault_password = sys.stdin.read().strip()
        else:
            ansible_vault_password = prompt(
                "Ansible Vault password: ", is_password=True
            )

        utils.redis.set(
            "ansible_vault_password", f.encrypt(ansible_vault_password.encode("utf-8"))
        )


class UnsetPassword(Command):
    def get_parser(self, prog_name):
        parser = super(UnsetPassword, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        utils.redis.delete("ansible_vault_password")


class View(Command):
    def get_parser(self, prog_name):
        parser = super(View, self).get_parser(prog_name)
        parser.add_argument(
            "path", nargs="?", type=str, help="Path to the secret.yml file"
        )
        return parser

    def take_action(self, parsed_args):
        path = parsed_args.path
        if not os.path.isabs(path):
            path = os.path.join("/opt/configuration", path)
        subprocess.call(f"/usr/local/bin/ansible-vault view {path}", shell=True)


class Decrypt(Command):
    def get_parser(self, prog_name):
        parser = super(Decrypt, self).get_parser(prog_name)
        parser.add_argument(
            "path", nargs="?", type=str, help="Path to the secret.yml file"
        )
        return parser

    def take_action(self, parsed_args):
        path = parsed_args.path
        if not os.path.isabs(path):
            path = os.path.join("/opt/configuration", path)
        subprocess.call(f"/usr/local/bin/ansible-vault decrypt {path}", shell=True)


# Well-known paths where secrets.yml files are typically found
SECRETS_SEARCH_PATHS = [
    "/opt/configuration/environments/kolla/secrets.yml",
    "/opt/configuration/environments/openstack/secrets.yml",
    "/opt/configuration/environments/infrastructure/secrets.yml",
    "/opt/configuration/environments/ceph/secrets.yml",
    "/opt/configuration/environments/monitoring/secrets.yml",
    "/opt/configuration/environments/generic/secrets.yml",
    "/opt/configuration/environments/manager/secrets.yml",
    "/opt/configuration/environments/custom/secrets.yml",
]


class Check(Command):
    """Check whether the Ansible Vault password is set and working.

    Verifies the full chain: keyfile, Redis storage, decryption,
    and optionally tests decryption against a secrets.yml file.
    """

    keyfile = "/share/ansible_vault_password.key"

    def get_parser(self, prog_name):
        parser = super(Check, self).get_parser(prog_name)
        parser.add_argument(
            "--path",
            nargs="?",
            type=str,
            default=None,
            help="Path to a vault-encrypted file to test decryption against. "
            "If not specified, searches for secrets.yml files automatically.",
        )
        parser.add_argument(
            "--format",
            default="log",
            help="Output type",
            const="log",
            nargs="?",
            choices=["script", "log"],
        )
        return parser

    def _find_secrets_file(self):
        """Find an existing vault-encrypted secrets.yml file for testing."""
        for path in SECRETS_SEARCH_PATHS:
            if os.path.isfile(path):
                return path

        # Fallback: glob for any secrets.yml under /opt/configuration/environments
        matches = glob.glob(
            "/opt/configuration/environments/**/secrets.yml", recursive=True
        )
        if matches:
            return matches[0]

        return None

    def take_action(self, parsed_args):
        from cryptography.fernet import Fernet, InvalidToken

        format = parsed_args.format
        passed = 0
        failed = 0

        # Step 1: Check keyfile exists
        if os.path.isfile(self.keyfile):
            if format == "log":
                logger.info(f"Keyfile exists: {self.keyfile}")
            passed += 1
        else:
            if format == "log":
                logger.error(f"Keyfile not found: {self.keyfile}")
            elif format == "script":
                print("FAILED: keyfile_missing")
            failed += 1
            self._report(format, passed, failed)
            return 1

        # Step 2: Check keyfile contains a valid Fernet key
        try:
            with open(self.keyfile, "r") as fp:
                key = fp.read()
            f = Fernet(key)
            if format == "log":
                logger.info("Keyfile contains a valid Fernet key")
            passed += 1
        except (ValueError, Exception) as exc:
            if format == "log":
                logger.error(f"Keyfile does not contain a valid Fernet key: {exc}")
            elif format == "script":
                print("FAILED: invalid_keyfile")
            failed += 1
            self._report(format, passed, failed)
            return 1

        # Step 3: Check vault password is set in Redis
        encrypted_password = utils.redis.get("ansible_vault_password")
        if encrypted_password is not None:
            if format == "log":
                logger.info("Vault password is set in Redis")
            passed += 1
        else:
            if format == "log":
                logger.error(
                    "Vault password is not set in Redis. "
                    "Use 'osism set vault password' to set it."
                )
            elif format == "script":
                print("FAILED: password_not_set")
            failed += 1
            self._report(format, passed, failed)
            return 1

        # Step 4: Check vault password can be decrypted
        try:
            password = f.decrypt(encrypted_password).decode("utf-8")
            if format == "log":
                logger.info("Vault password successfully decrypted from Redis")
            passed += 1
        except InvalidToken:
            if format == "log":
                logger.error(
                    "Failed to decrypt vault password from Redis. "
                    "The keyfile may have been regenerated after the password was set. "
                    "Use 'osism set vault password' to set it again."
                )
            elif format == "script":
                print("FAILED: decryption_failed")
            failed += 1
            self._report(format, passed, failed)
            return 1

        # Step 5: Check vault password is not empty
        if password and password.strip():
            if format == "log":
                logger.info("Vault password is not empty")
            passed += 1
        else:
            if format == "log":
                logger.error("Vault password is empty or contains only whitespace")
            elif format == "script":
                print("FAILED: password_empty")
            failed += 1
            self._report(format, passed, failed)
            return 1

        # Step 6: Test decryption against a secrets.yml file
        test_path = parsed_args.path
        if test_path and not os.path.isabs(test_path):
            test_path = os.path.join("/opt/configuration", test_path)

        if not test_path:
            test_path = self._find_secrets_file()

        if test_path:
            from ansible import constants as ansible_constants
            from ansible.parsing.vault import VaultLib, VaultSecret

            try:
                vault = VaultLib(
                    [
                        (
                            ansible_constants.DEFAULT_VAULT_ID_MATCH,
                            VaultSecret(password.encode()),
                        )
                    ]
                )

                with open(test_path, "rb") as fp:
                    file_data = fp.read()

                if vault.is_encrypted(file_data):
                    vault.decrypt(file_data)
                    if format == "log":
                        logger.info(
                            f"Vault password successfully decrypted: {test_path}"
                        )
                    passed += 1
                else:
                    if format == "log":
                        logger.warning(
                            f"File is not vault-encrypted, skipping decryption test: {test_path}"
                        )
            except Exception as exc:
                if format == "log":
                    logger.error(f"Vault password failed to decrypt {test_path}: {exc}")
                    logger.error(
                        "The vault password does not match the one used to encrypt "
                        "this file. Use 'osism set vault password' to set the correct password."
                    )
                elif format == "script":
                    print("FAILED: wrong_password")
                failed += 1
        else:
            if format == "log":
                logger.warning(
                    "No secrets.yml file found to test decryption against. "
                    "Use --path to specify a vault-encrypted file."
                )

        self._report(format, passed, failed)
        return 1 if failed else 0

    def _report(self, format, passed, failed):
        if format == "log":
            if failed:
                logger.error(f"Vault check FAILED ({passed} passed, {failed} failed)")
            else:
                logger.info(f"Vault check PASSED ({passed} passed)")
        elif format == "script":
            if not failed:
                print("PASSED")
