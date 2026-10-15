-- Time-weighted temperature averages per hour / day / week / month / quarter / year for one
-- rtl_433 sensor (model + id), stored in six tables per sensor. See README.md for the design,
-- the decisions taken and the reasoning; this file only documents what the code does.
--
-- Method
--   * The readings are a piecewise linear curve. The average of a period is the integral of that
--     curve divided by the time that is covered by data (integral_cs / covered_seconds).
--   * Two consecutive readings further apart than max_gap_seconds (config table) count as "no data
--     between them": that time is neither integrated nor counted as covered.
--   * The hour (UTC) is the building block. An interval is cut at the hour boundary with linear
--     interpolation. Day ... year rows are exact sums of the hourly rows, so all levels agree.
--     Day/week/month/quarter/year follow the LOCAL time of the OS (CONVERT_TZ(..., 'SYSTEM')),
--     including 23 h and 25 h days. Local midnight must exist exactly once (true for Europe).
--
-- Only FINAL periods are written (README, "Decisions"). An hour is final when a later reading
-- exists (the interval that crosses the hour boundary is known) or when max_gap_seconds have
-- passed without one. A day/week/... is written when it has ended and all its hours are final.
--
-- Every run recomputes from the raw readings (no "cursor" row to get out of step):
--   from = min(first hour after the last stored hourly row, final boundary - lookback_hours)
--   to   = last final hour boundary
-- The rows in [from, to) are deleted and rewritten, so the procedure is idempotent and late
-- readings inside the look-back window are picked up.
--
-- Entry points
--   proc_calculate_temperature_all_rates(model, id)         what the event calls (UTC_TIMESTAMP())
--   proc_calculate_temperature_all_rates_at(now_utc, model, id)  same for a given moment
--   proc_calculate_temperature_range(model, id, from_utc, to_utc)  repair / back-fill a range
--   proc_create_temperature_tables(model, id)               creates the six tables (idempotent)

SET sql_mode = 'ANSI_QUOTES';

DELIMITER $$

-- ---------------------------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------------------------

DROP FUNCTION IF EXISTS fn_hour_start$$
CREATE FUNCTION fn_hour_start(p_dt DATETIME) RETURNS DATETIME DETERMINISTIC
BEGIN
    RETURN p_dt - INTERVAL (MINUTE(p_dt) * 60 + SECOND(p_dt)) SECOND;
END$$

-- Start of the local day/week (Monday)/month/quarter/year that contains p_local.
DROP FUNCTION IF EXISTS fn_period_start_local$$
CREATE FUNCTION fn_period_start_local(p_level VARCHAR(10), p_local DATETIME) RETURNS DATETIME DETERMINISTIC
BEGIN
    RETURN CASE p_level
        WHEN 'daily'     THEN CAST(DATE(p_local) AS DATETIME)
        WHEN 'weekly'    THEN CAST(DATE(p_local) - INTERVAL WEEKDAY(p_local) DAY AS DATETIME)
        WHEN 'monthly'   THEN CAST(DATE(p_local) - INTERVAL (DAYOFMONTH(p_local) - 1) DAY AS DATETIME)
        WHEN 'quarterly' THEN CAST(MAKEDATE(YEAR(p_local), 1) + INTERVAL ((QUARTER(p_local) - 1) * 3) MONTH AS DATETIME)
        WHEN 'yearly'    THEN CAST(MAKEDATE(YEAR(p_local), 1) AS DATETIME)
        ELSE NULL
    END;
END$$

DROP FUNCTION IF EXISTS fn_period_end_local$$
CREATE FUNCTION fn_period_end_local(p_level VARCHAR(10), p_start_local DATETIME) RETURNS DATETIME DETERMINISTIC
BEGIN
    RETURN CASE p_level
        WHEN 'daily'     THEN p_start_local + INTERVAL 1 DAY
        WHEN 'weekly'    THEN p_start_local + INTERVAL 1 WEEK
        WHEN 'monthly'   THEN p_start_local + INTERVAL 1 MONTH
        WHEN 'quarterly' THEN p_start_local + INTERVAL 3 MONTH
        WHEN 'yearly'    THEN p_start_local + INTERVAL 1 YEAR
        ELSE NULL
    END;
END$$

-- rtl_433_<model>_<id>_TEMPERATURE_<level>; characters other than A-Z a-z 0-9 in the model
-- become "_" (inFactory-TH -> inFactory_TH).
DROP FUNCTION IF EXISTS fn_temperature_table$$
CREATE FUNCTION fn_temperature_table(p_model VARCHAR(32), p_id INT UNSIGNED, p_level VARCHAR(10))
RETURNS VARCHAR(100) DETERMINISTIC
BEGIN
    RETURN CONCAT('rtl_433_', REGEXP_REPLACE(p_model, '[^A-Za-z0-9]+', '_'), '_', p_id, '_TEMPERATURE_', p_level);
