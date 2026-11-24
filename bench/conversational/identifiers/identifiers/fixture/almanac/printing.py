"""Page layout for the printed almanac."""


def write_column(page, text):
    page.setdefault("left", []).append(text)
    return page


def write_columns(page, rows):
    for row in rows:
        write_column(page, row)
    return page


def right_column(page):
    return page.get("right", [])
