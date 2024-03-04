# SPDX-License-Identifier: Apache-2.0

import os
from re import findall
import subprocess
from urllib.parse import urljoin

from cliff.command import Command
import docker
from jinja2 import Template
from loguru import logger
import requests

from osism.data import TEMPLATE_IMAGE_CLUSTERAPI, TEMPLATE_IMAGE_OCTAVIA


class ImageClusterapi(Command):
    def get_parser(self, prog_name):
        parser = super(ImageClusterapi, self).get_parser(prog_name)

        parser.add_argument(
            "--cloud", type=str, help="Cloud name in clouds.yaml", default="openstack"
        )
        parser.add_argument(
            "--base-url",
            type=str,
            help="Base URL",
            default="https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-k8s-capi-images/",
        )
        return parser

    def take_action(self, parsed_args):
        cloud = parsed_args.cloud
        base_url = parsed_args.base_url

        os.makedirs("/tmp/clusterapi", exist_ok=True)
        for kubernetes_release in ["1.27", "1.28", "1.29"]:
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
            result = template.render(
                image_url=url,
                image_checksum=f"sha256:{splitted_checksum[0]}",
                image_version=r[0].strip(),
                image_builddate=splitted[0],
            )
            with open(f"/tmp/clusterapi/k8s-{kubernetes_release}.yml", "w+") as fp:
                fp.write(result)

        subprocess.call(
            "/usr/local/bin/openstack-image-manager --images=/tmp/clusterapi --cloud admin --filter 'Kubernetes CAPI'",
            shell=True,
        )


class ImageOctavia(Command):
    def get_parser(self, prog_name):
        parser = super(ImageOctavia, self).get_parser(prog_name)

        parser.add_argument(
            "--cloud", type=str, help="Cloud name in clouds.yaml", default="openstack"
        )
        parser.add_argument(
            "--base-url",
            type=str,
            help="Base URL",
            default="https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-octavia-amphora-image/",
        )
        return parser

    def take_action(self, parsed_args):
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
        result = template.render(
            image_url=url,
            image_checksum=f"sha256:{splitted_checksum[0]}",
            image_version=splitted[0],
            image_builddate=splitted[0],
        )

        os.makedirs("/tmp/octavia", exist_ok=True)
        with open("/tmp/octavia/octavia.yml", "w+") as fp:
            fp.write(result)

        subprocess.call(
            "/usr/local/bin/openstack-image-manager --images=/tmp/octavia --cloud octavia --deactivate",
            shell=True,
        )


class Images(Command):
    def get_parser(self, prog_name):
        parser = super(Images, self).get_parser(prog_name)

        # NOTE: This is a workaround. argparse.REMAINDER does not work well to pass all
        # arguments to openstack-image-manager. This is improved by switching from cliff
        # to typer. Then openstack-image-manager can simply be included directly at this
        # point.

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
            "--latest",
            default=False,
            help="Only import the latest version for images of type multi",
            action="store_true",
        )
        parser.add_argument(
            "--cloud", type=str, help="Cloud name in clouds.yaml", default="openstack"
        )
        parser.add_argument(
            "--hypervisor",
            type=str,
            help="Set hypervisor type meta information",
            default=None,
        )
        parser.add_argument(
            "--filter",
            type=str,
            help="Filter images with a regex on their name",
            default=None,
        )
        parser.add_argument(
            "--name",
            type=str,
            action="append",
            help="Name of the image to process, use repeatedly for multiple images",
        )

        return parser

    def take_action(self, parsed_args):
        cloud = parsed_args.cloud
        dry_run = parsed_args.dry_run
        filter = parsed_args.filter
        hide = parsed_args.hide
        hypervisor = parsed_args.hypervisor
        latest = parsed_args.latest
        names = parsed_args.name

        arguments = []
        if cloud:
            arguments.append(f"--cloud '{cloud}'")
        if filter:
            arguments.append(f"--filter '{filter}'")
        if dry_run:
            arguments.append("--dry-run")
        if latest:
            arguments.append("--latest")
        if hide:
            arguments.append("--hide")
        if hypervisor:
            arguments.append(f"--hypervisor '{hypervisor}'")
        if names:
            for name in names:
                arguments.append(f"--name '{name}'")

        joined_arguments = " ".join(arguments)
        subprocess.call(
            f"/usr/local/bin/openstack-image-manager --images=/etc/images {joined_arguments}",
            shell=True,
        )


class Flavors(Command):
    def get_parser(self, prog_name):
        parser = super(Flavors, self).get_parser(prog_name)

        # NOTE: This is a workaround. argparse.REMAINDER does not work well to pass all
        # arguments to openstack-image-manager. This is improved by switching from cliff
        # to typer. Then openstack-flavor-manager can simply be included directly at this
        # point.

        parser.add_argument(
            "--cloud", type=str, help="Cloud name in clouds.yaml", default="admin"
        )

        return parser

    def take_action(self, parsed_args):
        cloud = parsed_args.cloud

        arguments = []
        if cloud:
            arguments.append(f"--cloud '{cloud}'")

        joined_arguments = " ".join(arguments)
        subprocess.call(
            f"/usr/local/bin/openstack-flavor-manager {joined_arguments}",
            shell=True,
        )
