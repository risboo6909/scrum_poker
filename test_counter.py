import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from counter import RoomCounter


class CounterTests(unittest.TestCase):
    def test_survives_new_process_and_ignores_new_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "counter.sqlite3"
            counter = RoomCounter(path, 12)
            counter.increment()
            result = subprocess.check_output([
                sys.executable, "-c",
                "from counter import RoomCounter; import sys; print(RoomCounter(sys.argv[1], 999).read())",
                str(path),
            ], text=True)
            self.assertEqual(result.strip(), "13")

    def test_concurrent_increments_are_not_lost(self):
        with tempfile.TemporaryDirectory() as directory:
            counter = RoomCounter(Path(directory) / "counter.sqlite3")
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _: counter.increment(), range(50)))
            self.assertEqual(counter.read(), 50)


if __name__ == "__main__":
    unittest.main()
