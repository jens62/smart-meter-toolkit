# Scripts reference

Detailed reference for every script in this repo: what it does, its
important CLI flags, what it reads/writes, and gotchas worth knowing
before relying on it. `README.md` has quickstart usage; this doc goes
deeper on behavior and edge cases. `TODO.md` is the backlog, not
documentation - anything settled/permanent belongs here instead.

## Pipeline overview

```
gateway (SMGW)
  |
  |  every 14 min                     nightly, ad hoc, or via gap_backfill.py
  v                                    v
smgw2influx.sh --------> InfluxDB     read_SMGW.py (raw export_*.{cms,xml,csv,json})
  (readSMGW_multipleContracts.sh)          |
                                            v
                                       data/ directory
                                            |
                              +-------------+-------------+
                              v                           v
                     normalize_meter_csv.awk      daily-tar.sh / monthly-assemble.sh
                              |                    (archives/daily, archives/monthly)
                              v
                  meter_reading2consumption.py
                     (--append-to --add-gaps)
                              |
                              v
                       Excel workbook(s)
                    (one per detected meter)
```

`gap_backfill.py` sits between "gateway" and "data/ directory" in this
picture - it's just another way of populating `data/` with raw exports,
triggered by detected gaps rather than a fixed polling interval.

## Gateway access and export

### `read_SMGW.py`

Python rewrite of the gateway export logic, with automatic time-range
splitting for large requests. This is what `gap_backfill.py` shells out
to, and what the README's "Filling gaps in already-exported data"
section uses manually.

Key flags:

| Flag | Meaning |
|---|---|
| `--from` | `YYYY-MM-DD[ HH:MM:SS]`, or `0` for "use `--recording_started`" |
| `--to` | `YYYY-MM-DD[ HH:MM:SS]`, or `now` |
| `--past` | Relative range from now (e.g. `2h`) - mutually exclusive with `--from`/`--to` |
| `--recording_started` | What `--from 0` resolves to (default `2023-01-01 00:00:00`) |
| `--out-path` | Writes into `<out-path>/data/`, not `<out-path>` directly |
| `--out-format` | Any of `cms xml csv json` (default: all four) |
| `--meter` | Required when the gateway serves more than one meter |
| `--list-meters` | Connect, print every meter currently in the gateway's own meter-select form (one per line), and exit - no `--from`/`--to`/`--meter` needed |
| `--max` / `--interval` | Chunk sizing for splitting a large `--from`/`--to` span into multiple gateway requests - see "Chunking gotcha" below |

**Meter discovery (`--list-meters`)**: the gateway's `meterform` HTML
response includes a `<select name="mid">` with one `<option>` per meter
it currently sees (`extract_mid_and_tkn()` already parsed this to
validate `--meter` against, erroring out with the full list if `--meter`
was omitted and there was more than one option - `--list-meters` just
returns that same list instead of erroring). This is what
`gap_backfill.py` uses to discover meters dynamically instead of relying
on a fixed config value - see its own section below.

**A meter being physically disconnected doesn't reliably remove it from
this list.** Checked directly on 2026-07-15: `--list-meters` against
this household's real gateway still returned *both*
`01005e318002.1itr0310077721.sm` (ITR03, physically swapped out for
EMH00 back in 2023) *and* `01005e318002.1emh0011802881.sm` (EMH00, the
one actually connected today). Don't design anything that assumes a
disconnected meter will eventually stop appearing here - it may not,
at least not on this gateway/firmware.

**Timezone**: `--from`/`--to` are plain wall-clock strings passed
straight through to the gateway's own `exportMeterValues` HTTP action -
no timezone conversion happens in this script at all. Confirmed by
reading `parse_date()` (no tz-aware parsing) and the request-building
code (`'from': from_str` sent as-is). The gateway itself is synced to
German legal/local time per BSI TR-03109-1 (see
`docs/smgw-status-field.md`), so use Europe/Berlin wall-clock, matching
what the Excel workbook itself stores.

