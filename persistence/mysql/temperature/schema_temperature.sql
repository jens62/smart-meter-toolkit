-- Schema for the temperature roll-ups (see README.md in this folder).
--
-- Per sensor (model + id) there are six roll-up tables, named
--   rtl_433_<model>_<id>_TEMPERATURE_<hourly|daily|weekly|monthly|quarterly|yearly>
-- e.g. rtl_433_inFactory_TH_168_TEMPERATURE_daily. They are created by
-- proc_create_temperature_tables() (procedures_temperature.sql), which is also called at the
-- start of every roll-up run, so this file only holds what is shared by all sensors.

SET sql_mode = 'ANSI_QUOTES';

-- The raw table is created by telegraf with only the primary key. Every roll-up run reads one
-- sensor in time order, so index it.
ALTER TABLE rtl_433_events ADD KEY IF NOT EXISTS idx_model_id_time (model, id, time);

-- One row per sensor: where its history starts and how the roll-up treats gaps.
CREATE TABLE IF NOT EXISTS rtl_433_TEMPERATURE_config (
    model VARCHAR(32) NOT NULL,
    id INT UNSIGNED NOT NULL,
    -- Raw readings before this UTC time are ignored completely (no roll-up row, no interpolation
    -- anchor). The first period therefore starts with the first reading on or after it.
    data_from_utc DATETIME NOT NULL,
    -- Two consecutive readings further apart than this are treated as "no data between them"
    -- (not interpolated). Capped at 3600 by the procedure: the hourly split relies on an
    -- interval crossing at most one hour boundary.
    max_gap_seconds INT UNSIGNED NOT NULL DEFAULT 3600,
    -- Every run recomputes this many hours back, so readings that arrive late are picked up.
    lookback_hours INT UNSIGNED NOT NULL DEFAULT 48,
    PRIMARY KEY (model, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

INSERT IGNORE INTO rtl_433_TEMPERATURE_config (model, id, data_from_utc, max_gap_seconds, lookback_hours)
VALUES ('inFactory-TH', 168, '2026-09-01 00:00:00', 3600, 48);
