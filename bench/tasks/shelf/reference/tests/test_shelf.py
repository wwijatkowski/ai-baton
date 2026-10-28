import json
import tempfile
import unittest
from pathlib import Path

from shelf.cli import main
from shelf.models import Item
from shelf.store import Store, StoreError


class ShelfTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = str(Path(self.tmp.name) / 'shelf.json')

    def test_add_list_remove(self):
        store = Store(self.file)
        store.add(Item('Drill', 1, 'garage'))
        with self.assertRaises(StoreError):
            store.add(Item('drill'))
        self.assertEqual([i.name for i in store.load()], ['Drill'])
        store.remove('DRILL')
        self.assertEqual(store.load(), [])

    def test_cli_and_report(self):
        self.assertEqual(main(['--file', self.file, 'add', 'Tape', '--quantity', '3', '--location', 'drawer']), 0)
        self.assertEqual(main(['--file', self.file, 'add', 'Saw']), 0)
        self.assertEqual(main(['--file', self.file, 'add', 'saw']), 1)
        from shelf import report
        self.assertEqual(report.by_location(Store(self.file).load()), 'drawer (3)\n  Tape x3\n(no location) (1)\n  Saw x1')

    def test_format(self):
        Path(self.file).write_text(json.dumps({'format': 9, 'items': []}))
        with self.assertRaises(StoreError):
            Store(self.file).load()


if __name__ == '__main__':
    unittest.main()
