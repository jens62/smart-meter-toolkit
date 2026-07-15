# TODO archive

Resolved items moved out of [`TODO.md`](TODO.md) to keep it focused on open
work. Nothing here needs action; kept for history/context only.

## Archived 2026-07-15

### Nightly gap-filling script (resolved 2026-07-14)

`scripts/gap_backfill.py` - detailed reference (flags, DST/retry/InfluxDB
behavior, gotchas) is in
[`docs/scripts-reference.md`](docs/scripts-reference.md), not duplicated
here. Implemented, wired into `scripts/crontab.example`, deployed to
`ubuntu24-studio`, and verified end-to-end against the real gateway and
the real InfluxDB instance (a recovered gap's readings confirmed present
via an independent Flux query-back, with the gap's own missing reading
still correctly absent).

### Keep the Excel workbook up to date automatically (resolved 2026-07-14)

Added `--append-to XLSX` (with `--folder` pointing at a raw
`export_*.csv` directory) to `meter_reading2consumption.py`, updating an
existing workbook in place instead of regenerating it from scratch. The
"doesn't exist yet" case was already covered — running the script without
`--append-to` still generates a fresh workbook from a full input range.

The raw per-window export CSVs don't carry a meter-id column themselves,
so the folder is normalized via `normalize_meter_csv.awk` (its `lo`/`hi`
BEGIN vars are now overridable via `-v`, matching the existing `meter`
override) with the meter id auto-detected from each export's `.json`/`.xml`
sibling.

This ended up as a real merge rather than a strict "append newer" — it
dedupes by exact timestamp per month, so one run can backfill an older
archived day (e.g. from `daily-tar.sh`'s `archives/daily`) alongside
topping up with today's live export. New months are inserted in
chronological order ahead of any hand-added trailing rows (e.g. a `Summe`
total), whose `SUM(...)` range gets extended to match; the workbook is
renamed to reflect its new latest reading, and any remaining >20min gaps
per merged month are reported rather than silently left unfilled.

Added as a nightly cron job (before `daily-tar.sh`, though that ordering
isn't load-bearing) plus a daily `logrotate` check for its log, both
documented in `scripts/crontab.example` with a
`scripts/logrotate-append-excel.conf.example` template.

### Double-check a possibly corrupted line in the Mikrotik config example (resolved: not corrupted)

In `docs/Using_the_PPC_Smart_Meter_Gateway.md`, the RouterOS config block
under "Einsatz eines Routers" has:

```
add bridge=*C tagged=*C untagged=ether4 vlan-ids=1
```

Originally flagged as invalid/corrupted. Verified (2026-07-11): `*C` is a
legitimate RouterOS internal object-ID reference (MikroTik's `*hex-id`
format) — `bridge=`/`tagged=` accept either a symbolic name or this ID
form. The line also mirrors the self-referencing pattern of the line above
it (`bridge=bridge-vlan10 tagged=bridge-vlan10 ...`), and the whole config
block is full of `comment=defconf` entries confirming it's a raw, unedited
`/export` dump — exactly where RouterOS is likely to emit an ID instead of
a name for a default/system-managed bridge. No action needed; doc is
accurate as-is.

### Fix monthly consumption formula: it drops one reading interval per month boundary (resolved 2026-07-12)

`meter_reading2consumption.py`'s `generate_excel_output()` used to write
each month's `Verbrauch` row as `=MAX('2025_06'!B:B)-MIN('2025_06'!B:B)` —
last reading *within* the month minus first reading *within* the month.
This never counted the reading interval between a month's last reading and
the next month's first reading, dropping it from every month's total.

Fixed by adding five columns (C-G: this month's last reading, next month's
first reading, and a resulting boundary value) that chain each month's
boundary to the next, looked up by timestamp rather than inferred from the
register's value (so it isn't wrong-in-the-presence-of-feed-in the way
`MAX`/`MIN` would be), with linear interpolation when the next month's
first reading doesn't land exactly on the boundary, and edge-case fallbacks
for the oldest/newest month. All still pure Excel formulas, no Python-side
computation.

Also fixed a real collision this surfaced: `generate_excel/add_gaps_to_verbrauch.py`
defaulted to writing its "Lücken" block at columns F:H, which now overlaps
the new columns above. Changed its `--start-col` default from `F` to `I`.

Note for future edits: formula text written via openpyxl must use the
canonical English function names and comma separators (`IF`, `ISBLANK`,
`INDIRECT`, `DATEVALUE`, `TIMEVALUE`, ...), never the German
names/semicolons a German-locale user would type directly into a cell —
Excel translates for display automatically, but a file written with the
localized form gets flagged as corrupted.

### Merge add_gaps_to_verbrauch.py into meter_reading2consumption.py (resolved 2026-07-14)

Added `--add-gaps` to `meter_reading2consumption.py`: when passed, the same
run that generates the workbook also writes the "Lücken (keine Daten vom
SMGW)" block into the `Verbrauch` sheet (header text updated to match what
was already in use on the real production file), instead of a separate
`generate_excel/add_gaps_to_verbrauch.py` post-processing step.

Detection reuses `find_gaps()` — already shared with `append_to_workbook()`
from the previous item's work — rather than duplicating `gap_detector.py`'s
logic or shelling out to it. That reuse surfaced a real bug worth noting: a
naive datetime diff misreports every DST spring-forward transition (clocks
jumping 02:00→03:00 CEST) as a ~75-minute gap, even though the underlying
15-minute readings are continuous in real time. Fixed by re-localizing to
`Europe/Berlin`-aware and diffing that instead — but only for pairs that
already exceed the threshold under a plain naive diff, since blindly
re-localizing *every* pair breaks on DST fall-back's ambiguous repeated
hour (pytz can't tell which of the two 2025-10-26 02:00-02:59 occurrences
a naive time belongs to) and can otherwise manufacture a gap that was
never a candidate in the first place.

`generate_excel/add_gaps_to_verbrauch.py` and `generate_excel/gap_detector.py`
are kept as standalone scripts for now (not retired) - the layout question
from the original checklist (avoiding the Verbrauch sheet's A-G columns) no
longer applies, since the merged version reuses the same `start_col='I'`
default directly.

### Add a "Summe" total row below the Verbrauch sheet, fix the next-month check (resolved 2026-07-14)

Added the `Summe` row, plus a `Plausibilitätstest: jüngster Wert - ältester
Wert` row directly below it (newest overall reading minus oldest overall
reading - a telescoping-sum identity that must always equal `Summe` exactly
if the boundary-chaining formulas from the monthly-consumption-formula fix
are correct, making it a built-in regression check rather than a data
check). Both get the German number format; `Summe`'s A/B cells are
colorized like the header row.

Sidestepped the `ISBLANK`/`ISREF` question entirely: a blank spacer row
sits between the last month and `Summe`, so the last month's own
`ISBLANK(A{next_row})` check still correctly lands on a blank cell, not on
`"Summe"` — no formula rewrite needed. `append_to_workbook()` keeps both
rows correct when new months get appended later: it extends `Summe`'s
`SUM(...)` range and rewrites `Plausibilitätstest`'s reference to the new
last month.

Also found and fixed a related bug while implementing this:
`apply_zebra_formatting()` blanket-restripes every cell's fill in the
sheet's used range, which was silently overwriting `Summe`'s header-style
coloring on every `append_to_workbook()` run (not just when a new month
was added) - confirmed this had already happened to the real production
file. Now re-applied after every zebra pass.

## Memory snapshot 2026-07-15
Active memory entries: 6  |  Pruned: 2  |  Snapshot taken by /compress-memory