END$$

DROP PROCEDURE IF EXISTS proc_exec$$
CREATE PROCEDURE proc_exec(IN p_sql TEXT)
BEGIN
    SET @proc_exec_sql = p_sql;
    PREPARE proc_exec_stmt FROM @proc_exec_sql;
    EXECUTE proc_exec_stmt;
    DEALLOCATE PREPARE proc_exec_stmt;
END$$

-- ---------------------------------------------------------------------------------------------
-- The six tables of a sensor
-- ---------------------------------------------------------------------------------------------

DROP PROCEDURE IF EXISTS proc_create_temperature_tables$$
CREATE PROCEDURE proc_create_temperature_tables(IN p_model VARCHAR(32), IN p_id INT UNSIGNED)
BEGIN
    DECLARE v_i INT DEFAULT 1;

    WHILE v_i <= 6 DO
        CALL proc_exec(CONCAT(
            'CREATE TABLE IF NOT EXISTS ', fn_temperature_table(p_model, p_id, ELT(v_i, 'hourly', 'daily', 'weekly', 'monthly', 'quarterly', 'yearly')), ' (\n',
            -- identification
            '    model VARCHAR(32) NOT NULL,\n',
            '    id INT UNSIGNED NOT NULL,\n',
            -- the period: UTC start (primary key; for day and longer the UTC time of local midnight),
            -- exclusive UTC end, and the local wall clock of the start
            '    period_start_utc DATETIME NOT NULL,\n',
            '    period_end_utc DATETIME NOT NULL,\n',
            '    period_start_local DATETIME NOT NULL,\n',
            -- the readings that lie inside the period
            '    n_samples INT UNSIGNED NOT NULL,\n',
            '    first_sample_utc DATETIME NULL,\n',
            '    last_sample_utc DATETIME NULL,\n',
            '    min_temp_c DOUBLE NULL,\n',
            '    max_temp_c DOUBLE NULL,\n',
            '    sum_sample_c DOUBLE NOT NULL DEFAULT 0,\n',
            -- the time-weighted part: integral of the temperature curve over the covered time
            '    integral_cs DOUBLE NOT NULL DEFAULT 0,\n',
            '    covered_seconds INT UNSIGNED NOT NULL,\n',
            '    expected_seconds INT UNSIGNED NOT NULL,\n',
            -- how the data looked: longest gap between readings that start in the period, number
            -- of gaps that were longer than the limit (not bridged), the limit that was applied
            '    max_gap_seconds INT UNSIGNED NULL,\n',
            '    n_excluded_gaps INT UNSIGNED NOT NULL DEFAULT 0,\n',
            '    gap_limit_seconds INT UNSIGNED NOT NULL,\n',
            '    computed_at DATETIME NOT NULL,\n',
            -- derived, always consistent with the columns above
            '    avg_temp_c DOUBLE GENERATED ALWAYS AS (integral_cs / NULLIF(covered_seconds, 0)) STORED,\n',
            '    avg_sample_c DOUBLE GENERATED ALWAYS AS (sum_sample_c / NULLIF(n_samples, 0)) STORED,\n',
            '    coverage_pct DOUBLE GENERATED ALWAYS AS (100 * covered_seconds / expected_seconds) STORED,\n',
            '    PRIMARY KEY (period_start_utc),\n',
            '    KEY idx_start_local (period_start_local)\n',
            ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci'
        ));
        SET v_i = v_i + 1;
    END WHILE;
END$$

-- ---------------------------------------------------------------------------------------------
-- The roll-up
-- ---------------------------------------------------------------------------------------------

-- p_from_utc / p_to_utc NULL = automatic window (see header). Given: recompute that range,
-- but never beyond the last final hour.
DROP PROCEDURE IF EXISTS proc_calculate_temperature_all_rates_core$$
CREATE PROCEDURE proc_calculate_temperature_all_rates_core(
    IN p_now_utc DATETIME,
    IN p_model VARCHAR(32),
    IN p_id INT UNSIGNED,
    IN p_from_utc DATETIME,
    IN p_to_utc DATETIME)
