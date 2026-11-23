"""The till for printed copies sold at the counter."""


def flush(till):
    total = sum(till)
    till.clear()
    return total
