#!/usr/bin/env bash
#
# Archives raw gateway export files (export_*.csv/json/xml) from a data
# directory into one tar file per calendar day.
#
# Written for the Linux cron host this pipeline runs on (uses GNU `date -d`).
#
# With no date given, archives yesterday only (the crontab use case). Give a
# start date to backfill a range through yesterday; days whose archive
# already exists are skipped, so re-running is safe.

set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") [START_DATE] [options]

  START_DATE             First day to archive (YYYY-MM-DD), inclusive.
                         Archives through yesterday. Default: yesterday only.
                         (Can also be set via \$START_DATE instead of as an argument.)

Options:
  --base-dir PATH        Directory containing --data-dir, and where --daily-dir
                         is created (default: current directory)
  --data-dir NAME        Subdirectory of --base-dir with the raw export files
                         (default: data)
  --daily-dir NAME       Subdirectory of --base-dir to write daily tars into
                         (default: archives/daily)
  --tmp-dir PATH         Scratch directory for building a tar before an atomic
                         move into place (default: \$TMPDIR or /tmp)
  -h, --help             Show this help and exit
EOF
}

BASE="$(pwd)"
DATA_DIR="data"
DAILY_DIR="archives/daily"
TMP_DIR="${TMPDIR:-/tmp}"
START_DATE="${START_DATE:-}"

if [[ $# -gt 0 && "$1" != --* ]]; then
  START_DATE="$1"
  shift
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-dir) BASE="$2"; shift 2 ;;
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --daily-dir) DAILY_DIR="$2"; shift 2 ;;
    --tmp-dir) TMP_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$START_DATE" ]]; then
  START_DATE="$(date -d 'yesterday' +%Y-%m-%d)"
fi
END_DATE="$(date -d 'yesterday' +%Y-%m-%d)"

if ! date -d "$START_DATE" >/dev/null 2>&1; then
  echo "Invalid START_DATE: $START_DATE" >&2
  exit 2
fi

mkdir -p "$BASE/$DAILY_DIR"
cd "$BASE"

current="$START_DATE"
while [[ "$(date -d "$current" +%Y-%m-%d)" != "$(date -d "$END_DATE + 1 day" +%Y-%m-%d)" ]]; do
  day_label="$(date -d "$current" +%Y-%m-%d)"
  next_day="$(date -d "$current + 1 day" +%Y-%m-%d)"

  tmp_tar="$TMP_DIR/data-${day_label}.tar.$$"
  final_tar="$BASE/$DAILY_DIR/data-${day_label}.tar"

  if [[ -f "$final_tar" ]]; then
    echo "Skipping $day_label (archive exists)"
    current="$(date -d "$current + 1 day" +%Y-%m-%d)"
    continue
  fi

  echo "Archiving day $day_label ..."

  mapfile -t files < <(find "$DATA_DIR" -type f \( -name 'export_*.csv' -o -name 'export_*.json' -o -name 'export_*.xml' \) \
    -newermt "${current} 00:00:00" ! -newermt "${next_day} 00:00:00" -print)

  if [[ ${#files[@]} -eq 0 ]]; then
    echo "  No files for $day_label"
    current="$(date -d "$current + 1 day" +%Y-%m-%d)"
    continue
  fi

  filelist="$(mktemp)"
  for f in "${files[@]}"; do
    printf '%s\n' "$f" >> "$filelist"
  done

  tar -cf "$tmp_tar" --no-recursion --exclude="$DAILY_DIR" -T "$filelist"
  rm -f "$filelist"

  mv "$tmp_tar" "$final_tar"
  echo "  Created $final_tar"

  current="$(date -d "$current + 1 day" +%Y-%m-%d)"
done

echo "Done: processed $START_DATE .. $END_DATE"
