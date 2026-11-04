-- Hourly trigger for proc_calculate_temperature_configured (procedures_temperature.sql): rolls up
-- every sensor that is active in rtl_433_TEMPERATURE_config, so a new or replaced sensor needs a
-- config row (backfill_temperature.sh) but no change here.
-- Requires the event scheduler to be enabled - see ../README.md.
-- It runs at hh:05:30, after ev_calculate_consumption (hh:00:30), so the last readings of the
-- previous hour have been written by telegraf. A STARTS in the past keeps this phase: the first
-- run is the next hh:05:30. CREATE OR REPLACE so that re-running this file updates an old event
-- that still called proc_calculate_temperature_all_rates for one hardcoded sensor.

CREATE OR REPLACE EVENT ev_calculate_temperature
ON SCHEDULE EVERY 1 HOUR STARTS TIMESTAMP(DATE_FORMAT(NOW(), '%Y-%m-%d %H:05:30'))
ON COMPLETION NOT PRESERVE
ENABLE
DO
    CALL proc_calculate_temperature_configured();
