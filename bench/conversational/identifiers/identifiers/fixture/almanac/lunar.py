"""Moon phases."""

PHASES = ("new", "waxing", "full", "waning")


def parse_moon_phase(text):
    word = text.strip().lower()
    return word if word in PHASES else None


def parse_moon_phases(lines):
    return [parse_moon_phase(line) for line in lines]


class MoonCalendar:
    def __init__(self, year):
        self.year = year
        self.days = {}

    def init(self):
        self.days = {day: None for day in range(1, 366)}
        return self
