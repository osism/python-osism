# SPDX-License-Identifier: Apache-2.0

import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

from cliff.command import Command
import jinja2
from loguru import logger
import requests
from yaml import safe_load, YAMLError

from osism import utils
from osism.data import TEMPLATE_KOLLA_VERSIONS
from osism.tasks import ansible, conductor, handle_task


class Facts(Command):
    def get_parser(self, prog_name):
        parser = super(Facts, self).get_parser(prog_name)
        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        arguments = []
        t = ansible.run.delay(
            "generic", "gather-facts", arguments, auto_release_time=3600
        )
        rc = handle_task(t)
        return rc


class CephKeys(Command):
    def get_parser(self, prog_name):
        parser = super(CephKeys, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the sync has been completed",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        wait = not parsed_args.no_wait
        arguments = []
        t = ansible.run.delay(
            "manager", "copy-ceph-keys", arguments, auto_release_time=3600
        )
        logger.info(f"Task {t.task_id} (sync ceph-keys) started")
        rc = handle_task(t, wait)
        return rc


class Sonic(Command):
    def get_parser(self, prog_name):
        parser = super(Sonic, self).get_parser(prog_name)
        parser.add_argument(
            "device",
            nargs="?",
            help="Optional device name to sync configuration for a specific device",
        )
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until the sync has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--diff",
            default=True,
            help="Show configuration diff when changes are detected (default: True)",
            action="store_true",
        )
        parser.add_argument(
            "--no-diff",
            dest="diff",
            help="Do not show configuration diff",
            action="store_false",
        )
        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        wait = not parsed_args.no_wait
        device_name = parsed_args.device
        show_diff = parsed_args.diff

        task = conductor.sync_sonic.delay(device_name, show_diff)

        if device_name:
            logger.info(
                f"Task {task.task_id} (sync sonic for device {device_name}) started"
            )
        else:
            logger.info(f"Task {task.task_id} (sync sonic) started")

        rc = handle_task(task, wait=wait)
        return rc


