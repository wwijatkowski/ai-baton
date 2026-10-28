# Acceptance tests for ISSUE.md part 2 (and existing behavior); never shown to the agents.
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from habits.cli import main


class HiddenPausesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = str(Path(self.tmp.name) / 'habits.json')

    def cli(self, today, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--file', self.file, '--today', today, *args])
        return code, out.getvalue(), err.getvalue()

    def data(self):
        return json.loads(Path(self.file).read_text())

    def habit(self):
        return self.data()['habits'][0]

    def test_pause_and_resume(self):
        self.cli('2026-03-01', 'add', 'Read')
        self.assertEqual(self.cli('2026-03-05', 'pause', 'Read')[0], 0)
        self.assertEqual(self.data()['format'], 2)
        self.assertEqual(self.habit()['pauses'], [{'start': '2026-03-05', 'end': None}])
        self.assertEqual(self.cli('2026-03-05', 'list')[1], 'Read\tdaily\t0\tpaused\n')
        self.assertEqual(self.cli('2026-03-05', 'today')[1], '')
        self.assertEqual(self.cli('2026-03-09', 'resume', 'Read')[0], 0)
        self.assertEqual(self.habit()['pauses'], [{'start': '2026-03-05', 'end': '2026-03-08'}])
        self.assertEqual(self.cli('2026-03-09', 'list')[1], 'Read\tdaily\t0\tactive\n')
        code, _, err = self.cli('2026-03-09', 'resume', 'Read')
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith('habits: '))

    def test_resume_on_the_first_day_removes_the_pause(self):
        self.cli('2026-03-01', 'add', 'Read')
        self.cli('2026-03-05', 'pause', 'Read')
        self.assertEqual(self.cli('2026-03-05', 'resume', 'Read')[0], 0)
        self.assertEqual(self.habit()['pauses'], [])

    def test_explicit_period_and_errors(self):
        self.cli('2026-03-01', 'add', 'Gym')
        self.assertEqual(self.cli('2026-03-01', 'pause', 'Gym', '--from', '2026-03-10', '--to', '2026-03-12')[0], 0)
        before = Path(self.file).read_text()
        for args in (['--from', '2026-03-12', '--to', '2026-03-14'],   # overlaps
                     ['--from', '2026-03-20', '--to', '2026-03-18'],   # start after end
                     ['--from', '2026-03-05']):                        # open, covers the existing period
            code, _, err = self.cli('2026-03-01', 'pause', 'Gym', *args)
            self.assertEqual(code, 1, args)
            self.assertTrue(err.startswith('habits: '), args)
        self.assertEqual(Path(self.file).read_text(), before)
        self.assertEqual(self.cli('2026-03-01', 'pause', 'Nobody')[0], 1)

    def test_streak_stats_and_export_skip_paused_days(self):
        self.cli('2026-03-01', 'add', 'Read')
        for day in ('2026-03-01', '2026-03-02', '2026-03-03'):
            self.cli(day, 'done', 'Read')
        self.cli('2026-03-01', 'pause', 'Read', '--from', '2026-03-04', '--to', '2026-03-06')
        self.cli('2026-03-07', 'done', 'Read')
        self.assertEqual(self.cli('2026-03-07', 'stats', 'Read')[1], 'Streak: 4\nCompletion: 100%\nPaused days: 3\n')
        self.assertEqual(self.cli('2026-03-05', 'export')[1],
                         'name,frequency,streak,completion,status\nRead,daily,3,1.0,paused\n')
        self.assertEqual(self.cli('2026-03-07', 'export')[1],
                         'name,frequency,streak,completion,status\nRead,daily,4,1.0,active\n')

    def test_format_1_loads_and_is_upgraded(self):
        Path(self.file).write_text(json.dumps({'format': 1, 'habits': [
            {'name': 'Old', 'frequency': 'daily', 'created': '2026-01-01', 'done': ['2026-01-01']}]}))
        self.assertEqual(self.cli('2026-01-01', 'list')[1], 'Old\tdaily\t1\tactive\n')
        self.cli('2026-01-02', 'pause', 'Old')
        self.assertEqual(self.data()['format'], 2)
        self.assertEqual(self.habit()['done'], ['2026-01-01'])

    def test_existing_behavior(self):
        self.assertEqual(self.cli('2026-03-02', 'add', 'Read')[0], 0)
        self.assertEqual(self.cli('2026-03-02', 'add', 'read')[0], 1)
        self.cli('2026-03-02', 'done', 'Read')
        self.assertEqual(self.cli('2026-03-02', 'stats', 'Read')[1].splitlines()[:2], ['Streak: 1', 'Completion: 100%'])


if __name__ == '__main__':
    unittest.main()
