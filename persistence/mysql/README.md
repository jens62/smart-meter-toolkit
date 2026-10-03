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

## Known limitation

The last reading of a period is only picked up if it is already in the raw
table when the procedure runs. With Telegraf's flush interval a reading from
the last seconds before midnight can arrive after the run, then the period
uses the reading before it (difference of one reading, typically about 0.001 kWh,
balanced by the following period). Starting the event a few seconds after the
full hour (e.g. `STARTS` at `hh:00:30`) avoids that.
