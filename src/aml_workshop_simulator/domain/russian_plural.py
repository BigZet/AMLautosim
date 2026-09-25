"""Russian plural forms for integer counts."""


def russian_plural(value: int, one: str, few: str, many: str) -> str:
    value = abs(value)
    if 11 <= value % 100 <= 14:
        return many
    if value % 10 == 1:
        return one
    if 2 <= value % 10 <= 4:
        return few
    return many
