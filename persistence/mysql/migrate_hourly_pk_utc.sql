-- Migration for installations that created the hourly rollup table with PRIMARY KEY ("time") and a
-- procedures.sql that grouped the hourly rows by local hour (see README.md, "Time zones"). The repeated
-- hour in autumn then ended up as one hourly row with the consumption of two hours (24 rows instead
-- of 25 on that day).
--
-- Replace METER1 with the device name, back up the hourly table first, then:
--   1. run this file (key change + repair of the repeated hours)
--   2. reload procedures.sql (hourly buckets by UTC hour) - as the owner of the procedures
-- Run it BEFORE procedures.sql only if no hourly event run is due in between, or run both in one go.

SET sql_mode = 'ANSI_QUOTES';

-- 1. time_utc becomes the primary key; "time" (local) stays as an ordinary index.
ALTER TABLE tasmota_METER1_SENSOR_CONSUMPTION_hourly
    MODIFY "time_utc" DATETIME NOT NULL,
    DROP PRIMARY KEY,
    DROP INDEX IF EXISTS "idx_unique_time",
    DROP INDEX IF EXISTS "idx_time_utc",
    ADD PRIMARY KEY ("time_utc"),
    ADD KEY "idx_time" ("time");

-- 2. Repair: rewrite the hourly rows of a UTC range from the raw readings, one row per UTC hour.
--    Set the range to the hours of the repeated hour (autumn changeover: 00:00-02:00 UTC on the last
--    Sunday of October, here with one hour before and after as context). The hour before @from only
--    serves as predecessor for the first delta.
SET @from = '2026-10-25 00:00:00', @to = '2026-10-25 03:00:00';

DELETE FROM tasmota_METER1_SENSOR_CONSUMPTION_hourly WHERE "time_utc" >= @from AND "time_utc" < @to;

REPLACE INTO tasmota_METER1_SENSOR_CONSUMPTION_hourly
    ("time", "time_utc", "SML_1_8_0__Bezug_Gesamt", "SML_1_8_1__Bezug_HT", "SML_1_8_2__Bezug_NT",
     "power_consumption_total", "power_consumption_HT", "power_consumption_NT")
SELECT local_time, reading_utc, total, ht, nt, d_total, d_ht, d_nt
  FROM (
        SELECT local_time, reading_utc,
               "SML_1_8_0__Bezug_Gesamt" AS total, "SML_1_8_1__Bezug_HT" AS ht, "SML_1_8_2__Bezug_NT" AS nt,
               "SML_1_8_0__Bezug_Gesamt" - LAG("SML_1_8_0__Bezug_Gesamt") OVER (ORDER BY reading_utc) AS d_total,
               "SML_1_8_1__Bezug_HT"     - LAG("SML_1_8_1__Bezug_HT")     OVER (ORDER BY reading_utc) AS d_ht,
               "SML_1_8_2__Bezug_NT"     - LAG("SML_1_8_2__Bezug_NT")     OVER (ORDER BY reading_utc) AS d_nt
          FROM (
                SELECT berlin_time AS local_time, "time" AS reading_utc,
                       "SML_1_8_0__Bezug_Gesamt", "SML_1_8_1__Bezug_HT", "SML_1_8_2__Bezug_NT",
                       ROW_NUMBER() OVER (PARTITION BY DATE_FORMAT("time", '%Y-%m-%d %H') ORDER BY "time" DESC) AS rnk
                  FROM tasmota_METER1_SENSOR
                 WHERE "time" >= @from - INTERVAL 1 HOUR AND "time" < @to
               ) ranked
         WHERE rnk = 1
       ) d
 WHERE reading_utc >= @from AND d_total IS NOT NULL AND d_ht IS NOT NULL AND d_nt IS NOT NULL;
