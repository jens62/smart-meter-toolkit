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

## 3. Keep the Excel workbook up to date automatically

- [ ] If the target `.xlsx` doesn't exist yet, generate it from scratch
      (`meter_reading2consumption.py`)
- [ ] If it already exists, update it daily rather than fully regenerating
      it each time (append the new day's readings — may need an incremental
      mode in `meter_reading2consumption.py`, which currently only
      regenerates the whole workbook from a full input range)
- [ ] Add this as a daily cron job and document it in
      `scripts/crontab.example`

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

## 5. Fix monthly consumption formula: it drops one reading interval per month boundary

`meter_reading2consumption.py`'s `generate_excel_output()` writes each
month's `Verbrauch` row as:

```
=MAX('2025_06'!B:B)-MIN('2025_06'!B:B)
```

i.e. last reading *within* the month minus first reading *within* the
month. This never counts the reading interval between a month's last
reading (e.g. 2025-06-30 23:45) and the next month's first reading
(2025-07-01 00:00) — that ~15-minute (one reading interval, "eine
Viertelstunde") chunk of consumption is dropped from *every* month's
total, at every month boundary in the workbook.

- [ ] Change the formula to chain consecutive months' starting readings:
      `=MIN('2025_07'!B:B)-MIN('2025_06'!B:B)` for June's row (next
      month's first reading minus this month's first reading), instead of
      `MAX-MIN` within the same sheet
- [ ] Fall back to the current `MAX('2025_06'!B:B)` approximation for a
      month's end boundary whenever the true next-month border reading
      (e.g. 2025-07-01 00:00) isn't available to chain against — this
      covers two distinct triggers with the same fix: (a) the last month
      in the workbook, where no "next month" sheet exists yet at all, and
      (b) an existing next-month sheet whose first reading is delayed by a
      gap, where naively using `MIN('2025_07'!B:B)` would silently pick up
      the first post-gap reading instead of the true boundary value and
      inflate the current month's total with part of the next month's
      gap-period consumption. Needs a check (e.g. compare the next month's
      actual first-reading timestamp against the expected start-of-month
      timestamp) to detect case (b) — ideally cross-referenced with the
      gap tracking from item 2 above. Consider marking a row using this
      fallback as approximate either way.
- [ ] Check whether `generate_excel/add_gaps_to_verbrauch.py` or any other
      script relies on the old per-month `MAX-MIN` formula/assumption and
      needs updating too
