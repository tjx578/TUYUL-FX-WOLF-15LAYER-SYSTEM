from enum import StrEnum


class ExecutionMode(StrEnum):
    NORMAL = "NORMAL"
    SAFE = "SAFE"
    KILL_SWITCH = "KILL_SWITCH"
