import inspect

from cambc import Controller

from lib.agent.constants import SUBMISSION_ENV
from lib.agent.time.provider import (
    LocalTimeProvider,
    SubmissionTimeProvider,
    TimeProvider,
)
from lib.debug.output import tprint

ALLOCATED_MAP_TIME_MS = 1e6
ALLOCATED_BOT_TIME_MS = 1e6

MS_TO_MUS = 1e3

ALLOCATED_MAP_TIME_MUS = ALLOCATED_MAP_TIME_MS * MS_TO_MUS
ALLOCATED_BOT_TIME_MUS = ALLOCATED_BOT_TIME_MS * MS_TO_MUS

ALLOCATED_MAP_AND_BOT_TIME_MUS = ALLOCATED_MAP_TIME_MUS + ALLOCATED_BOT_TIME_MUS

OVERTIME_CHECK_INTERVAL_POWER_OF_TWO = 1 << 6
OVERTIME_CHECK_MASK = OVERTIME_CHECK_INTERVAL_POWER_OF_TWO - 1


class RoundStopwatch:
    def __init__(self):
        self.ct: Controller | None = None
        self.map_done: bool = False
        self.iterations: int = 0
        self.short_iterations: int = 0
        self.time_provider: TimeProvider = (
            SubmissionTimeProvider() if SUBMISSION_ENV else LocalTimeProvider()
        )

    def start_round(self, ct: Controller):
        self.ct = ct

        self.iterations = 0
        self.short_iterations = 0

        self.map_done = False

        self.time_provider.start_round(ct)

    def start_bot(self):
        self.map_done = True

    def end_round(self):
        active_time = self.time_provider.get_active_time()
        tprint(f"[end_round] {active_time:.2f} mus")

    def log_time(self, label: str = "log_time"):
        active_time = self.time_provider.get_active_time()
        tprint(f"[{label}] {active_time:.2f} mus")

    def check_overtime_interval(self):
        if self.ct is None:
            return False

        self.iterations += 1

        if self.iterations & OVERTIME_CHECK_MASK:
            return False

        active_cpu_time = self.time_provider.get_active_time()
        caller = inspect.currentframe().f_back.f_code.co_name
        tprint(f"[{caller}] {active_cpu_time:.2f} mus")

        if not SUBMISSION_ENV:
            return False

        return (
            active_cpu_time > ALLOCATED_MAP_AND_BOT_TIME_MUS
            if self.map_done
            else active_cpu_time > ALLOCATED_MAP_TIME_MUS
        )

    def check_overtime(self):
        if self.ct is None:
            return False

        active_cpu_time = self.time_provider.get_active_time()
        caller = inspect.currentframe().f_back.f_code.co_name
        tprint(f"[{caller}] {active_cpu_time:.2f} mus")

        if not SUBMISSION_ENV:
            return False

        return (
            active_cpu_time > ALLOCATED_MAP_AND_BOT_TIME_MUS
            if self.map_done
            else active_cpu_time > ALLOCATED_MAP_TIME_MUS
        )
