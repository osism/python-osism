# SPDX-License-Identifier: Apache-2.0

from re import findall
from urllib.parse import urljoin

from cliff.command import Command
import docker
from jinja2 import Template
from loguru import logger
import requests

from osism import utils
from osism.data import (
    TEMPLATE_IMAGE_CLUSTERAPI,
    TEMPLATE_IMAGE_OCTAVIA,
    TEMPLATE_IMAGE_GARDENLINUX,
    TEMPLATE_IMAGE_CLUSTERAPI_GARDENER,
)
from osism.tasks import openstack, ansible, handle_task

SUPPORTED_CLUSTERAPI_GARDENER_K8S_IMAGES = ["1.33"]
SUPPORTED_CLUSTERAPI_K8S_IMAGES = ["1.32", "1.33", "1.34"]
SUPPORTED_GARDENLINUX_VERSIONS = {"1877.7": "2025-11-14"}


class ImageClusterapi(Command):
    def get_parser(self, prog_name):
        parser = super(ImageClusterapi, self).get_parser(prog_name)

        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until image management has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--base-url",
            type=str,
            help="Base URL",
            default="https://nbg1.your-objectstorage.com/osism/openstack-k8s-capi-images/",
        )
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml (will be overruled by OS_AUTH_URL envvar)",
            default="admin",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not perform any changes (--dry-run passed to openstack-image-manager)",
        )
        parser.add_argument(
            "--tag",
            type=str,
            help="Name of the tag used to identify managed images (use openstack-image-manager's default if unset)",
            default=None,
        )
        parser.add_argument(
            "--filter",
            type=str,
            help="Filter the version to be managed (e.g. 1.32)",
            default=None,
        )
        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        base_url = parsed_args.base_url
        cloud = parsed_args.cloud
        filter = parsed_args.filter
        tag = parsed_args.tag
        wait = not parsed_args.no_wait

        if filter:
            supported_cluterapi_k8s_images = [filter]
        else:
            supported_cluterapi_k8s_images = SUPPORTED_CLUSTERAPI_K8S_IMAGES

        result = []
        for kubernetes_release in supported_cluterapi_k8s_images:
            url = urljoin(base_url, f"last-{kubernetes_release}")

            response = requests.get(url)
            splitted = response.text.strip().split(" ")

            logger.info(f"date: {splitted[0]}")
            logger.info(f"image: {splitted[1]}")

            r = findall(
                r".*ubuntu-[0-9][02468]04-kube-v(.*\..*\..*).qcow2", splitted[1]
            )
            logger.info(f"version: {r[0].strip()}")

            url = urljoin(base_url, splitted[1])
            logger.info(f"url: {url}")

            logger.info(f"checksum_url: {url}.CHECKSUM")
            response_checksum = requests.get(f"{url}.CHECKSUM")
            splitted_checksum = response_checksum.text.strip().split(" ")
            logger.info(f"checksum: {splitted_checksum[0]}")

            template = Template(TEMPLATE_IMAGE_CLUSTERAPI)
            result.extend(
                [
                    template.render(
                        image_url=url,
                        image_checksum=f"sha256:{splitted_checksum[0]}",
                        image_version=r[0].strip(),
                        image_builddate=splitted[0],
                    )
                ]
            )

        args = [
            "--cloud",
            cloud,
            "--filter",
            "ubuntu-capi-image",
            "--stuck-retry",
            "1",
        ]
        if tag is not None:
            args.extend(["--tag", tag])
        if parsed_args.dry_run:
            args.append("--dry-run")

        task_signature = openstack.image_manager.si(*args, configs=result, cloud=cloud)
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (image-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class ImageClusterapiGardener(Command):
    def get_parser(self, prog_name):
        parser = super(ImageClusterapiGardener, self).get_parser(prog_name)

        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until image management has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--base-url",
            type=str,
            help="Base URL",
            default="https://nbg1.your-objectstorage.com/osism/openstack-k8s-capi-images/",
        )
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml (will be overruled by OS_AUTH_URL envvar)",
            default="admin",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not perform any changes (--dry-run passed to openstack-image-manager)",
        )
        parser.add_argument(
            "--tag",
            type=str,
            help="Name of the tag used to identify managed images (use openstack-image-manager's default if unset)",
            default=None,
        )
        parser.add_argument(
            "--filter",
            type=str,
            help="Filter the version to be managed (e.g. 1.33)",
            default=None,
        )
        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        base_url = parsed_args.base_url
        cloud = parsed_args.cloud
        filter = parsed_args.filter
        tag = parsed_args.tag
        wait = not parsed_args.no_wait

        if filter:
            supported_cluterapi_gardener_k8s_images = [filter]
        else:
            supported_cluterapi_gardener_k8s_images = (
                SUPPORTED_CLUSTERAPI_GARDENER_K8S_IMAGES
            )

        result = []
        for kubernetes_release in supported_cluterapi_gardener_k8s_images:
            url = urljoin(base_url, f"last-{kubernetes_release}-gardener")

            response = requests.get(url)
            splitted = response.text.strip().split(" ")

            logger.info(f"date: {splitted[0]}")
            logger.info(f"image: {splitted[1]}")

            r = findall(
                r".*ubuntu-[0-9][02468]04-kube-v(.*\..*\..*)\.qcow2", splitted[1]
            )
            logger.info(f"version: {r[0].strip()}")

            url = urljoin(base_url, splitted[1])
            logger.info(f"url: {url}")

            logger.info(f"checksum_url: {url}.CHECKSUM")
            response_checksum = requests.get(f"{url}.CHECKSUM")
            splitted_checksum = response_checksum.text.strip().split(" ")
            logger.info(f"checksum: {splitted_checksum[0]}")

            template = Template(TEMPLATE_IMAGE_CLUSTERAPI_GARDENER)
            result.extend(
                [
                    template.render(
                        image_url=url,
                        image_checksum=f"sha256:{splitted_checksum[0]}",
                        image_version=r[0].strip(),
                        image_builddate=splitted[0],
                    )
                ]
            )

        args = [
            "--cloud",
            cloud,
            "--filter",
            "ubuntu-capi-image-gardener",
            "--stuck-retry",
            "1",
        ]
        if tag is not None:
            args.extend(["--tag", tag])
        if parsed_args.dry_run:
            args.append("--dry-run")

        task_signature = openstack.image_manager.si(*args, configs=result, cloud=cloud)
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (image-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class ImageGardenlinux(Command):
    def get_parser(self, prog_name):
        parser = super(ImageGardenlinux, self).get_parser(prog_name)

        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until image management has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--base-url",
            type=str,
            help="Base URL",
            default="https://nbg1.your-objectstorage.com/osism/openstack-images/gardenlinux/",
        )
        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml (will be overruled by OS_AUTH_URL envvar)",
            default="admin",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do not perform any changes (--dry-run passed to openstack-image-manager)",
        )
        parser.add_argument(
            "--tag",
            type=str,
            help="Name of the tag used to identify managed images (use openstack-image-manager's default if unset)",
            default=None,
        )
        parser.add_argument(
            "--filter",
            type=str,
            help="Filter the version to be managed (e.g. 1877.2)",
            default=None,
        )
        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        base_url = parsed_args.base_url
        cloud = parsed_args.cloud
        filter = parsed_args.filter
        tag = parsed_args.tag
        wait = not parsed_args.no_wait

        if filter:
            # For filter, we need to handle it as a dict with placeholder build date
            supported_gardenlinux_versions = {filter: "unknown"}
        else:
            supported_gardenlinux_versions = SUPPORTED_GARDENLINUX_VERSIONS

        result = []
        for version, build_date in supported_gardenlinux_versions.items():
            # Garden Linux uses direct URL construction instead of fetching last files
            url = urljoin(
                base_url, f"{version}/openstack-gardener_prod-amd64-{version}.qcow2"
            )
            logger.info(f"url: {url}")

            # Get checksum file
            checksum_url = f"{url}.sha256"
            logger.info(f"checksum_url: {checksum_url}")
            response_checksum = requests.get(checksum_url)
            checksum = response_checksum.text.strip().split()[0]
            logger.info(f"checksum: {checksum}")

            template = Template(TEMPLATE_IMAGE_GARDENLINUX)
            result.extend(
                [
                    template.render(
                        image_url=url,
                        image_checksum=f"sha256:{checksum}",
                        image_version=version,
                        image_builddate=build_date,
                    )
                ]
            )

        args = [
            "--cloud",
            cloud,
            "--filter",
            "garden-linux-image",
            "--stuck-retry",
            "1",
        ]
        if tag is not None:
            args.extend(["--tag", tag])
        if parsed_args.dry_run:
            args.append("--dry-run")

        task_signature = openstack.image_manager.si(*args, configs=result, cloud=cloud)
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (image-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class ImageOctavia(Command):
    def get_parser(self, prog_name):
        parser = super(ImageOctavia, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until image management has been completed",
            action="store_true",
        )

        parser.add_argument(
            "--cloud",
            type=str,
            help="Cloud name in clouds.yaml (will be overruled by OS_AUTH_URL envvar)",
            default="octavia",
        )
        parser.add_argument(
            "--base-url",
            type=str,
            help="Base URL",
            default="https://nbg1.your-objectstorage.com/osism/openstack-octavia-amphora-image/",
        )
        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        wait = not parsed_args.no_wait
        cloud = parsed_args.cloud
        base_url = parsed_args.base_url

        client = docker.from_env()
        container = client.containers.get("kolla-ansible")
        openstack_release = container.labels["de.osism.release.openstack"]
        url = urljoin(base_url, f"last-{openstack_release}")

        response = requests.get(url)
        splitted = response.text.strip().split(" ")

        logger.info(f"date: {splitted[0]}")
        logger.info(f"image: {splitted[1]}")

        url = urljoin(base_url, splitted[1])
        logger.info(f"url: {url}")

        logger.info(f"checksum_url: {url}.CHECKSUM")
        response_checksum = requests.get(f"{url}.CHECKSUM")
        splitted_checksum = response_checksum.text.strip().split(" ")
        logger.info(f"checksum: {splitted_checksum[0]}")

        template = Template(TEMPLATE_IMAGE_OCTAVIA)
        result = []
        result.extend(
            [
                template.render(
                    image_url=url,
                    image_checksum=f"sha256:{splitted_checksum[0]}",
                    image_version=splitted[0],
                    image_builddate=splitted[0],
                )
            ]
        )
        arguments = [
            "--cloud",
            cloud,
            "--deactivate",
            "--stuck-retry",
            "1",
        ]

        task_signature = openstack.image_manager.si(
            *arguments, configs=result, cloud=cloud
        )
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (image-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class Images(Command):
    def get_parser(self, prog_name):
        parser = super(Images, self).get_parser(prog_name)

        # NOTE: This is a workaround. argparse.REMAINDER does not work well to pass all
        # arguments to openstack-image-manager. This is improved by switching from cliff
        # to typer. Then openstack-image-manager can simply be included directly at this
        # point.

        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until image management has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--dry-run",
            default=False,
            help="Do not perform any changes",
            action="store_true",
        )
        parser.add_argument(
            "--hide",
            default=True,
            help="Hide images that should be deleted",
            action="store_true",
        )
        parser.add_argument(
            "--delete",
            default=False,
            help="Delete images that should be deleted",
            action="store_true",
        )
        parser.add_argument(
            "--latest",
            default=False,
            help="Only import the latest version for images of type multi",
            action="store_true",
        )
        parser.add_argument(
            "--cloud", type=str, help="Cloud name in clouds.yaml", default="openstack"
        )
        parser.add_argument(
            "--filter",
            type=str,
            help="Filter images with a regex on their name",
            default=None,
        )
        parser.add_argument(
            "--images",
            type=str,
            help="Path to the directory containing all image files or path to single image file",
            default=None,
        )

        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        wait = not parsed_args.no_wait

        arguments = []
        if parsed_args.cloud:
            arguments.append("--cloud")
            arguments.append(parsed_args.cloud)
        if parsed_args.filter:
            arguments.append("--filter")
            arguments.append(parsed_args.filter)
        if parsed_args.delete:
            arguments.append("--delete")
            arguments.append("--yes-i-really-know-what-i-do")
        if parsed_args.dry_run:
            arguments.append("--dry-run")
        if parsed_args.latest:
            arguments.append("--latest")
        if parsed_args.hide:
            arguments.append("--hide")

        arguments.append("--images")
        if parsed_args.images:
            arguments.append(parsed_args.images)
        else:
            arguments.append("/etc/images")

        arguments.append("--stuck-retry")
        arguments.append("1")

        task_signature = openstack.image_manager.si(*arguments, cloud=parsed_args.cloud)
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (image-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class Flavors(Command):
    def get_parser(self, prog_name):
        parser = super(Flavors, self).get_parser(prog_name)

        # NOTE: This is a workaround. argparse.REMAINDER does not work well to pass all
        # arguments to openstack-image-manager. This is improved by switching from cliff
        # to typer. Then openstack-flavor-manager can simply be included directly at this
        # point.

        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until flavor management has been completed",
            action="store_true",
        )
        parser.add_argument(
            "--cloud", type=str, help="Cloud name in clouds.yaml", default="admin"
        )
        parser.add_argument(
            "--name",
            type=str,
            help="Name of flavor definitions",
            default="local",
            choices=["cloudpod", "scs", "osism", "local", "url"],
        )
        parser.add_argument(
            "--url",
            type=str,
            help="Overwrite the default URL where the flavor definitions are available",
            default=None,
        )
        parser.add_argument(
            "--recommended",
            default=False,
            help="Also create recommended flavors",
            action="store_true",
        )

        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        wait = not parsed_args.no_wait
        cloud = parsed_args.cloud
        name = parsed_args.name
        recommended = parsed_args.recommended
        url = parsed_args.url

        arguments = ["--name", name]
        if cloud:
            arguments.append("--cloud")
            arguments.append(cloud)

        if recommended:
            arguments.append("--recommended")

        if url:
            arguments.append("--url")
            arguments.append(url)

        task_signature = openstack.flavor_manager.si(*arguments, cloud=cloud)
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (flavor-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class Dnsmasq(Command):
    def get_parser(self, prog_name):
        parser = super(Dnsmasq, self).get_parser(prog_name)
        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until dnsmasq has been applied",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        wait = not parsed_args.no_wait

        task_signature = ansible.run.si("infrastructure", "dnsmasq", [])
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (dnsmasq) has been started and output is visible here."
            )

        return handle_task(task, wait, format="log", timeout=300)


class ProjectCreate(Command):
    def get_parser(self, prog_name):
        parser = super(ProjectCreate, self).get_parser(prog_name)

        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until project creation has been completed",
            action="store_true",
        )

        # Boolean flags with positive and negative forms
        parser.add_argument(
            "--assign-admin-user",
            dest="assign_admin_user",
            default=True,
            help="Assign admin user to the project (default: True)",
            action="store_true",
        )
        parser.add_argument(
            "--noassign-admin-user",
            dest="assign_admin_user",
            help="Do not assign admin user to the project",
            action="store_false",
        )

        parser.add_argument(
            "--create-admin-user",
            dest="create_admin_user",
            default=True,
            help="Create admin user for the project (default: True)",
            action="store_true",
        )
        parser.add_argument(
            "--nocreate-admin-user",
            dest="create_admin_user",
            help="Do not create admin user for the project",
            action="store_false",
        )

        parser.add_argument(
            "--create-domain",
            dest="create_domain",
            default=False,
            help="Create a new domain for the project (default: False)",
            action="store_true",
        )
        parser.add_argument(
            "--nocreate-domain",
            dest="create_domain",
            help="Do not create a new domain for the project",
            action="store_false",
        )

        parser.add_argument(
            "--create-user",
            dest="create_user",
            default=False,
            help="Create a new user for the project (default: False)",
            action="store_true",
        )
        parser.add_argument(
            "--nocreate-user",
            dest="create_user",
            help="Do not create a new user for the project",
            action="store_false",
        )

        parser.add_argument(
            "--create-application-credential",
            dest="create_application_credential",
            default=False,
            help="Create application credential for user (default: False)",
            action="store_true",
        )
        parser.add_argument(
            "--nocreate-application-credential",
            dest="create_application_credential",
            help="Do not create application credential for user",
            action="store_false",
        )

        parser.add_argument(
            "--domain-name-prefix",
            dest="domain_name_prefix",
            default=True,
            help="Use domain name as prefix for project name (default: True)",
            action="store_true",
        )
        parser.add_argument(
            "--nodomain-name-prefix",
            dest="domain_name_prefix",
            help="Do not use domain name as prefix for project name",
            action="store_false",
        )

        parser.add_argument(
            "--has-service-network",
            dest="has_service_network",
            default=False,
            help="Create a service network for the project (default: False)",
            action="store_true",
        )
        parser.add_argument(
            "--nohas-service-network",
            dest="has_service_network",
            help="Do not create a service network for the project",
            action="store_false",
        )

        parser.add_argument(
            "--has-public-network",
            dest="has_public_network",
            default=True,
            help="Attach public network to the project (default: True)",
            action="store_true",
        )
        parser.add_argument(
            "--nohas-public-network",
            dest="has_public_network",
            help="Do not attach public network to the project",
            action="store_false",
        )

        parser.add_argument(
            "--has-shared-images",
            dest="has_shared_images",
            default=True,
            help="Allow access to shared images (default: True)",
            action="store_true",
        )
        parser.add_argument(
            "--nohas-shared-images",
            dest="has_shared_images",
            help="Do not allow access to shared images",
            action="store_false",
        )

        parser.add_argument(
            "--random",
            dest="random",
            default=False,
            help="Use random values for certain parameters (default: False)",
            action="store_true",
        )
        parser.add_argument(
            "--norandom",
            dest="random",
            help="Do not use random values",
            action="store_false",
        )

        parser.add_argument(
            "--managed-network-resources",
            dest="managed_network_resources",
            default=False,
            help="Manage network resources (default: False)",
            action="store_true",
        )
        parser.add_argument(
            "--nomanaged-network-resources",
            dest="managed_network_resources",
            help="Do not manage network resources",
            action="store_false",
        )

        # Integer arguments
        parser.add_argument(
            "--password-length",
            dest="password_length",
            type=int,
            default=16,
            help="Length of generated passwords (default: 16)",
        )

        parser.add_argument(
            "--quota-multiplier",
            dest="quota_multiplier",
            type=int,
            default=1,
            help="Quota multiplier for all resources (default: 1)",
        )

        parser.add_argument(
            "--quota-multiplier-compute",
            dest="quota_multiplier_compute",
            type=int,
            default=None,
            help="Quota multiplier for compute resources (default: None)",
        )

        parser.add_argument(
            "--quota-multiplier-network",
            dest="quota_multiplier_network",
            type=int,
            default=None,
            help="Quota multiplier for network resources (default: None)",
        )

        parser.add_argument(
            "--quota-multiplier-storage",
            dest="quota_multiplier_storage",
            type=int,
            default=None,
            help="Quota multiplier for storage resources (default: None)",
        )

        parser.add_argument(
            "--quota-router",
            dest="quota_router",
            type=int,
            default=1,
            help="Router quota (default: 1)",
        )

        # String arguments
        parser.add_argument(
            "--admin-domain",
            dest="admin_domain",
            type=str,
            default="default",
            help="Admin domain name (default: default)",
        )

        parser.add_argument(
            "--cloud",
            type=str,
            default="admin",
            help="Cloud name in clouds.yaml (default: admin)",
        )

        parser.add_argument(
            "--domain",
            type=str,
            default="default",
            help="Domain name for the project (default: default)",
        )

        parser.add_argument(
            "--internal-id",
            dest="internal_id",
            type=str,
            default=None,
            help="Internal ID for the project (default: None)",
        )

        parser.add_argument(
            "--name",
            type=str,
            default="sandbox",
            help="Project name (default: sandbox)",
        )

        parser.add_argument(
            "--owner",
            type=str,
            default=None,
            help="Project owner (default: None)",
        )

        parser.add_argument(
            "--password",
            type=str,
            default=None,
            help="Password for created users (default: None, auto-generated)",
        )

        parser.add_argument(
            "--public-network",
            dest="public_network",
            type=str,
            default="public",
            help="Public network name (default: public)",
        )

        parser.add_argument(
            "--quota-class",
            dest="quota_class",
            type=str,
            default="basic",
            help="Quota class to apply (default: basic)",
        )

        parser.add_argument(
            "--service-network-cidr",
            dest="service_network_cidr",
            type=str,
            default=None,
            help="Service network CIDR (default: None)",
        )

        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        wait = not parsed_args.no_wait
        cloud = parsed_args.cloud

        # Build arguments list from all parsed_args
        arguments = []

        # Add boolean flags
        if parsed_args.assign_admin_user:
            arguments.append("--assign-admin-user")
        else:
            arguments.append("--noassign-admin-user")

        if parsed_args.create_admin_user:
            arguments.append("--create-admin-user")
        else:
            arguments.append("--nocreate-admin-user")

        if parsed_args.create_domain:
            arguments.append("--create-domain")
        else:
            arguments.append("--nocreate-domain")

        if parsed_args.create_user:
            arguments.append("--create-user")
        else:
            arguments.append("--nocreate-user")

        if parsed_args.create_application_credential:
            arguments.append("--create-application-credential")
        else:
            arguments.append("--nocreate-application-credential")

        if parsed_args.domain_name_prefix:
            arguments.append("--domain-name-prefix")
        else:
            arguments.append("--nodomain-name-prefix")

        if parsed_args.has_service_network:
            arguments.append("--has-service-network")
        else:
            arguments.append("--nohas-service-network")

        if parsed_args.has_public_network:
            arguments.append("--has-public-network")
        else:
            arguments.append("--nohas-public-network")

        if parsed_args.has_shared_images:
            arguments.append("--has-shared-images")
        else:
            arguments.append("--nohas-shared-images")

        if parsed_args.random:
            arguments.append("--random")
        else:
            arguments.append("--norandom")

        if parsed_args.managed_network_resources:
            arguments.append("--managed-network-resources")
        else:
            arguments.append("--nomanaged-network-resources")

        # Add integer arguments
        arguments.extend(["--password-length", str(parsed_args.password_length)])
        arguments.extend(["--quota-multiplier", str(parsed_args.quota_multiplier)])
        arguments.extend(["--quota-router", str(parsed_args.quota_router)])

        if parsed_args.quota_multiplier_compute is not None:
            arguments.extend(
                [
                    "--quota-multiplier-compute",
                    str(parsed_args.quota_multiplier_compute),
                ]
            )

        if parsed_args.quota_multiplier_network is not None:
            arguments.extend(
                [
                    "--quota-multiplier-network",
                    str(parsed_args.quota_multiplier_network),
                ]
            )

        if parsed_args.quota_multiplier_storage is not None:
            arguments.extend(
                [
                    "--quota-multiplier-storage",
                    str(parsed_args.quota_multiplier_storage),
                ]
            )

        # Add string arguments
        arguments.extend(["--admin-domain", parsed_args.admin_domain])
        arguments.extend(["--cloud", cloud])
        arguments.extend(["--domain", parsed_args.domain])
        arguments.extend(["--name", parsed_args.name])
        arguments.extend(["--public-network", parsed_args.public_network])
        arguments.extend(["--quota-class", parsed_args.quota_class])

        if parsed_args.internal_id is not None:
            arguments.extend(["--internal-id", parsed_args.internal_id])

        if parsed_args.owner is not None:
            arguments.extend(["--owner", parsed_args.owner])

        if parsed_args.password is not None:
            arguments.extend(["--password", parsed_args.password])

        if parsed_args.service_network_cidr is not None:
            arguments.extend(
                ["--service-network-cidr", parsed_args.service_network_cidr]
            )

        # Call the task
        task_signature = openstack.project_manager.si(*arguments, cloud=cloud)
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (project-manager) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)


