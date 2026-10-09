-- Dry-run companion to proc_calculate_consumption_all_rates (procedures.sql).
--
-- Identical logic, except it SELECTs the Periods table (with each period's
-- boundary) and each generated query instead of EXECUTE-ing it, so nothing
-- gets written - safe to run against a real database at any time.
--
--   CALL proc_calculate_consumption_all_rates_debug_at('2026-03-01 00:00:00');
--
-- previews what would happen at that moment (e.g. a month/quarter/year
-- rollover) without waiting for it or faking the server clock. A period is
-- due when HOUR(p_now) = 0 (daily), additionally Monday (weekly), day 1
-- (monthly), first day of a quarter (quarterly), 1 January (yearly).
--
-- proc_calculate_consumption_all_rates_debug() keeps the old behaviour with a fixed
-- moment (2026-01-01 00:00:00, i.e. every period except weekly is due).

SET sql_mode = 'ANSI_QUOTES';

DELIMITER $$

DROP PROCEDURE IF EXISTS proc_calculate_consumption_all_rates_debug_at$$
CREATE PROCEDURE proc_calculate_consumption_all_rates_debug_at(IN p_now DATETIME)
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
        time DATETIME NOT NULL,
        time_utc DATETIME,
        SML_1_8_0__Bezug_Gesamt DOUBLE,
        SML_1_8_1__Bezug_HT DOUBLE,
        SML_1_8_2__Bezug_NT DOUBLE,
        power_consumption_total DOUBLE,
        power_consumption_HT DOUBLE,
        power_consumption_NT DOUBLE,
        PRIMARY KEY (time)
    );

    CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_daily (
        time DATETIME NOT NULL,
        time_utc DATETIME,
        SML_1_8_0__Bezug_Gesamt DOUBLE,
        SML_1_8_1__Bezug_HT DOUBLE,
        SML_1_8_2__Bezug_NT DOUBLE,
        power_consumption_total DOUBLE,
        power_consumption_HT DOUBLE,
        power_consumption_NT DOUBLE,
        PRIMARY KEY (time)
    );

    CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_weekly (
        time DATETIME NOT NULL,
        time_utc DATETIME,
        SML_1_8_0__Bezug_Gesamt DOUBLE,
        SML_1_8_1__Bezug_HT DOUBLE,
        SML_1_8_2__Bezug_NT DOUBLE,
        power_consumption_total DOUBLE,
        power_consumption_HT DOUBLE,
        power_consumption_NT DOUBLE,
        PRIMARY KEY (time)
    );

    CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_monthly (
        time DATETIME NOT NULL,
        time_utc DATETIME,
        SML_1_8_0__Bezug_Gesamt DOUBLE,
        SML_1_8_1__Bezug_HT DOUBLE,
        SML_1_8_2__Bezug_NT DOUBLE,
        power_consumption_total DOUBLE,
        power_consumption_HT DOUBLE,
        power_consumption_NT DOUBLE,
        PRIMARY KEY (time)
    );

    CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_quarterly (
        time DATETIME NOT NULL,
        time_utc DATETIME,
        SML_1_8_0__Bezug_Gesamt DOUBLE,
        SML_1_8_1__Bezug_HT DOUBLE,
        SML_1_8_2__Bezug_NT DOUBLE,
        power_consumption_total DOUBLE,
        power_consumption_HT DOUBLE,
        power_consumption_NT DOUBLE,
        PRIMARY KEY (time)
    );

    CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_yearly (
        time DATETIME NOT NULL,
        time_utc DATETIME,
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


    
    SELECT * FROM Periods;

    WHILE periodIndex <= (SELECT COUNT(*) FROM Periods) DO
        
        SELECT periodName, intervalValue, partitionExpression, tableName, boundary
        INTO v_periodName, v_intervalValue, v_partitionExpression, v_tableName, v_boundary
        FROM Periods
        WHERE id = periodIndex;

        
        SET insert_query = CONCAT(
            '\n',
            'REPLACE INTO ', v_tableName, ' (time, time_utc, SML_1_8_0__Bezug_Gesamt, SML_1_8_1__Bezug_HT, SML_1_8_2__Bezug_NT, power_consumption_total, power_consumption_HT, power_consumption_NT) \n',
            'WITH consumption AS ( \n',
            '    SELECT \n',
            '        local_time, \n',
            '        reading_utc, \n',
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
            '                    time AS reading_utc, \n',
            '                    SML_1_8_0__Bezug_Gesamt, \n',
            '                    SML_1_8_1__Bezug_HT, \n',
            '                    SML_1_8_2__Bezug_NT, \n',
            '                    ROW_NUMBER() OVER ( \n',
            '                        PARTITION BY  \n', 
            '                            ', v_partitionExpression, ' \n',
            '                            ORDER BY berlin_time DESC) AS rnk \n',
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
            '            SELECT * FROM ranked_data WHERE rnk = 1 \n',
            '        ) \n',
            '        SELECT * FROM period_bucket \n',
            '    ) AS final_query \n',
            ') \n',
            'SELECT * from consumption \n',
            'WHERE delta_power_total IS NOT NULL and delta_power_HT IS NOT NULL and delta_power_NT IS NOT NULL \n'
        );

        SET @insert_query = insert_query;
        

        
        SELECT v_periodName AS periode, v_boundary AS nur_messwerte_vor, @insert_query AS DebugQuery;

        
        SET periodIndex = periodIndex + 1;
    END WHILE;

    
    DROP TEMPORARY TABLE IF EXISTS Periods;
END$$

DROP PROCEDURE IF EXISTS proc_calculate_consumption_all_rates_debug$$
CREATE PROCEDURE proc_calculate_consumption_all_rates_debug()
BEGIN
    CALL proc_calculate_consumption_all_rates_debug_at('2026-01-01 00:00:00');
END$$

DELIMITER ;
