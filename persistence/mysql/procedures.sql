-- Rolls raw tasmota_METER1_SENSOR readings up into the six
-- tasmota_METER1_SENSOR_CONSUMPTION_* tables (see schema.sql). Called
-- hourly by the ev_calculate_consumption event (events.sql).
--
-- For each period type due this run, it looks at raw readings newer than
-- that period table's own last stored row (its "cursor", MAX(time)) and
-- OLDER than the start of the period that is currently open, keeps only the
-- single latest raw reading per period-bucket (hour/day/ISO-week/month/
-- quarter/year) in that window, and inserts the delta between consecutive
-- buckets as power_consumption_*.
--
-- Structure:
--   proc_calculate_consumption_all_rates_at(p_now)  the logic; can be called for a specific
--                                                   moment (tests, repairs, catching up)
--   proc_calculate_consumption_all_rates()          calls the above with NOW(); this is what
--                                                   the event calls
--
-- Why the upper bound ("only readings before the open period starts")
-- ------------------------------------------------------------------
-- Earlier versions had no upper bound. The periods are processed one after
-- the other (hourly, daily, weekly, monthly, ...), and each statement used
-- every reading that was already in the raw table when IT ran - up to
-- several seconds after the full hour. If a reading of the NEW period was
-- already there, it formed a bucket of its own and produced a near-zero
-- "stub" row dated the first moment of the new period. That is not
-- harmless: the stub becomes the cursor, so at the next period boundary
-- the window starts at the stub, the period that just ended is the first
-- bucket in the window, has no predecessor (LAG() is NULL) and is dropped
-- by the "delta IS NOT NULL" filter. One period is lost permanently for
-- every stub (a missing month in the monthly table, a missing week in the
-- weekly table, ...). It does NOT self-correct.
--
-- Since this version only counts readings before the period boundary
-- (Periods.boundary), no stub can be created, regardless of how late a
-- statement runs. The period detection is also robust now: HOUR(currentTime)
-- = 0 instead of "exactly 00:00:00" (an event that starts one second late
-- would skip the daily/monthly rollups) and WEEKDAY() instead of the
-- locale dependent DATE_FORMAT(..., '%W') = 'Montag'.
--
-- Upgrading an installation that already has stub rows: see README.md
-- ("Stub rows and lost periods").

SET sql_mode = 'ANSI_QUOTES';

DELIMITER $$

