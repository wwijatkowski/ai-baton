# Pausing habits

Users go on holiday or get ill. A paused habit should not be due, and a pause must not break its streak.

## Requirements
1. A habit has `pauses`: periods `{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}` (both days included); `end` may be
   `null` (still paused). `start` must not be after `end`; periods of one habit must not overlap (an open period
   covers every day from its start); at most one open period. Invalid pauses raise `HabitError`.
   `Habit.is_paused(day)` tells whether a habit is paused on a day.
2. Storage: the file format becomes 2 and stores pauses. Files in format 1 still load (no pauses) and are written as
   format 2 the next time they are saved. Any other format is still an error.
3. A habit is not due on a paused day: `today` leaves it out, and streaks and completion skip paused days (they
   neither break a streak nor count as done or missed).
4. `pause NAME [--from DATE] [--to DATE]` adds a pause (`--from` defaults to today; without `--to` it stays open).
   An invalid or overlapping pause is an error (`habits: ...`, exit code 1) and nothing is saved.
5. `resume NAME` ends the open pause: it lasts until yesterday; if it started today it is removed. A habit without an
   open pause is an error.
6. `list` prints a fourth column: `paused` when the habit is paused today, else `active`.
7. `stats NAME` prints a third line `Paused days: N`: paused days from the habit's creation to today, both included.
8. `export` adds a last column `status` (`paused` or `active` today).
9. Tests for all of the above; README updated.

## Work split
- Part 1: requirements 1 to 3 (model, storage, scheduler and streaks), with tests.
- Part 2: requirements 4 to 9 (command line, list, stats, export).
