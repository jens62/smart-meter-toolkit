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
- [x] Confirm `daily-tar.sh`'s `export_*.csv|json|xml` filename pattern
      actually matches what the reader produces (resolved 2026-07-14: it
      didn't - `readSMGW_multipleContracts.sh` also writes
      `export_*.cms` (the raw signed original each `.xml`/`.csv`/`.json`
      is derived from), which the pattern silently missed, so those
      files were never archived at all. Added `-o -name 'export_*.cms'`
      to the `find` in `daily-tar.sh`.)
- [ ] Wire the polling job, daily-tar.sh, and monthly-assemble.sh together
      into one coherent pipeline instead of three independent pieces

## 2. ~~Nightly gap-filling script~~ (implemented 2026-07-14, not yet scheduled)

`scripts/gap_backfill.py`: scans a workbook's last `--months` (default 3)
month-sheets using the same DST-aware `find_gaps()` as `--append-to`
(deliberately *not* `generate_excel/gap_detector.py`'s naive-diff version,
which would misreport DST transitions as gaps the same way
`meter_reading2consumption.py` used to before that was fixed), then
re-queries the gateway per gap via `read_SMGW.py --from ... --to ...`.

- [x] Detects gaps in the last N months of data
- [x] For each open gap, re-queries the gateway for that exact time window
      (padded by `--pad-minutes`, default 30, either side)
- [x] Retries a given gap once per calendar day (`--state-file` tracks
      `last_attempt_date`, so re-running manually the same day is a no-op);
      after `--max-retries` (default 3) attempts across separate days with
      the gap still open, marks it `given_up` and stops querying it
- [x] Persistent JSON state file (`--state-file`) surviving between runs;
      a gap that disappears from detection is dropped from state as
      resolved (or logged as "aged out of the window" if its end predates
      the current N-month scan window - not the same thing, see the
      script's docstring)
- [x] `--max-requests-per-run` caps gateway load per run, deferring the
      rest (oldest-gap-first) rather than silently dropping them
- [x] `--dry-run` for safe manual testing (no gateway calls, no state
      writes) - used to verify the retry/give-up/resolved/aged-out logic
      against a copy of the real workbook before this was ever pointed at
      the live gateway
- [ ] Add this job to `scripts/crontab.example` - **deliberately not done
      yet** (2026-07-14: implemented and manually tested per above, but
      not wired into cron per explicit instruction, pending a manual test
      run against the real gateway first)

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

## 6. ~~Merge add_gaps_to_verbrauch.py into meter_reading2consumption.py~~ (resolved 2026-07-14)

Added `--add-gaps` to `meter_reading2consumption.py`: when passed, the same
run that generates the workbook also writes the "Lücken (keine Daten vom
SMGW)" block into the `Verbrauch` sheet (header text updated to match what
was already in use on the real production file), instead of a separate
`generate_excel/add_gaps_to_verbrauch.py` post-processing step.

Detection reuses `find_gaps()` — already shared with `append_to_workbook()`
from item 3's work — rather than duplicating `gap_detector.py`'s logic or
shelling out to it. That reuse surfaced a real bug worth noting: a naive
datetime diff misreports every DST spring-forward transition (clocks
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

## 7. ~~Add a "Summe" total row below the Verbrauch sheet, fix the next-month check~~ (resolved 2026-07-14)

Added the `Summe` row, plus a `Plausibilitätstest: jüngster Wert - ältester
Wert` row directly below it (newest overall reading minus oldest overall
reading - a telescoping-sum identity that must always equal `Summe` exactly
if the boundary-chaining formulas from item 5 are correct, making it a
built-in regression check rather than a data check). Both get the German
number format; `Summe`'s A/B cells are colorized like the header row.

Sidestepped the `ISBLANK`/`ISREF` question entirely: a blank spacer row
sits between the last month and `Summe`, so the last month's own
`ISBLANK(A{next_row})` check still correctly lands on a blank cell, not on
`"Summe"` — no formula rewrite needed. `append_to_workbook()` (item 3) keeps
both rows correct when new months get appended later: it extends `Summe`'s
`SUM(...)` range and rewrites `Plausibilitätstest`'s reference to the new
last month.

Also found and fixed a related bug while implementing this:
`apply_zebra_formatting()` blanket-restripes every cell's fill in the
sheet's used range, which was silently overwriting `Summe`'s header-style
coloring on every `append_to_workbook()` run (not just when a new month
was added) - confirmed this had already happened to the real production
file. Now re-applied after every zebra pass.

## 8. Make the cron pipeline robust against `ubuntu24-studio` downtime

The host has rebooted 3 times in the last ~8 days (per `last reboot`).
Reviewed each cron job in `scripts/crontab.example` for what happens if a
scheduled run is simply missed because the box was down:

- [x] Merge job (`meter_reading2consumption.py --append-to`): already fixed
      (2026-07-14) - it now derives its "already covered" cutoff from the
      workbook's own latest-reading content (`get_workbook_cutoff()`)
      instead of the `.xlsx` file's filesystem mtime, so it correctly
      catches up regardless of how long it was down. The file mtime broke
      on any copy/scp/touch unrelated to an actual merge (found while
      deploying the full-history workbook to this host).
- [ ] `smgw2influx.sh` (every 14 min, gateway polling): a missed window
      isn't necessarily lost - **the SMGW itself caches roughly 15
      months of readings** (measured 2026-07-14 by binary-searching
      `readSMGW_multipleContractsInRanges.py --from <date> --to
      <date>+30min` between a known-empty and known-present date until
      it converged on the boundary: oldest reading found was
      2025-04-12 03:30:01 local, i.e. ~458.8 days / ~660,700 minutes
      before the measurement time - see
      `local-assets/smgw_retention_probe/` for the full bisection log
      and the raw response at that boundary. This is specific to this
      household's gateway/firmware at this point in time, not a
      documented spec value - re-measure if this matters again after a
      firmware update or long enough after 2026-07-14 that the number
      may have drifted), so a missed poll is recoverable by re-querying
      the gateway for the gap window after the fact. Item 2's
      `scripts/gap_backfill.py` *is* this mechanism - it doesn't need to
      distinguish "downtime-caused" from "routine" gaps, a gap is a gap
      either way. Same status as item 2: implemented and manually tested
      2026-07-14, not yet scheduled in cron.
- [x] `daily-tar.sh` (02:10): resolved 2026-07-14. It already skipped a
      day whose archive exists, so the cron line now always passes a
      14-day lookback (`daily-tar.sh "$(date -d '14 days ago' +%Y-%m-%d)"`)
      instead of no args (which only archived "yesterday" relative to
      whenever it ran) - redundant re-checks of already-archived days are
      cheap, and a multi-day outage now gets caught up automatically
      instead of silently skipping those days forever. Also made
      `--base-dir` explicit in the cron line while touching it - it was
      relying on cron's default cwd unstated, which is `$HOME`, not this
      script's directory. (While deploying this, found and replaced a
      corrupted copy of the script on the host - two old versions had
      somehow been concatenated into one file with duplicate shebangs;
      backed up to `archives/superseded/` before overwriting.)
