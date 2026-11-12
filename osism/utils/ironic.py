# SPDX-License-Identifier: Apache-2.0

"""Ironic helpers that need more than openstacksdk exposes.

Importing this module imports openstacksdk; import it where it is used,
not at the top of a command module.
"""

from openstack import resource
from openstack.baremetal.v1.node import Node


class DetailedNode(Node):
    """An Ironic node that also keeps ``provision_updated_at``.

    Ironic returns ``provision_updated_at`` (when the node entered its
    current provision state) with every detailed node, but openstacksdk's
    ``Node`` has no attribute for it, so the SDK drops the value while
    parsing the response. Declaring the field here keeps it. Remove the
    declaration once openstacksdk maps the field itself.
    """

    # openstacksdk looks up the alternate id only in the class's own
    # __dict__, not in its bases. Without repeating the declaration a
    # subclass of Node loses the "uuid" -> id mapping and every node's id
    # is None.
    id = resource.Body("uuid", alternate_id=True)

    provision_updated_at = resource.Body("provision_updated_at")


def list_detailed_nodes(conn, **query):
    """List nodes with all fields, as ``conn.baremetal.nodes(details=True)``.

    This goes through the same request and microversion negotiation as the
    SDK's own proxy method; only the resource class differs.
    """
    return DetailedNode.list(conn.baremetal, details=True, **query)
