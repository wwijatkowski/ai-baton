import argparse
import sys
from datetime import date, timedelta

from . import export
from .models import Habit, HabitError, check_pauses
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
    p = sub.add_parser('pause')
    p.add_argument('name')
    p.add_argument('--from', dest='start', type=date.fromisoformat)
    p.add_argument('--to', dest='end', type=date.fromisoformat)
    p = sub.add_parser('resume')
    p.add_argument('name')
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
                status = 'paused' if habit.is_paused(today) else 'active'
                print(f'{habit.name}\t{habit.frequency}\t{current_streak(habit, today)}\t{status}')
        elif args.command == 'today':
            for habit in due_today(habits, today):
                print(habit.name)
        elif args.command == 'stats':
            habit = storage.find(habits, args.name)
            print(f'Streak: {current_streak(habit, today)}')
            print(f'Completion: {round(completion_rate(habit, today) * 100)}%')
            day, paused = date.fromisoformat(habit.created or today.isoformat()), 0
            while day <= today:
                paused += habit.is_paused(day)
                day += timedelta(days=1)
            print(f'Paused days: {paused}')
        elif args.command == 'pause':
            habit = storage.find(habits, args.name)
            start = (args.start or today).isoformat()
            habit.pauses = check_pauses(habit.pauses + [{'start': start, 'end': args.end and args.end.isoformat()}])
            storage.save(habits)
        elif args.command == 'resume':
            habit = storage.find(habits, args.name)
            open_ = [p for p in habit.pauses if p['end'] is None]
            if not open_:
                raise HabitError(f'{habit.name!r} is not paused')
            end = (today - timedelta(days=1)).isoformat()
            if open_[0]['start'] > end:
                habit.pauses.remove(open_[0])
            else:
                open_[0]['end'] = end
            storage.save(habits)
        elif args.command == 'export':
            print(export.habits_csv(habits, today), end='')
    except HabitError as error:
        print(f'habits: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
