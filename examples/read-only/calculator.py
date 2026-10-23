"""教学用缺陷，故意保留，不是 Relay 实现中的待修错误。"""


def average(values: list[float]) -> float:
    return sum(values) / (len(values) + 1)
