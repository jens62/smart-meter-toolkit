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

## 4. Double-check a possibly corrupted line in the Mikrotik config example

In `docs/Using_the_PPC_Smart_Meter_Gateway.md`, the RouterOS config block
under "Einsatz eines Routers" has:

```
add bridge=*C tagged=*C untagged=ether4 vlan-ids=1
```

`*C` isn't valid RouterOS syntax. The next line (`add bridge=bridge-vlan00
untagged=ether4 vlan-ids=1`, same interface/vlan-id) looks like what this
line was supposed to say, making this a corrupted stray duplicate rather
than a real second rule. Needs manual verification against the actual
router config before fixing, since it's real infrastructure config, not
just prose.
