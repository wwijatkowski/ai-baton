import argparse
import sys
from datetime import date

from . import export
from .models import Habit, HabitError
from .scheduler import due_today
from .storage import Storage
from .streaks import completion_rate, current_streak


def main(argv=None):
    parser = argparse.ArgumentParser(prog='habits')
    parser.add_argument('--file', default='habits.json')
    parser.add_argument('--today', type=date.fromisoformat, default=None, help='pretend today is this date (YYYY-MM-DD)')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('add')
    p.add_argument('name')
    p.add_argument('--frequency', default='daily')
    p = sub.add_parser('done')
    p.add_argument('name')
    sub.add_parser('list')
    sub.add_parser('today')
    p = sub.add_parser('stats')
    p.add_argument('name')
    sub.add_parser('export')
    args = parser.parse_args(argv)
    today = args.today or date.today()
    storage = Storage(args.file)
    try:
        habits = storage.load()
        if args.command == 'add':
            if any(h.name.lower() == args.name.lower() for h in habits):
                raise HabitError(f'{args.name!r} already exists')
            habits.append(Habit(args.name, args.frequency, today.isoformat()))
            storage.save(habits)
        elif args.command == 'done':
            habit = storage.find(habits, args.name)
            habit.done = sorted(set(habit.done) | {today.isoformat()})
            storage.save(habits)
        elif args.command == 'list':
            for habit in sorted(habits, key=lambda h: h.name.lower()):
                print(f'{habit.name}\t{habit.frequency}\t{current_streak(habit, today)}')
        elif args.command == 'today':
            for habit in due_today(habits, today):
                print(habit.name)
        elif args.command == 'stats':
            habit = storage.find(habits, args.name)
            print(f'Streak: {current_streak(habit, today)}')
            print(f'Completion: {round(completion_rate(habit, today) * 100)}%')
        elif args.command == 'export':
            print(export.habits_csv(habits, today), end='')
    except HabitError as error:
        print(f'habits: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
