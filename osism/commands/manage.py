# SPDX-License-Identifier: Apache-2.0

from re import findall
from urllib.parse import urljoin

from cliff.command import Command
import docker
from jinja2 import Template
from loguru import logger
import requests

from osism.data import TEMPLATE_IMAGE_CLUSTERAPI, TEMPLATE_IMAGE_OCTAVIA
from osism.tasks import openstack, ansible, handle_task

SUPPORTED_CLUSTERAPI_K8S_IMAGES = ["1.31", "1.32", "1.33"]


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
            default="https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-k8s-capi-images/",
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

            r = findall(r".*ubuntu-2204-kube-v(.*\..*\..*).qcow2", splitted[1])
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
        ]
        if tag is not None:
            args.extend(["--tag", tag])
        if parsed_args.dry_run:
            args.append("--dry-run")

        task_signature = openstack.image_manager.si(*args, configs=result)
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
            default="https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-octavia-amphora-image/",
        )
        return parser

    def take_action(self, parsed_args):
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
        ]

        task_signature = openstack.image_manager.si(
            *arguments, configs=result, ignore_env=True
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

        task_signature = openstack.image_manager.si(*arguments)
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
            default="scs",
            choices=["scs", "osism", "local", "url"],
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

        task_signature = openstack.flavor_manager.si(*arguments)
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
        wait = not parsed_args.no_wait

        task_signature = ansible.run.si("infrastructure", "dnsmasq", [])
        task = task_signature.apply_async()
        if wait:
            logger.info(
                f"It takes a moment until task {task.task_id} (dnsmasq) has been started and output is visible here."
            )

        return handle_task(task, wait, format="log", timeout=300)
