"""Event hooks, numbered in the order they were added."""


def handler2(event):
    return {"event": event, "stage": "legacy"}


def handler_2(event):
    return {"event": event, "stage": "second"}


def handler_3(event):
    return {"event": event, "stage": "third"}
