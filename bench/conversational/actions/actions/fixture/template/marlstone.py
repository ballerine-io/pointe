"""Stock counts for an invented warehouse."""


def total(rows: list[tuple[str, int]]) -> int:
    return sum(count for _, count in rows)


def low_stock(rows: list[tuple[str, int]], floor: int = 5) -> list[str]:
    return [name for name, count in rows if count < floor]
