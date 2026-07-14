# TODO

Backlog of planned work for the smart-meter-toolkit data pipeline. Nothing
below is implemented yet.

## 1. Reorganize the output of the gateway-polling cron job

```
*/14 * * * * /home/jens/develop/smgw/smgw2influx.sh > /dev/null 2>&1
```

Every 14 minutes, this pulls the latest readings from the gateway and writes
them to InfluxDB (see `scripts/smgw2influx.sh`, `scripts/crontab.example`).
Along the way, the gateway reader it calls leaves raw
`export_*.{cms,xml,csv,json}` files behind — one small file per run,
accumulating indefinitely (218k+ files were seen doing this in one session
on this project). That output currently isn't tied into the archiving
pipeline (`scripts/daily-tar.sh`, `scripts/monthly-assemble.sh`) built for
exactly this kind of file.

- [ ] Decide where the raw export files should land relative to
      `daily-tar.sh`'s `--data-dir`
- [ ] Confirm `daily-tar.sh`'s `export_*.csv|json|xml` filename pattern
      actually matches what the reader produces
- [ ] Wire the polling job, daily-tar.sh, and monthly-assemble.sh together
      into one coherent pipeline instead of three independent pieces

## 2. Nightly gap-filling script

New script, run once per night via cron, that:

- [ ] Detects gaps in the last 3 months of data (reuse
      `generate_excel/gap_detector.py`'s detection logic — the same one
      `generate_excel/add_gaps_to_verbrauch.py` already calls out to —
      rather than duplicating it)
- [ ] For each open gap, re-queries the gateway for that exact time window
      (same technique as the "Filling gaps in already-exported data" section
      in the README: `read_SMGW.py --from ... --to ...`)
- [ ] Retries a given gap once per night; if it's still unfilled after 3
      consecutive nights, marks it as permanently lost so it stops being
      retried
- [ ] Needs a small persistent record of "known unrecoverable gaps" (e.g. a
      JSON or CSV file checked in / kept alongside the data) that survives
      between nightly runs, so a gap's retry count doesn't reset each night
      and a gap already given up on isn't queried again
- [ ] Add this job to `scripts/crontab.example`

## 3. ~~Keep the Excel workbook up to date automatically~~ (resolved 2026-07-14)

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

## 4. ~~Double-check a possibly corrupted line in the Mikrotik config example~~ (resolved: not corrupted)

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

## 5. ~~Fix monthly consumption formula: it drops one reading interval per month boundary~~ (resolved 2026-07-12)

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

## 6. Merge add_gaps_to_verbrauch.py into meter_reading2consumption.py

Currently a separate post-processing step: generate the workbook with
`meter_reading2consumption.py`, then run `generate_excel/add_gaps_to_verbrauch.py`
against it to add the "Lücken" block. Fold the latter into the former as an
opt-in CLI flag instead of a second script/step.

- [ ] Add a CLI arg to `meter_reading2consumption.py` (e.g. `--add-gaps`) that
      triggers writing the "Lücken" block into the `Verbrauch` sheet during
      the same run that generates it
- [ ] Reuse `generate_excel/add_gaps_to_verbrauch.py`'s existing gap-detection
      logic (which itself already reuses `generate_excel/gap_detector.py`)
      rather than duplicating it — likely as an importable function rather
      than shelling out to a separate script
- [ ] Keep the column layout in sync: the gaps block currently defaults to
      starting at column I (see item 5) to avoid the Verbrauch sheet's A-G
      columns — make sure a merged implementation still places it correctly
      relative to whatever columns `meter_reading2consumption.py` writes
- [ ] Decide whether `generate_excel/add_gaps_to_verbrauch.py` should be kept
      as a standalone script afterward (for adding gaps to an
      already-generated workbook without regenerating it) or retired once
      merged

## 7. Add a "Summe" total row below the Verbrauch sheet, fix the next-month check

Want a `Summe` row directly below the last month's row, summing the
`Verbrauch` column. This breaks the boundary-chaining formulas from item 5:
they detect "is there a next month" via `ISBLANK(A{next_row})`, which would
be `FALSE` for the `Summe` row (its `A` cell isn't blank, it says "Summe"),
so the last real month's `Grenzwert` formula would wrongly try to interpolate
against a nonexistent "Summe" sheet.

- [ ] Replace the `ISBLANK(A{next_row})` check with a real
      sheet-existence check: `ISREF(INDIRECT("'"&A{next_row}&"'!A1"))` (the
      `IS...` family of functions is error-tolerant, so this returns `FALSE`
      instead of propagating `INDIRECT`'s `#REF!` when no such sheet exists)
      — canonical English/comma form if writing via openpyxl, see item 5's
      note. Test the bare check alone in a scratch cell first, given how many
      formula surprises this workbook has produced already.
- [ ] Add the `Summe` row itself (label in column A, `=SUM(...)` over the
      `Verbrauch` column) once the check above no longer breaks on it
- [ ] Double check `generate_excel/add_gaps_to_verbrauch.py`'s gap rows
      (written below the last month row too) don't run into the same
      "next row isn't a real month" problem, and that a `Summe` row and the
      gaps block don't end up fighting over the same row
