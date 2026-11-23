"""The in-memory cache of computed pages."""


def flush(store):
    store.clear()
    return store
