import json
from pathlib import Path

from .models import Habit, HabitError

FORMAT = 2
READABLE = (1, 2)


class Storage:
    """Habits in a JSON file: {"format": 1, "habits": [...]}. Names are unique, compared without case."""

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if data.get('format') not in READABLE:
            raise HabitError(f'{self.path}: unknown format {data.get("format")!r}')
        return [Habit.from_dict(h) for h in data.get('habits', [])]

    def save(self, habits):
        payload = {'format': FORMAT, 'habits': [h.to_dict() for h in habits]}
        self.path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')

    def find(self, habits, name):
        for habit in habits:
            if habit.name.lower() == name.lower():
                return habit
        raise HabitError(f'no habit called {name!r}')
