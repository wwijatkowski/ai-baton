import contextlib
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

from habits.cli import main
from habits.models import Habit
from habits.streaks import completion_rate, current_streak


class HabitsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = str(Path(self.tmp.name) / 'habits.json')

    def cli(self, today, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(['--file', self.file, '--today', today, *args])
        return code, out.getvalue()

    def test_streaks(self):
        h = Habit('Read', 'daily', '2026-03-01', ['2026-03-02', '2026-03-03', '2026-03-04'])
        self.assertEqual(current_streak(h, date(2026, 3, 4)), 3)
        self.assertEqual(current_streak(h, date(2026, 3, 5)), 3)  # Today not done yet.
        self.assertEqual(current_streak(h, date(2026, 3, 6)), 0)
        w = Habit('Gym', 'weekdays', '2026-03-02', ['2026-03-05', '2026-03-06', '2026-03-09'])  # Thu, Fri, Mon
        self.assertEqual(current_streak(w, date(2026, 3, 9)), 3)
        self.assertEqual(completion_rate(h, date(2026, 3, 4)), 0.75)

    def test_cli(self):
        self.assertEqual(self.cli('2026-03-02', 'add', 'Read')[0], 0)
        self.assertEqual(self.cli('2026-03-02', 'add', 'read')[0], 1)
        self.cli('2026-03-02', 'done', 'Read')
        self.cli('2026-03-03', 'done', 'Read')
        self.assertEqual(self.cli('2026-03-03', 'list')[1], 'Read\tdaily\t2\tactive\n')
        self.assertEqual(self.cli('2026-03-04', 'today')[1], 'Read\n')
        self.assertEqual(self.cli('2026-03-03', 'stats', 'Read')[1], 'Streak: 2\nCompletion: 100%\nPaused days: 0\n')
        self.assertEqual(self.cli('2026-03-03', 'export')[1], 'name,frequency,streak,completion,status\nRead,daily,2,1.0,active\n')
        self.assertEqual(self.cli('2026-03-03', 'add', 'X', '--frequency', 'hourly')[0], 1)


if __name__ == '__main__':
    unittest.main()