- [x] `monthly-assemble.sh` (03:00, day 2): resolved 2026-07-14. Added a
      "skip if this month's archive already exists" guard (it didn't have
      one before, unlike `daily-tar.sh`) plus a `--lookback-months N`
      option that also re-checks the N-1 months before the target,
      skipping any already assembled. Cron line now passes
      `--lookback-months 3`, so missing day 2 for a given month no longer
      means that month is silently never assembled.

## 9. Surface the raw exports' `status` field instead of discarding it

Investigated (2026-07-14) whether switching from the raw CSV exports to
their sibling XML files would give access to an "error flag" the meter/
gateway reports. It wouldn't: the XML's `<ns2:status><ns2:unsigned>`
element carries the exact same value as the CSV's own `status` column
(schema-1: column 6; schema-2: column 5) - XML has no extra information
here, and is meaningfully more expensive to parse at scale (nested XML per
file vs. flat `awk`-friendly CSV, across tens of thousands of files).
`normalize_meter_csv.awk` currently discards this column entirely in both
schemas.

Across the full historical dataset (~370k readings), the overwhelming
majority are `status=0`; a non-zero value, `status=3`, occurs 126 times
(0.03%). Cross-checked all 31 distinct `status=3` timestamps against the
current EMH00 workbook's 11 known gaps (±30min tolerance on either
boundary): only 3/11 gaps (27%) have a `status=3` reading nearby, and 28
of the 31 `status=3` occurrences don't correspond to any currently-known
>20min gap at all. Conclusion: it's a real signal (the meter/gateway
does occasionally flag a reading as suspect) but neither comprehensive
(misses most real gaps) nor gap-exclusive (mostly flags brief blips that
never became a full gap) - not a substitute for the existing
timestamp-based gap detection, but a useful supplementary signal.

- [ ] Extend `normalize_meter_csv.awk` to emit `status` as a 4th output
      column (currently `_time;_value;_measurement` only) for both
      schema 1 and schema 2
- [ ] Thread it through as an optional per-reading annotation - e.g. a
      "Status" column on month sheets, populated only for non-zero values
- [ ] Add a separate "Auffällige Messungen" (flagged readings) block to
      the `Verbrauch` sheet listing every `status != 0` reading and its
      value - kept independent from the existing `Lücken` block, since
      that's a different, already-reliable mechanism (don't dilute it by
      merging in a signal that's known to be incomplete on its own)

### What the `status` value actually means (found 2026-07-14)

Full writeup, including a bit table and sources, in
[`docs/smgw-status-field.md`](docs/smgw-status-field.md). Short version:
the `.cms`/`.xml` exports are the DKE K461/BSI TR-03109 standardized
SMGW format (not vendor-proprietary), and BSI TR-03109-1
"Detailspezifikation" v2.0, Chapter 15 ("Messwertstatus") defines the
bit meanings for exactly this attribute. Our observed values (0, 3)
are consistent with bit 1, `SMGW_ValueNotValidated` ("reading not yet
validated for billing") - a plausible, well-documented match for the
empirical finding above, though not certain to the bit (see the doc
for caveats).
