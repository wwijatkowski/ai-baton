import csv
import io

from .streaks import completion_rate, current_streak


def habits_csv(habits, today):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(['name', 'frequency', 'streak', 'completion', 'status'])
    for habit in sorted(habits, key=lambda h: h.name.lower()):
        writer.writerow([habit.name, habit.frequency, current_streak(habit, today), completion_rate(habit, today),
                         'paused' if habit.is_paused(today) else 'active'])
    return out.getvalue()
