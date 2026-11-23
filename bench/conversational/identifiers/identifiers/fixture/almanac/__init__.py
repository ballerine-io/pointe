"""The almanac service."""

__version__ = "0.4.1"

VERSION = (0, 4, 1)


def version():
    return ".".join(str(part) for part in VERSION)
