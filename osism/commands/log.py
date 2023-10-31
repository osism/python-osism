# SPDX-License-Identifier: Apache-2.0

import argparse
import json
import subprocess

from cliff.command import Command
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
import requests

from osism import settings


class Ansible(Command):
    def get_parser(self, prog_name):
        parser = super(Ansible, self).get_parser(prog_name)
        parser.add_argument(
            "parameter",
            nargs=argparse.REMAINDER,
            type=str,
            help="Parameters to add (all paraemters of the ara command are possible)",
        )
        return parser

    def take_action(self, parsed_args):
        parameters = " ".join(parsed_args.parameter)
        subprocess.call(
            f"/usr/local/bin/ara {parameters}",
            shell=True,
        )


class Container(Command):
    def get_parser(self, prog_name):
        parser = super(Container, self).get_parser(prog_name)
        parser.add_argument("host", nargs=1, type=str, help="Hostname or address")
        parser.add_argument(
            "container", nargs=1, type=str, help="Name of the container"
        )
        parser.add_argument(
            "parameter",
            nargs=argparse.REMAINDER,
            type=str,
            help="Parameters to add (all paraemters of the docker logs command are possible)",
        )
        return parser

    def take_action(self, parsed_args):
        host = parsed_args.host[0]
        container_name = parsed_args.container[0]
        parameters = " ".join(parsed_args.parameter)

        ssh_command = f"docker logs {parameters} {container_name}"
        ssh_options = "-o StrictHostKeyChecking=no -o LogLevel=ERROR"

        # FIXME: use paramiko or something else more Pythonic + make operator user + key configurable
        subprocess.call(
            f"/usr/bin/ssh -i /ansible/secrets/id_rsa.operator {ssh_options} dragon@{host} {ssh_command}",
            shell=True,
        )


class File(Command):
    def get_parser(self, prog_name):
        parser = super(File, self).get_parser(prog_name)
        parser.add_argument("host", nargs=1, type=str, help="Hostname or address")
        return parser

    def take_action(self, parsed_args):
        print("NOT YET IMPLEMENTED")


class Opensearch(Command):
    def get_parser(self, prog_name):
        parser = super(Opensearch, self).get_parser(prog_name)
        parser.add_argument(
            "--verbose",
            default=False,
            help="Verbose output",
            action="store_true",
        )
        return parser

    def take_action(self, parsed_args):
        session = PromptSession(history=FileHistory("/tmp/.opensearch.history"))
        verbose = parsed_args.verbose

        while True:
            query = session.prompt(">>> ")
            if query in ["Exit", "exit", "EXIT"]:
                break

            result = requests.post(
                f"{settings.OPENSEARCH_PROTOCOL}://{settings.OPENSEARCH_ADDRESS}:{settings.OPENSEARCH_PORT}/_plugins/_sql?format=json",
                data=json.dumps({"query": query}),
                headers={"content-type": "application/json"},
                verify=False,
            )
            data = result.json()
            if "hits" in data:
                for hit in data["hits"]["hits"]:
                    source = hit["_source"]
                    if verbose:
                        if "timestamp" not in source:
                            source["timestamp"] = source["@timestamp"]

                        if "programname" in source:
                            print(
                                f"{source['timestamp']} | {source['Hostname']} | {source['programname']} | {source['Payload']}"
                            )
                        else:
                            print(
                                f"{source['timestamp']} | {source['Hostname']} | {source['Payload']}"
                            )
                    else:
                        print(source["Payload"])
            else:
                print(data)
