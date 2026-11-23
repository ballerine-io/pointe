"""Version 1 of the HTTP API."""


def list_events(request):
    return {"events": [], "version": 1}
