-- MariaDB/MySQL schema for storing Tasmota IR-head meter readings and their
-- rolled-up consumption figures.
--
-- Table names below use the placeholder device id "METER1" - telegraf's
-- `name_override` (see ../../acquisition/tasmota-ir/telegraf-mqtt-input.conf.example)
-- determines the raw table name, so rename every `tasmota_METER1_*` table
-- here to match whatever device id you actually used there. It doesn't need
-- to be anything specific - it just has to be consistent across the raw
-- table, the six rollup tables, and procedures.sql/events.sql.

SET sql_mode = 'ANSI_QUOTES';

-- Raw readings, one row per MQTT message received from telegraf.
CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR (
    -- UTC wall clock, stored as DATETIME (no session time zone conversion, unlike TIMESTAMP).
    "time" DATETIME NOT NULL,
    "host" VARCHAR(32) DEFAULT NULL,
    "topic" VARCHAR(32) DEFAULT NULL,
    -- OBIS-code-derived columns below match a typical German SML electricity
    -- meter (1-8-0/1/2 = total/HT/NT registers). Adjust field names to
    -- whatever OBIS codes your own meter and Tasmota SML rule expose.
    "SML_1_8_0__Bezug_Gesamt" DOUBLE DEFAULT NULL,
    "SML_1_8_1__Bezug_HT" DOUBLE DEFAULT NULL,
    "SML_1_8_2__Bezug_NT" DOUBLE DEFAULT NULL,
    "SML_2_8_0" DOUBLE DEFAULT NULL,
    "SML_16_7_0" DOUBLE DEFAULT NULL,
    "SML_36_7_0" DOUBLE DEFAULT NULL,
    "SML_56_7_0" DOUBLE DEFAULT NULL,
    "SML_76_7_0" DOUBLE DEFAULT NULL,
    "SML_32_7_0" DOUBLE DEFAULT NULL,
    "SML_52_7_0" DOUBLE DEFAULT NULL,
    "SML_72_7_0" DOUBLE DEFAULT NULL,
    -- Meter serial/manufacturer id, hex-encoded (see get_meter_number() in
    -- ../../presentation/email/send_results_from_DB_as_html_mail_daily_with_bar_3dec.py
    -- for how this gets decoded into a human-readable meter number).
    "SML_96_1_0" VARCHAR(32) DEFAULT NULL,
    -- "time" is UTC; this generated column gives the local Berlin wall clock to bucket by,
    -- which proc_calculate_consumption_all_rates relies on for its day/week/month/quarter/year
    -- partitioning. Not unique: in the repeated hour in autumn the same local time occurs twice.
    -- "time" is a plain index (not UNIQUE) for the same reason (two readings can get the same time).
    "berlin_time" DATETIME GENERATED ALWAYS AS (CONVERT_TZ("time", 'UTC', 'Europe/Berlin')) STORED,
    KEY "time_idx" ("time"),
    KEY "idx_berlin_time" ("berlin_time")
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- One rollup table per period. All six share the same shape: the meter's
-- cumulative register values at the end of the period ("Stand"/Bezug_*),
-- plus the consumption *during* that period (power_consumption_*), computed
-- by proc_calculate_consumption_all_rates as the delta between this row and
-- the previous one.
CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_hourly (
    -- Local Berlin time of the last reading of the period (what reports use).
    "time" DATETIME NOT NULL,
    -- UTC time of that same reading (unambiguous; use this for UTC dashboards).
    "time_utc" DATETIME NULL,
    "SML_1_8_0__Bezug_Gesamt" DOUBLE DEFAULT NULL,
    "SML_1_8_1__Bezug_HT" DOUBLE DEFAULT NULL,
    "SML_1_8_2__Bezug_NT" DOUBLE DEFAULT NULL,
    "power_consumption_total" DOUBLE DEFAULT NULL,
    "power_consumption_HT" DOUBLE DEFAULT NULL,
    "power_consumption_NT" DOUBLE DEFAULT NULL,
    PRIMARY KEY ("time"),
    KEY "idx_time_utc" ("time_utc")
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_daily (
    -- Local Berlin time of the last reading of the period (what reports use).
    "time" DATETIME NOT NULL,
    -- UTC time of that same reading (unambiguous; use this for UTC dashboards).
    "time_utc" DATETIME NULL,
    "SML_1_8_0__Bezug_Gesamt" DOUBLE DEFAULT NULL,
    "SML_1_8_1__Bezug_HT" DOUBLE DEFAULT NULL,
    "SML_1_8_2__Bezug_NT" DOUBLE DEFAULT NULL,
    "power_consumption_total" DOUBLE DEFAULT NULL,
    "power_consumption_HT" DOUBLE DEFAULT NULL,
    "power_consumption_NT" DOUBLE DEFAULT NULL,
    PRIMARY KEY ("time"),
    KEY "idx_time_utc" ("time_utc")
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_weekly (
    -- Local Berlin time of the last reading of the period (what reports use).
    "time" DATETIME NOT NULL,
    -- UTC time of that same reading (unambiguous; use this for UTC dashboards).
    "time_utc" DATETIME NULL,
    "SML_1_8_0__Bezug_Gesamt" DOUBLE DEFAULT NULL,
    "SML_1_8_1__Bezug_HT" DOUBLE DEFAULT NULL,
    "SML_1_8_2__Bezug_NT" DOUBLE DEFAULT NULL,
    "power_consumption_total" DOUBLE DEFAULT NULL,
    "power_consumption_HT" DOUBLE DEFAULT NULL,
    "power_consumption_NT" DOUBLE DEFAULT NULL,
    PRIMARY KEY ("time"),
    KEY "idx_time_utc" ("time_utc")
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_monthly (
    -- Local Berlin time of the last reading of the period (what reports use).
    "time" DATETIME NOT NULL,
    -- UTC time of that same reading (unambiguous; use this for UTC dashboards).
    "time_utc" DATETIME NULL,
    "SML_1_8_0__Bezug_Gesamt" DOUBLE DEFAULT NULL,
    "SML_1_8_1__Bezug_HT" DOUBLE DEFAULT NULL,
    "SML_1_8_2__Bezug_NT" DOUBLE DEFAULT NULL,
    "power_consumption_total" DOUBLE DEFAULT NULL,
    "power_consumption_HT" DOUBLE DEFAULT NULL,
    "power_consumption_NT" DOUBLE DEFAULT NULL,
    PRIMARY KEY ("time"),
    KEY "idx_time_utc" ("time_utc")
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_quarterly (
    -- Local Berlin time of the last reading of the period (what reports use).
    "time" DATETIME NOT NULL,
    -- UTC time of that same reading (unambiguous; use this for UTC dashboards).
    "time_utc" DATETIME NULL,
    "SML_1_8_0__Bezug_Gesamt" DOUBLE DEFAULT NULL,
    "SML_1_8_1__Bezug_HT" DOUBLE DEFAULT NULL,
    "SML_1_8_2__Bezug_NT" DOUBLE DEFAULT NULL,
    "power_consumption_total" DOUBLE DEFAULT NULL,
    "power_consumption_HT" DOUBLE DEFAULT NULL,
    "power_consumption_NT" DOUBLE DEFAULT NULL,
    PRIMARY KEY ("time"),
    KEY "idx_time_utc" ("time_utc")
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS tasmota_METER1_SENSOR_CONSUMPTION_yearly (
    -- Local Berlin time of the last reading of the period (what reports use).
    "time" DATETIME NOT NULL,
    -- UTC time of that same reading (unambiguous; use this for UTC dashboards).
    "time_utc" DATETIME NULL,
    "SML_1_8_0__Bezug_Gesamt" DOUBLE DEFAULT NULL,
    "SML_1_8_1__Bezug_HT" DOUBLE DEFAULT NULL,
    "SML_1_8_2__Bezug_NT" DOUBLE DEFAULT NULL,
    "power_consumption_total" DOUBLE DEFAULT NULL,
    "power_consumption_HT" DOUBLE DEFAULT NULL,
    "power_consumption_NT" DOUBLE DEFAULT NULL,
    PRIMARY KEY ("time"),
    KEY "idx_time_utc" ("time_utc")
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
