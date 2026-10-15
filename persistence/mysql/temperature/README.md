# Temperature roll-ups (rtl_433)

Time-weighted average temperature per **hour / day / week / month / quarter / year** for one
rtl_433 sensor (`model` + `id`), computed inside the database and stored in six tables per sensor,
in the same spirit as the consumption roll-ups in `../` (`proc_calculate_consumption_all_rates`).

Example sensor used below: `model = 'inFactory-TH'`, `id = 168`, raw table `rtl_433_events`
(written by telegraf, `time` is UTC `DATETIME`, temperature in `temperature_F`).

## Files

| File | Purpose |
|---|---|
| `schema_temperature.sql` | Index on the raw table, config table `rtl_433_TEMPERATURE_config` (one row per sensor). |
| `procedures_temperature.sql` | Helper functions, `proc_create_temperature_tables`, the roll-up, `proc_calculate_temperature_range` (repair/back-fill). |
| `events_temperature.sql` | `ev_calculate_temperature`, runs hourly at hh:05:30. |

## Setup

```bash
mysql -u <db_user> -p <db_name> < schema_temperature.sql
mysql -u <db_user> -p <db_name> < procedures_temperature.sql
mysql -u <db_user> -p <db_name> < events_temperature.sql     # needs event_scheduler=ON, see ../README.md
```

The first run (the event, or `CALL proc_calculate_temperature_all_rates('inFactory-TH', 168);`)
creates the six tables and back-fills everything from `data_from_utc` on. The database account
that creates the procedures needs `CREATE TEMPORARY TABLES` (the roll-up uses temporary tables).

For another sensor add a row to `rtl_433_TEMPERATURE_config` and a `CALL` line to the event.

## Tables

Names: `rtl_433_<model>_<id>_TEMPERATURE_<period>` with characters other than `A-Za-z0-9` in the
model replaced by `_`, e.g. `rtl_433_inFactory_TH_168_TEMPERATURE_daily` (`hourly`, `daily`,
`weekly` (Monday), `monthly`, `quarterly`, `yearly`). All six have the same columns:

| Column | Meaning |
|---|---|
| `model`, `id` | The sensor (also in the table name). |
| `period_start_utc` (PK), `period_end_utc` | UTC start and exclusive end. For day and longer, `period_start_utc` is the UTC time of **local midnight** (e.g. `2026-10-24 22:00:00` for the local day 25 Oct 2026). |
| `period_start_local` | Local wall clock of the start (label for reports). |
| **`avg_temp_c`** | **The time-weighted average in °C** (`integral_cs / covered_seconds`). Generated column. |
| `n_samples` | Readings inside the period. |
| `first_sample_utc`, `last_sample_utc` | First and last reading inside the period. |
| `min_temp_c`, `max_temp_c` | Lowest / highest reading inside the period. |
| `avg_sample_c` | Plain arithmetic mean of the readings (sanity check, shows how much time weighting matters). Generated. |
| `integral_cs`, `covered_seconds` | The integral of the temperature curve (°C·s) and the seconds it covers. Higher levels are exact sums of the hourly values of these two. |
| `expected_seconds`, `coverage_pct` | Length of the period (3600, 82800 and 90000 on DST days, ...) and the share covered by data. |
| `max_gap_seconds`, `n_excluded_gaps`, `gap_limit_seconds` | Longest gap between readings starting in the period, number of gaps longer than the limit (not bridged), the limit that was applied. |
| `sum_sample_c`, `computed_at` | Helper for the roll-up, time of the calculation (UTC). |

## How the average is calculated

* The readings form a piecewise linear curve (trapezoid rule); the average of a period is the
  integral divided by the **covered** time, not by 24 h. Days with outages are therefore not
  biased towards zero, and `coverage_pct` tells how much of the day was real data.
* The UTC **hour** is the building block: an interval between two readings is cut at the hour
  boundary with linear interpolation (so readings crossing midnight are split correctly). Day,
  week, month, quarter and year are exact sums of hourly rows, so all levels agree.
