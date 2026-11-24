"""Holiday rules, read from a text file."""


def load_holiday_rules(path):
    with open(path, encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]


def load_holiday_rule(path, name):
    return next((rule for rule in load_holiday_rules(path) if rule.startswith(name)), None)
