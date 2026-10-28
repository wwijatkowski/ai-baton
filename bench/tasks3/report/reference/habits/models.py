from dataclasses import dataclass, field

FREQUENCIES = ('daily', 'weekdays', 'weekly')


class HabitError(ValueError):
    pass


@dataclass
class Habit:
    name: str
    frequency: str = 'daily'
    created: str = ''  # ISO date
    done: list = field(default_factory=list)  # ISO dates on which it was done, sorted, unique

    def __post_init__(self):
        if self.frequency not in FREQUENCIES:
            raise HabitError(f'unknown frequency {self.frequency!r}; use one of {", ".join(FREQUENCIES)}')
        self.done = sorted(set(self.done))

    def to_dict(self):
        return {'name': self.name, 'frequency': self.frequency, 'created': self.created, 'done': self.done}

    @classmethod
    def from_dict(cls, data):
        return cls(data['name'], data.get('frequency', 'daily'), data.get('created', ''), data.get('done', []))