* Day ... year follow the **local time of the OS** (`CONVERT_TZ(..., 'SYSTEM')`), including DST
  (23 h and 25 h days). Hourly rows are keyed by UTC, so the repeated hour in autumn is two rows
  with the same `period_start_local` but different `period_start_utc`. Requirement: the local
  midnight must exist exactly once (true for Europe).
* Identical timestamps are collapsed to one reading (rtl_433 repeats transmissions).
* The temperature comes from `temperature_F` converted to °C. (`temperature_C` is `NULL` in the
  existing data; the procedure uses it if it is filled.)

## Decisions

### 1. Provisional rows or final only → **A: final only**

Question: what happens with the current, not yet finished hour/day/... ?

| | **A: final only (chosen)** | B: provisional rows with an `is_final` flag | C: final only, plus a live view for the open period |
|---|---|---|---|
| How it works | A row appears only once its period is closed and its last hour is final. | Open periods are written right away with `is_final = 0` and recomputed every run. | Tables hold only final rows; a view computes the open day, week, ... on demand. |
| Pros | Same semantics as the consumption tables, so existing report code works unchanged. No row ever changes meaning. Simplest to reason about. | "Today so far" is available; dashboards need no special case. | Tables stay clean and final, live values are still available. |
| Cons | The newest day/week/month is missing until it has ended; no "current" value. | A consumer that forgets `WHERE is_final = 1` can mistake a partial value (a partial month) for a final one. | More code, two code paths that must agree. |

Consequences of A in this implementation:

* An **hour is final** when a later reading exists (the interval that crosses the hour boundary
  is then known) or when `max_gap_seconds` have passed without one. The same logic answers
  "what if there is no reading yet to interpolate the last temperature of the previous day":
  nothing is written for that hour yet, and **the next run computes it** (verified, see below).
* A day/week/month/quarter/year is written when it has ended and all its hours are final.
* There is no `is_final` column. "Final" means closed: rows inside the look-back window
  (`lookback_hours`, default 48) are recomputed on every run, so late readings are picked up;
  older rows change only if you call `proc_calculate_temperature_range`.

### 2. `max_gap` → **60 minutes**

Question: two readings further apart than this are not bridged (no interpolation, the time is
not counted). The data of sensor 168 (period since 27 Sep 2026, about 429 h):

| Gap size | Intervals | Hours | Cumulative coverage |
|---|---|---|---|
| ≤ 5 min | 8,980 | 276 | 64 % |
| 5–10 min | 666 | 78 | 83 % |
| 10–15 min | 184 | 37 | 91 % |
| 15–30 min | 84 | 28 | 98 % (at 30 min) |
| 30–60 min | 11 | 7 | 99.5 % (at 60 min) |
| 1–6 h | 2 | 2 | 100 % |

The distribution is a continuum, there is no natural cut.

| | 30 min | **60 min (chosen)** |
|---|---|---|
| Pros | Conservative: never interpolates across a long outage. 98 % of the recorded time counts. | Bridges 11 more gaps (all 33–46 min). Coverage 99.5 %. |
| Cons | The 33–46 min gaps are dropped, and most of them are at night, so the daily mean is biased towards daytime temperatures. | Interpolates linearly across up to 1 h, which would hide a real temperature swing in that hour. |
| Limit | | 60 min is the maximum of this design (an interval may cross at most one hour boundary). |

The value is `max_gap_seconds` in `rtl_433_TEMPERATURE_config` (capped at 3600). Changing it is
not destructive: everything is recomputed from the raw readings, so
`CALL proc_calculate_temperature_range('inFactory-TH', 168, '<data_from_utc>', UTC_TIMESTAMP());`
rewrites all rows with the new limit. `n_excluded_gaps` and `coverage_pct` flag days that rest
on little data.

### 3. Start of the data → **first data in September 2026**

