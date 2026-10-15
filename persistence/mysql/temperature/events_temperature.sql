-- Hourly trigger for proc_calculate_temperature_all_rates (procedures_temperature.sql).
-- Requires the event scheduler to be enabled - see ../README.md.
-- It runs at hh:05:30, after ev_calculate_consumption (hh:00:30), so the last readings of the
-- previous hour have been written by telegraf. A STARTS in the past keeps this phase: the first
-- run is the next hh:05:30. One CALL per sensor; add a line for every sensor you roll up.

CREATE EVENT IF NOT EXISTS ev_calculate_temperature
ON SCHEDULE EVERY 1 HOUR STARTS TIMESTAMP(DATE_FORMAT(NOW(), '%Y-%m-%d %H:05:30'))
ON COMPLETION NOT PRESERVE
ENABLE
DO
    CALL proc_calculate_temperature_all_rates('inFactory-TH', 168);
