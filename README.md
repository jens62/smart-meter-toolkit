# Smart Meter Toolkit

This repository is about 
- reading meters, 
- storing the meter readings and 
- calculating the (monthly) consumption based on the meter readings.

The integration of a smart meter gateway (using PPC as an example) into an existing network and script-based access to the smart meter gateway is also considered.

All of this may be of particular interest to those who do not use home automation software such as openHAB or homeassitant.

The Python scripts in the scripts folder may help. The scripts can be copied, and apart from a few Python modules, no installation is required.

## Requirements

The Python scripts need Python 3 plus a few third-party packages: `pandas`, `openpyxl`, `requests`, `beautifulsoup4`.

```bash
python3 -m venv venv
source venv/bin/activate
pip install pandas openpyxl requests beautifulsoup4
```

On macOS, the system `python3` is usually "externally managed" by Homebrew, which blocks a plain `pip install`. Use a venv as shown above instead of fighting that.

## Quickstart

### reading from Smart Meter
**Usage for the impatient**

To test the process in principle, create an Excel spreadsheet of the monthly consumption based on the meter readings of the last two hours provided by a smart meter gateway:

```bash
python read_SMGW.py \
    --user <user> \
    --password <top secret password> \
    --past 2h \
    --stdout-format csv \
    --out-format none \
| python meter_reading2consumption.py \
    --stdin \
    --time-col capture_time \
    --value-col value \
    --measurement-col logical_name \
    --divisor 10000 \
    --delimiter ";"
```

**Note:** *My smart meter serves several meters. I therefore have to specify the parameter `--meter` when calling `read_SMGW.py` and could not test and only guess for the implementation how the access is to be implemented if the smart meter gateway only serves one meter. I would be grateful if I could get feedback on whether the `read_SMGW.py` script works with just one meter and therefore without the `--meter` parameter.*


The above command consists of two parts:
1. reading from the smart meter gateway with output to stdout in csv format and transfer via pipe to 
2. calculate the monthly consumption with output to an Excel file.

The calculation of monthly consumption is implemented in a second script so that data sources other than the smart meter can be used.

**read all data from Smart Meter**
Generate an Excel sheet of monthly consumption based on all meter readings provided by the smart meter gateway.

Be patient ( ;-) ), this will take a while (in my case 20 minutes for a period of x days), the Smart Meter Gateway is not the fastest device.

```python
python read_SMGW.py \
    --user <user> \
    --password <top secret password> \
    --from 0 \
    --to now \
    --stdout-format csv \
    --out-format none \
| python meter_reading2consumption.py \
    --stdin \
    --time-col capture_time \
    --value-col value \
    --measurement-col logical_name \
    --divisor 10000 \
    --delimiter ";"
```

#### Usage
Use the usual `--help` or `--h` to be overwhelmed by the possibilities.

### Output format

`meter_reading2consumption.py` writes one Excel workbook per run: a `Verbrauch` sheet with one row per month (`Monat` / `Verbrauch [kWh]`, using the formula `=MAX('YYYY_MM'!B:B)-MIN('YYYY_MM'!B:B)`), plus one sheet per `YYYY_MM` present in the data (`Zeit der Messung` / `Zählerstand [kWh]` / `Zähleridentifikation`), a `Summe` total row, and a `Plausibilitätstest` cross-check row. If the data covers more than one meter (e.g. the meter behind your gateway was swapped at some point), it's detected automatically and a **separate, complete workbook is generated per meter** - the output filename encodes which meter and time range each file covers.

`--folder` only scans the **top level** of a directory (not recursive) for files matching `--pattern` (default: any `.csv`), except with `--append-to` (see below), which scans recursively for raw `export_*.csv` files.

### Keeping an existing workbook up to date (`--append-to`)

Instead of regenerating a workbook from scratch every time, `--append-to` merges newer (or backfilled) readings into an existing one in place:

```bash
python3 meter_reading2consumption.py \
    --append-to workbook.xlsx \
    --folder /path/to/raw-exports \
    --divisor 10000 \
    --add-gaps
```

- `--folder` here points at a directory of the gateway's *raw* `export_*.csv`/`.json`/`.xml` files (as produced by `read_SMGW.py`/`smgw2influx.sh`), not the normalized CSV `meter_reading2consumption.py` otherwise expects.
- The merge is dedup-safe: existing rows are left alone, only genuinely new timestamps are added, so it's fine to point `--folder` at a directory with overlapping or re-exported data, or to run the same command repeatedly (e.g. from cron).
- The meter id is auto-detected per file from its `.json`/`.xml` sibling; `--meter` overrides this if a folder has no siblings.
- `--add-gaps` rescans every month sheet from scratch on each run (not just the months this run touched) and rewrites the `Lücken (keine Daten vom SMGW)` block, so a gap in an older month is removed once a later backfill closes it.

See `scripts/crontab.example` for a full nightly-cron setup built around `--append-to`, including log rotation (`scripts/logrotate-append-excel.conf.example`), gateway gap recovery, and raw-export archiving (below) - written to keep working correctly even after the cron host has been down for a while. Shared config (gateway/InfluxDB credentials, IP addresses, filesystem layout) for all of these jobs lives in one file - copy `scripts/smgw-pipeline.env.example` to e.g. `~/.config/smgw-pipeline.env` and fill it in, rather than repeating the same values across every cron line.

### Recovering gaps from the gateway (`gap_backfill.py`)

