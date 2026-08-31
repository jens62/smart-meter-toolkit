-- Rolls raw tasmota_METER1_SENSOR readings up into the six
-- tasmota_METER1_SENSOR_CONSUMPTION_* tables (see schema.sql). Called
-- hourly by the ev_calculate_consumption event (events.sql).
--
-- For each period type due this run, it looks at raw readings newer than
-- that period table's own last stored row, keeps only the single latest
-- raw reading per period-bucket (hour/day/ISO-week/month/quarter/year) in
-- that window, and inserts the delta between consecutive buckets as
-- power_consumption_*.
--
-- Known quirk (not fixed here, just documented): because a new reading
-- typically exists within seconds of any period boundary, the very first
-- run after a boundary produces two rows in one pass - the correct final
-- total for the period that just ended, AND a near-zero "stub" row dated
-- the first moment of the period that just started (delta between the two
-- readings a few seconds apart). For daily this self-corrects within 24h
-- and is rarely visible; for weekly/monthly/quarterly/yearly the stub sits
-- in the table, visible in any report, until the *next* period boundary
-- resolves it. A consumer of these tables (e.g. presentation/email's mail
-- report) should exclude the still-open current period rather than assume
-- every row is a completed period.

SET sql_mode = 'ANSI_QUOTES';

DELIMITER $$

CREATE PROCEDURE proc_calculate_consumption_all_rates()
BEGIN
    DECLARE periodIndex INT DEFAULT 1;
    DECLARE v_periodName VARCHAR(20);
    DECLARE v_intervalValue VARCHAR(128);
    DECLARE v_partitionExpression VARCHAR(128);
    DECLARE v_tableName VARCHAR(100);
    DECLARE insert_query VARCHAR(2176);
    DECLARE currentTime DATETIME DEFAULT NOW();

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
        tableName VARCHAR(100)
    );

    INSERT INTO Periods (periodName, intervalValue, partitionExpression, tableName)
    VALUES
        ('hourly', '1 HOUR', 'DATE_FORMAT(berlin_time, ''%Y-%m-%d %H'')', 'tasmota_METER1_SENSOR_CONSUMPTION_hourly');

    IF DATE_FORMAT(currentTime, '%H:%i:%s') = '00:00:00' THEN
        INSERT INTO Periods (periodName, intervalValue, partitionExpression, tableName)
        VALUES
            ('daily', '1 DAY', 'DATE_FORMAT(berlin_time, ''%Y-%m-%d'')', 'tasmota_METER1_SENSOR_CONSUMPTION_daily');
    END IF;

    -- WEEKDAY() (Monday=0) instead of DATE_FORMAT(..., '%W') = 'Monday':
    -- %W returns a locale-dependent day name (lc_time_names), so a literal
    -- 'Monday' comparison only works on an English-locale server - WEEKDAY()
    -- avoids that trap entirely.
    IF WEEKDAY(currentTime) = 0 AND DATE_FORMAT(currentTime, '%H:%i:%s') = '00:00:00' THEN
        INSERT INTO Periods (periodName, intervalValue, partitionExpression, tableName)
        VALUES
            ('weekly', '1 WEEK', 'DATE_FORMAT(berlin_time, ''%Y-%u'')', 'tasmota_METER1_SENSOR_CONSUMPTION_weekly');
    END IF;

    IF DATE_FORMAT(currentTime, '%d') = '01' AND DATE_FORMAT(currentTime, '%H:%i:%s') = '00:00:00' THEN
        INSERT INTO Periods (periodName, intervalValue, partitionExpression, tableName)
        VALUES
            ('monthly', '1 MONTH', 'DATE_FORMAT(berlin_time, ''%Y-%m'')', 'tasmota_METER1_SENSOR_CONSUMPTION_monthly');
    END IF;

    IF QUARTER(currentTime) != QUARTER(currentTime - INTERVAL 1 MONTH)
        AND DATE_FORMAT(currentTime, '%d') = '01'
        AND DATE_FORMAT(currentTime, '%H:%i:%s') = '00:00:00' THEN
        INSERT INTO Periods (periodName, intervalValue, partitionExpression, tableName)
        VALUES
            ('quarterly', '1 QUARTER', 'CONCAT(YEAR(berlin_time), ''-Q'', QUARTER(berlin_time))', 'tasmota_METER1_SENSOR_CONSUMPTION_quarterly');
    END IF;

    IF DATE_FORMAT(currentTime, '%m-%d') = '01-01'
        AND DATE_FORMAT(currentTime, '%H:%i:%s') = '00:00:00' THEN
        INSERT INTO Periods (periodName, intervalValue, partitionExpression, tableName)
        VALUES
            ('yearly', '1 YEAR', 'DATE_FORMAT(berlin_time, ''%Y'')', 'tasmota_METER1_SENSOR_CONSUMPTION_yearly');
    END IF;

    WHILE periodIndex <= (SELECT COUNT(*) FROM Periods) DO

        SELECT periodName, intervalValue, partitionExpression, tableName
        INTO v_periodName, v_intervalValue, v_partitionExpression, v_tableName
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
            '                WHERE ( \n',
            '                    SELECT MAX(time) \n',
            '                    FROM ', v_tableName, ' \n',
            '                ) \n',
            '                IS NULL OR \n',
            '                berlin_time >= (\n',
            '                   SELECT  \n',
            '                       MAX(time) \n',
            '                   FROM \n',
            '                       ', v_tableName, '\n'
            '                ) \n',
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

DELIMITER ;