class Versions(Command):
    """Sync Kolla versions from SBOM container image to configuration repository."""

    def get_parser(self, prog_name):
        parser = super(Versions, self).get_parser(prog_name)
        parser.add_argument(
            "type",
            nargs="?",
            default="kolla",
            choices=["kolla"],
            help="Type of versions to sync (default: kolla)",
        )
        parser.add_argument(
            "--openstack-version",
            type=str,
            default=os.environ.get("OPENSTACK_VERSION", "2025.1"),
            help="OpenStack version (default: 2025.1, env: OPENSTACK_VERSION)",
        )
        parser.add_argument(
            "--configuration-path",
            type=str,
            default="/opt/configuration",
            help="Path to configuration repository (default: /opt/configuration)",
        )
        parser.add_argument(
            "--sbom-image",
            type=str,
            default=None,
            help="SBOM container image (default: registry.osism.cloud/kolla/sbom:<version>)",
        )
        parser.add_argument(
            "--release",
            type=str,
            default=None,
            help="OSISM release version (e.g., 9.4.0) to fetch SBOM version from",
        )
        parser.add_argument(
            "--release-repository-url",
            type=str,
            default="https://raw.githubusercontent.com/osism/release/main",
            help="Base URL for the release repository (default: https://raw.githubusercontent.com/osism/release/main)",
        )
        parser.add_argument(
            "--sbom-image-base",
            type=str,
            default="registry.osism.cloud/kolla/release/sbom",
            help="Base path for the SBOM container image (default: registry.osism.cloud/kolla/release/sbom)",
        )
        parser.add_argument(
            "--dry-run",
            default=False,
            help="Show rendered versions without writing to file",
            action="store_true",
        )
        return parser

    def _extract_sbom_with_skopeo(self, image_ref: str) -> dict:
        """
        Extract SBOM from container image using skopeo.

        Args:
            image_ref: Container image reference

        Returns:
            Parsed SBOM data dictionary
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            oci_dir = Path(tmpdir) / "oci"

            logger.info(f"Copying image {image_ref} using skopeo...")
            try:
                subprocess.run(
                    [
                        "skopeo",
                        "copy",
                        f"docker://{image_ref}",
                        f"oci:{oci_dir}:latest",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to copy image with skopeo: {e.stderr}")
                raise RuntimeError(f"skopeo copy failed: {e.stderr}")
            except FileNotFoundError:
                logger.error("skopeo not found. Please install skopeo.")
                raise RuntimeError("skopeo not found")

            logger.info("Extracting images.yml from OCI image...")

            # Read the OCI index to find the manifest
            index_path = oci_dir / "index.json"
            with open(index_path) as f:
                index = safe_load(f)

            # Get the manifest digest
            manifest_digest = index["manifests"][0]["digest"]
            manifest_hash = manifest_digest.split(":")[1]

            # Read the manifest
            manifest_path = oci_dir / "blobs" / "sha256" / manifest_hash
            with open(manifest_path) as f:
                manifest = safe_load(f)

            # Extract each layer and look for images.yml
            sbom = None
            for layer in manifest["layers"]:
                layer_digest = layer["digest"]
                layer_hash = layer_digest.split(":")[1]
                layer_path = oci_dir / "blobs" / "sha256" / layer_hash

                try:
                    with tarfile.open(layer_path, "r:*") as tar:
                        for member in tar.getmembers():
                            if member.name == "images.yml" or member.name.endswith(
                                "/images.yml"
                            ):
                                extracted = tar.extractfile(member)
                                if extracted:
                                    sbom = safe_load(extracted.read())
                                    logger.success("Found and extracted images.yml")
                                    break
                except (tarfile.TarError, EOFError):
                    # Not a tar file or empty, skip
                    continue

                if sbom:
                    break

            if sbom is None:
                raise RuntimeError("images.yml not found in container image")

            return sbom

    def _get_kolla_version_from_release(
        self, release: str, release_repository_url: str
    ) -> str:
        """
        Fetch the Kolla SBOM version from the OSISM release repository.

        Args:
            release: OSISM release version (e.g., '9.4.0')
            release_repository_url: Base URL for the release repository

        Returns:
            Kolla SBOM version string (e.g., '0.20250928.0')
        """
        url = f"{release_repository_url}/{release}/base.yml"
        logger.info(f"Fetching release configuration from {url}")

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to fetch release configuration: {e}")

        try:
            release_config = safe_load(response.text)
        except YAMLError as e:
            raise RuntimeError(f"Failed to parse release configuration: {e}")

        docker_images = release_config.get("docker_images", {})
        kolla_version = docker_images.get("kolla")

        if kolla_version is None:
            raise RuntimeError(
                f"Kolla version not found in release {release} configuration"
            )

        logger.info(f"Found Kolla version {kolla_version} for release {release}")
        return kolla_version

    def take_action(self, parsed_args):
        sync_type = parsed_args.type
        openstack_version = parsed_args.openstack_version
        config_path = Path(parsed_args.configuration_path)
        dry_run = parsed_args.dry_run
        release = parsed_args.release
        release_repository_url = parsed_args.release_repository_url.rstrip("/")
        sbom_image_base = parsed_args.sbom_image_base

        if sync_type == "kolla":
            return self._sync_kolla_versions(
                openstack_version,
                config_path,
                parsed_args.sbom_image,
                dry_run,
                release,
                release_repository_url,
                sbom_image_base,
            )

        logger.error(f"Unknown sync type: {sync_type}")
        return 1

    def _sync_kolla_versions(
        self,
        openstack_version: str,
        config_path: Path,
        sbom_image: str | None,
        dry_run: bool,
        release: str | None,
        release_repository_url: str,
        sbom_image_base: str,
    ) -> int:
        """Sync Kolla versions from SBOM container image."""

        # Construct SBOM image reference if not provided
        if sbom_image is None:
            # If release is specified, fetch the Kolla version from the release repository
            if release is not None:
                try:
                    kolla_version = self._get_kolla_version_from_release(
                        release, release_repository_url
                    )
                    sbom_image = f"{sbom_image_base}:{kolla_version}"
                except RuntimeError as e:
                    logger.error(str(e))
                    return 1
            else:
                # Strip 'v' prefix if present (v0.20251128.0 -> 0.20251128.0)
                version_tag = openstack_version.lstrip("v")

                # Use kolla/release/sbom for release versions (contain date like 0.20251128.0)
                # Use kolla/sbom for OpenStack versions (like 2025.1)
                is_release_version = any(
                    len(part) == 8 and part.startswith("20") and part.isdigit()
                    for part in version_tag.split(".")
                )

                if is_release_version:
                    sbom_image = f"{sbom_image_base}:{version_tag}"
                else:
                    sbom_image = f"registry.osism.cloud/kolla/sbom:{version_tag}"

        # Check configuration path exists
        if not dry_run and not config_path.exists():
            logger.error(f"Configuration path does not exist: {config_path}")
            return 1

        # Extract SBOM from container
        try:
            sbom = self._extract_sbom_with_skopeo(sbom_image)
        except RuntimeError as e:
            logger.error(str(e))
            return 1
        except YAMLError as e:
            logger.error(f"Failed to parse SBOM YAML: {e}")
            return 1

        versions = sbom.get("versions", {})

        # Always use openstack_version from SBOM
        openstack_version = sbom.get("openstack_version", openstack_version)

        if release is not None:
            logger.info(f"OSISM release: {release}")
        logger.info(f"OpenStack version: {openstack_version}")
        logger.info(f"Configuration path: {config_path}")
        logger.info(f"SBOM image: {sbom_image}")
        logger.info(f"Found {len(versions)} version entries in SBOM")

        # Render template
        environment = jinja2.Environment()
        template = environment.from_string(TEMPLATE_KOLLA_VERSIONS)
        result = template.render(
            {
                "openstack_version": openstack_version,
                "versions": versions,
            }
        )

        if dry_run:
            logger.info("Dry run - rendered versions.yml:")
            print(result)
            return 0

        # Write to configuration repository
        output_path = config_path / "environments" / "kolla" / "versions.yml"

        # Ensure directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            f.write(result)

        logger.success(f"Versions written to {output_path}")
        return 0
