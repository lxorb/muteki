import time
import itertools


class GlobalRoundStopwatch:
    checkpoint_time = 0
    map_done = False

    iterations = 0

    ALLOCATED_MAP_TIME_MS = 0.7
    ALLOCATED_BOT_TIME_MS = 1.2

    MS_TO_NS = 1e6

    ALLOCATED_MAP_TIME = ALLOCATED_MAP_TIME_MS * MS_TO_NS
    ALLOCATED_BOT_TIME = ALLOCATED_BOT_TIME_MS * MS_TO_NS

    OVERTIME_CHECK_INTERVAL_POWER_OF_TWO = 1 << 6
    OVERTIME_CHECK_MASK = OVERTIME_CHECK_INTERVAL_POWER_OF_TWO - 1

    @classmethod
    def start_map_time(cls):
        cls.iterations = 0

        cls.checkpoint_time = time.perf_counter_ns()
        cls.map_done = False

    @classmethod
    def start_bot_time(cls):
        cls.checkpoint_time = time.perf_counter_ns()
        cls.map_done = True

    @classmethod
    def is_overtime(cls):
        cls.iterations += 1

        return cls.iterations & cls.OVERTIME_CHECK_MASK == 0 and (
            time.perf_counter_ns() - cls.checkpoint_time > cls.ALLOCATED_BOT_TIME
            if cls.map_done
            else time.perf_counter_ns() - cls.checkpoint_time > cls.ALLOCATED_MAP_TIME
        )


class Stopwatch:
    def __init__(self, name: str):
        """
        Initializes a new named stopwatch.
        """
        self.name = name

        self.start_time = 0
        self.last_lap = 0
        self.lap_times = []

    def start(self):
        """
        Starts tracking time by setting a start time and clearing previous results.
        """
        self.lap_times.clear()

        self.start_time = time.perf_counter_ns()
        self.lap_times.append((self.start_time, "_"))

    def lap(self, msg: str = "_"):
        """
        Registers the current time in the stopwatch with an optional message.
        """
        self.last_lap = time.perf_counter_ns()
        self.lap_times.append((self.last_lap, msg))

    def log(self):
        """
        Outputs the elapsed milliseconds between every two registered times, using messages if provided.
        """
        print(f"{self.name} - Time elapsed")
        for t1, t2 in itertools.pairwise(self.lap_times):
            elapsed = ((t2[0] - t1[0]) // 100000) / 10
            print(f"|- {t2[1]}: {elapsed} ms")

        total_elapsed = ((self.lap_times[-1][0] - self.lap_times[0][0]) // 100000) / 10
        print(f"Σ = {total_elapsed} ms")
