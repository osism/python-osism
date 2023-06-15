from osism import settings
import pynetbox
from redis import Redis

redis = Redis(host="redis", port="6379")

if settings.NETBOX_URL and settings.NETBOX_TOKEN:
    nb = pynetbox.api(settings.NETBOX_URL, token=settings.NETBOX_TOKEN)

    if settings.IGNORE_SSL_ERRORS and nb:
        import requests

        requests.packages.urllib3.disable_warnings()
        session = requests.Session()
        session.verify = False
        nb.http_session = session

else:
    nb = None


# https://stackoverflow.com/questions/2361426/get-the-first-item-from-an-iterable-that-matches-a-condition
def first(iterable, condition=lambda x: True):
    """
    Returns the first item in the `iterable` that
    satisfies the `condition`.

    If the condition is not given, returns the first item of
    the iterable.

    Raises `StopIteration` if no item satysfing the condition is found.

    >>> first( (1,2,3), condition=lambda x: x % 2 == 0)
    2
    >>> first(range(3, 100))
    3
    >>> first( () )
    Traceback (most recent call last):
    ...
    StopIteration
    """

    return next(x for x in iterable if condition(x))
