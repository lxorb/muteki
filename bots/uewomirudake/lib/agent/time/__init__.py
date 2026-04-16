from cambc import Controller

ALLOCATED_MAP_TIME_MS = 0.75
ALLOCATED_BOT_TIME_MS = 0.8

MS_TO_MUS = 1e3

ALLOCATED_MAP_TIME_MUS = ALLOCATED_MAP_TIME_MS * MS_TO_MUS
ALLOCATED_BOT_TIME_MUS = ALLOCATED_BOT_TIME_MS * MS_TO_MUS

ALLOCATED_MAP_AND_BOT_TIME_MUS = ALLOCATED_MAP_TIME_MUS + ALLOCATED_BOT_TIME_MUS

OVERTIME_CHECK_INTERVAL_POWER_OF_TWO = 1 << 6
OVERTIME_CHECK_MASK = OVERTIME_CHECK_INTERVAL_POWER_OF_TWO - 1

import inspect

LOG_TIME = False


class RoundStopwatch:
    def __init__(self):
        self.ct: Controller | None = None
        self.map_done: bool = False
        self.iterations: int = 0
        self.short_iterations: int = 0

    def start_round(self, ct: Controller):
        self.ct = ct

        self.iterations = 0
        self.short_iterations = 0

        self.map_done = False

    def start_bot(self):
        self.map_done = True

    def check_overtime_interval(self):
        if self.ct is None:
            return False

        self.iterations += 1

        if self.iterations & OVERTIME_CHECK_MASK:
            return False

        active_cpu_time = self.ct.get_cpu_time_elapsed()

        if LOG_TIME:
            print(active_cpu_time, inspect.currentframe().f_back.f_code.co_name)

        return (
            active_cpu_time > ALLOCATED_MAP_AND_BOT_TIME_MUS
            if self.map_done
            else active_cpu_time > ALLOCATED_MAP_TIME_MUS
        )

    def check_overtime(self):
        if self.ct is None:
            return False

        active_cpu_time = self.ct.get_cpu_time_elapsed()

        if LOG_TIME:
            print(active_cpu_time, inspect.currentframe().f_back.f_code.co_name)

        return (
            active_cpu_time > ALLOCATED_MAP_AND_BOT_TIME_MUS
            if self.map_done
            else active_cpu_time > ALLOCATED_MAP_TIME_MUS
        )
