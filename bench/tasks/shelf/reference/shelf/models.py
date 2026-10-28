import re
from dataclasses import dataclass, field
from datetime import date

TAG = re.compile(r'[A-Za-z0-9-]{1,20}')


class TagError(ValueError):
    pass


def normalize_tag(tag):
    if not isinstance(tag, str) or not TAG.fullmatch(tag):
        raise TagError(f"invalid tag '{tag}'")
    return tag.lower()


def normalize_tags(tags):
    return sorted({normalize_tag(t) for t in tags})


@dataclass
class Item:
    name: str
    quantity: int = 1
    location: str = ''
    added: str = field(default_factory=lambda: date.today().isoformat())
    tags: list = field(default_factory=list)

    def __post_init__(self):
        self.tags = normalize_tags(self.tags)

    def to_dict(self):
        return {'name': self.name, 'quantity': self.quantity, 'location': self.location, 'added': self.added,
                'tags': self.tags}

    @classmethod
    def from_dict(cls, data):
        return cls(name=data['name'], quantity=int(data.get('quantity', 1)), location=data.get('location', ''),
                   added=data.get('added') or date.today().isoformat(), tags=data.get('tags', []))
