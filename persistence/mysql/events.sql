-- Hourly trigger for proc_calculate_consumption_all_rates (procedures.sql).
-- Requires the event scheduler to be enabled - see README.md.
-- Optional: let it run a few seconds after the full hour (STARTS at hh:00:30) so that the last
-- reading of the previous hour has been written by telegraf; the exact second does not matter
-- for correctness, the procedure only counts readings before the period boundary.

CREATE EVENT IF NOT EXISTS ev_calculate_consumption
ON SCHEDULE EVERY 1 HOUR STARTS CURRENT_TIMESTAMP
ON COMPLETION NOT PRESERVE
ENABLE
DO
BEGIN
    CALL proc_calculate_consumption_all_rates();
END;