class ProjectSync(Command):
    def get_parser(self, prog_name):
        parser = super(ProjectSync, self).get_parser(prog_name)

        # Boolean flags
        parser.add_argument(
            "--assign-admin-user",
            dest="assign_admin_user",
            default=False,
            help="Assign admin user to projects (default: False)",
            action="store_true",
        )
        parser.add_argument(
            "--noassign-admin-user",
            dest="assign_admin_user",
            help="Do not assign admin user to projects",
            action="store_false",
        )

        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            default=False,
            help="Do not really do anything, just simulate (default: False)",
            action="store_true",
        )
        parser.add_argument(
            "--nodry-run",
            dest="dry_run",
            help="Execute actions (not a dry run)",
            action="store_false",
        )

        parser.add_argument(
            "--manage-endpoints",
            dest="manage_endpoints",
            default=False,
            help="Manage endpoints (default: False)",
            action="store_true",
        )
        parser.add_argument(
            "--nomanage-endpoints",
            dest="manage_endpoints",
            help="Do not manage endpoints",
            action="store_false",
        )

        parser.add_argument(
            "--manage-homeprojects",
            dest="manage_homeprojects",
            default=False,
            help="Manage home projects (default: False)",
            action="store_true",
        )
        parser.add_argument(
            "--nomanage-homeprojects",
            dest="manage_homeprojects",
            help="Do not manage home projects",
            action="store_false",
        )

        parser.add_argument(
            "--manage-privatevolumetypes",
            dest="manage_privatevolumetypes",
            default=True,
            help="Manage private volume types (default: True)",
            action="store_true",
        )
        parser.add_argument(
            "--nomanage-privatevolumetypes",
            dest="manage_privatevolumetypes",
            help="Do not manage private volume types",
            action="store_false",
        )

        parser.add_argument(
            "--manage-privateflavors",
            dest="manage_privateflavors",
            default=True,
            help="Manage private flavors (default: True)",
            action="store_true",
        )
        parser.add_argument(
            "--nomanage-privateflavors",
            dest="manage_privateflavors",
            help="Do not manage private flavors",
            action="store_false",
        )

        # String arguments
        parser.add_argument(
            "--admin-domain",
            dest="admin_domain",
            type=str,
            default="default",
            help="Admin domain name (default: default)",
        )

        parser.add_argument(
            "--classes",
            type=str,
            default="etc/classes.yml",
            help="Path to the classes.yml file (default: etc/classes.yml)",
        )

        parser.add_argument(
            "--endpoints",
            type=str,
            default="etc/endpoints.yml",
            help="Path to the endpoints.yml file (default: etc/endpoints.yml)",
        )

        parser.add_argument(
            "--cloud",
            type=str,
            default="admin",
            help="Cloud name in clouds.yaml (default: admin)",
        )

        parser.add_argument(
            "--domain",
            type=str,
            default=None,
            help="Domain to be managed (default: None)",
        )

        parser.add_argument(
            "--name",
            type=str,
            default=None,
            help="Project to be managed (default: None)",
        )

        parser.add_argument(
            "--no-wait",
            default=False,
            help="Do not wait until project sync has been completed",
            action="store_true",
        )

        return parser

    def take_action(self, parsed_args):
        # Check if tasks are locked before proceeding
        utils.check_task_lock_and_exit()

        wait = not parsed_args.no_wait
        cloud = parsed_args.cloud

        # Build arguments list from all parsed_args
        arguments = []

        # Add boolean flags
        if parsed_args.assign_admin_user:
            arguments.append("--assign-admin-user")
        else:
            arguments.append("--noassign-admin-user")

        if parsed_args.dry_run:
            arguments.append("--dry-run")
        else:
            arguments.append("--nodry-run")

        if parsed_args.manage_endpoints:
            arguments.append("--manage-endpoints")
        else:
            arguments.append("--nomanage-endpoints")

        if parsed_args.manage_homeprojects:
            arguments.append("--manage-homeprojects")
        else:
            arguments.append("--nomanage-homeprojects")

        if parsed_args.manage_privatevolumetypes:
            arguments.append("--manage-privatevolumetypes")
        else:
            arguments.append("--nomanage-privatevolumetypes")

        if parsed_args.manage_privateflavors:
            arguments.append("--manage-privateflavors")
        else:
            arguments.append("--nomanage-privateflavors")

        # Add string arguments
        arguments.extend(["--admin-domain", parsed_args.admin_domain])
        arguments.extend(["--classes", parsed_args.classes])
        arguments.extend(["--endpoints", parsed_args.endpoints])
        arguments.extend(["--cloud", cloud])

        if parsed_args.domain is not None:
            arguments.extend(["--domain", parsed_args.domain])

        if parsed_args.name is not None:
            arguments.extend(["--name", parsed_args.name])

        # Call the task
        task_signature = openstack.project_manager_sync.si(*arguments, cloud=cloud)
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (project-manager-sync) has been started and output is visible here."
            )

        return handle_task(task, wait, format="script", timeout=3600)
