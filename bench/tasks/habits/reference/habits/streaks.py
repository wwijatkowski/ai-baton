from datetime import timedelta

from .scheduler import is_due


def current_streak(habit, today):
    """Due days in a row, ending today (or yesterday when today is not done yet), on which the habit was done."""
    done = set(habit.done)
    day = today if today.isoformat() in done else today - timedelta(days=1)
    streak = 0
    for _ in range(3660):
        if habit.created and day.isoformat() < habit.created:
            break
        if is_due(habit, day):
            if day.isoformat() not in done:
                break
            streak += 1
        day -= timedelta(days=1)
    return streak


def completion_rate(habit, today):
    """Share of due days since creation (today included) on which it was done, 0..1."""
    if not habit.created:
        return 0.0
    day, due, done = today, 0, set(habit.done)
    while day.isoformat() >= habit.created:
        if is_due(habit, day):
            due += 1
            done_today = day.isoformat() in done
            due -= 0 if done_today or day != today else 1  # Today counts only once it is done.
        day -= timedelta(days=1)
    hits = sum(1 for d in done if habit.created <= d <= today.isoformat())
    return round(hits / due, 2) if due else 0.0
