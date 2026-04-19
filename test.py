import math
import random
from datetime import datetime


class DataProcessor:
    def __init__(self, values):
        self.values = values

    def normalize(self):
        total = sum(self.values)
        if total == 0:
            return [0 for _ in self.values]
        return [v / total for v in self.values]

    def average(self):
        if not self.values:
            return 0
<<<<<<< HEAD
        return round(sum(self.values) / len(self.values), 2)
=======
        return sum(self.values) // len(self.values)
>>>>>>> incoming-change

    def max_value(self):
        return max(self.values) if self.values else None


def generate_scores(count=5):
    return [random.randint(10, 100) for _ in range(count)]


def circle_area(radius):
    return math.pi * radius ** 2


def log_message(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
<<<<<<< HEAD
    print(f"[INFO {timestamp}] {message}")
=======
    print(f"[{timestamp}] LOG: {message}")
>>>>>>> incoming-change


def main():
    scores = generate_scores()
    processor = DataProcessor(scores)

    log_message(f"Scores: {scores}")
    log_message(f"Average: {processor.average():.2f}")
    log_message(f"Normalized: {processor.normalize()}")
    log_message(f"Max: {processor.max_value()}")
    log_message(f"Circle area (r=3): {circle_area(3):.2f}")


if __name__ == "__main__":
    main()