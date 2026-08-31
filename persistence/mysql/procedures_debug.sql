-- Dry-run companion to proc_calculate_consumption_all_rates (procedures.sql).
--
-- Identical logic, except:
--   - currentTime is pinned to a fixed value instead of NOW(), so you can
--     preview what would happen at a specific period boundary (e.g. a
--     month/quarter/year rollover) without waiting for it or faking the
--     server clock.
--   - it SELECTs the Periods table and each generated query instead of
--     EXECUTE-ing it, so nothing gets written - safe to run against a real
--     database at any time.
--
-- Edit the SET currentTime line below to whichever moment you want to
-- inspect (must be exactly HH:MM:SS = 00:00:00 for daily/weekly/monthly/
-- quarterly/yearly rollups to even be considered - see procedures.sql).

SET sql_mode = 'ANSI_QUOTES';

DELIMITER $$

CREATE PROCEDURE proc_calculate_consumption_all_rates_debug()
BEGIN
    DECLARE periodIndex INT DEFAULT 1;
    DECLARE v_periodName VARCHAR(20);
    DECLARE v_intervalValue VARCHAR(128);
    DECLARE v_partitionExpression VARCHAR(128);
    DECLARE v_tableName VARCHAR(100);
    DECLARE insert_query VARCHAR(2176);
    DECLARE currentTime DATETIME DEFAULT NOW();
    SET currentTime = '2026-01-01 00:00:00';

    SELECT currentTime AS Uhrzeit_lokal;

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

    SELECT * FROM Periods;

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

        -- Preview only - deliberately no PREPARE/EXECUTE/DEALLOCATE here,
        -- unlike procedures.sql. Nothing gets written.
        SELECT @insert_query AS DebugQuery;

        SET periodIndex = periodIndex + 1;
    END WHILE;

    DROP TEMPORARY TABLE IF EXISTS Periods;
END$$

DELIMITER ;
