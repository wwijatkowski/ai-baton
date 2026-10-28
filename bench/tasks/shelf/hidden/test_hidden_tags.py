# Acceptance tests for ISSUE.md; never shown to the agents. Run from the repo root: python -m unittest hidden_test_tags
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from shelf.cli import main


class HiddenTagsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = str(Path(self.tmp.name) / 'shelf.json')

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--file', self.file, *args])
        return code, out.getvalue(), err.getvalue()

    def data(self):
        return json.loads(Path(self.file).read_text())

    def test_add_with_tags_and_list(self):
        self.assertEqual(self.run_cli('add', 'Drill', '--location', 'garage', '--tag', 'Power-Tool', '--tag', 'heavy')[0], 0)
        self.assertEqual(self.run_cli('add', 'Tape')[0], 0)
        self.assertEqual(self.data()['format'], 2)
        self.assertEqual(self.run_cli('list')[1], 'Drill\t1\tgarage\theavy,power-tool\nTape\t1\t\t\n')
        self.assertEqual(self.run_cli('list', '--tag', 'heavy')[1], 'Drill\t1\tgarage\theavy,power-tool\n')
        self.assertEqual(self.run_cli('list', '--tag', 'heavy', '--tag', 'fragile')[1], '')

    def test_tag_untag(self):
        self.run_cli('add', 'Vase')
        self.assertEqual(self.run_cli('tag', 'vase', 'fragile', 'Glass', 'fragile')[0], 0)
        self.assertEqual(self.run_cli('list')[1], 'Vase\t1\t\tfragile,glass\n')
        self.assertEqual(self.run_cli('untag', 'Vase', 'glass', 'missing')[0], 0)
        self.assertEqual(self.run_cli('list')[1], 'Vase\t1\t\tfragile\n')
        code, _, err = self.run_cli('tag', 'Nothing', 'x')
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith('shelf: '))

    def test_invalid_tags_save_nothing(self):
        self.run_cli('add', 'Vase')
        before = Path(self.file).read_text()
        for bad in ('x y', '', 'a' * 21, 'naïve!'):
            code, _, err = self.run_cli('tag', 'Vase', bad)
            self.assertEqual((code, err.strip()), (1, f"shelf: invalid tag '{bad}'"), bad)
        self.assertEqual(Path(self.file).read_text(), before)
        self.assertEqual(self.run_cli('add', 'Box', '--tag', 'bad tag')[0], 1)
        self.assertNotIn('Box', Path(self.file).read_text())

    def test_report_by_tag(self):
        self.run_cli('add', 'Drill', '--quantity', '2', '--tag', 'tool', '--tag', 'heavy')
        self.run_cli('add', 'Saw', '--tag', 'tool')
        self.run_cli('add', 'Tape', '--quantity', '3', '--location', 'drawer')
        self.assertEqual(self.run_cli('report', '--by', 'tag')[1].rstrip('\n'),
                         'heavy (2)\n  Drill x2\ntool (3)\n  Drill x2\n  Saw x1\n(untagged) (3)\n  Tape x3')
        location = 'drawer (3)\n  Tape x3\n(no location) (3)\n  Drill x2\n  Saw x1'
        self.assertEqual(self.run_cli('report')[1].rstrip('\n'), location)
        self.assertEqual(self.run_cli('report', '--by', 'location')[1].rstrip('\n'), location)

    def test_format_1_still_loads_and_is_upgraded(self):
        Path(self.file).write_text(json.dumps({'format': 1, 'items': [
            {'name': 'Old', 'quantity': 2, 'location': 'attic', 'added': '2024-01-01'}]}))
        self.assertEqual(self.run_cli('list')[1], 'Old\t2\tattic\t\n')
        self.assertEqual(self.run_cli('tag', 'Old', 'keep')[0], 0)
        data = self.data()
        self.assertEqual(data['format'], 2)
        self.assertEqual(data['items'][0]['tags'], ['keep'])
        self.assertEqual(data['items'][0]['added'], '2024-01-01')
        Path(self.file).write_text(json.dumps({'format': 7, 'items': []}))
        self.assertEqual(self.run_cli('list')[0], 1)

    def test_existing_behavior(self):
        self.assertEqual(self.run_cli('add', 'Saw')[0], 0)
        self.assertEqual(self.run_cli('add', 'saw')[0], 1)
        self.assertEqual(self.run_cli('remove', 'SAW')[0], 0)
        self.assertEqual(self.run_cli('remove', 'saw')[0], 1)


if __name__ == '__main__':
    unittest.main()
