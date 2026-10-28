from datetime import date


def is_due(habit, day):
    """Whether the habit is expected on this day (a date)."""
    if habit.created and day < date.fromisoformat(habit.created):
        return False
    if habit.is_paused(day):
        return False
    if habit.frequency == 'daily':
        return True
    if habit.frequency == 'weekdays':
        return day.weekday() < 5
    return day.weekday() == 0  # weekly: Mondays


def due_today(habits, today):
    return [h for h in habits if is_due(h, today) and today.isoformat() not in h.done]
