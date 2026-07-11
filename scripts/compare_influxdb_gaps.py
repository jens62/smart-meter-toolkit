#!/usr/bin/env python3
"""Cross-validate gaps found in a local meter-reading CSV against gaps found in an
InfluxDB v2 time series for the same physical meter.

Two independent pipelines can record the same meter (e.g. a gateway->XML->CSV export
chain, and an openHAB binding persisting into InfluxDB). If both pipelines show a gap
at the exact same time, that's strong evidence the gap is genuine data loss at the
device rather than an artifact of one specific pipeline. Gaps that appear in only one
of the two sources point to a difference in what each pipeline actually captured.

Example:
  python3 compare_influxdb_gaps.py \\
      --csv normalized_1_EMH00_1180_2881_from_2025-03-01_00-00-01_to_2026-06-30_23-45-01.csv \\
      --timestamp _time --delimiter ";" \\
      --influx-url http://192.168.0.194:8086 --org 2a4ad7687e68903b --bucket openhab \\
      --measurement SMGW_EPPC0211923304 \\
      --range-start 2025-03-01T00:00:00Z --range-stop 2026-07-01T00:00:00Z \\
      --delta 20m

The InfluxDB API token is never hardcoded: pass --token, or set the INFLUXDB_TOKEN
environment variable.
"""
import argparse
import io
import os
import sys

import pandas as pd
import requests

FLUX_TEMPLATE = """
from(bucket: "{bucket}")
  |> range(start: {range_start}, stop: {range_stop})
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> keep(columns: ["_time"])
  |> sort(columns: ["_time"])
  |> elapsed(unit: 1ns)
  |> map(fn: (r) => ({{
      gap_start: time(v: uint(v: r._time) - uint(v: r.elapsed)),
      gap_end: r._time,
      duration_ns: r.elapsed,
  }}))
  |> filter(fn: (r) => r.duration_ns > uint(v: duration(v: {threshold})))
  |> yield(name: "gaps")
"""


def parse_delta(delta_str):
    """Parse a duration string like '20m', '2h', '1d' into a pandas Timedelta."""
    units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    unit = delta_str[-1]
    if unit not in units:
        raise argparse.ArgumentTypeError(
            f"Invalid delta '{delta_str}'. Use a number followed by s, m, h, d, or w."
        )
    value = int(delta_str[:-1])
    return pd.Timedelta(**{units[unit]: value})


def query_influx_gaps(influx_url, org, bucket, token, measurement, range_start, range_stop, delta_str):
    flux = FLUX_TEMPLATE.format(
        bucket=bucket, measurement=measurement,
        range_start=range_start, range_stop=range_stop, threshold=delta_str,
    )
    resp = requests.post(
        f"{influx_url}/api/v2/query",
        params={"org": org, "bucket": bucket},
        headers={
            "Authorization": f"Token {token}",
            "Accept": "application/csv",
            "Content-Type": "application/vnd.flux",
        },
        data=flux.encode("utf-8"),
        timeout=120,
    )
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    if "gap_start" not in df.columns:
        return []
    df = df.dropna(subset=["gap_start", "gap_end"])
    gaps = [
        (pd.to_datetime(row["gap_start"], utc=True), pd.to_datetime(row["gap_end"], utc=True))
        for _, row in df.iterrows()
    ]
    return sorted(gaps)


def detect_csv_gaps(csv_path, timestamp_col, delimiter, threshold):
    df = pd.read_csv(csv_path, sep=delimiter)
    df[timestamp_col] = pd.to_datetime(df[timestamp_col], utc=True)
    df = df.drop_duplicates(subset=[timestamp_col]).sort_values(timestamp_col).reset_index(drop=True)
    diffs = df[timestamp_col].diff()
    gaps = []
    for idx in diffs.index:
        d = diffs[idx]
        if pd.notna(d) and d > threshold:
            gaps.append((df[timestamp_col].iloc[idx - 1], df[timestamp_col].iloc[idx]))
    return gaps


def fmt(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    parser = argparse.ArgumentParser(
        description="Compare gaps in a local CSV against gaps in an InfluxDB v2 measurement.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--csv", required=True, help="Local CSV with meter readings")
    parser.add_argument("--timestamp", default="_time", help="Timestamp column name in the CSV")
    parser.add_argument("--delimiter", default=";", help="CSV delimiter character")
    parser.add_argument("--delta", default="20m", help="Minimum gap duration (e.g. 20m, 2h)")

    parser.add_argument("--influx-url", required=True, help="InfluxDB base URL, e.g. http://host:8086")
    parser.add_argument("--org", required=True, help="InfluxDB organization (name or id)")
    parser.add_argument("--bucket", required=True, help="InfluxDB bucket")
    parser.add_argument("--measurement", required=True, help="InfluxDB _measurement to inspect")
    parser.add_argument("--range-start", required=True, help="Flux range start, e.g. 2025-03-01T00:00:00Z")
    parser.add_argument("--range-stop", required=True, help="Flux range stop, e.g. 2026-07-01T00:00:00Z")
    parser.add_argument(
        "--token", default=os.environ.get("INFLUXDB_TOKEN"),
        help="InfluxDB API token (defaults to $INFLUXDB_TOKEN)",
    )

    args = parser.parse_args()

    if not args.token:
        parser.error("An InfluxDB token is required: pass --token or set INFLUXDB_TOKEN")

    threshold = parse_delta(args.delta)

    csv_gaps = detect_csv_gaps(args.csv, args.timestamp, args.delimiter, threshold)
    influx_gaps = query_influx_gaps(
        args.influx_url, args.org, args.bucket, args.token, args.measurement,
        args.range_start, args.range_stop, args.delta,
    )

    csv_set = {(fmt(s), fmt(e)) for s, e in csv_gaps}
    influx_set = {(fmt(s), fmt(e)) for s, e in influx_gaps}

    both = sorted(csv_set & influx_set)
    only_csv = sorted(csv_set - influx_set)
    only_influx = sorted(influx_set - csv_set)

    print(f"CSV gaps:     {len(csv_set)}")
    print(f"InfluxDB gaps: {len(influx_set)}")
    print()
    print(f"Matching in both sources ({len(both)}):")
    for s, e in both:
        print(f"  {s} -> {e}")
    print()
    print(f"Only in CSV, not in InfluxDB ({len(only_csv)}):")
    for s, e in only_csv:
        print(f"  {s} -> {e}")
    print()
    print(f"Only in InfluxDB, not in CSV ({len(only_influx)}):")
    for s, e in only_influx:
        print(f"  {s} -> {e}")


if __name__ == "__main__":
    main()
