# Persistence: MariaDB/MySQL

Stores raw Tasmota IR-head readings and rolls them up into hourly / daily /
weekly / monthly / quarterly / yearly consumption tables, entirely inside
the database (no external cron job needed for the rollups themselves).

See `../../acquisition/tasmota-ir/` for how readings get here, and
`../../presentation/email/` for a report that reads the rollup tables.

## Setup

1. Create a database and a user for telegraf to write into:

   ```sql
   CREATE DATABASE IF NOT EXISTS <db_name>;
   CREATE USER IF NOT EXISTS '<db_user>'@'<db_host_or_%>' IDENTIFIED BY '<db_password>';
   -- Scope this to just the one database - telegraf never needs anything
   -- broader than that.
   GRANT ALL PRIVILEGES ON <db_name>.* TO '<db_user>'@'<db_host_or_%>';
   FLUSH PRIVILEGES;
   ```

2. Load the schema, procedure, and event, in this order:

   ```bash
   mysql -u <db_user> -p <db_name> < schema.sql
   mysql -u <db_user> -p <db_name> < procedures.sql
   mysql -u <db_user> -p <db_name> < events.sql
   ```

3. Rename every `tasmota_METER1_*` table/reference across all three files
   first if you want a different device id - it just needs to stay
   consistent with `name_override`/`table` in the telegraf configs under
   `../../acquisition/tasmota-ir/` and this folder.

4. Enable the event scheduler (events.sql's `ev_calculate_consumption` does
   nothing otherwise):

   ```sql
   SET GLOBAL event_scheduler = ON;
   ```

   Make this persist across restarts via `event_scheduler=ON` in your
   `my.cnf`/`mariadb.conf.d` - `SET GLOBAL` alone reverts on restart.

5. Point telegraf's `[[outputs.sql]]` at this database -
   `telegraf-mysql-output.conf.example` in this folder.

## Previewing a rollup without writing anything

`procedures_debug.sql` is a dry-run twin of `proc_calculate_consumption_all_rates`:
same logic, but `currentTime` is pinned to a fixed value you edit in the file
(instead of `NOW()`), and it `SELECT`s each generated query instead of
executing it - nothing gets written. Useful for previewing what a
month/quarter/year boundary rollup would do without waiting for it:

```sql
CALL proc_calculate_consumption_all_rates_debug();
```

## Time zones

- The raw table stores `time` as **UTC** in a `DATETIME` column (not `TIMESTAMP`: a
  `TIMESTAMP` is converted with the session time zone on every write and read, which loses
  or distorts values around the daylight-saving changes). Telegraf sends UTC; nothing in
  the database converts it.
- `berlin_time` (generated column) is the local Berlin wall clock of the same reading. It is
  not unique: in the repeated hour in autumn the same local time occurs twice. `time` is a plain
  index, not `UNIQUE`, for the same reason.
- The six rollup tables keep `time` = **local Berlin time** of the last reading of the period (primary
  key, what reports like `presentation/email` use) and have `time_utc` = the **UTC time of the
  same reading**. `time_utc` is unambiguous (also in the repeated autumn hour) and is what a
  dashboard in UTC should plot and filter on.
- Grafana: one MySQL data source with the time zone **UTC**. Plot/filter raw data on `time`
  and rollup tables on `time_utc`, e.g. `SELECT time_utc AS time, power_consumption_total
  FROM ..._hourly WHERE $__timeFilter(time_utc)`. Do not put expressions such as
  `CONVERT_TZ(...)` inside `$__timeFilter()` (the macro does not parse them); write the
  `BETWEEN FROM_UNIXTIME($__unixEpochFrom()) AND FROM_UNIXTIME($__unixEpochTo())` filter out.
- Telegraf: `[outputs.sql.convert] timestamp = "DATETIME"` (see `telegraf-mysql-output.conf.example`).

### Upgrading an existing installation (TIMESTAMP columns, no `time_utc`)

Do this with a backup and while telegraf keeps running into a copy, e.g. create the new raw table,
copy the history, check it (row counts and a checksum per month), then swap the names with a
single `RENAME TABLE`. Read `time` as UTC wall clock when converting: do the conversion in a session
whose time zone is the one that was used when the rows were written. For the rollup tables:

```sql
ALTER TABLE tasmota_METER1_SENSOR_CONSUMPTION_hourly MODIFY time DATETIME NOT NULL;   -- same for the others
ALTER TABLE tasmota_METER1_SENSOR_CONSUMPTION_hourly ADD COLUMN time_utc DATETIME NULL AFTER time,
                                                     ADD KEY idx_time_utc (time_utc);
UPDATE tasmota_METER1_SENSOR_CONSUMPTION_hourly c JOIN tasmota_METER1_SENSOR r
   ON r.berlin_time = c.time AND r.SML_1_8_0__Bezug_Gesamt <=> c.SML_1_8_0__Bezug_Gesamt
   SET c.time_utc = r.time;                                                           -- same for the others
-- rows without a matching raw reading (very old data): unambiguous conversion from the label
UPDATE tasmota_METER1_SENSOR_CONSUMPTION_hourly SET time_utc = CONVERT_TZ(time, 'Europe/Berlin', 'UTC') WHERE time_utc IS NULL;
```

Then reload `procedures.sql` (it fills `time_utc` for new rows) and check that
`CONVERT_TZ(time_utc, 'UTC', 'Europe/Berlin') = time` holds for every row.

## Stub rows and lost periods (fixed)

Earlier versions of `proc_calculate_consumption_all_rates` could write a
near-zero "stub" row (consumption 0.001, dated the first seconds of the new
period) at a period boundary - for the monthly table e.g. `01.06 - 01.06`
instead of `01.06 - 30.06` in a report. This was documented as harmless and
"self-correcting". **It is not:** the stub becomes the table's cursor, and at
the next boundary the period that just ended has no predecessor in the
window, so it is dropped. Every stub therefore costs one lost period (a
missing month in the monthly table, a missing week in the weekly table, ...).
Details are in the comment at the top of `procedures.sql`.

Fixed by only counting readings **before** the start of the currently open
period. `procedures.sql` now contains `proc_calculate_consumption_all_rates_at(p_now)`
(the logic, callable for any moment) and `proc_calculate_consumption_all_rates()`
(calls it with `NOW()`, used by the event).

### Upgrading an installation that already has stub rows

1. Back up the rollup tables (`mysqldump`).
2. Reload `procedures.sql` (and `procedures_debug.sql`).
3. Find the stubs: rows whose `time` is within the first minute of a period and
   whose consumption is ~0.001, e.g. for the monthly table
   `SELECT * FROM tasmota_METER1_SENSOR_CONSUMPTION_monthly WHERE DAY(time) = 1 AND TIME(time) < '00:01:00';`
   (weekly: `WEEKDAY(time) = 0`; quarterly/yearly accordingly).
4. For each table, delete all rows from the first stub on (the lost periods
   after it are rebuilt from the raw readings) and let the procedure recompute
   them for a moment at which the periods are due and completed, e.g. monthly and quarterly:

   ```sql
   DELETE FROM tasmota_METER1_SENSOR_CONSUMPTION_monthly WHERE time >= '<first stub day> 00:00:00';
   CALL proc_calculate_consumption_all_rates_at('<first day of the current month> 00:00:00');
   ```

   For the weekly table use a Monday 00:00:00 as the moment. Rows before the
   first stub stay untouched. Check the result against a report or the raw
   readings before dropping your backup.

Use `CALL proc_calculate_consumption_all_rates_debug_at('<moment>');` first to see
which periods would be processed and with which boundary.
