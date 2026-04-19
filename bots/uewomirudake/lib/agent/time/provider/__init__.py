import time as _time

from cambc import Controller


class TimeProvider:
    """
    Abstraction for retrieving the current active time within a round.
    Units are microseconds so the value is directly comparable with
    ALLOCATED_MAP_TIME_MUS / ALLOCATED_MAP_AND_BOT_TIME_MUS.
    """

    def start_round(self, ct: Controller) -> None:
        pass

    def get_active_time(self) -> float:
        raise NotImplementedError


class SubmissionTimeProvider(TimeProvider):
    """
    Reads the per-turn CPU time reported by the game controller.
    This is what the competition environment enforces, so it is the
    source of truth for overtime checks in real matches.
    """

    def __init__(self):
        self.ct: Controller | None = None

    def start_round(self, ct: Controller) -> None:
        self.ct = ct

    def get_active_time(self) -> float:
        if self.ct is None:
            return 0.0
        return float(self.ct.get_cpu_time_elapsed())


class LocalTimeProvider(TimeProvider):
    """
    Uses wall-clock perf_counter_ns for a finer-grained view of elapsed
    time during local debugging, where get_cpu_time_elapsed may be noisy
    or less informative than the real time we actually burn.
    """

    def __init__(self):
        self.start_ns: int = 0

    def start_round(self, ct: Controller) -> None:
        self.start_ns = _time.perf_counter_ns()

    def get_active_time(self) -> float:
        if self.start_ns == 0:
            return 0.0
        return (_time.perf_counter_ns() - self.start_ns) / 1_000.0
