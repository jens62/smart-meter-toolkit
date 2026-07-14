#!/usr/bin/env python3
"""Nightly gap-filling: detect gaps in a workbook's recent months and
re-request each one from the gateway via read_SMGW.py.

The gateway itself caches roughly 15 months of readings (measured
2026-07-14 for this household's specific gateway - see TODO.md item 8 and
local-assets/smgw_retention_probe/ for how; re-measure if this matters
again much later or after a firmware update), so a gap caused by a missed
poll (e.g. the cron host being down) is usually still recoverable after
the fact - this is the "gap in already-exported data" technique from the
README's "Filling gaps in already-exported data" section, run
automatically instead of by hand.

Only the last `--months` month-sheets of the workbook are scanned (default
15, matching the measured gateway retention above - see TODO.md item 8),
matching this script's purpose: recovering *recent, still-recoverable*
gaps while they're still in the gateway's own retention window. Older gaps
remain visible forever in the `--add-gaps` "Luecken" block on the Verbrauch
sheet - this script doesn't need to, and deliberately doesn't, cover those.
One consequence of the month-window cut: a gap whose start falls in the
month just before the window (i.e. the boundary between the excluded and
included range) is invisible here, since gap detection only compares
timestamps it was actually given.

A gap is retried once per calendar day (state persisted in --state-file,
so re-running this script multiple times in the same day is a no-op for
gaps already attempted today - safe for manual testing). After
--max-retries attempts across separate days with the gap still open, it's
marked "given up" and skipped on every later run, until the day it
actually disappears from detection (at which point it's dropped from the
state file as resolved).

This script never touches the workbook itself - it only writes new raw
export files into --out-path's data/ subdirectory, the same place
smgw2influx.sh's underlying reader writes them, and the same place
--append-to and daily-tar.sh already expect to find them. Picking up the
recovered data into the workbook and its Luecken block still happens via
the normal --append-to --add-gaps run, whenever that next runs.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta

import pandas as pd
import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meter_reading2consumption import MONTH_TAG_RE, find_gaps, read_month_rows  # noqa: E402

from openpyxl import load_workbook


def setup_logging(log_level):
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )
    return logging.getLogger(__name__)


def gap_key(gap_start, gap_end):
    return f"{gap_start.isoformat()}__{gap_end.isoformat()}"


def collect_recent_times(xlsx_path, months, logger):
    """Sorted-descending datetimes from the workbook's last `months`
    month-sheets, plus the earliest month-sheet name included (so callers
    can tell whether a since-vanished gap aged out of the window or was
    actually resolved)."""
    wb = load_workbook(xlsx_path, read_only=True)
    try:
        month_sheets = sorted(s for s in wb.sheetnames if MONTH_TAG_RE.match(s))
        if not month_sheets:
            raise ValueError(f"No monthly sheets found in {xlsx_path}")
        window = month_sheets[-months:]
        logger.info(f"Scanning {len(window)} month sheet(s): {', '.join(window)}")
        times = []
        for name in window:
            for dt, _time_str, _value, _meas in read_month_rows(wb[name]):
                times.append(dt)
        times.sort(reverse=True)
        window_start = datetime.strptime(f"{window[0]}_01", "%Y_%m_%d")
        return times, window_start
    finally:
        wb.close()


def load_state(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_state(path, state):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def pad_local_time(naive_local_dt, minutes, timezone):
    """naive_local_dt +/- minutes of real elapsed time, DST-safe.

    Plain `timedelta` arithmetic on a naive wall-clock time can land on a
    local time that doesn't exist (e.g. padding across the spring-forward
    night can produce "02:15", even though Europe/Berlin's clocks jump
    straight from 02:00 to 03:00 that night) or is ambiguous (the
    fall-back night's repeated hour). Localizing, adding in absolute time,
    then normalizing back gives the correct real-time-shifted wall clock
    instead - the same pytz idiom meter_reading2consumption.py's
    find_gaps() relies on for the same reason.
    """
    tz = pytz.timezone(timezone)
    aware = tz.localize(naive_local_dt)
    return tz.normalize(aware + timedelta(minutes=minutes)).replace(tzinfo=None)


def query_gateway(args, gap_start, gap_end, logger):
    from_str = pad_local_time(gap_start, -args.pad_minutes, args.timezone).strftime("%Y-%m-%d %H:%M:%S")
    to_str = pad_local_time(gap_end, args.pad_minutes, args.timezone).strftime("%Y-%m-%d %H:%M:%S")

    cmd = [
        args.python, args.read_smgw_script,
        "--host", args.host,
        "--user", args.user,
        "--password", args.password,
        "--from", from_str,
        "--to", to_str,
        "--out-path", args.out_path,
    ]
    if args.meter:
        cmd += ["--meter", args.meter]

    logged_cmd = [c if c != args.password else "***" for c in cmd]
    logger.info(f"Querying gateway for {from_str} .. {to_str}: {' '.join(logged_cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=args.request_timeout)
    except subprocess.TimeoutExpired:
        logger.warning(f"Gateway request timed out after {args.request_timeout}s")
        return False

    if result.returncode != 0:
        logger.warning(
            f"read_SMGW.py exited {result.returncode} for {from_str} .. {to_str}: "
            f"{result.stderr.strip()[-500:]}"
        )
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Detect recent gaps in a workbook and re-request them from the gateway.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Example (manual test run, not yet wired into cron):
  %(prog)s \\
      --workbook /path/to/1_EMH00_..._to_....xlsx \\
      --state-file /path/to/gap_backfill_state.json \\
      --out-path /path/to/data-directory \\
      --user <user> --password <password> \\
      --dry-run
""",
    )
    parser.add_argument("--workbook", required=True, help="Workbook to scan for gaps")
    parser.add_argument("--months", type=int, default=15,
                        help="How many trailing month-sheets to scan (default: 15, matching this "
                             "gateway's measured retention window - see TODO.md item 8)")
    parser.add_argument("--delta", default="20m", help="Minimum gap duration to act on (e.g. 20m, 1h)")
    parser.add_argument("--timezone", default="Europe/Berlin", help="Timezone for gap detection")

    parser.add_argument("--state-file", required=True, help="JSON file tracking per-gap retry state")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="Give up on a gap after this many days of still being open")
    parser.add_argument("--max-requests-per-run", type=int, default=10,
                        help="Cap gateway requests in one run (be gentle on the gateway); "
                             "excess eligible gaps are deferred to the next run, oldest first")
    parser.add_argument("--pad-minutes", type=int, default=30,
                        help="Widen each gateway request by this many minutes on either side "
                             "of the detected gap, to be safe against boundary readings")
    parser.add_argument("--request-timeout", type=int, default=180,
                        help="Per-request subprocess timeout in seconds")

    parser.add_argument("--host", default="192.168.1.200", help="Gateway IP")
    parser.add_argument("--user", required=True, help="Gateway user")
    parser.add_argument("--password", default=os.environ.get("SMGW_PASSWORD"),
                        help="Gateway password (default: $SMGW_PASSWORD)")
    parser.add_argument("--meter", help="Meter id override, passed through to read_SMGW.py")
    parser.add_argument("--out-path", required=True,
                        help="Base directory read_SMGW.py writes into (creates/uses its own data/ subdir)")
    parser.add_argument("--read-smgw-script",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "read_SMGW.py"),
                        help="Path to read_SMGW.py")
    parser.add_argument("--python", default=sys.executable, help="Python interpreter to run read_SMGW.py with")

    parser.add_argument("--dry-run", action="store_true",
                        help="Detect and report gaps/state changes without querying the gateway "
                             "or writing the state file")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    args = parser.parse_args()

    logger = setup_logging(args.log_level)

    if not args.password:
        logger.error("No gateway password given (--password or $SMGW_PASSWORD)")
        sys.exit(1)

    delta = pd.Timedelta(args.delta)

    try:
        times, window_start = collect_recent_times(args.workbook, args.months, logger)
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        sys.exit(1)

    detected = find_gaps(times, threshold=delta, timezone=args.timezone)
    detected.sort(key=lambda g: g[0])  # oldest gap first - find_gaps() returns newest-first
    detected_keys = {gap_key(start, end): (start, end) for start, end, _duration in detected}
    logger.info(f"Detected {len(detected)} gap(s) over {delta} in the last {args.months} month(s)")

    state = load_state(args.state_file)
    today = date.today().isoformat()

    for key in list(state.keys()):
        if key not in detected_keys:
            entry = state.pop(key)
            gap_end = datetime.fromisoformat(entry["end"])
            if gap_end < window_start:
                logger.info(f"Gap {entry['start']} .. {entry['end']} aged out of the {args.months}-month window (untracked)")
            else:
                logger.info(f"Gap {entry['start']} .. {entry['end']} resolved (no longer detected)")

    to_query = []
    for key, (start, end) in detected_keys.items():
        entry = state.setdefault(key, {
            "start": start.isoformat(), "end": end.isoformat(),
            "attempts": 0, "last_attempt_date": None, "status": "open",
        })
        if entry["status"] == "given_up":
            logger.debug(f"Gap {start} .. {end}: given up previously, skipping")
            continue
        if entry["attempts"] >= args.max_retries:
            entry["status"] = "given_up"
            logger.warning(f"Gap {start} .. {end}: still open after {entry['attempts']} attempts, giving up")
            continue
        if entry["last_attempt_date"] == today:
            logger.debug(f"Gap {start} .. {end}: already attempted today, skipping")
            continue
        to_query.append((key, start, end, entry))

    deferred = to_query[args.max_requests_per_run:]
    to_query = to_query[:args.max_requests_per_run]
    if deferred:
        logger.warning(
            f"Deferring {len(deferred)} eligible gap(s) to a later run (--max-requests-per-run={args.max_requests_per_run}): "
            + ", ".join(f"{s} .. {e}" for _k, s, e, _entry in deferred)
        )

    queried, failed = 0, 0
    for key, start, end, entry in to_query:
        if args.dry_run:
            logger.info(f"[dry-run] would query gateway for gap {start} .. {end} (attempt {entry['attempts'] + 1}/{args.max_retries})")
            continue
        ok = query_gateway(args, start, end, logger)
        entry["attempts"] += 1
        entry["last_attempt_date"] = today
        entry["last_result"] = "ok" if ok else "failed"
        queried += 1
        if not ok:
            failed += 1

    if not args.dry_run:
        save_state(args.state_file, state)
    else:
        logger.info("[dry-run] state file not written")

    logger.info(
        f"Done: {len(detected)} open gap(s), {queried} queried ({failed} failed), "
        f"{len(deferred)} deferred, "
        f"{sum(1 for e in state.values() if e['status'] == 'given_up')} given up total"
    )


if __name__ == "__main__":
    main()