**Chunking gotcha**: `calculate_time_ranges()` (the same buggy logic was
also present, separately, in the now-retired
`readSMGW_multipleContractsInRanges.py` - see below) turns
`--interval`/`--max` into a *minimum chunk size in whole days*, clamped
to at least 1 day - it does **not** cap the total number of requests.
`--from 0 --to now --max 1` (a hint the script's own `--help` gives) does
**not** mean "one request" - with a multi-year `--from`/`--to` span it
splits into one request *per day* in that span, e.g. `--from
2023-01-01` produced ~1,291 sequential requests before being killed
(see `local-assets/smgw_retention_probe/` for how this was discovered
and stopped). For a **small, explicit** `--from`/`--to` window (a few
hours or less), this doesn't apply - the algorithm always collapses to
exactly one request once the requested span is smaller than the minimum
chunk size, verified directly in `pad_local_time()`'s test-through and
in the binary-search probes referenced above. Always use small explicit
windows, never a wide `--from 0 --to now`-style span, when probing or
recovering specific dates.

**Server-side 500 behavior**: a single request whose window straddles
both a period the gateway has data for and one it doesn't (e.g. spans a
retention boundary) returns a full `500 Internal Server Error`, not a
partial result - confirmed by re-testing an already-confirmed-good
sub-window immediately after such a failure and getting a clean success
again (ruling out general flakiness). Keep probe windows tightly scoped
to a single question ("does data exist near <date>?"), not wide ranges.

### `readSMGW_multipleContracts.sh` (legacy, but still actively used)

Older bash gateway reader, predates this repo but *is* tracked in it
(added 2026-07-11) - `smgw2influx.sh` depends on it directly via
`--readsmgw-script`. Same `--from`/`--to`/`--past`/`--recording_started`
contract as `read_SMGW.py` above. Not superseded by anything, unlike its
Python-side siblings below - still the one the live 14-minute polling
job actually runs.

### `readSMGW_multipleContractsInRanges.py` (retired 2026-07-15)

A Python gateway reader that used to live alongside the scripts above
directly on `ubuntu24-studio` (never part of this repo), used for manual
gateway probing throughout this project's early investigation (the
retention-boundary bisection, the exhaustive per-gap checks). Confirmed
2026-07-15 to be fully superseded by `read_SMGW.py`, not just similar:
every function it has, `read_SMGW.py` also has (under the same or an
equivalent name), plus several it lacks entirely
(`get_namespaces`/`list_meters`/`parse_xml_entry`); every line unique to
it in a full diff was duplicated, less robust XML-parsing logic
(hardcoded namespace prefixes instead of `get_namespaces()`'s dynamic
discovery) or a stricter, less graceful `--meter` requirement. Moved to `archives/scripts/` on the deployment host, along with the
other long-dormant script versions found there (see "Housekeeping"
below). Use `read_SMGW.py` for any future manual gateway investigation
instead.

### `smgw2influx.sh`

Writes gateway readings directly into an InfluxDB v2 bucket, via the
legacy `readSMGW_multipleContracts.sh`.

