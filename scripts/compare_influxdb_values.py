#!/usr/bin/env python3
"""Compare the full raw reading series in a local meter-reading CSV against the full
series stored in an InfluxDB v2 measurement for the same physical meter.

Unlike compare_influxdb_gaps.py (which only compares detected *gaps*), this pulls
every timestamp+value pair from both sources over a given range and reports:
  - timestamps present in both, and whether their values match exactly
  - timestamps present only in the CSV (InfluxDB is missing them)
  - timestamps present only in InfluxDB (the CSV is missing them)

Note on range boundaries: InfluxDB's `range(start, stop)` is start-inclusive /
stop-exclusive and always in UTC. If your CSV's start/stop boundaries were chosen to
align with a *local* time boundary (e.g. "local midnight March 1"), make sure
--range-start/--range-stop are the equivalent UTC instants, not the UTC calendar-day
boundary - otherwise you'll see spurious "only in CSV" rows right at the edges that
are really just a range mismatch, not a real gap in InfluxDB.

Example:
  python3 compare_influxdb_values.py \\
      --csv normalized_1_ABC00_1234_5678_from_2025-03-01_00-00-01_to_2026-06-30_23-45-01.csv \\
      --timestamp _time --delimiter ";" --divisor 10000 \\
      --influx-url http://192.168.0.194:8086 --org 2a4ad7687e68903b --bucket openhab \\
      --measurement SMGW_EPPC0211923304 \\
      --range-start 2025-02-28T23:00:00Z --range-stop 2026-06-30T22:00:00Z

The InfluxDB API token is never hardcoded: pass --token, or set the INFLUXDB_TOKEN
environment variable.
"""
import argparse
import io
import os

import pandas as pd
import requests

FLUX_TEMPLATE = """
from(bucket: "{bucket}")
  |> range(start: {range_start}, stop: {range_stop})
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> keep(columns: ["_time", "_value"])
  |> sort(columns: ["_time"])
"""


def query_influx_series(influx_url, org, bucket, token, measurement, range_start, range_stop):
    flux = FLUX_TEMPLATE.format(
        bucket=bucket, measurement=measurement,
        range_start=range_start, range_stop=range_stop,
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
        timeout=180,
    )
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df = df.rename(columns={"_time": "time", "_value": "influx_value"})
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df[["time", "influx_value"]].drop_duplicates(subset=["time"])


def load_csv_series(csv_path, timestamp_col, delimiter, divisor):
    df = pd.read_csv(csv_path, sep=delimiter)
    df[timestamp_col] = pd.to_datetime(df[timestamp_col], utc=True)
    df = df.rename(columns={timestamp_col: "time"})
    df = df.drop_duplicates(subset=["time"]).sort_values("time")
    value_col = [c for c in df.columns if c != "time" and c not in ("_measurement",)][0]
    df["csv_value"] = df[value_col] / divisor
    return df[["time", "csv_value"]]


def main():
    parser = argparse.ArgumentParser(
        description="Compare a local CSV's readings against an InfluxDB v2 measurement's readings.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--csv", required=True, help="Local CSV with meter readings")
    parser.add_argument("--timestamp", default="_time", help="Timestamp column name in the CSV")
    parser.add_argument("--delimiter", default=";", help="CSV delimiter character")
    parser.add_argument("--divisor", type=float, default=10000.0, help="Divide raw CSV values by this to match InfluxDB's units")
    parser.add_argument("--tolerance", type=float, default=1e-6, help="Value diff above this counts as a mismatch")

    parser.add_argument("--influx-url", required=True, help="InfluxDB base URL, e.g. http://host:8086")
    parser.add_argument("--org", required=True, help="InfluxDB organization (name or id)")
    parser.add_argument("--bucket", required=True, help="InfluxDB bucket")
    parser.add_argument("--measurement", required=True, help="InfluxDB _measurement to inspect")
    parser.add_argument("--range-start", required=True, help="Flux range start (UTC), e.g. 2025-02-28T23:00:00Z")
    parser.add_argument("--range-stop", required=True, help="Flux range stop (UTC), e.g. 2026-06-30T22:00:00Z")
    parser.add_argument(
        "--token", default=os.environ.get("INFLUXDB_TOKEN"),
        help="InfluxDB API token (defaults to $INFLUXDB_TOKEN)",
    )
    parser.add_argument("--show-mismatches", type=int, default=20, help="Max mismatched rows to print")

    args = parser.parse_args()
    if not args.token:
        parser.error("An InfluxDB token is required: pass --token or set INFLUXDB_TOKEN")

    csv_series = load_csv_series(args.csv, args.timestamp, args.delimiter, args.divisor)
    influx_series = query_influx_series(
        args.influx_url, args.org, args.bucket, args.token, args.measurement,
        args.range_start, args.range_stop,
    )

    merged = pd.merge(csv_series, influx_series, on="time", how="outer", indicator=True)
    only_csv = merged[merged["_merge"] == "left_only"].sort_values("time")
    only_influx = merged[merged["_merge"] == "right_only"].sort_values("time")
    both = merged[merged["_merge"] == "both"].copy()
    both["diff"] = (both["csv_value"] - both["influx_value"]).abs()
    mismatched = both[both["diff"] > args.tolerance]

    print(f"CSV timestamps:      {len(csv_series)}")
    print(f"InfluxDB timestamps: {len(influx_series)}")
    print(f"Present in both:     {len(both)}")
    print(f"Only in CSV:         {len(only_csv)}")
    print(f"Only in InfluxDB:    {len(only_influx)}")
    print()
    print("Value diff stats for matching timestamps:")
    print(both["diff"].describe())
    print()
    print(f"Mismatched values (diff > {args.tolerance}): {len(mismatched)}")
    if len(mismatched):
        print(mismatched.head(args.show_mismatches).to_string(index=False))
    print()
    print(f"Only in CSV, not in InfluxDB ({len(only_csv)}):")
    print(only_csv[["time", "csv_value"]].head(args.show_mismatches).to_string(index=False))
    print()
    print(f"Only in InfluxDB, not in CSV ({len(only_influx)}):")
    print(only_influx[["time", "influx_value"]].head(args.show_mismatches).to_string(index=False))


if __name__ == "__main__":
    main()
