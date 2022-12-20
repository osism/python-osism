import sys

from cliff.app import App
from cliff.commandmanager import CommandManager

from . import __version__


class OsismApp(App):
    def __init__(self):
        super(OsismApp, self).__init__(
            description="OSISM manager interface",
            version=__version__,
            command_manager=CommandManager("osism.commands"),
            deferred_help=True,
        )


def main(argv=sys.argv[1:]):
    app = OsismApp()
    result = app.run(argv)
    return result


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