DROP PROCEDURE IF EXISTS proc_calculate_consumption_all_rates_at$$
CREATE PROCEDURE proc_calculate_consumption_all_rates_at(IN p_now DATETIME)
BEGIN
    DECLARE periodIndex INT DEFAULT 1;
    DECLARE v_periodName VARCHAR(20);
    DECLARE v_intervalValue VARCHAR(128);
    DECLARE v_partitionExpression VARCHAR(128);
    DECLARE v_tableName VARCHAR(100);
    DECLARE v_boundary DATETIME;
    DECLARE insert_query VARCHAR(2176);
    DECLARE currentTime DATETIME DEFAULT p_now;
    

    
    CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_hourly (
        time TIMESTAMP NOT NULL,
        SML_1_8_0__Bezug_Gesamt DOUBLE,
        SML_1_8_1__Bezug_HT DOUBLE,
        SML_1_8_2__Bezug_NT DOUBLE,
        power_consumption_total DOUBLE,
        power_consumption_HT DOUBLE,
        power_consumption_NT DOUBLE,
        PRIMARY KEY (time)
    );

    CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_daily (
        time TIMESTAMP NOT NULL,
        SML_1_8_0__Bezug_Gesamt DOUBLE,
        SML_1_8_1__Bezug_HT DOUBLE,
        SML_1_8_2__Bezug_NT DOUBLE,
        power_consumption_total DOUBLE,
        power_consumption_HT DOUBLE,
        power_consumption_NT DOUBLE,
        PRIMARY KEY (time)
    );

    CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_weekly (
        time TIMESTAMP NOT NULL,
        SML_1_8_0__Bezug_Gesamt DOUBLE,
        SML_1_8_1__Bezug_HT DOUBLE,
        SML_1_8_2__Bezug_NT DOUBLE,
        power_consumption_total DOUBLE,
        power_consumption_HT DOUBLE,
        power_consumption_NT DOUBLE,
        PRIMARY KEY (time)
    );

    CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_monthly (
        time TIMESTAMP NOT NULL,
        SML_1_8_0__Bezug_Gesamt DOUBLE,
        SML_1_8_1__Bezug_HT DOUBLE,
        SML_1_8_2__Bezug_NT DOUBLE,
        power_consumption_total DOUBLE,
        power_consumption_HT DOUBLE,
        power_consumption_NT DOUBLE,
        PRIMARY KEY (time)
    );

    CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_quarterly (
        time TIMESTAMP NOT NULL,
        SML_1_8_0__Bezug_Gesamt DOUBLE,
        SML_1_8_1__Bezug_HT DOUBLE,
        SML_1_8_2__Bezug_NT DOUBLE,
        power_consumption_total DOUBLE,
        power_consumption_HT DOUBLE,
        power_consumption_NT DOUBLE,
        PRIMARY KEY (time)
    );

    CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_yearly (
        time TIMESTAMP NOT NULL,
        SML_1_8_0__Bezug_Gesamt DOUBLE,
        SML_1_8_1__Bezug_HT DOUBLE,
        SML_1_8_2__Bezug_NT DOUBLE,
        power_consumption_total DOUBLE,
        power_consumption_HT DOUBLE,
        power_consumption_NT DOUBLE,
        PRIMARY KEY (time)
    );

    
    DROP TEMPORARY TABLE IF EXISTS Periods;
    CREATE TEMPORARY TABLE Periods (
        id INT AUTO_INCREMENT PRIMARY KEY,
        periodName VARCHAR(20),
        intervalValue VARCHAR(128),
        partitionExpression VARCHAR(128),
        tableName VARCHAR(100),
        boundary DATETIME
    );

    
    INSERT INTO Periods (periodName, intervalValue, partitionExpression, tableName, boundary)
    VALUES 
        ('hourly', '1 HOUR', 'DATE_FORMAT(berlin_time, ''%Y-%m-%d %H'')', 'tasmota_METER1_SENSOR_CONSUMPTION_hourly', DATE_FORMAT(currentTime, '%Y-%m-%d %H:00:00'));

    IF HOUR(currentTime) = 0 THEN
        INSERT INTO Periods (periodName, intervalValue, partitionExpression, tableName, boundary)
        VALUES 
            ('daily', '1 DAY', 'DATE_FORMAT(berlin_time, ''%Y-%m-%d'')', 'tasmota_METER1_SENSOR_CONSUMPTION_daily', DATE(currentTime));
    END IF;

    IF WEEKDAY(currentTime) = 0 AND HOUR(currentTime) = 0 THEN
        INSERT INTO Periods (periodName, intervalValue, partitionExpression, tableName, boundary)
        VALUES 
            ('weekly', '1 WEEK', 'DATE_FORMAT(berlin_time, ''%Y-%u'')', 'tasmota_METER1_SENSOR_CONSUMPTION_weekly', DATE(currentTime) - INTERVAL WEEKDAY(currentTime) DAY);
    END IF;

    IF DAY(currentTime) = 1 AND HOUR(currentTime) = 0 THEN
        INSERT INTO Periods (periodName, intervalValue, partitionExpression, tableName, boundary)
        VALUES 
            ('monthly', '1 MONTH', 'DATE_FORMAT(berlin_time, ''%Y-%m'')', 'tasmota_METER1_SENSOR_CONSUMPTION_monthly', DATE_FORMAT(currentTime, '%Y-%m-01'));
    END IF;

    IF QUARTER(currentTime) != QUARTER(currentTime - INTERVAL 1 MONTH)
        AND DAY(currentTime) = 1
        AND HOUR(currentTime) = 0 THEN
        INSERT INTO Periods (periodName, intervalValue, partitionExpression, tableName, boundary)
        VALUES 
            ('quarterly', '1 QUARTER', 'CONCAT(YEAR(berlin_time), ''-Q'', QUARTER(berlin_time))', 'tasmota_METER1_SENSOR_CONSUMPTION_quarterly', MAKEDATE(YEAR(currentTime), 1) + INTERVAL ((QUARTER(currentTime) - 1) * 3) MONTH);
    END IF;

    IF DATE_FORMAT(currentTime, '%m-%d') = '01-01'
        AND HOUR(currentTime) = 0 THEN
        INSERT INTO Periods (periodName, intervalValue, partitionExpression, tableName, boundary)
        VALUES 
            ('yearly', '1 YEAR', 'DATE_FORMAT(berlin_time, ''%Y'')', 'tasmota_METER1_SENSOR_CONSUMPTION_yearly', MAKEDATE(YEAR(currentTime), 1));
    END IF;


    
    WHILE periodIndex <= (SELECT COUNT(*) FROM Periods) DO
        
        SELECT periodName, intervalValue, partitionExpression, tableName, boundary
        INTO v_periodName, v_intervalValue, v_partitionExpression, v_tableName, v_boundary
        FROM Periods
        WHERE id = periodIndex;

        
        SET insert_query = CONCAT(
            '\n',
            'REPLACE INTO ', v_tableName, ' (time, SML_1_8_0__Bezug_Gesamt, SML_1_8_1__Bezug_HT, SML_1_8_2__Bezug_NT, power_consumption_total, power_consumption_HT, power_consumption_NT) \n',
            'WITH consumption AS ( \n',
            '    SELECT \n',
            '        local_time, \n',
            '        SML_1_8_0__Bezug_Gesamt, \n',
            '        SML_1_8_1__Bezug_HT, \n',
            '        SML_1_8_2__Bezug_NT, \n',
            '        (SML_1_8_0__Bezug_Gesamt - LAG(SML_1_8_0__Bezug_Gesamt) OVER (ORDER BY local_time)) AS delta_power_total, \n',
            '        (SML_1_8_1__Bezug_HT - LAG(SML_1_8_1__Bezug_HT) OVER (ORDER BY local_time)) AS delta_power_HT, \n',
            '        (SML_1_8_2__Bezug_NT - LAG(SML_1_8_2__Bezug_NT) OVER (ORDER BY local_time)) AS delta_power_NT \n',
            '    FROM ( \n',
            '        WITH period_bucket AS ( \n',
            '            WITH ranked_data AS ( \n',
            '                SELECT \n',
            '                    berlin_time AS local_time, \n',
            '                    SML_1_8_0__Bezug_Gesamt, \n',
            '                    SML_1_8_1__Bezug_HT, \n',
            '                    SML_1_8_2__Bezug_NT, \n',
            '                    ROW_NUMBER() OVER ( \n',
            '                        PARTITION BY  \n', 
            '                            ', v_partitionExpression, ' \n',
            '                            ORDER BY local_time DESC) AS rank \n',
            '                FROM tasmota_METER1_SENSOR \n',
            '                WHERE ( ( \n',
            '                    SELECT MAX(time) \n',
            '                    FROM ', v_tableName, ' \n',
            '                ) \n',
            '                IS NULL OR \n',
            '                berlin_time >= (\n',
            '                   SELECT  \n',
            '                       MAX(time) \n',
            '                   FROM \n',
            '                       ', v_tableName, '\n'
            '                ) ) \n',
            '                AND berlin_time < ''', v_boundary, ''' \n',
            '            ) \n',
            '            SELECT * FROM ranked_data WHERE rank = 1 \n',
            '        ) \n',
            '        SELECT * FROM period_bucket \n',
            '    ) AS final_query \n',
            ') \n',
            'SELECT * from consumption \n',
            'WHERE delta_power_total IS NOT NULL and delta_power_HT IS NOT NULL and delta_power_NT IS NOT NULL \n'
        );

        SET @insert_query = insert_query;
        

        
        PREPARE stmt FROM @insert_query;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;

        
        SET periodIndex = periodIndex + 1;
    END WHILE;

    
    DROP TEMPORARY TABLE IF EXISTS Periods;
END$$

DROP PROCEDURE IF EXISTS proc_calculate_consumption_all_rates$$
CREATE PROCEDURE proc_calculate_consumption_all_rates()
BEGIN
    CALL proc_calculate_consumption_all_rates_at(NOW());
END$$

DELIMITER ;
