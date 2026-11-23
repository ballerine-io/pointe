"""Entry rendering, two formats."""


def render_v1(entry):
    return f"{entry['date']}: {entry['text']}"


def render_v2(entry):
    return {"date": entry["date"], "text": entry["text"], "format": 2}
