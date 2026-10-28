Hi! I'd like a weekly report for the habits tool. Here is what we need.

1. A week runs Monday to Sunday. For a given week, each habit gets: on how many of its due days that week it was done,
   out of how many days it was due. Only days on or after the habit was created count, and days after today do not
   count yet. A done mark on a day the habit was not due does not count. The percentage is done/due, rounded half up
   to a whole number. A habit with no due days in that week is left out.

2. Part 1 (please do this now): a new module `habits/summary.py` with `week_summary(habits, week_start, today)`
   returning a list of `(name, done, due)` sorted by name without case, and `percent(done, due)`. `week_start` must be
   a Monday, otherwise `ValueError`. With tests.

3. Part 2 (later, in another conversation): a `report` command.
   - `report [--week YYYY-MM-DD]`: the week that contains that date; without `--week`, the current week (as given by
     `--today`).
   - Text output, exactly like this (names padded to the longest of the names and "Total", two spaces between
     columns):
     ```
     Week of 2026-03-02
     Gym    3/5  60%
     Read   5/7  71%
     Total  8/12  67%
     ```
     Habits sorted by name. The Total line adds up done and due; its percentage is computed from those sums.
   - When nothing was due that week: the "Week of ..." line, then `Nothing was due this week.`
   - `report --json` prints `{"week": "2026-03-02", "habits": [{"name": ..., "done": ..., "due": ..., "percent": ...}],
     "total": {"done": ..., "due": ..., "percent": ...}}` (habits in the same order; "total" always present, with
     zeros and percent 0 when nothing was due).
   - README and tests updated.

Thanks!
