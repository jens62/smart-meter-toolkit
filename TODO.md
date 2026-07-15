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

- [x] Decide where the raw export files should land relative to
      `daily-tar.sh`'s `--data-dir` (resolved 2026-07-14: confirmed by
      code and by direct observation while healing/verifying daily
      tars this session - `readSMGW_multipleContracts.sh --path X`
      writes into `${X}data/`, exactly `daily-tar.sh --base-dir X`'s
      default `--data-dir`. Already aligned, nothing to reorganize.)
- [x] Confirm `daily-tar.sh`'s `export_*.csv|json|xml` filename pattern
      actually matches what the reader produces (resolved 2026-07-14: it
      didn't - `readSMGW_multipleContracts.sh` also writes
      `export_*.cms` (the raw signed original each `.xml`/`.csv`/`.json`
      is derived from), which the pattern silently missed, so those
      files were never archived at all. Added `-o -name 'export_*.cms'`
      to the `find` in `daily-tar.sh`.)
- [ ] Wire the polling job, daily-tar.sh, and monthly-assemble.sh together
      into one coherent pipeline instead of independent pieces.
      Partially addressed 2026-07-14: all jobs (now including
      `gap_backfill.py`) share one config file
      (`scripts/smgw-pipeline.env.example`) instead of repeating
      credentials/paths, and are scheduled with awareness of each
      other (`gap_backfill.py` deliberately before the merge job,
      deliberately clear of the polling job's minutes - see
      `scripts/crontab.example`'s comments). What's still true: these
      are independently-scheduled cron entries, not one orchestrating
      script - nothing actually checks that e.g. the merge job
      succeeded before `daily-tar.sh` runs, they just happen to be
      scheduled at compatible times.

Items 2-7 (nightly gap-filling, workbook auto-append, the Mikrotik config
line check, the monthly consumption formula fix, merging
`add_gaps_to_verbrauch.py`, and the `Summe` total row) were resolved and
have been moved to [`TODO-archive.md`](TODO-archive.md) to keep this file
focused on open work.

## 8. ~~Make the cron pipeline robust against `ubuntu24-studio` downtime~~ (resolved 2026-07-14)

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
- [x] `smgw2influx.sh` (every 14 min, gateway polling): a missed window
      isn't necessarily lost - **the SMGW itself caches roughly 15
      months of readings** (measured 2026-07-14; not a documented spec
      value, specific to this household's gateway/firmware at this
      point in time - exact measurement and raw evidence are in
      `local-assets/smgw_retention_probe/`, not repeated here since
      they're specific to this gateway. Re-measure if this matters again
      much later or after a firmware update), so a missed poll is
      recoverable by re-querying the gateway for the gap window after
      the fact. Resolved via item 2's `scripts/gap_backfill.py` - it
      doesn't need to distinguish "downtime-caused" from "routine" gaps,
      a gap is a gap either way. Scheduled in `scripts/crontab.example`,
      deployed to `ubuntu24-studio`, and verified end-to-end against the
      real gateway and InfluxDB (see item 2).
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

## 10. Extend meter auto-discovery to smgw2influx.sh and the merge job

`gap_backfill.py` no longer needs a fixed `SMGW_METER`/`SMGW_WORKBOOK_PREFIX`
- it discovers whichever meter(s) the gateway's own meter-select form
currently reports (`read_SMGW.py --list-meters`) and matches each one
against whichever workbook in `--workbook-dir` actually holds that
meter's data, read from the workbook's own content (see
`docs/scripts-reference.md`). `smgw2influx.sh` (the live 14-min polling
job) and the merge job's `XLSX=$(ls -t ..."$SMGW_WORKBOOK_PREFIX"_from_*.xlsx
| head -1)` resolution still rely on the fixed config values - both were
explicitly out of scope when `gap_backfill.py` was reworked (2026-07-14),
since they're higher-risk to touch (one runs unattended every 14 minutes
in production, both are already working).

Until this is done, `SMGW_METER` and `SMGW_WORKBOOK_PREFIX` must stay in
`~/.config/smgw-pipeline.env` on `ubuntu24-studio` - removing them now
would break both of those jobs, even though `gap_backfill.py` itself no
longer reads either one.

- [ ] `smgw2influx.sh`: discover the meter(s) to poll instead of requiring
      `--meter`/`$SMGW_METER` - needs a decision on what to do if the
      gateway reports more than one (poll all of them each cycle? one
      InfluxDB write per meter, presumably needing a per-meter
      measurement name too, unlike `gap_backfill.py`'s current
      single-shared-measurement assumption)
- [ ] Merge job (`meter_reading2consumption.py --append-to`): resolve
      which workbook(s) to merge into by discovering `*_from_*.xlsx`
      files in the workbook directory and matching by each workbook's own
      stored meter id (same approach `gap_backfill.py`'s
      `find_candidate_workbooks()`/`workbook_own_meter()` already use),
      instead of a fixed `$SMGW_WORKBOOK_PREFIX` glob
- [ ] Once both are done, drop `SMGW_METER` and `SMGW_WORKBOOK_PREFIX`
      from `scripts/smgw-pipeline.env.example` and the real
      `~/.config/smgw-pipeline.env` on `ubuntu24-studio`

## 11. `daily-tar.sh`'s cron run silently skipped a day, no reproducible cause found

First night the reworked pipeline ran fully unattended (2026-07-14 into
2026-07-15). `gap_backfill.py` (01:35) and the merge job (01:50) both ran
correctly per their logs. `daily-tar.sh` (02:10) did not: its cron
session opened and closed within the same logged second (per
`journalctl -u cron`) - too fast for what it should do (13 skip-checks
plus one archive+tar) - and `archives/daily/data-2026-07-14.tar` was
confirmed missing afterward (its mtime only appeared once manually run
by hand later that morning).

Could not reproduce the failure: running the exact same command
(`daily-tar.sh "$(date -d '14 days ago' +%Y-%m-%d)" --base-dir
/home/jens/develop/smgw`) by hand worked correctly, and running it again
under a stripped-down cron-like environment (`env -i PATH=/usr/bin:/bin
HOME=/home/jens SHELL=/bin/sh ...`) also worked correctly. No error was
visible anywhere (this cron line has no log redirection - unlike
`gap_backfill.py`'s and the merge job's lines, it still uses the
original pre-`smgw-pipeline.env` style, see item 10), and there's no
local mail spool to check for a message cron might otherwise have sent.

Not urgent on its own - the 14-day lookback means a single missed night
self-corrects within two weeks regardless - but worth tracking since the
cause is genuinely unknown, not just unfixed.

- [x] Add log redirection to `daily-tar.sh`'s and `monthly-assemble.sh`'s
      cron lines (resolved 2026-07-15: both now source
      `smgw-pipeline.env` and redirect to `daily-tar.log`/
      `monthly-assemble.log`, matching the other jobs). Also added
      timestamped `log()` lines throughout `daily-tar.sh` itself (start,
      resolved args/paths, per-day file counts, an `ERR` trap logging the
      failing line/command, and an `EXIT` trap logging the final exit
      code) plus an optional `--debug` flag for full `set -x` tracing -
      previously a silent failure like this one left literally no trace
      anywhere to diagnose from.
- [ ] Watch the next few nights to see if this recurs; if it does,
      narrow down whether it's specific to `daily-tar.sh` or a broader
      "first job to run after a stretch of gateway-querying jobs"
      timing issue
