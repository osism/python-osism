# SPDX-License-Identifier: Apache-2.0

from functools import lru_cache
import keystoneauth1
import openstack


@lru_cache
def get_cloud_connection(profile="admin"):
    try:
        conn = openstack.connect(cloud=profile)
    except keystoneauth1.exceptions.auth_plugins.MissingRequiredOptions:
        pass

    return conn


@lru_cache
def get_cloud_project(project_id):
    conn = get_cloud_connection()
    return conn.identity.get_project(project_id)
