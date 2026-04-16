import itertools
import time


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
            elapsed = (t2[0] - t1[0]) / 1_000_000
            print(f"|- {t2[1]}: {elapsed:.2f} ms")

        total_elapsed = (self.lap_times[-1][0] - self.lap_times[0][0]) / 1_000_000
        print(f"Σ = {total_elapsed:.2f} ms")
