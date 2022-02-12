import logging

from oslo_config import cfg
import oslo_messaging


class NotificationEndpoint(object):

    # https://docs.openstack.org/ironic/latest/admin/notifications.html
    filter_rule = oslo_messaging.NotificationFilter(
        publisher_id='^baremetal.*')

    def warn(self, ctxt, publisher_id, event_type, payload, metadata):
        logging.info(payload)


def main():
    transport = oslo_messaging.get_notification_transport(cfg.CONF)
    targets = [
        oslo_messaging.Target(topic='notifications'),
    ]
    endpoints = [
        NotificationEndpoint()
    ]
    pool = "listener-workers"
    server = oslo_messaging.get_notification_listener(
        transport,
        targets,
        endpoints,
        pool=pool
    )
    server.start()
    server.wait()


if __name__ == "__main__":
    main()
