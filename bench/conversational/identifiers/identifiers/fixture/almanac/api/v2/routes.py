"""Version 2 of the HTTP API."""


def list_events(request):
    return {"items": [], "next": None, "version": 2}
