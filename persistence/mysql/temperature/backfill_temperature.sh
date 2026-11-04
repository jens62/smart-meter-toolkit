#!/bin/bash
# Register an rtl_433 sensor for the temperature roll-ups and back-fill its history.
#
#   backfill_temperature.sh <db_name> <model> <id> [from_utc]
#
#   from_utc   start of the history, UTC 'YYYY-MM-DD HH:MM:SS'. Default: the hour of the first
#              reading of this sensor in rtl_433_events.
#
# What it does (safe to repeat):
#   1. inserts/activates the sensor in rtl_433_TEMPERATURE_config (an existing row keeps its
#      data_from_utc, max_gap_seconds and lookback_hours, it is only set to active = 1),
#   2. CALL proc_calculate_temperature_range(model, id, from_utc, now) - creates the six tables
#      and writes every closed period.
# From then on the hourly event (events_temperature.sql) keeps the sensor up to date.
#
# Extra mysql options (user, host, socket) go in MYSQL_ARGS, e.g. MYSQL_ARGS='-u user -p'.
# Prerequisite: schema_temperature.sql, procedures_temperature.sql and events_temperature.sql
# are installed.
set -euo pipefail

if [ $# -lt 3 ] || [ $# -gt 4 ]; then
    sed -n '2,/^set -e/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
    exit 2
fi
db=$1; model=$2; id=$3; from_utc=${4:-}

[[ $db =~ ^[A-Za-z0-9_]+$ ]]      || { echo "invalid db name: $db" >&2; exit 2; }
[[ $model =~ ^[A-Za-z0-9_-]+$ ]]  || { echo "invalid model: $model" >&2; exit 2; }
[[ $id =~ ^[0-9]+$ ]]             || { echo "invalid id: $id" >&2; exit 2; }
if [ -n "$from_utc" ] && ! [[ $from_utc =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}:[0-9]{2}$ ]]; then
    echo "invalid from_utc (use 'YYYY-MM-DD HH:MM:SS'): $from_utc" >&2; exit 2
fi

# shellcheck disable=SC2086
mysql ${MYSQL_ARGS:-} "$db" <<SQL
SET sql_mode = 'ANSI_QUOTES';
SET @model = '$model', @id = $id;
SET @from = COALESCE(NULLIF('$from_utc', ''),
    (SELECT DATE_FORMAT(MIN(time), '%Y-%m-%d %H:00:00') FROM rtl_433_events WHERE model = @model AND id = @id));
SELECT IF(@from IS NULL, 'no readings for this model/id in rtl_433_events', CONCAT('history from ', @from, ' UTC')) AS info;
INSERT INTO rtl_433_TEMPERATURE_config (model, id, data_from_utc) VALUES (@model, @id, @from)
    ON DUPLICATE KEY UPDATE active = 1;
SELECT data_from_utc INTO @from FROM rtl_433_TEMPERATURE_config WHERE model = @model AND id = @id;
CALL proc_calculate_temperature_range(@model, @id, @from, UTC_TIMESTAMP());
SELECT model, id, data_from_utc, active FROM rtl_433_TEMPERATURE_config WHERE model = @model AND id = @id;
SQL
