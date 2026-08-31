#!/usr/bin/env python3
"""Subscribe to a meter's raw MQTT topic and continuously republish the
latest reading as an RSS feed and a JSON snapshot - a fourth presentation
channel alongside email/website/Grafana, for the same data acquired by
../../acquisition/tasmota-ir/.

Runs forever (MQTT loop), meant to be managed by a service supervisor - see
mqtt_feed.service.example. All deployment-specific values (broker, topic,
output paths) are CLI flags; nothing here has a real-looking default.
"""
import argparse
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom

logger = logging.getLogger(__name__)


def flatten_json(obj, parent_key="", sep="."):
    items = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.update(flatten_json(v, new_key, sep=sep))
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    items.update(flatten_json(item, f"{new_key}[{i}]", sep=sep))
            else:
                items[new_key] = v
    else:
        items[parent_key] = obj
    return items


def sanitize_tag(name: str) -> str:
    name = name.replace(".", "_").replace("[", "_").replace("]", "")
    name = re.sub(r"[^A-Za-z0-9_\-]", "_", name)
    if not name or not re.match(r"[A-Za-z_]", name[0]):
        name = f"f_{name}"
    return name


def build_rss(flat_data, rss_title, rss_link, rss_description):
    """Erstellt den RSS-XML-Baum."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = rss_title
    ET.SubElement(channel, "link").text = rss_link
    ET.SubElement(channel, "description").text = rss_description

    item_el = ET.SubElement(channel, "item")
    ET.SubElement(item_el, "title").text = f"MQTT Update {datetime.now(timezone.utc).isoformat()}"
    ET.SubElement(item_el, "pubDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    # Blattfelder als Tags
    for key, value in flat_data.items():
        tag_name = sanitize_tag(key)
        ET.SubElement(item_el, tag_name).text = str(value)

    # HTML-Liste als Description
    description_html = "<br/>".join([f"{k}: {v}" for k, v in flat_data.items()])
    desc = ET.SubElement(item_el, "description", {"data-cdata": "1"})
    desc.text = description_html
    return rss


def write_rss_pretty_with_cdata(rss_elem, rss_file):
    """Pretty Print mit CDATA für Description."""
    rough_xml = ET.tostring(rss_elem, encoding="utf-8", xml_declaration=True)
    dom = minidom.parseString(rough_xml)

    for d in dom.getElementsByTagName("description"):
        if d.hasAttribute("data-cdata") and d.getAttribute("data-cdata") == "1":
            original_text = "".join(
                node.data for node in d.childNodes if node.nodeType in (node.TEXT_NODE, node.CDATA_SECTION_NODE)
            )
            d.removeAttribute("data-cdata")
            while d.firstChild:
                d.removeChild(d.firstChild)
            d.appendChild(dom.createCDATASection(original_text))

    pretty_xml = dom.toprettyxml(indent="  ")
    with open(rss_file, "w", encoding="utf-8") as f:
        f.write(pretty_xml)


def write_rss_and_json(raw_json, rss_file, json_file, rss_title, rss_link, rss_description):
    """Schreibt RSS und JSON-Datei."""
    flat_data = flatten_json(raw_json)
    rss_elem = build_rss(flat_data, rss_title, rss_link, rss_description)
    write_rss_pretty_with_cdata(rss_elem, rss_file)

    # Original JSON speichern (überschreiben)
    with open(json_file, "w", encoding="utf-8") as jf:
        json.dump(raw_json, jf, ensure_ascii=False, indent=2)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--mqtt-host", default=os.environ.get("MQTT_HOST", "localhost"),
                         help="MQTT broker host (default: $MQTT_HOST or localhost)")
    parser.add_argument("--mqtt-port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")),
                         help="MQTT broker port (default: $MQTT_PORT or 1883)")
    parser.add_argument("--mqtt-username", default=os.environ.get("MQTT_USERNAME"),
                         help="Optional MQTT username (default: $MQTT_USERNAME)")
    parser.add_argument("--mqtt-password", default=os.environ.get("MQTT_PASSWORD"),
                         help="Optional MQTT password (default: $MQTT_PASSWORD)")
    parser.add_argument("--topic", required=True,
                         help="MQTT topic to subscribe to, e.g. tele/<device-id>/SENSOR - "
                              "see ../../acquisition/tasmota-ir/")

    parser.add_argument("--rss-file", required=True, help="Output path for the RSS XML file")
    parser.add_argument("--json-file", required=True, help="Output path for the latest-reading JSON snapshot")
    parser.add_argument("--log-file", default=None,
                         help="Optional log file path - if unset, logs to stdout/stderr only "
                              "(fine when run under a service supervisor that captures those, e.g. journald)")

    parser.add_argument("--rss-title", default="MQTT JSON Feed", help="RSS channel title")
    parser.add_argument("--rss-link", default="http://example.com", help="RSS channel link")
    parser.add_argument("--rss-description", default="Letzte MQTT-Nachricht als RSS",
                         help="RSS channel description")

    return parser.parse_args()


def main():
    args = parse_args()

    handlers = [logging.StreamHandler()]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=handlers)

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info(f"Verbunden mit {args.mqtt_host}:{args.mqtt_port}")
            client.subscribe(args.topic)
            logger.info(f"Abonniert: {args.topic}")
        else:
            logger.warning(f"Fehler Code {rc}")

    def on_message(client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8")
            data = json.loads(payload)
            write_rss_and_json(data, args.rss_file, args.json_file,
                                args.rss_title, args.rss_link, args.rss_description)
            logger.info("RSS & JSON aktualisiert")
        except Exception as e:
            logger.error(f"Fehler: {e}")

    def on_disconnect(client, userdata, rc):
        if rc != 0:
            logger.warning("Verbindung verloren. Versuche erneut...")
            try:
                client.reconnect()
            except Exception as e:
                logger.error(f"Reconnect fehlgeschlagen: {e}")

    client = mqtt.Client()
    if args.mqtt_username and args.mqtt_password:
        client.username_pw_set(args.mqtt_username, args.mqtt_password)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    client.connect(args.mqtt_host, args.mqtt_port, keepalive=60)
    client.loop_start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
