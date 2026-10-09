-- Hourly trigger for proc_calculate_consumption_all_rates (procedures.sql).
-- Requires the event scheduler to be enabled - see README.md.
-- It runs at hh:00:30, i.e. a few seconds after the full hour, so that the last reading of the
-- previous hour has already been written by telegraf (flush interval). A STARTS in the past
-- keeps this phase: the first run is the next hh:00:30.

CREATE EVENT IF NOT EXISTS ev_calculate_consumption
ON SCHEDULE EVERY 1 HOUR STARTS TIMESTAMP(DATE_FORMAT(NOW(), '%Y-%m-%d %H:00:30'))
ON COMPLETION NOT PRESERVE
ENABLE
DO
    CALL proc_calculate_consumption_all_rates();
