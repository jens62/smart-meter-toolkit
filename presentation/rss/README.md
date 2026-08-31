# Presentation: RSS/JSON feed

A fourth presentation channel alongside email/website/Grafana: subscribes to
the meter's raw MQTT topic (the same one `../../acquisition/tasmota-ir/`
documents) and continuously republishes the latest single reading as an RSS
feed and a JSON snapshot - useful for feed readers or any other tool that
wants "the latest reading" without querying the database.

Unlike the other presentation components, this one reacts to every incoming
MQTT message in real time rather than running once a day - it's meant to
run continuously under a service supervisor.

## Setup

1. `pip install paho-mqtt` (see the top-level README's Requirements section).
2. Copy `mqtt_feed.service.example` to `/etc/systemd/system/mqtt_feed.service`,
   fill in the placeholders, then:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now mqtt_feed.service
   ```
3. `--rss-file`/`--json-file` should point into your webserver's public
   directory if you want them served over HTTP - they're written with no
   particular permissions handling beyond the process's own umask, so make
   sure the service's `User`/`Group` can write there.
4. If you set `--log-file` (as the systemd example does), also copy
   `logrotate-mqtt-feed.conf.example` to `/etc/logrotate.d/`, filling in the
   same path/user - otherwise that log grows forever. Its `postrotate`
   restarts the service, which is required: the script opens the log file
   once via `logging.FileHandler` and would otherwise keep writing to the
   rotated-away inode.

## Notes

- `--topic` must match `name_override`/the topic used in
  `../../acquisition/tasmota-ir/telegraf-mqtt-input.conf.example` - same
  raw data, different consumer.
- `--rss-link`/`--rss-title`/`--rss-description` default to generic
  placeholder-ish text (matching the original deployment, which never
  filled these in with anything real) - override them if you want the feed
  to point at your actual site.
