from dataclasses import dataclass, field
from datetime import date


@dataclass
class Item:
    name: str
    quantity: int = 1
    location: str = ''
    added: str = field(default_factory=lambda: date.today().isoformat())

    def to_dict(self):
        return {'name': self.name, 'quantity': self.quantity, 'location': self.location, 'added': self.added}

    @classmethod
    def from_dict(cls, data):
        return cls(name=data['name'], quantity=int(data.get('quantity', 1)), location=data.get('location', ''),
                   added=data.get('added') or date.today().isoformat())
