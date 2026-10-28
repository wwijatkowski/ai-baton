# Tags for items

Users want to tag items ("power-tool", "fragile") and find them by tag.

## Requirements
1. An item has `tags`: a list of tags. A tag is 1-20 characters: ASCII letters, digits and `-`, stored in lower case.
   Tags of an item are unique and kept sorted. An invalid tag is an error: `shelf: invalid tag 'x y'` and exit code 1;
   nothing is saved.
2. Storage: the file format becomes 2 and stores tags. Files in format 1 (no tags) still load (their items have no
   tags) and are written as format 2 the next time the shelf is saved. Any other format is still an error.
3. `add NAME --tag T` (repeatable) sets the new item's tags.
4. `tag NAME T [T ...]` adds tags to an existing item; `untag NAME T [T ...]` removes them (removing a tag the item
   does not have is not an error). An unknown item is an error, as for `remove`.
5. `list` prints a fourth tab-separated column: the item's tags joined with `,` (empty when it has none).
   `list --tag T` (repeatable) shows only items that have all the given tags.
6. `report --by tag` groups items by tag instead of location: an item appears under each of its tags; groups sorted
   by tag, items without tags last under `(untagged)`; same layout and totals as the location report.
   `report` (and `report --by location`) is unchanged.
7. Tests for all of the above; README updated.

## Work split
- Part 1: the model and storage (requirements 1 and 2), with tests.
- Part 2: the command line and report (requirements 3 to 7).
