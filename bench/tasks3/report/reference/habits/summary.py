from datetime import timedelta

from .scheduler import is_due


def percent(done, due):
    return (done * 200 + due) // (2 * due) if due else 0  # Half up.


def week_summary(habits, week_start, today):
    if week_start.weekday() != 0:
        raise ValueError(f'{week_start} is not a Monday')
    rows = []
    for habit in habits:
        done = due = 0
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            if day > today or not is_due(habit, day):
                continue
            due += 1
            done += day.isoformat() in habit.done
        if due:
            rows.append((habit.name, done, due))
    return sorted(rows, key=lambda r: r[0].lower())