The gateway itself caches readings well beyond its 15-minute polling interval - typically well over a year, though this varies by device (`TODO.md` item 8 has this project's own measured figure). That means a gap caused by e.g. the cron host being down, rather than the meter itself failing to capture a reading, is often still recoverable after the fact:

```bash
python3 scripts/gap_backfill.py \
    --workbook workbook.xlsx \
    --state-file gap-backfill-state.json \
    --out-path /path/to/data-directory \
    --user <user> --password <password> \
    --dry-run
```

- Scans the workbook's last `--months` month-sheets (default 15) for gaps, using the same DST-aware gap detection as `--append-to`, then re-requests each one from the gateway via `read_SMGW.py`.
- A gap is retried once per calendar day; after `--max-retries` (default 3) days of still being open, it's marked given-up and stops being retried, until the day it's no longer detected at all (then it's dropped from `--state-file` as resolved).
- `--max-requests-per-run` caps gateway load per run - deferring the rest to a later run rather than dropping them.
- `--dry-run` detects and reports without making any gateway requests or writing `--state-file` - use it to check what a run would do first.

Wired into `scripts/crontab.example` scheduled specifically to avoid overlapping the gateway-polling job (see that file's comments for why the exact minute and `--max-requests-per-run` value matter).

### Archiving raw exports

Two scripts keep the raw `export_*.csv`/`.json`/`.xml`/`.cms` files from piling up indefinitely, without ever deleting data that `--append-to` might still need:

- `scripts/daily-tar.sh` tars up a day's raw export files at a time; safe to re-run (skips any day already archived), and accepts a lookback window so a multi-day host outage doesn't leave days permanently unarchived.
- `scripts/monthly-assemble.sh` concatenates a month's daily tars into one compressed monthly archive; likewise safe to re-run and supports a lookback window for the same reason.

Both are wired into `scripts/crontab.example` alongside the jobs above.

## Additional scripts

### Normalizing raw CSV exports

If you let the gateway export run continuously, you'll end up with two different CSV schemas in your data over time: an older full-dump format (`logical_name;capture_time;value;scaler;unit;status;signature`, with the meter id on every row) and a newer per-window export format (`id;value;scaler;unit;status;capture_time`, with no meter id column at all — the id only lives in that file's sibling XML/JSON, once per file). `scripts/normalize_meter_csv.awk` auto-detects which schema each input file uses and emits a uniform `_time;_value;_measurement` stream, filtered to a `[lo, hi)` UTC time window (edit the `BEGIN` block to change the window; the meter id can also be overridden without editing the file via `-v meter=...`):

```bash
echo "_time;_value;_measurement" > out.csv
find data -maxdepth 1 -name '*.csv' -print0 \
  | xargs -0 awk -f scripts/normalize_meter_csv.awk -- >> out.csv
```

`xargs` batches the file list automatically, which matters once `data/` accumulates tens of thousands of small export files — passing them all directly to one `awk` invocation would hit the OS's argument-length limit.

### Filling gaps in already-exported data

If a gap-detection pass turns up missing readings, `read_SMGW.py` can re-request each gap window directly from the gateway (it often still has the data in its own history, even if an earlier export missed it):

```bash
python read_SMGW.py \
    --user <user> --password <password> --meter <meter> \
    --from "2025-04-07 00:45:00" --to "2025-04-07 05:45:00" \
    --out-path <path>
```

Two things to know:
- `--out-path X` writes into `X/data/`, not `X` directly.
- Each request is a full digest-auth handshake plus several sequential POSTs, so it's slow — batches of more than ~6 requests can approach the default shell timeout. Run larger gap lists in a few sequential batches.

### Adding a gaps overview to the `Verbrauch` sheet

`meter_reading2consumption.py --add-gaps` inserts a "Lücken (keine Daten vom SMGW)" block — Start / Ende / Dauer columns, with a live `=Ende-Start` duration formula — into the `Verbrauch` sheet, for gaps over 20 minutes. This is the current, maintained way to get a gaps overview; see the `--append-to` section above for the common case of refreshing it on an existing workbook.

`generate_excel/add_gaps_to_verbrauch.py` (using `generate_excel/gap_detector.py`) is the original standalone version of the same functionality, kept around for one-off use against a workbook you don't otherwise want to touch with `meter_reading2consumption.py`:

```bash
python3 generate_excel/add_gaps_to_verbrauch.py \
    --xlsx <workbook>.xlsx \
    --input <normalized>.csv \
    --delta 20m
```

`--delta` is the threshold above which a gap between two consecutive readings gets reported — set it to a bit more than your normal reading interval (e.g. `20m` for 15-minute readings).

## Getting Started: The Full Guide

If you have meters for electricity, water, gas, etc., you may want to read them.
Consumption, trends and comparisons are certainly desirable.
If you know the data situation, you can take measures to save resources and measure the effects.

The first step is to gain technical access to the meter data.
The next step is to store the meter readings with a time stamp. The last step is to analyse the data.

As an option for accessing data from a digital electricity meter, I will describe a **PPC Smart Meter Gateway**.

For data storage I use **InfluxDB v2**, **InfluxDB v3** and **MySQL** (in the **MariaDB** variant).

There are some useful Python scripts for processing the data, such as calculating monthly consumption based on meter readings.

There is separate documentation for each of the different topics:
- [Using the PPC Smart Meter Gateway](docs/Using_the_PPC_Smart_Meter_Gateway.md)
- [The SMGW `status` field: format and meaning](docs/smgw-status-field.md)

To write readings from the gateway directly into an InfluxDB v2 bucket, see `scripts/smgw2influx.sh`. To cross-check a local CSV export against what ended up in InfluxDB — useful for telling real device-side data loss apart from a pipeline-specific gap — see `scripts/compare_influxdb_gaps.py` and `scripts/compare_influxdb_values.py`.




