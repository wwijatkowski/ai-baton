# Acceptance tests for the weekly report (part 2) and existing behavior; never shown to the agents.
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from habits.cli import main

HABITS = {'format': 1, 'habits': [
    {'name': 'Read', 'frequency': 'daily', 'created': '2026-02-20',
     'done': ['2026-03-02', '2026-03-03', '2026-03-04', '2026-03-06', '2026-03-08']},
    {'name': 'Gym', 'frequency': 'weekdays', 'created': '2026-02-20',
     'done': ['2026-03-02', '2026-03-04', '2026-03-06', '2026-03-07']},   # 03-07 is a Saturday: not due
    {'name': 'Journal', 'frequency': 'daily', 'created': '2026-03-20', 'done': []},  # created later: left out
]}


class HiddenReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / 'habits.json'
        self.file.write_text(json.dumps(HABITS))

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(['--file', str(self.file), *args])
        return code, out.getvalue()

    def test_text_report_of_a_whole_week(self):
        code, out = self.cli('--today', '2026-03-10', 'report', '--week', '2026-03-04')
        self.assertEqual(code, 0)
        self.assertEqual(out, 'Week of 2026-03-02\nGym    3/5  60%\nRead   5/7  71%\nTotal  8/12  67%\n')

    def test_current_week_counts_only_days_until_today(self):
        # Wednesday 2026-03-04: Mon-Wed count.
        self.assertEqual(self.cli('--today', '2026-03-04', 'report')[1],
                         'Week of 2026-03-02\nGym    2/3  67%\nRead   3/3  100%\nTotal  5/6  83%\n')

    def test_json(self):
        data = json.loads(self.cli('--today', '2026-03-10', 'report', '--week', '2026-03-08', '--json')[1])
        self.assertEqual(data, {'week': '2026-03-02', 'habits': [
            {'name': 'Gym', 'done': 3, 'due': 5, 'percent': 60},
            {'name': 'Read', 'done': 5, 'due': 7, 'percent': 71}],
            'total': {'done': 8, 'due': 12, 'percent': 67}})

    def test_nothing_due(self):
        self.assertEqual(self.cli('--today', '2026-03-10', 'report', '--week', '2026-02-10')[1],
                         'Week of 2026-02-09\nNothing was due this week.\n')
        data = json.loads(self.cli('--today', '2026-03-10', 'report', '--week', '2026-02-10', '--json')[1])
        self.assertEqual(data, {'week': '2026-02-09', 'habits': [], 'total': {'done': 0, 'due': 0, 'percent': 0}})

    def test_existing_behavior(self):
        self.assertEqual(self.cli('--today', '2026-03-08', 'list')[1], 'Gym\tweekdays\t1\nJournal\tdaily\t0\nRead\tdaily\t1\n')
        self.assertEqual(self.cli('--today', '2026-03-08', 'add', 'read')[0], 1)


if __name__ == '__main__':
    unittest.main()
