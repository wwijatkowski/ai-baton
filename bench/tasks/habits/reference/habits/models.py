from dataclasses import dataclass, field
from datetime import date

FREQUENCIES = ('daily', 'weekdays', 'weekly')


class HabitError(ValueError):
    pass


@dataclass
class Habit:
    name: str
    frequency: str = 'daily'
    created: str = ''  # ISO date
    done: list = field(default_factory=list)  # ISO dates on which it was done, sorted, unique
    pauses: list = field(default_factory=list)  # [{"start": ISO, "end": ISO or None}], sorted

    def __post_init__(self):
        if self.frequency not in FREQUENCIES:
            raise HabitError(f'unknown frequency {self.frequency!r}; use one of {", ".join(FREQUENCIES)}')
        self.done = sorted(set(self.done))
        self.pauses = check_pauses(self.pauses)

    def is_paused(self, day):
        iso = day.isoformat() if isinstance(day, date) else day
        return any(p['start'] <= iso and (p['end'] is None or iso <= p['end']) for p in self.pauses)

    def to_dict(self):
        return {'name': self.name, 'frequency': self.frequency, 'created': self.created, 'done': self.done,
                'pauses': self.pauses}

    @classmethod
    def from_dict(cls, data):
        return cls(data['name'], data.get('frequency', 'daily'), data.get('created', ''), data.get('done', []),
                   data.get('pauses', []))


def check_pauses(pauses):
    clean = []
    for p in pauses:
        try:
            start = date.fromisoformat(p['start']).isoformat()
            end = None if p.get('end') is None else date.fromisoformat(p['end']).isoformat()
        except (KeyError, TypeError, ValueError):
            raise HabitError(f'invalid pause {p!r}')
        if end is not None and start > end:
            raise HabitError(f'invalid pause: {start} is after {end}')
        clean.append({'start': start, 'end': end})
    clean.sort(key=lambda p: p['start'])
    if sum(1 for p in clean if p['end'] is None) > 1:
        raise HabitError('only one open pause')
    for a, b in zip(clean, clean[1:]):
        if a['end'] is None or b['start'] <= a['end']:
            raise HabitError(f'pauses overlap: {a["start"]} and {b["start"]}')
    return clean
