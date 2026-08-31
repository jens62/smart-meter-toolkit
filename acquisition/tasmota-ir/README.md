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

## What's not included here

The Tasmota device's own configuration (its SML-parsing rule/script and MQTT
publish settings, set via the Tasmota web console or `Backlog` commands) is
device firmware config, not something reachable from the host running
telegraf - it isn't captured here. If you want it documented, export it from
the device's console (`Rule1`/`Rule2`/`Rule3` and the relevant `SetOption`s)
and add it as a file in this folder.

## Setup

1. Flash and configure the Tasmota device so it publishes SML readings to
   your MQTT broker under a topic like `tele/<device_id>/SENSOR`.
2. Copy `telegraf-mqtt-input.conf.example` into your telegraf config,
   filling in the broker host, credentials, and device id.
3. Continue with `../../persistence/mysql/README.md` for the storage side.