| Flag | Meaning |
|---|---|
| `--user` / `--password` | Gateway credentials (`--password` optional if `$SMGW_PASSWORD` is set) |
| `--meter` | Meter logical name |
| `--host` | Gateway IP (default: the underlying script's own default) |
| `--past` | Minutes back to fetch (default 30) |
| `--divisor` | Raw counter value -> target unit (default 10000, Wh -> kWh) |
| `--influx-url` / `--influx-org` / `--influx-bucket` | InfluxDB target (`--influx-token` optional if `$INFLUXDB_TOKEN` is set) |
| `--measurement` | InfluxDB measurement/item name - required, no env fallback |

Scheduled every 14 minutes in `crontab.example` (not 15, so a single
missed run can't create a gap against the meter's own 15-minute
interval).

**Deployment history**: `ubuntu24-studio` originally ran an ad-hoc
hardcoded copy (credentials and InfluxDB target inline, no CLI args at
all) that predated this script's existence in the repo. Replaced
2026-07-15 with this actual repo version, wired to
`~/.config/smgw-pipeline.env` like every other job - same underlying
reader (`readSMGW_multipleContracts.sh`), just the parameterized wrapper
instead of the hardcoded one. Verified with a real write before cutover
and again after, independently confirmed via a Flux query-back. The old
copy is kept at
`archives/scripts/smgw2influx.sh.legacy-hardcoded` on the host, not
deleted. This is a smaller, separate step from `TODO.md` item 10's first
bullet (discovering meters dynamically via `read_SMGW.py`, replacing
`readSMGW_multipleContracts.sh` itself) - that part is still open; this
was just retiring the hardcoded wrapper around the same underlying
reader.

## Normalization

### `normalize_meter_csv.awk`

Auto-detects which of three raw export CSV schemas a file uses and
emits a uniform `_time;_value;_measurement` stream, filtered to a
`[lo, hi)` UTC window:

- **Schema 1** (`logical_name;capture_time;value;scaler;unit;status;signature`):
  meter id on every row.
- **Schema 2** (`id;value;scaler;unit;status;capture_time`): no meter id
  column - falls back to the `meter` variable (override with
  `-v meter=...`).
- **Schema 3** (`no;meter;id;...` or `no;cis;meter;id;...`): multi-contract
  dumps with varying column count - locates `meter`/`value`/`capture_time`
  by header name, not fixed position.

`lo`/`hi`/`meter` are set in the `BEGIN` block and can all be overridden
via `-v` without editing the file. `status` (present in schemas 1 and 2)
is currently discarded - see `docs/smgw-status-field.md` and `TODO.md`
item 9 for what it means and the plan to surface it.

Files with schema-3 headers occasionally have every row joined by a
literal two-character `\n` instead of a real newline (a bug in whatever
produced them) - `meter_reading2consumption.py`'s
`fix_literal_newlines()` detects and repairs this before handing files
to this script; the awk script itself doesn't handle it.

## Excel generation and consumption calculation

### `meter_reading2consumption.py`

The core script. Three broad modes:

1. **Fresh generation** (`--folder`/`--file`/`--stdin` without
   `--append-to`): builds a new workbook (or one workbook per detected
   meter, if the input covers more than one - see below) from scratch.
2. **Incremental merge** (`--append-to XLSX`): merges newer or backfilled
   readings into an existing workbook in place. `--folder` in this mode
   means something different - see below.
3. **Downsampling/reformatting** (`--keep-every`): thins out rows for
   quick spreadsheet checks, independent of the other two modes.

Key flags:

| Flag | Meaning |
|---|---|
| `--folder` | **Fresh generation**: any files matching `--pattern` (default any `.csv`), top-level only, not recursive. **`--append-to`**: the raw `export_*.csv`/`.json`/`.xml` folder, scanned recursively |
| `--append-to` | Existing workbook to update instead of generating a new one |
| `--meter` | Meter id override for raw exports under `--append-to` (default: auto-detected per file from its `.json`/`.xml` sibling) |
| `--divisor` | Raw counter value -> display unit (10000 for Wh -> kWh) |
| `--add-gaps` | Adds/refreshes the "Lücken (keine Daten vom SMGW)" block. Under `--append-to`, rescans *every* month sheet each run, not just ones this run touched - a later backfill can retroactively close an older gap |
| `--out-format` | `excel` (default), `csv`, `json`, `xml`, `none`, any combination |
| `--stdout-format` | For piping into another tool; `csv`/`json`/`xml`/`none` |
| `--time-col` / `--value-col` / `--measurement-col` | Column name mapping for non-standard input (e.g. `read_SMGW.py`'s stdout CSV: `capture_time`/`value`/`logical_name`) |

**Multi-meter handling**: if the input data covers more than one meter
(e.g. the physical meter behind the gateway was swapped), this is
detected automatically from the `_measurement` column and one **complete,
separate workbook** is generated per meter - the output filename encodes
which meter and time range each file covers. This applies to fresh
generation; `--append-to` always targets one specific workbook (single
meter) by design.

**Merge semantics** (`--append-to`): a real merge, not a tail-append.
Existing rows are deduped by exact timestamp; new readings can be older
than, newer than, or interleaved with what a month's sheet already has -
useful for backfilling an archived day and topping up with a live export
in the same run. New months get a fresh sheet plus a `Verbrauch` row
inserted in chronological order (there may be hand-added rows below the
last month, e.g. a `Summe` total, so it's not assumed to be the sheet's
last row). The merge's own "already covered" cutoff comes from the
workbook's own content (`get_workbook_cutoff()`), not the `.xlsx` file's
filesystem mtime - deliberately, since a plain file copy/scp/touch
resets mtime without touching content, which previously broke the
"only process files newer than the workbook" optimization after
deploying a workbook to a new host.

**Output sheet layout**: a `Verbrauch` summary sheet (one row per month,
`=MAX(...)-MIN(...)` formula), one sheet per `YYYY_MM`, a `Summe` total
row, and a `Plausibilitätstest` cross-check row
(`jüngster Wert - ältester Wert`, should equal the `Summe` row's total).
Both extra rows are colorized like the header and get their formulas
extended automatically as new months are appended.

**Gap detection**: `find_gaps()` is DST-aware - it only re-checks
candidate gaps (already over the threshold under a naive datetime diff)
against a timezone-aware diff, and never lets that recheck manufacture a
new gap. This matters specifically for German DST: a naive diff
misreports every spring-forward transition as a ~75-minute gap, and
blindly re-localizing every pair around a fall-back can invent a gap
that was never a real candidate. `generate_excel/gap_detector.py` (see
below) does **not** have this fix - don't use it for anything where DST
correctness matters.

## Gap detection and recovery

### `gap_backfill.py`

Nightly gap-filling: detects gaps in one or more workbooks' recent
months, then re-requests each one from the gateway via `read_SMGW.py`.

| Flag | Meaning |
|---|---|
| `--workbook-dir` | Normal mode: discover every currently-connected meter and match each against a workbook found here (see "Multi-meter discovery" below) |
| `--workbook` / `--meter` | Manual override, bypassing discovery entirely - process exactly this one workbook/meter pair. Both required together if either is given |
| `--months` | Trailing month-sheets to scan per workbook (default 15, matching this gateway's measured retention - see `TODO.md` item 8) |
| `--state-file` | JSON file tracking per-gap retry state, persisted across runs |
| `--max-retries` | Give up on a gap after this many *days* of still being open (default 3) |
| `--max-requests-per-run` | Caps gateway load per run, shared across every workbook processed (not per-workbook); excess eligible gaps are deferred (oldest first), never silently dropped |
| `--pad-minutes` | Widens each gateway request on either side of the detected gap (default 30) |
| `--influx-url` / `--influx-org` / `--influx-bucket` / `--influx-measurement` | If all four (plus `--influx-token` or `$INFLUXDB_TOKEN`) are given, a successfully-recovered gap's readings are also written to InfluxDB - omit any of them to skip InfluxDB entirely |
| `--divisor` | Raw counter value -> InfluxDB unit, only used for the InfluxDB write (default 10000) |
| `--dry-run` | Detects and reports without any gateway contact, InfluxDB write, or state-file write |

**Retry semantics**: a gap is retried at most once per *calendar day*
(tracked via `last_attempt_date` in `--state-file`), so re-running the
script multiple times manually in the same day is a no-op for gaps
already attempted today - safe for testing. After `--max-retries`
separate days of still being open, a gap is marked `given_up` and
skipped on every later run, until the day it's no longer detected at
all (at which point it's dropped from the state file as resolved).

**Multi-meter discovery** (`--workbook-dir` mode, the normal
cron-scheduled path): rather than a fixed meter/workbook in config,
`resolve_workbook_meter_pairs()` (1) calls `read_SMGW.py --list-meters`
to get every meter the gateway *currently* reports, (2)
`find_candidate_workbooks()` globs `*_from_*.xlsx` in `--workbook-dir`
and reads each file's *own* stored meter id (`workbook_own_meter()` -
the "Zähleridentifikation" value from its first data row), deduping to
the latest-modified file per distinct meter, and (3) only keeps a
workbook whose meter is in the live list - a workbook whose meter isn't
currently connected is skipped and logged, since the gateway
definitionally has nothing to recover for it.

Two things this had to specifically account for, both found by testing
against the real deployment host's actual files, not assumed:

- **String format mismatch between old and new workbooks.** An
  abandoned workbook from an earlier pipeline version (found directly on
  `ubuntu24-studio`: `01005e31803c.1emh0011802881.sm_from_..._to_2025-04-18...xlsx`,
  over a year stale) stores its meter id as the *raw* dotted logical
  name, while the live workbook stores `format_measurement()`'s
  formatted form - same physical meter, two different strings. Grouping
  candidates by their raw stored id would treat these as two different
  meters and process the stale one too. Fixed by running every stored id
  through `format_measurement()` before comparing - it's idempotent (an
  already-formatted value passes through unchanged), so it correctly
  normalizes either convention to the same key regardless of which one a
  given workbook happens to use.
- **A disconnected meter isn't reliably removed from the gateway's own
  list** (see `read_SMGW.py`'s section above - ITR03 still showed up in
  2026-07-15 testing, over 2 years after being swapped out). So
  "currently connected" per this mechanism is necessary but not
  sufficient to guarantee a workbook's gaps are actually recoverable -
  if a long-dormant workbook's meter is (still) listed, its gaps will
  get genuinely queried, just harmlessly failing until `--max-retries`
  gives up on each one after a few nights. Not a problem in practice
  today (the ITR03 workbook was never deployed to `ubuntu24-studio` -
  it's a `local-assets`-only research artifact from this repo's history,
  see `TODO.md` item 10), but would matter if it, or something like it,
  ever were.

`--workbook`/`--meter` bypass all of the above for manual single-pair
use (e.g. testing) - both are required together since guessing one from
the other isn't attempted.

**Padding is DST-safe**: `pad_local_time()` localizes the naive gap
boundary, adds the padding in absolute time, then normalizes back to
local wall-clock, rather than doing plain `timedelta` arithmetic on the
naive datetime. Plain arithmetic can land on a wall-clock time that
never existed (e.g. padding across the spring-forward night can produce
"02:15", even though Europe/Berlin's clock jumps straight from 02:00 to
03:00 that night) - confirmed concretely: naive gives `02:15:00`, the
DST-safe version correctly gives `03:15:00`.

**InfluxDB writes**: the regular `smgw2influx.sh` polling job only ever
writes "the last `--past` N minutes from now" - it has no way to write a
historical gap's data, so without this a gap recovered here would show
up in the Excel workbook but never in InfluxDB. When enabled, uses the
same line-protocol shape as the legacy `smgw2influx.sh` on the
deployment host (`<measurement>,item=<measurement> value=<v>
<epoch_ns>`), so recovered points land in the same series as everything
else rather than a separate one. Deliberately **not** a shell pipeline
adapted from that legacy script, even though the shape matches: its
`awk` column positions (`$2`=value, `$6`=capture_time) match
`readSMGW_multipleContracts.sh`'s CSV, not `read_SMGW.py`'s (`capture_time`
in column 2, the value column named `long64_value` in column 3) - reusing
those column positions verbatim would silently write the wrong values.
`read_SMGW.py` also names a live query's combined CSV output
`export_from_none-files_export_<from>---<to>.csv`, not the plainer
`export_<from>---<to>.csv` the per-chunk `.cms`/`.xml` files use (its
`generate_outputs()` prefixes with `export_from_<input_format>-files_`
whenever it's given source files to combine, which a live query always
does) - `gap_backfill.py` locates the CSV with a glob on the escaped
from/to substring rather than assuming either exact name, so it isn't
tied to that detail either way.

**Where recovered files end up, and a non-obvious consequence for
archiving**: this script never touches the workbook directly - it only
writes new raw export files into `--out-path`'s `data/` subdirectory
(resolved by `read_SMGW.py`'s own `setup_paths()`), the same directory
`smgw2influx.sh`'s regular polling writes into. That means:

- The recovered files get picked up by the *next* `--append-to
  --add-gaps` run, same as any other new file in `data/`.
- **`daily-tar.sh` selects files by filesystem mtime, not by the date
  encoded in the filename.** A file recovered for, say, a 2025-06-02 gap
  gets *today's* mtime (whenever `gap_backfill.py` actually ran it), so
  it's archived into *today's* daily tar, not into `data-2025-06-02.tar`
  - that historical tar already exists and `daily-tar.sh` never reopens
    an already-archived day. If you ever go looking for a recovered
    gap's raw file in the archives, look in the tar for the day it was
    *recovered*, not the day it's *from*.

**Scheduling**: run at 01:35, before the merge job (01:50), deliberately
scheduled ~7 minutes from the nearest `smgw2influx.sh` poll (which runs
every 14 minutes around the clock) to avoid overlapping it -
schedule-only, no lock file or process check (see `crontab.example`'s
comments for the exact reasoning).

### `generate_excel/gap_detector.py` (standalone, no DST fix)

Detects gaps in a CSV via naive datetime diffing and writes a
Start/End report (Excel, JSON, or text). Predates the DST fix described
above under `meter_reading2consumption.py` - **do not** use this for
anything where DST correctness matters (i.e. anything spanning a
March/October boundary). Kept for one-off text/JSON gap reports where
that doesn't matter.

### `generate_excel/add_gaps_to_verbrauch.py` (standalone, superseded)

Original standalone version of `meter_reading2consumption.py`'s
`--add-gaps` flag - inserts a Start/Ende/Dauer "Lücken" block into an
existing workbook's `Verbrauch` sheet, using `gap_detector.py` above for
detection. `--add-gaps` is the current, maintained path; this script is
kept only for one-off use against a workbook you don't otherwise want
to touch with `meter_reading2consumption.py`.

## Archiving

### `daily-tar.sh`

Archives a day's raw export files (`export_*.{csv,json,xml,cms}`) into
one uncompressed tar per calendar day, selected by filesystem mtime (see
the `gap_backfill.py` note above for why that matters). Skips any day
whose archive already exists, so re-running - including with an
overlapping date range - is always safe. `--base-dir`/`--data-dir`/
`--daily-dir` control the layout; a `START_DATE` argument backfills a
range through yesterday.

Scheduled nightly with a 14-day lookback (not just "yesterday"), so a
multi-day host outage doesn't leave days permanently unarchived - the
skip-if-exists check makes the redundant re-checking cheap.

### `monthly-assemble.sh`

Concatenates a month's daily tars (`tar --concatenate`) into one
gzip-compressed monthly archive. Also skips a month whose archive
already exists, and supports `--lookback-months N` for the same
downtime-resilience reason as `daily-tar.sh`'s lookback. Run on day 2 of
the month so the last day of the previous month has definitely been
archived by `daily-tar.sh` first.

## Cross-checking against InfluxDB

### `compare_influxdb_gaps.py`

Compares gaps detected in a local CSV against gaps in an InfluxDB v2
measurement over the same range, to tell real device-side data loss
apart from a pipeline-specific gap (i.e. "is this missing from the
gateway too, or just from this particular export?"). Takes
`--csv`/`--timestamp`/`--delimiter`/`--delta` for the local side and
`--influx-url`/`--org`/`--bucket`/`--measurement`/`--range-start`/
`--range-stop` for the InfluxDB side.

### `compare_influxdb_values.py`

Compares a local CSV's actual readings against InfluxDB's for the same
range, row for row (within `--tolerance`), reporting rows present in one
source but missing from the other. `--divisor` converts the local CSV's
raw values to InfluxDB's units for the comparison (default 10000).
`--show-mismatches` caps how many mismatched rows get printed.

Both scripts were used this session to confirm two things worth knowing
if you use them again: InfluxDB measurement names here are per-*gateway*,
not per-*meter* - they just reflect whichever physical meter happened to
be connected at the time, so a meter swap shows up as the same
measurement's values changing character, not a new measurement
appearing. And a local export can catch readings a particular InfluxDB
write path missed, so "present in InfluxDB but missing locally" and
"present locally but missing in InfluxDB" are both real, independent
findings worth checking - one doesn't imply the other.

## Configuration and deployment

### `crontab.example`

Reference crontab for the full pipeline. Every job sources one shared
config file (see below) rather than repeating credentials/paths across
lines. Comments in this file explain scheduling decisions in detail
(why 14 minutes not 15, why 01:35 not some other minute, why lookback
windows exist) - read them before changing a schedule, since several of
the choices are load-bearing for downtime resilience, not arbitrary.

### `smgw-pipeline.env.example`

Template for the shared config file (`~/.config/smgw-pipeline.env`,
`chmod 600`, not committed to git): gateway connection (host, user,
password, meter), InfluxDB connection, and shared filesystem paths
(base data directory, workbook directory/prefix, log directory). One
file to update instead of hunting down every cron line that needs the
same value - notably relevant now that three separate jobs
(`smgw2influx.sh`, `gap_backfill.py`, and indirectly the merge job via
its paths) all need overlapping pieces of this configuration.

### `logrotate-append-excel.conf.example`

Weekly rotation, 8 kept, gzip compressed, for the merge job's log.
Uses its own state file (not root's `/var/lib/logrotate/status`) so it
works without root access - run daily via cron and let logrotate itself
decide whether a week has actually elapsed.

## Housekeeping

### `ubuntu24-studio:/home/jens/develop/smgw/archives/scripts/`

On 2026-07-15, moved 23 long-dormant script files out of the deployment
host's top-level directory into `archives/scripts/`, to make it clear
at a glance which scripts there are actually part of the running
pipeline (the 8 remaining at the top level: `daily-tar.sh`,
`gap_backfill.py`, `gap_detector.py`, `meter_reading2consumption.py`,
`monthly-assemble.sh`, `readSMGW_multipleContracts.sh`, `read_SMGW.py`,
`smgw2influx.sh`) versus historical, unreferenced versions. Verified
first that nothing (crontab, or any other script) referenced any of
them before moving.

What moved and why each was dormant, not just old:
- `readSMGW_multipleContractsInRanges.py` - confirmed superseded by
  `read_SMGW.py` (see that script's section above)
- `readSMGW_multipleContracts.py`, `meter_csv2excel.py` - earlier-named
  predecessors of `readSMGW_multipleContractsInRanges.py` and
  `meter_reading2consumption.py` respectively, before each was renamed
  and grew significantly (automatic time-range splitting; `--append-to`/
  `--add-gaps`)
- `time_ranges.py` - a standalone prototype for chunking logic that's
  since been absorbed inline into `calculate_time_ranges()` in the
  Python readers
- Every `*V<N>.<N>_ok.py`/`*V<N>.0_...py` file (for
  `readSMGW_multipleContracts(InRanges)`, `meter_csv2excel`,
  `gap_detector`) - explicit version history, superseded by the
  unsuffixed file of the same base name
- `smgw2influx17h.sh`, `smgw2influx2h.sh`, `smgw2influx48h.sh`,
  `smgw2influx9h.sh`, `smgw2influx_from_to.sh`, `smgw2influx _raspi.sh` -
  fixed-time-window forks predating today's parameterized `--past N`
  design already in the repo's `smgw2influx.sh`
- `readSMGW_multipleContracts_from_raspi.sh`,
  `readSMGW_multipleContracts_raspi_tests.sh` - a Raspberry Pi-specific
  variant and its test harness

None of these were modified in over a year and nothing referenced them
- confirmed by grepping the crontab and every remaining script for each
filename before moving anything.

A second, later addition to the same directory: the original
hardcoded `smgw2influx.sh` (see that script's section above), moved
aside as `smgw2influx.sh.legacy-hardcoded` when it was replaced by the
repo version - this one *was* actively referenced (by the live crontab)
right up until the replacement, unlike everything else in this
directory.
