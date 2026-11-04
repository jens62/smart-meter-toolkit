# Grafana alerts: rtl_433 sensor ids that disappear or appear

Many rtl_433 sensors (e.g. `inFactory-TH`) pick a **new random id after a battery change**. The
roll-ups (`../../persistence/mysql/temperature/`), the daily mail and the dashboards then silently
stop, because they follow one id. Two Grafana alert rules, both on the raw table
`rtl_433_events`, tell you by email when that happens:

| Rule | Fires when | Typical case |
|---|---|---|
| **rtl_433 id silent** | an id that sent at least 100 readings in the last 7 days has sent nothing for 30 minutes | batteries swapped, sensor dead, receiver down |
| **rtl_433 new id** | an id appears for the first time (within the last 24 h, at least 5 readings) | the same sensor with a new id, or a new neighbour sensor |

A battery swap therefore produces both mails, one for the old and one for the new id. A silent
id stops alerting when it has been gone for 7 days (it drops out of the window). A new id stops
alerting after 24 h.

Both rules use the MySQL data source of `telegraf_data`. Edit the model list (`IN (...)`) to the
models you care about. Do not alert on all models: some, like `Oregon-SL109H` or `Springfield-Soil`,
pick up neighbours' sensors, whose ids appear once and never come back.

## Rule 1: id silent

Query A (data source: MySQL, format **Time series**, mode Code):

```sql
SELECT UTC_TIMESTAMP() AS time, model, id,
       TIMESTAMPDIFF(MINUTE, MAX(time), UTC_TIMESTAMP()) AS minutes_silent
  FROM rtl_433_events
 WHERE model IN ('inFactory-TH', 'Hideki-TS04')
   AND time >= UTC_TIMESTAMP() - INTERVAL 7 DAY
 GROUP BY model, id
HAVING COUNT(*) >= 100
```

B = Reduce (A, function `Last`), C = Threshold (B) `is above 30`. The 30 minutes are well above the
69 s send interval and the longest gaps seen (about 10 minutes of lost reception). Pending
period 0 s, no data / error handling: `OK` / `Error`.

## Rule 2: new id

Query A (same settings):

```sql
SELECT UTC_TIMESTAMP() AS time, model, id, COUNT(*) AS readings
  FROM rtl_433_events
 WHERE model IN ('inFactory-TH', 'Hideki-TS04')
 GROUP BY model, id
HAVING MIN(time) >= UTC_TIMESTAMP() - INTERVAL 24 HOUR AND COUNT(*) >= 5
```

B = Reduce (A, `Last`), C = Threshold (B) `is above 0`. The `(model, id, time)` index added by
`schema_temperature.sql` makes the grouping cheap. If the table gets large, add
`AND time >= UTC_TIMESTAMP() - INTERVAL 30 DAY` and accept that ids older than that count as new again.

## Email

Needs SMTP in Grafana's `grafana.ini` (`[smtp]` section) and an email contact point. Give both
rules the label `alertgroup = rtl_433_ids` and add a notification policy that routes that label
to the contact point. Set its repeat interval to 24 h, otherwise Grafana repeats the mail every
4 hours while the rule is firing.

## As provisioning file

`/etc/grafana/provisioning/alerting/rtl_433_ids.yaml` (replace the two placeholders; this file
has not been loaded into a live Grafana, check it in *Alerting > Alert rules* after the restart):

```yaml
apiVersion: 1
groups:
  - orgId: 1
    name: rtl_433_ids
    folder: rtl_433
    interval: 5m
    rules:
      - uid: rtl433-id-silent
        title: rtl_433 id silent
        condition: C
        for: 0s
        noDataState: OK
        execErrState: Error
        labels: { alertgroup: rtl_433_ids }
        annotations:
          summary: "{{ $labels.model }} id {{ $labels.id }} sent nothing for {{ $values.B }} minutes"
        data:
          - refId: A
            relativeTimeRange: { from: 600, to: 0 }
            datasourceUid: <MYSQL_DATASOURCE_UID>
            model:
              refId: A
              format: time_series
              editorMode: code
              rawQuery: true
              rawSql: >-
                SELECT UTC_TIMESTAMP() AS time, model, id,
                TIMESTAMPDIFF(MINUTE, MAX(time), UTC_TIMESTAMP()) AS minutes_silent
                FROM rtl_433_events
                WHERE model IN ('inFactory-TH', 'Hideki-TS04')
                AND time >= UTC_TIMESTAMP() - INTERVAL 7 DAY
                GROUP BY model, id HAVING COUNT(*) >= 100
          - refId: B
            datasourceUid: __expr__
            model: { refId: B, type: reduce, expression: A, reducer: last, datasource: { type: __expr__, uid: __expr__ } }
          - refId: C
            datasourceUid: __expr__
            model:
              refId: C
              type: threshold
              expression: B
              conditions: [ { evaluator: { type: gt, params: [30] } } ]
              datasource: { type: __expr__, uid: __expr__ }
      - uid: rtl433-id-new
        title: rtl_433 new id
        condition: C
        for: 0s
        noDataState: OK
        execErrState: Error
        labels: { alertgroup: rtl_433_ids }
        annotations:
          summary: "New {{ $labels.model }} id {{ $labels.id }} ({{ $values.B }} readings in the first 24 h)"
        data:
          - refId: A
            relativeTimeRange: { from: 600, to: 0 }
            datasourceUid: <MYSQL_DATASOURCE_UID>
            model:
              refId: A
              format: time_series
              editorMode: code
              rawQuery: true
              rawSql: >-
                SELECT UTC_TIMESTAMP() AS time, model, id, COUNT(*) AS readings
                FROM rtl_433_events WHERE model IN ('inFactory-TH', 'Hideki-TS04')
                GROUP BY model, id
                HAVING MIN(time) >= UTC_TIMESTAMP() - INTERVAL 24 HOUR AND COUNT(*) >= 5
          - refId: B
            datasourceUid: __expr__
            model: { refId: B, type: reduce, expression: A, reducer: last, datasource: { type: __expr__, uid: __expr__ } }
          - refId: C
            datasourceUid: __expr__
            model:
              refId: C
              type: threshold
              expression: B
              conditions: [ { evaluator: { type: gt, params: [0] } } ]
              datasource: { type: __expr__, uid: __expr__ }
```