main: BEGIN
    DECLARE v_data_from DATETIME DEFAULT NULL;
    DECLARE v_max_gap INT DEFAULT NULL;
    DECLARE v_lookback INT DEFAULT NULL;
    DECLARE v_last_sample DATETIME;
    DECLARE v_b0 DATETIME;
    DECLARE v_f DATETIME;
    DECLARE v_from DATETIME;
    DECLARE v_to DATETIME;
    DECLARE v_i INT;
    DECLARE v_level VARCHAR(10);
    DECLARE v_t_hourly VARCHAR(100);
    DECLARE v_t_level VARCHAR(100);
    DECLARE v_ps_local DATETIME;
    DECLARE v_ps_utc DATETIME;
    DECLARE v_pe_utc DATETIME;
    DECLARE v_cols VARCHAR(700) DEFAULT 'model, id, period_start_utc, period_end_utc, period_start_local, n_samples, first_sample_utc, last_sample_utc, min_temp_c, max_temp_c, sum_sample_c, integral_cs, covered_seconds, expected_seconds, max_gap_seconds, n_excluded_gaps, gap_limit_seconds, computed_at';

    SELECT data_from_utc, LEAST(max_gap_seconds, 3600), lookback_hours
      INTO v_data_from, v_max_gap, v_lookback
      FROM rtl_433_TEMPERATURE_config
     WHERE model = p_model AND id = p_id;
    IF v_data_from IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'No row in rtl_433_TEMPERATURE_config for this model/id';
    END IF;

    CALL proc_create_temperature_tables(p_model, p_id);
    SET v_t_hourly = fn_temperature_table(p_model, p_id, 'hourly');

    -- Newest reading (nothing to do without data since data_from_utc).
    SELECT MAX(time) INTO v_last_sample
      FROM rtl_433_events
     WHERE model = p_model AND id = p_id AND time >= v_data_from AND time <= p_now_utc;
    IF v_last_sample IS NULL THEN
        LEAVE main;
    END IF;

    -- v_f = newest hour boundary B <= now for which every hour before B is final:
    -- a reading exists at or after B, or at least max_gap has passed since B.
    SET v_b0 = fn_hour_start(p_now_utc);
    SET v_f = LEAST(v_b0, GREATEST(fn_hour_start(v_last_sample),
                                   fn_hour_start(p_now_utc - INTERVAL v_max_gap SECOND)));

    CALL proc_exec(CONCAT('SELECT MAX(period_start_utc) INTO @tc_last_stored FROM ', v_t_hourly));
    IF p_from_utc IS NOT NULL THEN
        SET v_from = GREATEST(fn_hour_start(p_from_utc), fn_hour_start(v_data_from));
    ELSE
        SET v_from = GREATEST(fn_hour_start(v_data_from),
                              LEAST(COALESCE(@tc_last_stored + INTERVAL 1 HOUR, fn_hour_start(v_data_from)),
                                    v_f - INTERVAL v_lookback HOUR));
    END IF;
    SET v_to = IF(p_to_utc IS NULL, v_f, LEAST(v_f, fn_hour_start(p_to_utc)));
    IF v_to <= v_from THEN
        LEAVE main;
    END IF;

    DROP TEMPORARY TABLE IF EXISTS tmp_hour;
    DROP TEMPORARY TABLE IF EXISTS tmp_h;
    DROP TEMPORARY TABLE IF EXISTS tmp_p;
    CALL proc_exec(CONCAT('CREATE TEMPORARY TABLE tmp_hour LIKE ', v_t_hourly));
    CALL proc_exec(CONCAT('CREATE TEMPORARY TABLE tmp_h LIKE ', v_t_hourly));
    CALL proc_exec(CONCAT('CREATE TEMPORARY TABLE tmp_p LIKE ', v_t_hourly));

    -- Hours [v_from, v_to). Readings are read with a margin of max_gap on both sides so the
    -- intervals that reach into the window are complete.
    INSERT INTO tmp_hour (model, id, period_start_utc, period_end_utc, period_start_local,
                          n_samples, first_sample_utc, last_sample_utc, min_temp_c, max_temp_c, sum_sample_c,
                          integral_cs, covered_seconds, expected_seconds,
                          max_gap_seconds, n_excluded_gaps, gap_limit_seconds, computed_at)
    WITH
    s AS (   -- one value per timestamp (rtl_433 repeats transmissions)
        SELECT time AS t, AVG(COALESCE(temperature_C, (temperature_F - 32) * 5 / 9)) AS c
          FROM rtl_433_events
         WHERE model = p_model AND id = p_id
           AND time >= GREATEST(v_data_from, v_from - INTERVAL v_max_gap SECOND)
           AND time <  v_to + INTERVAL v_max_gap SECOND
           AND COALESCE(temperature_C, temperature_F) IS NOT NULL
         GROUP BY time
    ),
    iv AS (  -- interval from each reading to the next one
        SELECT t AS t1, LEAD(t) OVER (ORDER BY t) AS t2,
               c AS c1, LEAD(c) OVER (ORDER BY t) AS c2
          FROM s
    ),
    iv_ok AS (  -- the intervals that are bridged
        SELECT t1, t2, c1, c2, fn_hour_start(t1) AS h0, fn_hour_start(t1) + INTERVAL 1 HOUR AS h1
          FROM iv
         WHERE t2 IS NOT NULL AND TIMESTAMPDIFF(SECOND, t1, t2) <= v_max_gap
    ),
    seg AS (    -- cut at the hour boundary: the part in t1's hour, and the part in the next hour
        SELECT t1, t2, c1, c2, h0 AS hr, t1 AS a, LEAST(t2, h1) AS b FROM iv_ok
        UNION ALL
        SELECT t1, t2, c1, c2, h1 AS hr, h1 AS a, t2 AS b FROM iv_ok WHERE t2 > h1
    ),
    cov AS (    -- trapezoid: mean of the interpolated start and end temperature times duration
        SELECT hr,
               SUM(TIMESTAMPDIFF(SECOND, a, b)) AS covered,
               SUM(((c1 + TIMESTAMPDIFF(SECOND, t1, a) / TIMESTAMPDIFF(SECOND, t1, t2) * (c2 - c1))
                  + (c1 + TIMESTAMPDIFF(SECOND, t1, b) / TIMESTAMPDIFF(SECOND, t1, t2) * (c2 - c1))) / 2
                   * TIMESTAMPDIFF(SECOND, a, b)) AS integral
          FROM seg
         GROUP BY hr
    ),
    smp AS (    -- readings inside the hour
        SELECT fn_hour_start(t) AS hr, COUNT(*) AS n, MIN(t) AS first_t, MAX(t) AS last_t,
               MIN(c) AS min_c, MAX(c) AS max_c, SUM(c) AS sum_c
          FROM s
         GROUP BY fn_hour_start(t)
    ),
    gp AS (     -- gaps are attributed to the hour of the earlier reading
        SELECT fn_hour_start(t1) AS hr,
               MAX(TIMESTAMPDIFF(SECOND, t1, t2)) AS max_gap,
               SUM(TIMESTAMPDIFF(SECOND, t1, t2) > v_max_gap) AS n_excl
          FROM iv
         WHERE t2 IS NOT NULL
         GROUP BY fn_hour_start(t1)
    ),
    hrs AS (SELECT hr FROM cov UNION SELECT hr FROM smp)
    SELECT p_model, p_id, hrs.hr, hrs.hr + INTERVAL 1 HOUR, CONVERT_TZ(hrs.hr, '+00:00', 'SYSTEM'),
           COALESCE(smp.n, 0), smp.first_t, smp.last_t, smp.min_c, smp.max_c, COALESCE(smp.sum_c, 0),
           COALESCE(cov.integral, 0), COALESCE(cov.covered, 0), 3600,
           gp.max_gap, COALESCE(gp.n_excl, 0), v_max_gap, p_now_utc
      FROM hrs
      LEFT JOIN cov ON cov.hr = hrs.hr
      LEFT JOIN smp ON smp.hr = hrs.hr
      LEFT JOIN gp  ON gp.hr  = hrs.hr
     WHERE hrs.hr >= v_from AND hrs.hr < v_to;

    START TRANSACTION;
    CALL proc_exec(CONCAT('DELETE FROM ', v_t_hourly,
                          ' WHERE period_start_utc >= ''', v_from, ''' AND period_start_utc < ''', v_to, ''''));
    CALL proc_exec(CONCAT('INSERT INTO ', v_t_hourly, ' (', v_cols, ') SELECT ', v_cols, ' FROM tmp_hour'));
    COMMIT;

    -- Day ... year: exact sums of the hourly rows. A level is processed when the period that
    -- contains v_from has ended by v_to (otherwise no period of that level can be complete).
    SET v_i = 2;
    WHILE v_i <= 6 DO
        SET v_level = ELT(v_i, 'hourly', 'daily', 'weekly', 'monthly', 'quarterly', 'yearly');
        SET v_t_level = fn_temperature_table(p_model, p_id, v_level);

        SET v_ps_local = fn_period_start_local(v_level, CONVERT_TZ(v_from, '+00:00', 'SYSTEM'));
        SET v_ps_utc = CONVERT_TZ(v_ps_local, 'SYSTEM', '+00:00');
        SET v_pe_utc = CONVERT_TZ(fn_period_end_local(v_level, v_ps_local), 'SYSTEM', '+00:00');

        IF v_pe_utc <= v_to THEN
            DELETE FROM tmp_h;
            DELETE FROM tmp_p;
            CALL proc_exec(CONCAT('INSERT INTO tmp_h (', v_cols, ') SELECT ', v_cols, ' FROM ', v_t_hourly,
                                  ' WHERE period_start_utc >= ''', v_ps_utc, ''' AND period_start_utc < ''', v_to, ''''));

            INSERT INTO tmp_p (model, id, period_start_utc, period_end_utc, period_start_local,
                               n_samples, first_sample_utc, last_sample_utc, min_temp_c, max_temp_c, sum_sample_c,
                               integral_cs, covered_seconds, expected_seconds,
                               max_gap_seconds, n_excluded_gaps, gap_limit_seconds, computed_at)
            SELECT p_model, p_id, ps_utc, pe_utc, ps_local,
                   n, first_t, last_t, min_c, max_c, sum_c,
                   integral, covered, TIMESTAMPDIFF(SECOND, ps_utc, pe_utc),
                   max_gap, n_excl, gap_limit, p_now_utc
              FROM (
                    SELECT ps_local,
                           CONVERT_TZ(ps_local, 'SYSTEM', '+00:00') AS ps_utc,
                           CONVERT_TZ(fn_period_end_local(v_level, ps_local), 'SYSTEM', '+00:00') AS pe_utc,
                           SUM(n_samples) AS n, MIN(first_sample_utc) AS first_t, MAX(last_sample_utc) AS last_t,
                           MIN(min_temp_c) AS min_c, MAX(max_temp_c) AS max_c, SUM(sum_sample_c) AS sum_c,
                           SUM(integral_cs) AS integral, SUM(covered_seconds) AS covered,
                           MAX(max_gap_seconds) AS max_gap, SUM(n_excluded_gaps) AS n_excl,
                           MAX(gap_limit_seconds) AS gap_limit
                      FROM (SELECT h.*, fn_period_start_local(v_level, h.period_start_local) AS ps_local
                              FROM tmp_h h) x
                     GROUP BY ps_local
                   ) q
             WHERE pe_utc <= v_to AND pe_utc > v_from;

            START TRANSACTION;
            -- delete exactly the periods that are rewritten (complete ones), no more
            CALL proc_exec(CONCAT('DELETE FROM ', v_t_level,
                                  ' WHERE period_start_utc >= ''', v_ps_utc, ''' AND period_end_utc <= ''', v_to, ''''));
            CALL proc_exec(CONCAT('INSERT INTO ', v_t_level, ' (', v_cols, ') SELECT ', v_cols, ' FROM tmp_p'));
            COMMIT;
        END IF;

        SET v_i = v_i + 1;
    END WHILE;

    DROP TEMPORARY TABLE IF EXISTS tmp_hour;
    DROP TEMPORARY TABLE IF EXISTS tmp_h;
    DROP TEMPORARY TABLE IF EXISTS tmp_p;
END$$

DROP PROCEDURE IF EXISTS proc_calculate_temperature_all_rates_at$$
CREATE PROCEDURE proc_calculate_temperature_all_rates_at(IN p_now_utc DATETIME, IN p_model VARCHAR(32), IN p_id INT UNSIGNED)
BEGIN
    CALL proc_calculate_temperature_all_rates_core(p_now_utc, p_model, p_id, NULL, NULL);
END$$

DROP PROCEDURE IF EXISTS proc_calculate_temperature_all_rates$$
CREATE PROCEDURE proc_calculate_temperature_all_rates(IN p_model VARCHAR(32), IN p_id INT UNSIGNED)
BEGIN
    CALL proc_calculate_temperature_all_rates_at(UTC_TIMESTAMP(), p_model, p_id);
END$$

-- Repair / back-fill: recompute the hours in [p_from_utc, p_to_utc) and every period they touch.
DROP PROCEDURE IF EXISTS proc_calculate_temperature_range$$
CREATE PROCEDURE proc_calculate_temperature_range(
    IN p_model VARCHAR(32), IN p_id INT UNSIGNED, IN p_from_utc DATETIME, IN p_to_utc DATETIME)
BEGIN
    CALL proc_calculate_temperature_all_rates_core(UTC_TIMESTAMP(), p_model, p_id, p_from_utc, p_to_utc);
END$$

DELIMITER ;
