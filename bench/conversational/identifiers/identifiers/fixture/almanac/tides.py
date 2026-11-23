"""Tide tables."""

MAX_TIDE_HEIGHT = 12.5

MAX_TIDE_HEIGHTS = {"north": 9.0, "south": 12.5}


def get_tide_table(port):
    return {"port": port, "rows": []}


def max_tide_height(table):
    return max((row["height"] for row in table["rows"]), default=0.0)