`data_from_utc = '2026-09-01 00:00:00'` in the config table. Readings before it are ignored
completely (no row, no interpolation anchor); the first reading on or after it is
`2026-09-27 10:03:32` UTC. There is a gap of about 293 days before that reading, so the older
readings (Dec 2025) would have produced nothing useful anyway. The first month, quarter and
week therefore have a low `coverage_pct`.

### 4. Time zone → **the OS time zone, via `'SYSTEM'`**

`@@system_time_zone` shows `CEST`, which is only the abbreviation at server start, so it is not
used as a zone name. `CONVERT_TZ(x, '+00:00', 'SYSTEM')` follows the OS including its DST
rules (verified on the server: `2026-07-01 12:00 UTC → 14:00`, `2026-12-01 12:00 UTC → 13:00`,
and the switch on 25 Oct 2026).

`TIMEDIFF(NOW(), UTC_TIMESTAMP())` was considered instead: it gives only the **current** offset
(`02:00:00` now). That is wrong for every timestamp on the other side of a DST change (after
25 Oct the offset is `01:00:00`, but September still needs `+02:00`), so it cannot be used to
convert stored timestamps. `'SYSTEM'` needs no time zone tables.

## Operation

```sql
-- what the event does every hour
CALL proc_calculate_temperature_all_rates('inFactory-TH', 168);

-- the same for a given moment (UTC), e.g. to test or catch up
CALL proc_calculate_temperature_all_rates_at('2026-10-15 06:35:30', 'inFactory-TH', 168);

-- repair / re-calculate a range (e.g. after changing max_gap_seconds); UTC, rounded to hours
CALL proc_calculate_temperature_range('inFactory-TH', 168, '2026-09-01 00:00:00', UTC_TIMESTAMP());

-- daily averages, newest first
SELECT period_start_local AS day, ROUND(avg_temp_c, 2) AS avg_c, n_samples,
       ROUND(coverage_pct, 1) AS coverage_pct
FROM rtl_433_inFactory_TH_168_TEMPERATURE_daily
ORDER BY period_start_utc DESC;
```

Grafana (data source time zone UTC): plot `period_start_utc AS time` and filter with
`$__timeFilter(period_start_utc)`.

Every run recomputes from the raw readings: there is no "cursor" row that can get out of step,
which is what caused the lost periods described in `../README.md` ("Stub rows and lost
periods"). After an outage of the event scheduler the next run catches up on its own.

## Verification

Run against a copy of the real readings of sensor 168 in a throw-away MariaDB 10.11 container
with `TZ=Europe/Berlin` and `sql_mode=ANSI_QUOTES`:

* All 18 closed days (27 Sep to 14 Oct 2026): `avg_temp_c` and `covered_seconds` equal an
  independent day-based calculation (different SQL, offset +2 h, 3600 s gap limit) to 9
  decimals.
* Replaying the data hour by hour with a simulated clock (each run sees only the readings that
  existed at that moment) produces exactly the same rows as the one-shot back-fill. At 06:05:30
  on 15 Oct hour 05:00 is correctly **not** written yet (last reading 05:57:30, the next
  06:11:18 had not arrived); the next run writes it. A replay every 30 minutes gives the same
  result.
* Running the same moment twice changes nothing. `proc_calculate_temperature_range` repairs a
  damaged row, including a range that ends in the middle of a day, and a full range reproduces
  the original state exactly.
* Month = sum of its days, quarter = month, three weeks = their days (integral and covered
  seconds; difference 1e-9 °C·s from floating point).
* DST, synthetic sensors with one reading per minute around 25 Oct 2026: the local day has
  `expected_seconds = 90000`, runs from `2026-10-24 22:00` to `2026-10-25 23:00` UTC; a ramp of
  exactly +1 °C/h gives daily means of 10.0 / 34.5 / 59.0 °C (the value at the middle of the
  day); a 90 minute outage gives `covered_seconds = 81000`, `n_excluded_gaps = 1`,
  `max_gap_seconds = 5400`; the repeated hour shows as two rows with the same
  `period_start_local`.
