-- Hourly trigger for proc_calculate_consumption_all_rates (procedures.sql).
-- Requires the event scheduler to be enabled - see README.md.

CREATE EVENT IF NOT EXISTS ev_calculate_consumption
ON SCHEDULE EVERY 1 HOUR STARTS CURRENT_TIMESTAMP
ON COMPLETION NOT PRESERVE
ENABLE
DO
BEGIN
    CALL proc_calculate_consumption_all_rates();
END;
