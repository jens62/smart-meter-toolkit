# Acquisition: Tasmota IR read head

An alternative to the PPC Smart Meter Gateway (`../../docs/Using_the_PPC_Smart_Meter_Gateway.md`)
for households without one: a Tasmota-flashed IR read head clipped onto the
meter's optical port, reading SML data straight off an eBZ-style meter and
publishing it over MQTT.

## Pipeline

```
meter (optical/IR port, SML protocol)
  -> Tasmota IR read head (parses SML, publishes to MQTT)
  -> local MQTT broker (e.g. Mosquitto)
  -> telegraf inputs.mqtt_consumer  (this folder: telegraf-mqtt-input.conf.example)
  -> telegraf outputs.sql           (../../persistence/mysql/telegraf-mysql-output.conf.example)
  -> MariaDB/MySQL                  (../../persistence/mysql/)
```

## Unambiguous times (daylight saving time)

By default Tasmota publishes `"Time"` as local time without an offset
(`2025-10-26T02:30:00`). When daylight saving time ends, the hour 02:00-02:59
occurs twice and both halves yield the same timestamp, so readings with two
different meter values share one `time` (and a `UNIQUE` index on `time` would
block the SQL output).

Fix: send `SetOption52 1` once on the device console (or
`http://<device>/cm?cmnd=SetOption52%201`). It is stored persistently and
appends the offset: `"Time":"2025-10-26T02:30:00+01:00"`. The example input
config then parses it with `timestamp_format = "2006-01-02T15:04:05Z07:00"`
(no `timestamp_timezone`).

Device and telegraf config must be switched together: a config expecting an
offset discards messages without one (and vice versa) with a parse error; it
does not store wrong times. Stop telegraf, change the config, set the option,
start telegraf. Roll back with `SetOption52 0` and the old format. Everything
else reading the raw `Time` field (other MQTT clients) has to cope with the
offset as well.

## What's not included here

The Tasmota device's own configuration (its SML-parsing rule/script and MQTT
publish settings, set via the Tasmota web console or `Backlog` commands) is
device firmware config, not something reachable from the host running
telegraf - it isn't captured here. If you want it documented, export it from
the device's console (`Rule1`/`Rule2`/`Rule3` and the relevant `SetOption`s, e.g. `SetOption52`)
and add it as a file in this folder.

## Setup

1. Flash and configure the Tasmota device so it publishes SML readings to
   your MQTT broker under a topic like `tele/<device_id>/SENSOR`.
2. Copy `telegraf-mqtt-input.conf.example` into your telegraf config,
   filling in the broker host, credentials, and device id.
3. Continue with `../../persistence/mysql/README.md` for the storage side.
