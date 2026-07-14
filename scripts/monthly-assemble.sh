#!/usr/bin/env bash
#
# Concatenates a month's daily tar files (data-YYYY-MM-DD.tar, as produced by
# daily-tar.sh) into one compressed monthly archive.
#
# Written for the Linux cron host this pipeline runs on (uses GNU `date -d`).

set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") [YYYY-MM] [options]

  YYYY-MM                Target month to assemble. Default: last month
                         (run this on day 2 of the following month).

Options:
  --daily-dir PATH       Directory containing the daily tar files
                         (default: current directory)
  --monthly-dir PATH     Directory to write the assembled monthly tar.gz into
                         (default: current directory)
  --tmp-dir PATH         Scratch directory for assembling before an atomic
                         move into place (default: \$TMPDIR or /tmp)
  --lookback-months N    Also (re-)check the N-1 months before YYYY-MM,
                         skipping any whose archive already exists. Safe to
                         run redundantly every night - makes this resilient
                         to the host being down on day 2 of a given month,
                         when it would otherwise silently never assemble
                         that month at all (default: 1, i.e. only YYYY-MM)
  -h, --help             Show this help and exit
EOF
}

DAILY_DIR="$(pwd)"
MONTHLY_DIR="$(pwd)"
TMP_DIR="${TMPDIR:-/tmp}"
MONTH_LABEL=""
LOOKBACK_MONTHS=1

if [[ $# -gt 0 && "$1" != --* ]]; then
  MONTH_LABEL="$1"
  shift
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --daily-dir) DAILY_DIR="$2"; shift 2 ;;
    --monthly-dir) MONTHLY_DIR="$2"; shift 2 ;;
    --tmp-dir) TMP_DIR="$2"; shift 2 ;;
    --lookback-months) LOOKBACK_MONTHS="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$MONTH_LABEL" ]]; then
  MONTH_LABEL="$(date -d 'last month' +%Y-%m)"
fi

mkdir -p "$MONTHLY_DIR"

assemble_month() {
  local month_label="$1"
  local month_tar_tmp="$TMP_DIR/data-${month_label}.tar.$$"
  local month_tar_final="$MONTHLY_DIR/data-${month_label}.tar"
  local month_tar_gz="$month_tar_final.gz"

  if [[ -f "$month_tar_gz" ]]; then
    echo "Skipping $month_label (monthly archive already exists)"
    return 0
  fi

  # Find daily tar files for that month (assumes daily files named data-YYYY-MM-DD.tar)
  shopt -s nullglob
  local daily_files=( "$DAILY_DIR"/data-"$month_label"-*.tar )
  shopt -u nullglob

  if [[ ${#daily_files[@]} -eq 0 ]]; then
    echo "No daily tar files found for $month_label" >&2
    return 0
  fi

  # Concatenate into one tar (requires uncompressed tars): start with the
  # first file, then --concatenate the rest.
  cp "${daily_files[0]}" "$month_tar_tmp"
  for f in "${daily_files[@]:1}"; do
    tar --concatenate --file="$month_tar_tmp" "$f"
  done

  mv "$month_tar_tmp" "$month_tar_final"
  gzip -9 "$month_tar_final"

  echo "Created $month_tar_gz"
}

for (( i = LOOKBACK_MONTHS - 1; i >= 0; i-- )); do
  label="$(date -d "${MONTH_LABEL}-01 -${i} month" +%Y-%m)"
  assemble_month "$label"
done
