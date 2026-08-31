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

## Known quirk

`proc_calculate_consumption_all_rates` occasionally writes a near-zero
"stub" row for a period that has barely started (see the comment at the top
of `procedures.sql`). It's most visible for monthly/weekly/quarterly/yearly
rollups, since it can sit there for a whole period before self-correcting.
Anything reading these tables for a report should exclude the still-open
current period rather than assume every row is a completed one.
