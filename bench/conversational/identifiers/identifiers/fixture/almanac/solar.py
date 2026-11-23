"""Sun times and seasons."""

DEFAULT_ZONE = "UTC"


def default_zone():
    return DEFAULT_ZONE


def sunrise_offset(lat):
    return round(lat / 15.0, 2)


def sunrise_offsets(lats):
    return [sunrise_offset(lat) for lat in lats]


def peak_season(year):
    return (year, "summer")


def peek_season(year):
    return (year + 1, "spring")


def sunday_index(day):
    return (6 - day.weekday()) % 7


def sun_day_index(day):
    return day.timetuple().tm_yday


def round_to_15(minutes):
    return 15 * round(minutes / 15)


def round_to_5(minutes):
    return 5 * round(minutes / 5)
